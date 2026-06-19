"""
Graph Builder Service for ChangeTrace

Builds and maintains the live service dependency graph from OpenTelemetry traces.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import azure.functions as func
from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
import urllib.parse

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds and updates the service dependency graph from traces."""
    
    def __init__(self):
        self.cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.cosmos_key = os.getenv("COSMOS_DB_KEY")
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
        self.graph_name = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")
        
        self._gremlin_client = None
        self._connection = None
        self._g = None
    
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
        min_spans: int = 10
    ) -> Dict[str, Any]:
        """
        Build dependency graph from OpenTelemetry traces.
        
        Queries Application Insights / Log Analytics for traces,
        extracts service-to-service calls, and updates the graph.
        """
        logger.info(f"Building graph from traces (lookback: {lookback_hours}h)")
        
        await self._connect()
        
        try:
            edges = await self._extract_edges_from_traces(lookback_hours, min_spans)
            updated = await self._update_graph(edges)
            
            return {
                "edges_processed": len(edges),
                "vertices_updated": updated["vertices"],
                "edges_updated": updated["edges"],
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            await self._close()
    
    async def _extract_edges_from_traces(
        self, 
        lookback_hours: int, 
        min_spans: int
    ) -> List[Dict[str, Any]]:
        """Extract service-to-service edges from trace data."""
        
        if not self._logs_client:
            raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

        try:
            credential = DefaultAzureCredential()
            self._logs_client = LogsQueryClient(credential)

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
                workspace_id=self._workspace_id,
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
    
    async def _update_graph(self, edges: List[Dict[str, Any]]) -> Dict[str, int]:
        """Update graph vertices and edges in Cosmos DB Gremlin."""
        
        vertices_updated = 0
        edges_updated = 0
        
        # Collect all unique services
        services = set()
        for edge in edges:
            services.add(edge["source"])
            services.add(edge["target"])
        
        # Upsert vertices (services)
        for service in services:
            try:
                query = f"""
                g.V().has('serviceName', '{service}').fold().
                coalesce(unfold(), addV('Service').property('serviceName', '{service}')).
                property('updatedAt', '{datetime.utcnow().isoformat()}').
                property('criticality', 'medium')
                """
                self._gremlin_client.submit(query).all().result()
                vertices_updated += 1
            except Exception as e:
                logger.error(f"Failed to upsert vertex {service}: {e}")
        
        # Upsert edges (dependencies)
        for edge in edges:
            try:
                query = f"""
                g.V().has('serviceName', '{edge['source']}').as('s').
                V().has('serviceName', '{edge['target']}').as('t').
                coalesce(
                    __.inE('depends_on').where(__.outV().as('s')),
                    __.addE('depends_on').from('s').to('t')
                ).
                property('callCount', {edge['count']}).
                property('latencyP99', {edge['latency_p99']}).
                property('updatedAt', '{datetime.utcnow().isoformat()}')
                """
                self._gremlin_client.submit(query).all().result()
                edges_updated += 1
            except Exception as e:
                logger.error(f"Failed to upsert edge {edge['source']}->{edge['target']}: {e}")
        
        return {"vertices": vertices_updated, "edges": edges_updated}
    
    async def compute_blast_radius(
        self,
        service_name: str,
        max_hops: int = 3
    ) -> Dict[str, Any]:
        """
        Compute blast radius from a service using graph traversal.
        
        Returns all services that depend on the given service (reverse dependencies).
        """
        await self._connect()
        
        try:
            query = f"""
            g.V().has('serviceName', '{service_name}').
            repeat(__.in('depends_on').simplePath()).
            times({max_hops}).
            emit().
            dedup().
            path().
            by('serviceName')
            """
            
            result_set = self._gremlin_client.submit(query)
            paths = list(result_set.all().result())
            
            # Extract unique affected services
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
            return {"affected_services": [], "paths": [], "error": str(e)}
        finally:
            await self._close()
    
    async def get_service_dependencies(
        self,
        service_name: str,
        direction: str = "both"  # "in", "out", "both"
    ) -> Dict[str, List[str]]:
        """Get direct dependencies for a service."""
        
        await self._connect()
        
        try:
            upstream = []
            downstream = []
            
            if direction in ["in", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').in('depends_on').values('serviceName')"
                result_set = self._gremlin_client.submit(query)
                upstream = list(result_set.all().result())
            
            if direction in ["out", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').out('depends_on').values('serviceName')"
                result_set = self._gremlin_client.submit(query)
                downstream = list(result_set.all().result())
            
            return {"upstream": upstream, "downstream": downstream}
        except Exception as e:
            logger.error(f"Failed to get dependencies: {e}")
            return {"upstream": [], "downstream": []}
        finally:
            await self._close()


# Azure Function entry points
async def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger for graph operations."""
    
    builder = GraphBuilder()
    action = req.params.get("action")
    
    try:
        if action == "build":
            lookback = int(req.params.get("lookback_hours", 1))
            result = await builder.build_from_traces(lookback_hours=lookback)
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
            result = await builder.compute_blast_radius(service, hops)
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
            result = await builder.get_service_dependencies(service, direction)
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
    result = await builder.build_from_traces(lookback_hours=1)
    logger.info(f"Graph update completed: {result}")