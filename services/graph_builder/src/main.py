"""Graph Builder Service for ChangeTrace."""

import asyncio
import logging
import os
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import azure.functions as func
from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __

from azure.identity import DefaultAzureCredential
from services.shared.cosmos import get_cosmos_config_from_env

logger = logging.getLogger(__name__)

_thread_local = threading.local()
_gremlin_executor = None


def _get_executor():
    global _gremlin_executor
    if _gremlin_executor is None:
        _gremlin_executor = ThreadPoolExecutor(max_workers=4)
    return _gremlin_executor


def _connect_client():
    """Create and return a new Gremlin client (used within thread executor)."""
    config = get_cosmos_config_from_env()
    if not config["endpoint"] or not config["key"]:
        raise ValueError("Cosmos DB credentials not configured")
    parsed = urllib.parse.urlparse(config["endpoint"])
    host = parsed.netloc
    return client.Client(
        f"wss://{host}/gremlin",
        "g",
        username=f"/dbs/{config['database']}/colls/{config['graph']}",
        password=config["key"],
        message_serializer=serializer.GraphSONSerializersV2d0()
    )


def _run_gremlin_query(query: str) -> list:
    """Run a Gremlin query in a thread and return all results."""
    if not hasattr(_thread_local, "client") or _thread_local.client is None:
        _thread_local.client = _connect_client()
    rs = _thread_local.client.submit(query)
    return rs.all().result()


