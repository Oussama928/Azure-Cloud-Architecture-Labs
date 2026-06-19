"""
OpenTelemetry Ingestion for Graph Builder

Ingests OpenTelemetry traces and extracts service dependencies.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, MetricsQueryClient
from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
import urllib.parse

logger = logging.getLogger(__name__)


class OTELIngestor:
    """Ingests OpenTelemetry traces and builds dependency graph."""
    
    def __init__(self):
        self.workspace_id = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
        self.app_insights_connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        
        if self.workspace_id:
            credential = DefaultAzureCredential()
            self.logs_client = LogsQueryClient(credential)
            self.metrics_client = MetricsQueryClient(credential)
        else:
            self.logs_client = None
            self.metrics_client = None
        
        # Gremlin client for graph updates
        self._gremlin_client = None
        self._connection = None
        self._g = None
    
    async def _connect_gremlin(self):
        """Establish connection to Cosmos DB Gremlin."""
        if self._g is not None:
            return
            
        endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        key = os.getenv("COSMOS_DB_KEY")
        database = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
        graph = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")
        
        if not endpoint or not key:
            raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")
        
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.netloc
        
        self._gremlin_client = client.Client(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{database}/colls/{graph}",
            password=key,
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        
        self._connection = DriverRemoteConnection(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{database}/colls/{graph}",
            password=key
        )
        
        self._g = traversal().withRemote(self._connection)
        logger.info("Connected to Cosmos DB Gremlin")
    
    async def _close_gremlin(self):
        """Close Gremlin connections."""
        if self._gremlin_client:
            self._gremlin_client.close()
        if self._connection:
            self._connection.close()
        self._g = None
    
    async def ingest_traces(
        self,
        lookback_hours: int = 1,
        min_spans: int = 10
    ) -> Dict[str, Any]:
        """
        Ingest traces from Application Insights / Log Analytics.
        
        Extracts service-to-service calls and updates dependency graph.
        """
        logger.info(f"Ingesting traces (lookback: {lookback_hours}h, min_spans: {min_spans})")
        
        if not self.logs_client:
            raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")
        
        await self._connect_gremlin()
        
        try:
            # Query for traces
            query = self._build_trace_query(lookback_hours, min_spans)
            
            response = self.logs_client.query_workspace(
                workspace_id=self.workspace_id,
                query=query,
                timespan=timedelta(hours=lookback_hours)
            )
            
            edges = self._parse_trace_results(response)
            
            # Update graph in Cosmos DB
            updated = await self._update_graph(edges)
            
            return {
                "edges_processed": len(edges),
                "services_discovered": len(set([e["source"] for e in edges] + [e["target"] for e in edges])),
                "updated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Trace ingestion failed: {e}")
            raise
        finally:
            await self._close_gremlin()
    
    def _build_trace_query(self, lookback_hours: int, min_spans: int) -> str:
        """Build KQL query for trace ingestion."""
        return f"""
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
    
    def _parse_trace_results(self, response) -> List[Dict[str, Any]]:
        """Parse KQL query results into edge list."""
        edges = []
        
        if response.tables:
            for table in response.tables:
                for row in table.rows:
                    edges.append({
                        "source": row[0],
                        "target": row[1],
                        "call_count": row[2],
                        "latency_p99": 0,  # Would need additional query
                        "timestamp": datetime.utcnow().isoformat()
                    })
        
        return edges
    
    async def _update_graph(self, edges: List[Dict[str, Any]]) -> Dict[str, int]:
        """Update dependency graph with new edges in Cosmos DB Gremlin."""
        
        if not self._gremlin_client:
            raise ValueError("Gremlin client not connected")
        
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
                property('callCount', {edge['call_count']}).
                property('latencyP99', {edge['latency_p99']}).
                property('updatedAt', '{datetime.utcnow().isoformat()}')
                """
                self._gremlin_client.submit(query).all().result()
                edges_updated += 1
            except Exception as e:
                logger.error(f"Failed to upsert edge {edge['source']}->{edge['target']}: {e}")
        
        return {"vertices": vertices_updated, "edges": edges_updated}
    
    async def close(self):
        """Close all connections."""
        if self._gremlin_client:
            self._gremlin_client.close()
        if self._connection:
            self._connection.close()
        self._g = None


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger for trace ingestion."""
    
    ingestor = OTELIngestor()
    
    try:
        body = req.get_json() if req.get_body() else {}
        lookback = body.get("lookback_hours", 1)
        min_spans = body.get("min_spans", 10)
        
        result = await ingestor.ingest_traces(lookback, min_spans)
        
        return func.HttpResponse(
            body=str(result),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"OTEL ingestion error: {e}")
        return func.HttpResponse(str(e), status_code=500)


# Timer trigger for periodic ingestion
async def timer_trigger(timer: func.TimerRequest) -> None:
    """Timer trigger to periodically ingest traces."""
    
    ingestor = OTELIngestor()
    result = await ingestor.ingest_traces(lookback_hours=1, min_spans=10)
    logger.info(f"Scheduled trace ingestion completed: {result}")