"""
Activity: Gather Context for Incident Response

Collects all relevant context for an incident:
- Recent changes from change history
- Blast radius from dependency graph
- Service metrics from Azure Monitor
- Recent logs
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, MetricsQueryClient
from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
import urllib.parse

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================
COSMOS_DB_ENDPOINT = os.getenv("COSMOS_DB_ENDPOINT")
COSMOS_DB_KEY = os.getenv("COSMOS_DB_KEY")
COSMOS_DB_DATABASE = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
COSMOS_DB_GRAPH = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")

LOG_ANALYTICS_WORKSPACE_ID = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
APPLICATION_INSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

# ============================================================
# Gremlin Client Helper
# ============================================================
async def _get_gremlin_client():
    """Get connected Gremlin client."""
    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    parsed = urllib.parse.urlparse(COSMOS_DB_ENDPOINT)
    host = parsed.netloc

    gremlin_client = client.Client(
        f"wss://{host}/gremlin",
        "g",
        username=f"/dbs/{COSMOS_DB_DATABASE}/colls/{COSMOS_DB_GRAPH}",
        password=COSMOS_DB_KEY,
        message_serializer=serializer.GraphSONSerializersV2d0()
    )

    connection = DriverRemoteConnection(
        f"wss://{host}/gremlin",
        "g",
        username=f"/dbs/{COSMOS_DB_DATABASE}/colls/{COSMOS_DB_GRAPH}",
        password=COSMOS_DB_KEY
    )

    g = traversal().withRemote(connection)
    return gremlin_client, connection, g


# ============================================================
# Activity: Gather Context for Incident Response
# ============================================================
async def main(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Gather context for incident correlation.

    Input:
    {
        "incident_id": "INC-123",
        "affected_service": "payment-service",
        "lookback_hours": 2,
        "correlation_id": "workflow-123"
    }

    Output:
    {
        "recent_changes": [...],
        "blast_radius": {...},
        "service_metrics": {...},
        "recent_logs": [...]
    }
    """
    incident_id = activity_input.get("incident_id")
    affected_service = activity_input.get("affected_service")
    lookback_hours = activity_input.get("lookback_hours", 2)
    correlation_id = activity_input.get("correlation_id")

    logger.info(f"Gathering context for incident {incident_id}, service {affected_service}")

    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    # Gather all context in parallel
    recent_changes = await _get_recent_changes(affected_service, lookback_hours)
    blast_radius = await _get_blast_radius(affected_service)
    service_metrics = await _get_service_metrics(affected_service, lookback_hours)
    recent_logs = await _get_recent_logs(affected_service, lookback_hours)

    return {
        "recent_changes": recent_changes,
        "blast_radius": blast_radius,
        "service_metrics": service_metrics,
        "recent_logs": recent_logs,
        "gathered_at": datetime.utcnow().isoformat(),
        "correlation_id": correlation_id
    }


async def _get_recent_changes(service_name: str, lookback_hours: int) -> list[dict[str, Any]]:
    """Query Cosmos DB change-history graph for recent changes."""
    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    try:
        gremlin_client, connection, g = await _get_gremlin_client()

        # Calculate timestamp threshold
        threshold = datetime.utcnow() - timedelta(hours=lookback_hours)
        threshold_iso = threshold.isoformat()

        # Gremlin query: Find change events for the affected service and its dependencies
        query = f"""
        g.V().hasLabel('ChangeEvent')
          .has('timestamp', gte('{threshold_iso}'))
          .order().by('timestamp', desc)
          .limit(50)
          .valueMap(true)
        """

        result_set = gremlin_client.submit(query)
        changes = list(result_set)

        gremlin_client.close()
        connection.close()

        logger.info(f"Found {len(changes)} recent changes")
        return changes

    except Exception as e:
        logger.error(f"Failed to gather recent changes: {e}")
        raise


async def _get_blast_radius(service_name: str) -> dict[str, Any]:
    """Query Gremlin dependency graph for blast radius."""
    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    try:
        gremlin_client, connection, g = await _get_gremlin_client()

        # Gremlin query: Find all services that depend on the affected service (reverse depends_on)
        query = f"""
        g.V().has('serviceName', '{service_name}')
          .repeat(__.in('depends_on').simplePath())
          .times(3)
          .emit()
          .dedup()
          .values('serviceName')
        """

        result_set = gremlin_client.submit(query)
        affected_services = list(result_set)

        # Also get paths for visualization
        path_query = f"""
        g.V().has('serviceName', '{service_name}')
          .repeat(__.in('depends_on').simplePath())
          .times(3)
          .emit()
          .path()
          .by('serviceName')
        """

        path_result = gremlin_client.submit(path_query)
        paths = list(path_result)

        gremlin_client.close()
        connection.close()

        return {
            "source_service": service_name,
            "affected_services": affected_services,
            "paths": paths,
            "total_services_affected": len(affected_services),
            "critical_services_affected": [s for s in affected_services if "checkout" in s or "payment" in s]
        }

    except Exception as e:
        logger.error(f"Failed to get blast radius: {e}")
        raise


async def _get_service_metrics(service_name: str, lookback_hours: int) -> dict[str, Any]:
    """Query Azure Monitor / Application Insights for service metrics."""
    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    try:
        credential = DefaultAzureCredential()
        logs_client = LogsQueryClient(credential)

        # Query Application Insights metrics via Log Analytics
        query = f"""
        requests
        | where TimeGenerated >= ago({lookback_hours}h)
        | where cloud_RoleName == '{service_name}'
        | summarize
            total=count(),
            failed=countif(success == false),
            latency_p99=percentile(duration, 99)
        | extend
            error_rate = failed * 1.0 / total,
            availability = 1.0 - (failed * 1.0 / total)
        | project error_rate, latency_p99, total, failed, availability
        """

        response = logs_client.query_workspace(
            workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
            query=query,
            timespan=timedelta(hours=lookback_hours)
        )

        if response.tables and response.tables[0].rows:
            row = response.tables[0].rows[0]
            return {
                "service_name": service_name,
                "error_rate": row[0],
                "latency_p99": row[1],
                "request_volume": row[2],
                "failed_requests": row[3],
                "availability": row[4],
                "timestamp": datetime.utcnow().isoformat()
            }

        raise ValueError(f"No metrics data found for service {service_name}")

    except Exception as e:
        logger.error(f"Failed to get service metrics: {e}")
        raise


async def _get_recent_logs(service_name: str, lookback_hours: int) -> list[dict[str, Any]]:
    """Query Log Analytics for recent error logs."""
    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    try:
        credential = DefaultAzureCredential()
        logs_client = LogsQueryClient(credential)

        # KQL query for recent errors
        query = f"""
        AppTraces
        | where TimeGenerated >= ago({lookback_hours}h)
        | where SeverityLevel >= 3  // ERROR = 3, CRITICAL = 4
        | where Cloud_RoleName == '{service_name}'
        | project TimeGenerated, SeverityLevel, Message, OperationId, ServiceName
        | order by TimeGenerated desc
        | limit 50
        """

        response = logs_client.query_workspace(
            workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
            query=query,
            timespan=timedelta(hours=lookback_hours)
        )

        logs = []
        if response.tables:
            for row in response.tables[0].rows:
                logs.append({
                    "timestamp": row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
                    "level": ["VERBOSE", "INFO", "WARNING", "ERROR", "CRITICAL"][row[1]] if row[1] < 5 else "UNKNOWN",
                    "message": row[2],
                    "trace_id": row[3],
                    "service": row[4]
                })

        return logs

    except Exception as e:
        logger.error(f"Failed to get recent logs: {e}")
        raise
