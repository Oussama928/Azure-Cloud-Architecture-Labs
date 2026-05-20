"""
Correlator for ChangeTrace Correlation Engine

Main orchestration logic for incident correlation:
1. Fetch recent changes from graph
2. Compute blast radius from affected service
3. Extract features for each candidate change
4. Rank candidates using ML model
5. Return ranked candidates with confidence scores
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.strategies import *

from .confidence_model import ConfidenceModel, HeuristicConfidenceModel
from .models.correlation import (
    BlastRadiusResult,
    CandidateRanking,
    CorrelationRequest,
    CorrelationResponse,
    FeatureVector,
    Incident,
    TrainingExample,
)

logger = logging.getLogger(__name__)


class Correlator:
    """
    Main correlation engine for root cause analysis.

    Uses Cosmos DB Gremlin for graph queries and ML model for ranking.
    """

    def __init__(
        self,
        cosmos_connection_string: str,
        cosmos_database: str = "changetrace-graph",
        cosmos_graph: str = "dependency-graph",
        model: ConfidenceModel | None = None,
        lookback_hours: int = 2,
        max_candidates: int = 10,
    ):
        self.cosmos_connection_string = cosmos_connection_string
        self.cosmos_database = cosmos_database
        self.cosmos_graph = cosmos_graph
        self.lookback_hours = lookback_hours
        self.max_candidates = max_candidates

        # Initialize model (use heuristic if no trained model provided)
        self.model = model or HeuristicConfidenceModel()

        # Gremlin client
        self._gremlin_client: client.Client | None = None
        self._g = None

    async def initialize(self) -> None:
        """Initialize Gremlin connection"""
        # Parse connection string for Gremlin endpoint
        endpoint = None
        key = None
        for param in self.cosmos_connection_string.split(";"):
            param = param.strip()
            if param.startswith("AccountEndpoint="):
                endpoint = param[16:]
            elif param.startswith("AccountKey="):
                key = param[11:]

        if not endpoint or not key:
            raise ValueError("Invalid Cosmos DB connection string")

        # Create Gremlin client
        self._gremlin_client = client.Client(
            endpoint,
            "g",
            username=f"/dbs/{self.cosmos_database}/colls/{self.cosmos_graph}",
            password=key,
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )

        # Create traversal source
        self._g = traversal().withRemote(
            DriverRemoteConnection(endpoint, "g", username=f"/dbs/{self.cosmos_database}/colls/{self.cosmos_graph}", password=key)
        )

        logger.info("Initialized Gremlin connection to Cosmos DB")

    async def close(self) -> None:
        """Close connections"""
        if self._gremlin_client:
            self._gremlin_client.close()
        logger.info("Closed Gremlin connection")

    async def correlate_incident(self, request: CorrelationRequest) -> CorrelationResponse:
        """
        Main correlation entry point.

        Returns:
            CorrelationResponse with ranked candidates
        """
        start_time = datetime.utcnow()

        logger.info(f"Correlating incident {request.incident_id} for service {request.affected_service}")

        # 1. Get blast radius from affected service
        blast_radius = await self.compute_blast_radius(
            request.affected_service,
            request.affected_namespace,
        )

        # 2. Get candidate changes within blast radius and lookback window
        candidates = await self.get_candidate_changes(
            blast_radius.affected_services,
            request.lookback_hours,
        )

        logger.info(f"Found {len(candidates)} candidate changes")

        if not candidates:
            return CorrelationResponse(
                incident_id=request.incident_id,
                candidates=[],
                analysis_time_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                model_version=self.model.model_version,
                features_used=[],
            )

        # 3. Extract features for each candidate
        feature_vectors = await self.extract_features(
            request.incident_id,
            request.affected_service,
            candidates,
            blast_radius,
        )

        # 4. Rank candidates using model
        ranked_candidates = self.model.rank_candidates(
            Incident(id=request.incident_id, affected_service=request.affected_service),
            candidates,
            feature_vectors,
        )

        # 5. Limit to max candidates
        ranked_candidates = ranked_candidates[:request.max_candidates]

        # 6. Filter by minimum confidence threshold
        ranked_candidates = [
            c for c in ranked_candidates
            if c.confidence_score >= request.min_confidence_threshold
        ]

        analysis_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return CorrelationResponse(
            incident_id=request.incident_id,
            candidates=ranked_candidates,
            analysis_time_ms=analysis_time,
            model_version=self.model.model_version,
            features_used=FeatureVector.feature_names(),
        )

    async def compute_blast_radius(
        self,
        service_name: str,
        namespace: str | None = None,
        max_hops: int = 3,
    ) -> BlastRadiusResult:
        """
        Compute blast radius from a service using graph traversal.

        Finds all services that depend on the given service (reverse dependencies)
        up to max_hops distance.
        """
        logger.debug(f"Computing blast radius for {service_name} (namespace: {namespace})")

        # Build query to find all services that depend on the source service
        # Traverse reverse 'depends_on' edges (incoming edges to source)
        query = f"""
        g.V().has('serviceName', '{service_name}')
        """

        if namespace:
            query += f".has('namespace', '{namespace}')"

        query += f"""
        .repeat(__.in('depends_on').simplePath())
        .times({max_hops})
        .emit()
        .dedup()
        .values('serviceName')
        """

        try:
            result = await self._execute_query(query)
            affected_services = [r for r in result if r != service_name]

            # Also get paths for each affected service
            paths = await self._get_dependency_paths(service_name, affected_services, max_hops)

            # Identify critical services (those with high dependent count)
            critical_services = await self._identify_critical_services(affected_services)

            return BlastRadiusResult(
                source_service=service_name,
                affected_services=affected_services,
                hop_count=max_hops,
                paths=paths,
                total_services_affected=len(affected_services),
                critical_services_affected=critical_services,
            )
        except Exception as e:
            logger.error(f"Error computing blast radius: {e}")
            return BlastRadiusResult(
                source_service=service_name,
                affected_services=[],
                hop_count=max_hops,
                paths=[],
                total_services_affected=0,
                critical_services_affected=[],
            )

    async def _get_dependency_paths(
        self,
        source: str,
        targets: list[str],
        max_hops: int,
    ) -> list[list[str]]:
        """Get dependency paths from source to each target"""
        paths = []

        for target in targets:
            query = f"""
            g.V().has('serviceName', '{source}')
            .repeat(__.in('depends_on').simplePath())
            .times({max_hops})
            .until(has('serviceName', '{target}'))
            .path()
            .by('serviceName')
            .limit(5)
            """

            try:
                result = await self._execute_query(query)
                for path in result:
                    if isinstance(path, list):
                        paths.append(path)
            except Exception as e:
                logger.warning(f"Error getting path to {target}: {e}")

        return paths

    async def _identify_critical_services(self, services: list[str]) -> list[str]:
        """Identify critical services based on dependent count"""
        if not services:
            return []

        # Query for services with high in-degree (many dependents)
        service_list = "', '".join(services)
        query = f"""
        g.V().has('serviceName', within('{service_list}'))
        .where(__.in('depends_on').count().is(gt(3)))
        .values('serviceName')
        """

        try:
            result = await self._execute_query(query)
            return list(result)
        except Exception as e:
            logger.warning(f"Error identifying critical services: {e}")
            return []

    async def get_candidate_changes(
        self,
        affected_services: list[str],
        lookback_hours: int,
    ) -> list[CandidateRanking]:
        """
        Get recent changes for affected services within lookback window.

        Queries the change-history graph for changes to services in the blast radius.
        """
        if not affected_services:
            return []

        # Include the source service itself
        all_services = list(set(affected_services))

        service_list = "', '".join(all_services)
        cutoff_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()

        query = f"""
        g.V().has('serviceName', within('{service_list}'))
        .has('timestamp', gte('{cutoff_time}'))
        .order().by('timestamp', desc)
        .limit({self.max_candidates * 3})
        .valueMap(true)
        """

        try:
            results = await self._execute_query(query)

            candidates = []
            for vertex in results:
                candidate = self._vertex_to_candidate(vertex)
                if candidate:
                    candidates.append(candidate)

            return candidates
        except Exception as e:
            logger.error(f"Error getting candidate changes: {e}")
            return []

    def _vertex_to_candidate(self, vertex: dict[str, Any]) -> CandidateRanking | None:
        """Convert Gremlin vertex to CandidateRanking"""
        try:
            # Extract properties (Gremlin returns lists for properties)
            def get_prop(v, key, default=None):
                val = v.get(key, [default])
                return val[0] if isinstance(val, list) else val

            return CandidateRanking(
                change_event_id=get_prop(vertex, 'eventId', get_prop(vertex, 'id', '')),
                service_name=get_prop(vertex, 'serviceName', ''),
                change_type=get_prop(vertex, 'changeType', ''),
                source=get_prop(vertex, 'source', ''),
                timestamp=datetime.fromisoformat(get_prop(vertex, 'timestamp', datetime.utcnow().isoformat())),
                confidence_score=0.0,  # Will be set by model
                graph_distance_score=0.0,
                temporal_proximity_score=0.0,
                change_type_score=0.0,
                historical_base_rate_score=0.0,
                evidence={
                    'eventId': get_prop(vertex, 'eventId', ''),
                    'status': get_prop(vertex, 'status', ''),
                    'author': get_prop(vertex, 'author', ''),
                    'description': get_prop(vertex, 'description', ''),
                    'pipelineName': get_prop(vertex, 'pipelineName', ''),
                    'deploymentId': get_prop(vertex, 'deploymentId', ''),
                    'newVersion': get_prop(vertex, 'newVersion', ''),
                },
                blast_radius_services=[],
            )
        except Exception as e:
            logger.warning(f"Error converting vertex to candidate: {e}")
            return None

    async def extract_features(
        self,
        incident_id: str,
        affected_service: str,
        candidates: list[CandidateRanking],
        blast_radius: BlastRadiusResult,
    ) -> list[FeatureVector]:
        """
        Extract feature vectors for each candidate change.

        Features include:
        - Graph distance from affected service
        - Temporal proximity to incident
        - Change type encoding
        - Historical failure rates
        - Service criticality
        """
        feature_vectors = []

        # Pre-compute service metrics
        service_metrics = await self._get_service_metrics(
            [c.service_name for c in candidates] + [affected_service]
        )

        for candidate in candidates:
            # Graph distance
            graph_distance = self._compute_graph_distance(
                affected_service,
                candidate.service_name,
                blast_radius,
            )

            # Temporal proximity
            time_delta = datetime.utcnow() - candidate.timestamp
            time_delta_hours = time_delta.total_seconds() / 3600
            time_delta_minutes = time_delta.total_seconds() / 60

            # Change type encoding
            change_type_encoded = self._encode_change_type(candidate.change_type)
            is_deployment = candidate.change_type == "code_deployment"
            is_config_change = candidate.change_type == "config_change"
            is_infra_change = candidate.change_type == "infrastructure_change"
            is_rollback = candidate.change_type == "rollback"

            # Get service metrics
            svc_metrics = service_metrics.get(candidate.service_name, {})

            fv = FeatureVector(
                change_event_id=candidate.change_event_id,
                incident_id=incident_id,
                graph_distance=graph_distance,
                shortest_path_length=graph_distance if graph_distance > 0 else None,
                num_paths=len([p for p in blast_radius.paths if candidate.service_name in p]),
                shared_dependencies=self._count_shared_dependencies(affected_service, candidate.service_name),
                blast_radius_overlap=self._compute_blast_radius_overlap(
                    affected_service,
                    candidate.service_name,
                    blast_radius,
                ),
                time_delta_hours=time_delta_hours,
                time_delta_minutes=time_delta_minutes,
                is_within_lookback=time_delta_hours <= self.lookback_hours,
                change_type_encoded=change_type_encoded,
                is_deployment=is_deployment,
                is_config_change=is_config_change,
                is_infra_change=is_infra_change,
                is_rollback=is_rollback,
                deployment_size=svc_metrics.get('deployment_size'),
                files_changed=svc_metrics.get('files_changed'),
                service_incident_rate_7d=svc_metrics.get('incident_rate_7d', 0.0),
                service_incident_rate_30d=svc_metrics.get('incident_rate_30d', 0.0),
                change_failure_rate_7d=svc_metrics.get('change_failure_rate_7d', 0.0),
                change_failure_rate_30d=svc_metrics.get('change_failure_rate_30d', 0.0),
                same_change_type_failure_rate=svc_metrics.get('same_type_failure_rate', 0.0),
                service_criticality=svc_metrics.get('criticality', 1.0),
                service_dependency_count=svc_metrics.get('dependency_count', 0),
                service_dependent_count=svc_metrics.get('dependent_count', 0),
            )

            feature_vectors.append(fv)

        return feature_vectors

    def _compute_graph_distance(
        self,
        source: str,
        target: str,
        blast_radius: BlastRadiusResult,
    ) -> int:
        """Compute graph distance from source to target"""
        if source == target:
            return 0

        # Check paths in blast radius
        for path in blast_radius.paths:
            if target in path:
                return path.index(target)

        # If in affected services but no path found, assume 1 hop
        if target in blast_radius.affected_services:
            return 1

        # Not in blast radius
        return 99

    def _count_shared_dependencies(self, service1: str, service2: str) -> int:
        """Count shared dependencies between two services"""
        # This would require a graph query but simplified for now
        return 0

    def _compute_blast_radius_overlap(
        self,
        source: str,
        target: str,
        blast_radius: BlastRadiusResult,
    ) -> float:
        """Compute blast radius overlap ratio"""
        if target not in blast_radius.affected_services:
            return 0.0

        # Get blast radius of target
        # Simplified: return 1.0 if in blast radius, 0 otherwise
        return 1.0

    def _encode_change_type(self, change_type: str) -> int:
        """Encode change type as integer"""
        encoding = {
            "code_deployment": 0,
            "config_change": 1,
            "infrastructure_change": 2,
            "release": 3,
            "rollback": 4,
            "scale_event": 5,
        }
        return encoding.get(change_type, -1)

    async def _get_service_metrics(self, services: list[str]) -> dict[str, dict[str, Any]]:
        """Get historical metrics for services"""
        # This would query the graph for historical incident/change data
        # Simplified for now - return defaults
        metrics = {}
        for svc in services:
            metrics[svc] = {
                'incident_rate_7d': 0.0,
                'incident_rate_30d': 0.0,
                'change_failure_rate_7d': 0.0,
                'change_failure_rate_30d': 0.0,
                'same_type_failure_rate': 0.0,
                'criticality': 1.0,
                'dependency_count': 0,
                'dependent_count': 0,
                'deployment_size': None,
                'files_changed': None,
            }
        return metrics

    async def _execute_query(self, query: str) -> list[Any]:
        """Execute Gremlin query"""
        if not self._gremlin_client:
            raise RuntimeError("Gremlin client not initialized")

        try:
            result_set = self._gremlin_client.submit(query)
            results = []
            for result in result_set:
                results.append(result)
            return results
        except Exception as e:
            logger.error(f"Gremlin query failed: {query[:200]}... Error: {e}")
            raise

    async def create_training_example(
        self,
        incident: Incident,
        candidate: CandidateRanking,
        feature_vector: FeatureVector,
        is_root_cause: bool,
    ) -> TrainingExample:
        """Create a training example from a confirmed incident"""
        return TrainingExample(
            incident_id=incident.incident_id,
            change_event_id=candidate.change_event_id,
            features=feature_vector,
            label=is_root_cause,
            weight=1.0,
        )

    def get_model_info(self) -> dict[str, Any]:
        """Get model information"""
        return {
            "model_version": self.model.model_version,
            "is_trained": self.model.is_trained,
            "feature_importance": self.model.get_feature_importance(),
            "training_metrics": self.model.training_metrics.to_dict() if self.model.training_metrics else None,
        }


async def create_correlator(
    cosmos_connection_string: str,
    model_path: str | None = None,
    **kwargs,
) -> Correlator:
    """Factory function to create and initialize correlator"""
    model = None
    if model_path:
        try:
            model = ConfidenceModel.load(model_path)
            logger.info(f"Loaded trained model from {model_path}")
        except Exception as e:
            logger.warning(f"Failed to load model from {model_path}: {e}. Using heuristic model.")
            model = HeuristicConfidenceModel()
    else:
        model = HeuristicConfidenceModel()
        logger.info("Using heuristic confidence model (no trained model provided)")

    correlator = Correlator(
        cosmos_connection_string=cosmos_connection_string,
        model=model,
        **kwargs,
    )

    await correlator.initialize()
    return correlator
