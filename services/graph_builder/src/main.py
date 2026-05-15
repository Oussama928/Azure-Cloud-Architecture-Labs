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
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds and updates the service dependency graph from traces."""
    
    def __init__(self):
        self.cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.cosmos_key = os.getenv("COSMOS_DB_KEY")
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
        self.graph_name = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")
        
        if self.cosmos_endpoint and self.cosmos_key:
            self.client = CosmosClient(self.cosmos_endpoint, self.cosmos_key)
            self.database = self.client.get_database_client(self.database_name)
            self.graph = self.database.get_graph_client(self.graph_name)
        else:
            self.client = None
            logger.warning("Cosmos DB not configured")
    
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
        
        # TODO: Query Application Insights for traces
        # This would use the Azure Monitor Query API
        # For now, return mock structure
        
        edges = await self._extract_edges_from_traces(lookback_hours)
        
        # Update graph in Cosmos DB
        updated = await self._update_graph(edges)
        
        return {
            "edges_processed": len(edges),
            "vertices_updated": updated["vertices"],
            "edges_updated": updated["edges"],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _extract_edges_from_traces(self, lookback_hours: int) -> List[Dict[str, Any]]:
        """Extract service-to-service edges from trace data."""
        
        # This would query Log Analytics:
        # traces
        # | where timestamp > ago({lookback_hours}h)
        # | where cloud_RoleName != ""
        # | summarize count() by cloud_RoleName, tostring(customDimensions['peer.service'])
        # | where count_ > {min_spans}
        
        # Mock edges for now
        return [
            {"source": "api-gateway", "target": "auth-service", "count": 1500, "latency_p99": 45},
            {"source": "api-gateway", "target": "payment-service", "count": 800, "latency_p99": 120},
            {"source": "payment-service", "target": "fraud-service", "count": 600, "latency_p99": 200},
            {"source": "payment-service", "target": "inventory-service", "count": 400, "latency_p99": 80},
            {"source": "order-service", "target": "payment-service", "count": 300, "latency_p99": 150},
        ]
    
    async def _update_graph(self, edges: List[Dict[str, Any]]) -> Dict[str, int]:
        """Update graph vertices and edges in Cosmos DB Gremlin."""
        
        if not self.graph:
            return {"vertices": 0, "edges": 0}
        
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
                self.graph.execute_query(query)
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
                self.graph.execute_query(query)
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
        if not self.graph:
            return {"affected_services": [], "paths": [], "hop_count": max_hops}
        
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
            
            result = self.graph.execute_query(query)
            paths = list(result)
            
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
    
    async def get_service_dependencies(
        self,
        service_name: str,
        direction: str = "both"  # "in", "out", "both"
    ) -> Dict[str, List[str]]:
        """Get direct dependencies for a service."""
        
        if not self.graph:
            return {"upstream": [], "downstream": []}
        
        try:
            upstream = []
            downstream = []
            
            if direction in ["in", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').in('depends_on').values('serviceName')"
                result = self.graph.execute_query(query)
                upstream = list(result)
            
            if direction in ["out", "both"]:
                query = f"g.V().has('serviceName', '{service_name}').out('depends_on').values('serviceName')"
                result = self.graph.execute_query(query)
                downstream = list(result)
            
            return {"upstream": upstream, "downstream": downstream}
        except Exception as e:
            logger.error(f"Failed to get dependencies: {e}")
            return {"upstream": [], "downstream": []}


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