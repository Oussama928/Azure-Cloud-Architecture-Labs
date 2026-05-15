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
from azure.monitor.query import LogsQueryClient

logger = logging.getLogger(__name__)


class OTELIngestor:
    """Ingests OpenTelemetry traces and builds dependency graph."""
    
    def __init__(self):
        self.workspace_id = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
        self.app_insights_connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        
        if self.workspace_id:
            credential = DefaultAzureCredential()
            self.logs_client = LogsQueryClient(credential)
        else:
            self.logs_client = None
    
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
            logger.warning("Log Analytics not configured, returning mock data")
            return await self._mock_ingest()
        
        # Query for traces
        query = self._build_trace_query(lookback_hours, min_spans)
        
        try:
            response = self.logs_client.query_workspace(
                workspace_id=self.workspace_id,
                query=query,
                timespan=timedelta(hours=lookback_hours)
            )
            
            edges = self._parse_trace_results(response)
            
            # Update graph (would call graph builder service)
            updated = await self._update_graph(edges)
            
            return {
                "edges_processed": len(edges),
                "services_discovered": len(set([e["source"] for e in edges] + [e["target"] for e in edges])),
                "updated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Trace ingestion failed: {e}")
            return {"error": str(e)}
    
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
        """Update dependency graph with new edges."""
        # This would call the graph builder service
        # For now only return mock result
        return {"vertices": 0, "edges": len(edges)}
    
    async def _mock_ingest(self) -> Dict[str, Any]:
        """Return mock ingestion result for development."""
        return {
            "edges_processed": 10,
            "services_discovered": 8,
            "updated_at": datetime.utcnow().isoformat(),
            "mock": True
        }


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