class GraphBuilder:
    """Builds and updates the service dependency graph from traces."""
    
    def __init__(self):
        config = get_cosmos_config_from_env()
        self.cosmos_endpoint = config["endpoint"]
        self.cosmos_key = config["key"]
        self.database_name = config["database"]
        self.graph_name = config["graph"]
        
        self._gremlin_client = None
        self._connection = None
        self._g = None
        self._logs_client = None
        self._workspace_id = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
    
    async def _connect(self):
        """Establish Gremlin connection."""
        if self._g is not None:
            return
            
        if not self.cosmos_endpoint or not self.cosmos_key:
            raise ValueError("Cosmos DB credentials not configured")
        
        parsed = urllib.parse.urlparse(self.cosmos_endpoint)
        host = parsed.netloc
        
        self._gremlin_client = client.Client(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{self.database_name}/colls/{self.graph_name}",
            password=self.cosmos_key,
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        
        self._connection = DriverRemoteConnection(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{self.database_name}/colls/{self.graph_name}",
            password=self.cosmos_key
        )
        
        self._g = traversal().withRemote(self._connection)
        logger.info("Connected to Cosmos DB Gremlin")
    
    async def _close(self):
        """Close connections."""
        if self._gremlin_client:
            self._gremlin_client.close()
        if self._connection:
            self._connection.close()
        self._g = None
    
    async def build_from_traces(
        self,
        lookback_hours: int = 1,
        min_spans: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Dict[str, Any]:
        """Build dependency graph from OpenTelemetry traces."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        logger.info(f"Building graph from traces (lookback: {lookback_hours}h, tenant: {tenant_id})")
        
        await self._connect()
        
        try:
            edges = await self._extract_edges_from_traces(lookback_hours, min_spans, workspace_id=workspace_id)
            updated = await self._update_graph(edges, tenant_id=tenant_id)
            
            return {
                "edges_processed": len(edges),
                "vertices_updated": updated["vertices"],
                "edges_updated": updated["edges"],
                "timestamp": datetime.utcnow().isoformat(),
                "tenant_id": tenant_id,
            }
        finally:
            await self._close()
    
    async def build_from_change_events(
        self,
        tenant_id: str,
        lookback_hours: int = 24,
        min_events: int = 1,
    ) -> Dict[str, Any]:
        """
        Build dependency graph for a tenant from their ChangeEvent vertices.

        This is the primary self-serve path for SaaS clients: services and
        dependency edges are derived from the change events the collector has
        stored under the tenant's id, so a client's graph reflects their own
        data without sharing a Log Analytics workspace.

        Service vertices are upserted with the tenant's id; edges are inferred
        from change events that reference related services (e.g. a deployment
        whose source/target context spans multiple services).
        """
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        logger.info(f"Building graph from change events (tenant: {tenant_id})")

        await self._connect()

        try:
            loop = asyncio.get_running_loop()
            executor = _get_executor()

            query = (
                f"g.V().hasLabel('ChangeEvent')"
                f".has('tenantId', '{tenant_id}')"
                f".has('timestamp', gte('{(datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()}'))"
                f".valueMap(true)"
            )
            raw = await loop.run_in_executor(executor, _run_gremlin_query, query)

            services: set[str] = set()
            edges: list[Dict[str, Any]] = []
            seen_edges: set[tuple[str, str]] = set()

            for result in raw:
                props = {k: (v[0] if isinstance(v, list) else v) for k, v in result.items()}
                svc = props.get("serviceName")
                if not svc:
                    continue
                services.add(svc)

                related = self._related_services(props)
                for target in related:
                    if target == svc:
                        continue
                    key = (svc, target)
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edges.append({
                        "source": svc,
                        "target": target,
                        "count": 1,
                        "latency_p99": 0,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

            # If a service has no related services, still ensure its vertex exists
            updated = await self._update_graph(edges, tenant_id=tenant_id, extra_services=list(services))

            return {
                "edges_processed": len(edges),
                "vertices_updated": updated["vertices"],
                "edges_updated": updated["edges"],
                "services": sorted(services),
                "timestamp": datetime.utcnow().isoformat(),
                "tenant_id": tenant_id,
            }
        finally:
            await self._close()

    @staticmethod
    def _related_services(props: Dict[str, Any]) -> set[str]:
        """Extract related service names from a change event's properties."""
        related: set[str] = set()
        blast = props.get("blastRadiusServices")
        if blast:
            if isinstance(blast, str):
                import json
                try:
                    blast = json.loads(blast)
                except (ValueError, TypeError):
                    blast = []
            if isinstance(blast, list):
                related.update(str(s) for s in blast)
        return related

    async def _extract_edges_from_traces(
        self, 
        lookback_hours: int, 
        min_spans: int,
        workspace_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Extract service-to-service edges from trace data."""
        
        workspace_id = workspace_id or self._workspace_id
        if not workspace_id:
            raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

        if not self._logs_client:
            from azure.monitor.query import LogsQueryClient
            credential = DefaultAzureCredential()
            self._logs_client = LogsQueryClient(credential)

        try:

            # KQL query for trace ingestion
            query = f"""
            traces
            | where timestamp > ago({lookback_hours}h)
            | where cloud_RoleName != ""
            | extend source = cloud_RoleName
            | extend target = tostring(customDimensions['peer.service'])
            | where isnotempty(target)
            | summarize call_count = count() by source, target
            | where call_count >= {min_spans}
            | project source, target, call_count
            """

            response = self._logs_client.query_workspace(
                workspace_id=workspace_id,
                query=query,
                timespan=timedelta(hours=lookback_hours)
            )

            edges = []
            if response.tables:
                for table in response.tables:
                    for row in table.rows:
                        edges.append({
                            "source": row[0],
                            "target": row[1],
                            "count": row[2],
                            "latency_p99": 0,  # Would need additional query
                            "timestamp": datetime.utcnow().isoformat()
                        })

            return edges

        except Exception as e:
            logger.error(f"Trace ingestion failed: {e}")
            raise
    
    async def _update_graph(self, edges: List[Dict[str, Any]], tenant_id: str | None = None, extra_services: List[str] | None = None) -> Dict[str, int]:
        """Update graph vertices and edges in Cosmos DB Gremlin."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        loop = asyncio.get_running_loop()
        executor = _get_executor()

        vertices_updated = 0
        edges_updated = 0
        
        services = set()
        for edge in edges:
            services.add(edge["source"])
            services.add(edge["target"])
        if extra_services:
            services.update(extra_services)
        
        # Upsert vertices (services)
        for service in services:
            try:
                query = f"""
                g.V().hasLabel('Service').has('serviceName', '{service}').has('tenantId', '{tenant_id}').fold().
                coalesce(unfold(), addV('Service').
                    property('serviceName', '{service}').
                    property('tenantId', '{tenant_id}')).
                property('updatedAt', '{datetime.utcnow().isoformat()}').
                coalesce(properties('criticality'), property('criticality', 'medium')).
                coalesce(properties('namespace'), property('namespace', 'production'))
                """
                await loop.run_in_executor(executor, _run_gremlin_query, query)
                vertices_updated += 1
            except Exception as e:
                logger.error(f"Failed to upsert vertex {service}: {e}")
        
        # Upsert edges (dependencies)
        for edge in edges:
            now = datetime.utcnow().isoformat()
            source = edge['source']
            target = edge['target']
            count = edge['count']
            latency = edge.get('latency_p99', 0)
            try:
                # 1) Create the edge only if it does not already exist, applying
                #    properties inside the addE branch (Cosmos rejects
                #    coalesce(...).property(...) on a produced edge).
                create_query = f"""
                g.V().hasLabel('Service').has('serviceName', '{source}').has('tenantId', '{tenant_id}').as('s').
                V().hasLabel('Service').has('serviceName', '{target}').has('tenantId', '{tenant_id}').as('t').
                coalesce(
                    __.inE('depends_on').where(__.outV().as('s')),
                    __.addE('depends_on').from('s').to('t').
                        property('tenantId', '{tenant_id}').
                        property('callCount', {count}).
                        property('latencyP99', {latency}).
                        property('updatedAt', '{now}')
                )
                """
                await loop.run_in_executor(executor, _run_gremlin_query, create_query)

                # 2) Update properties on the (now existing) edge.
                update_query = f"""
                g.V().hasLabel('Service').has('serviceName', '{source}').has('tenantId', '{tenant_id}').
                outE('depends_on').
                where(otherV().hasLabel('Service').has('serviceName', '{target}').has('tenantId', '{tenant_id}')).
                property('callCount', {count}).
                property('latencyP99', {latency}).
                property('updatedAt', '{now}')
                """
                await loop.run_in_executor(executor, _run_gremlin_query, update_query)
                edges_updated += 1
            except Exception as e:
                logger.error(f"Failed to upsert edge {source}->{target}: {e}")
        
        return {"vertices": vertices_updated, "edges": edges_updated}
    
    async def compute_blast_radius(
        self,
        service_name: str,
        max_hops: int = 3,
        tenant_id: str | None = None,
    ) -> Dict[str, Any]:
        """Compute blast radius from a service using graph traversal."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        loop = asyncio.get_running_loop()
        executor = _get_executor()
        
        try:
            query = f"""
            g.V().has('serviceName', '{service_name}').has('tenantId', '{tenant_id}').
            repeat(__.in('depends_on').simplePath()).
            times({max_hops}).
            emit().
            dedup().
            path().
            by('serviceName')
            """
            
            paths = await loop.run_in_executor(executor, _run_gremlin_query, query)
            
            affected = set()
            for path in paths:
                for service in path:
                    if service != service_name:
                        affected.add(service)
            
            return {
                "source_service": service_name,
                "affected_services": list(affected),
                "paths": paths,
                "hop_count": max_hops,
                "total_affected": len(affected)
            }
        except Exception as e:
            logger.error(f"Blast radius computation failed: {e}")
            return {
                "source_service": service_name,
                "affected_services": [],
                "paths": [],
                "hop_count": max_hops,
                "total_affected": 0,
                "error": str(e),
            }
    
    async def get_service_dependencies(
        self,
        service_name: str,
        direction: str = "both",  # "in", "out", "both"
        tenant_id: str | None = None,
    ) -> Dict[str, List[str]]:
        """Get direct dependencies for a service."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        loop = asyncio.get_running_loop()
        executor = _get_executor()
        
        try:
            upstream = []
            downstream = []
            
            if direction in ["in", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').has('tenantId', '{tenant_id}').in('depends_on').values('serviceName')"
                upstream = await loop.run_in_executor(executor, _run_gremlin_query, query)
            
            if direction in ["out", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').has('tenantId', '{tenant_id}').out('depends_on').values('serviceName')"
                downstream = await loop.run_in_executor(executor, _run_gremlin_query, query)
            
            return {"upstream": upstream, "downstream": downstream}
        except Exception as e:
            logger.error(f"Failed to get dependencies: {e}")
            return {"upstream": [], "downstream": []}


# Azure Function entry points
async def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger for graph operations."""
    
    builder = GraphBuilder()
    action = req.params.get("action")
    tenant_id = req.params.get("tenant_id") or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
    
    try:
        if action == "build":
            lookback = int(req.params.get("lookback_hours", 1))
            result = await builder.build_from_traces(lookback_hours=lookback, tenant_id=tenant_id)
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == "build-from-events":
            lookback = int(req.params.get("lookback_hours", 24))
            result = await builder.build_from_change_events(tenant_id=tenant_id, lookback_hours=lookback)
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == "blast-radius":
            service = req.params.get("service")
            hops = int(req.params.get("hops", 3))
            if not service:
                return func.HttpResponse("service parameter required", status_code=400)
            result = await builder.compute_blast_radius(service, hops, tenant_id=tenant_id)
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == "dependencies":
            service = req.params.get("service")
            direction = req.params.get("direction", "both")
            if not service:
                return func.HttpResponse("service parameter required", status_code=400)
            result = await builder.get_service_dependencies(service, direction, tenant_id=tenant_id)
            return func.HttpResponse(
                body=str(result),
                status_code=200,
                mimetype="application/json"
            )
        
        else:
            return func.HttpResponse("Invalid action", status_code=400)
            
    except Exception as e:
        logger.error(f"Graph builder error: {e}")
        return func.HttpResponse(str(e), status_code=500)


# Timer trigger for periodic graph updates
async def timer_trigger(timer: func.TimerRequest) -> None:
    """Timer trigger to periodically rebuild graph from traces."""

    builder = GraphBuilder()
    tenant_id = os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
    result = await builder.build_from_change_events(tenant_id=tenant_id, lookback_hours=24)
    logger.info(f"Graph update completed: {result}")
