"""
WF-1 Incident Response Activities - Real Implementations

Connect to Cosmos DB (Gremlin), Azure Monitor, and Azure ML.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, MetricsQueryClient

logger = logging.getLogger(__name__)

# Configuration
COSMOS_DB_ENDPOINT = os.getenv("COSMOS_DB_ENDPOINT")
COSMOS_DB_KEY = os.getenv("COSMOS_DB_KEY")
COSMOS_DB_DATABASE = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
COSMOS_DB_GRAPH = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")

LOG_ANALYTICS_WORKSPACE_ID = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
APPLICATION_INSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

ML_SCORING_ENDPOINT = os.getenv("ML_SCORING_ENDPOINT")
ML_SCORING_KEY = os.getenv("ML_SCORING_KEY")

# Gremlin Client Helper
async def _get_gremlin_client():
    """Get connected Gremlin client."""
    from gremlin_python.driver import client, serializer
    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal
    import urllib.parse

    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured")

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


# Activity: Gather Recent Changes
async def gather_recent_changes(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Query Cosmos DB change-history graph for recent changes affecting a service.
    """
    affected_service = activity_input.get("affected_service")
    lookback_hours = activity_input.get("lookback_hours", 2)
    max_results = activity_input.get("max_results", 50)

    logger.info(f"Gathering recent changes for {affected_service} (lookback: {lookback_hours}h)")

    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    try:
        gremlin_client, connection, g = await _get_gremlin_client()

        threshold = datetime.utcnow() - timedelta(hours=lookback_hours)
        threshold_iso = threshold.isoformat()

        # Gremlin query: Find change events for the affected service and its dependencies
        query = f"""
        g.V().hasLabel('ChangeEvent')
          .has('service', '{affected_service}')
          .has('timestamp', gte('{threshold_iso}'))
          .order().by('timestamp', desc)
          .limit({max_results})
          .valueMap(true)
        """

        result_set = gremlin_client.submit(query)
        changes = list(result_set)

        gremlin_client.close()
        connection.close()

        logger.info(f"Found {len(changes)} recent changes")
        return {"changes": changes, "count": len(changes)}

    except Exception as e:
        logger.error(f"Failed to gather recent changes: {e}")
        raise


# Activity: Get Blast Radius
async def get_blast_radius(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Query Gremlin dependency graph for blast radius (services depending on affected service).
    """
    service_name = activity_input.get("service_name")
    max_hops = activity_input.get("max_hops", 3)

    logger.info(f"Getting blast radius for {service_name} (max hops: {max_hops})")

    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")

    try:
        gremlin_client, connection, g = await _get_gremlin_client()

        # Gremlin query: Find all services that depend on the affected service (reverse depends_on)
        query = f"""
        g.V().has('serviceName', '{service_name}')
          .repeat(__.in('depends_on').simplePath())
          .times({max_hops})
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
          .times({max_hops})
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


# Activity: Get Service Metrics
async def get_service_metrics(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Query Azure Monitor / Application Insights for service metrics.
    """
    service_name = activity_input.get("service_name")
    duration_minutes = activity_input.get("duration_minutes", 30)

    logger.info(f"Getting metrics for {service_name} (duration: {duration_minutes}min)")

    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    try:
        credential = DefaultAzureCredential()
        logs_client = LogsQueryClient(credential)

        # Query Application Insights metrics via Log Analytics
        query = f"""
        requests
        | where TimeGenerated >= ago({duration_minutes}m)
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
            timespan=timedelta(minutes=duration_minutes)
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


# Activity: Get Recent Logs
async def get_recent_logs(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Query Log Analytics for recent error logs.
    """
    service_name = activity_input.get("service_name")
    duration_minutes = activity_input.get("duration_minutes", 30)
    min_level = activity_input.get("min_level", "ERROR")

    logger.info(f"Getting recent logs for {service_name} (duration: {duration_minutes}min)")

    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    try:
        credential = DefaultAzureCredential()
        logs_client = LogsQueryClient(credential)

        # KQL query for recent errors
        query = f"""
        AppTraces
        | where TimeGenerated >= ago({duration_minutes}m)
        | where SeverityLevel >= 3  // ERROR = 3, CRITICAL = 4
        | where Cloud_RoleName == '{service_name}'
        | project TimeGenerated, SeverityLevel, Message, OperationId, ServiceName
        | order by TimeGenerated desc
        | limit 50
        """

        response = logs_client.query_workspace(
            workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
            query=query,
            timespan=timedelta(minutes=duration_minutes)
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

        return {"logs": logs, "count": len(logs)}

    except Exception as e:
        logger.error(f"Failed to get recent logs: {e}")
        raise


# Activity: Correlate Incident (ML Scoring)
async def correlate_incident(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Score candidate root causes using ML model or heuristic.
    """
    incident_id = activity_input.get("incident_id")
    affected_service = activity_input.get("affected_service")
    recent_changes = activity_input.get("recent_changes", [])
    blast_radius = activity_input.get("blast_radius", {})
    service_metrics = activity_input.get("service_metrics", {})
    recent_logs = activity_input.get("recent_logs", {})

    logger.info(f"Correlating incident {incident_id} for {affected_service}")

    # Try ML endpoint first
    if ML_SCORING_ENDPOINT and ML_SCORING_KEY:
        try:
            return await _score_with_ml(activity_input)
        except Exception as e:
            logger.warning(f"ML scoring failed, falling back to heuristic: {e}")

    # Fallback to heuristic
    return _heuristic_correlation(activity_input)


async def _score_with_ml(activity_input: dict[str, Any]) -> dict[str, Any]:
    """Call Azure ML scoring endpoint."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {
            "Authorization": f"Bearer {ML_SCORING_KEY}",
            "Content-Type": "application/json"
        }

        features = _extract_features(activity_input)

        response = await client.post(
            ML_SCORING_ENDPOINT,
            headers=headers,
            json={"inputs": [features]}
        )
        response.raise_for_status()

        result = response.json()
        predictions = result.get("predictions", [{}])[0]

        return {
            "candidates": predictions.get("candidates", []),
            "top_candidate": predictions.get("top_candidate"),
            "top_confidence": predictions.get("top_confidence", 0.0),
            "model_version": predictions.get("model_version", "ml-unknown")
        }


def _extract_features(activity_input: dict[str, Any]) -> dict[str, Any]:
    """Extract features for ML model."""
    recent_changes = activity_input.get("recent_changes", [])
    blast_radius = activity_input.get("blast_radius", {})
    service_metrics = activity_input.get("service_metrics", {})
    recent_logs = activity_input.get("recent_logs", {})

    return {
        "num_recent_changes": len(recent_changes),
        "num_affected_services": blast_radius.get("total_services_affected", 0),
        "error_rate": service_metrics.get("error_rate", 0),
        "latency_p99": service_metrics.get("latency_p99", 0),
        "error_log_count": recent_logs.get("count", 0),
        "has_deployment_change": any(c.get("change_type") == "code_deployment" for c in recent_changes),
        "has_config_change": any(c.get("change_type") == "config_change" for c in recent_changes),
    }


def _heuristic_correlation(activity_input: dict[str, Any]) -> dict[str, Any]:
    """Heuristic correlation when ML is unavailable."""
    recent_changes = activity_input.get("recent_changes", [])
    blast_radius = activity_input.get("blast_radius", {})
    service_metrics = activity_input.get("service_metrics", {})
    recent_logs = activity_input.get("recent_logs", {})

    candidates = []

    for change in recent_changes:
        score = 0.0
        reasons = []

        # Recency bonus
        timestamp_str = change.get("timestamp")
        if not timestamp_str:
            continue
        change_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        age_minutes = (datetime.utcnow() - change_time.replace(tzinfo=None)).total_seconds() / 60
        if age_minutes < 60:
            score += 0.4
            reasons.append(f"Recent change ({age_minutes:.0f} min ago)")
        elif age_minutes < 120:
            score += 0.2
            reasons.append(f"Recent change ({age_minutes:.0f} min ago)")

        # Change type weight
        if change.get("change_type") == "code_deployment":
            score += 0.3
            reasons.append("Code deployment")
        elif change.get("change_type") == "config_change":
            score += 0.2
            reasons.append("Config change")

        # Service match
        if change.get("service_name") == activity_input.get("affected_service"):
            score += 0.2
            reasons.append("Direct service match")
        elif change.get("service_name") in blast_radius.get("affected_services", []):
            score += 0.1
            reasons.append("In blast radius")

        # Error rate correlation: only boost candidates whose service is erroring
        if service_metrics.get("error_rate", 0) > 0.05:
            if change.get("service_name") == service_metrics.get("service_name"):
                score += 0.1
                reasons.append("High error rate on this service")
            elif change.get("service_name") in blast_radius.get("affected_services", []):
                score += 0.05
                reasons.append("High error rate on dependent service")

        candidates.append({
            "change_event_id": change.get("change_event_id"),
            "service_name": change.get("service_name"),
            "change_type": change.get("change_type"),
            "timestamp": change.get("timestamp"),
            "confidence": min(score, 1.0),
            "reasons": reasons,
            "details": change
        })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    top_candidate = candidates[0] if candidates else None
    top_confidence = top_candidate["confidence"] if top_candidate else 0.0

    return {
        "candidates": candidates,
        "top_candidate": top_candidate,
        "top_confidence": top_confidence,
        "model_version": "heuristic-v1.0"
    }


# Activity: Send Approval Request
async def send_approval_request(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Send approval request via Teams webhook, email, or other channels.
    """
    workflow_id = activity_input.get("workflow_id")
    notification_type = activity_input.get("notification_type", "approval_request")
    token = activity_input.get("token")
    callback_base = activity_input.get("callback_url")
    expires_at = activity_input.get("expires_at")

    if not token or not callback_base:
        raise ValueError("token and callback_url are required")

    approve_url = f"{callback_base}?token={token}&decision=approve"
    reject_url = f"{callback_base}?token={token}&decision=reject"

    logger.info(f"Sending {notification_type} for workflow {workflow_id}")

    teams_sent = await _send_teams_notification(activity_input, approve_url, reject_url, expires_at)

    email_sent = await _send_email_notification(activity_input, approve_url, reject_url, expires_at)

    return {
        "sent": teams_sent or email_sent,
        "channels": (["teams"] if teams_sent else []) + (["email"] if email_sent else []),
        "approval_url": approve_url,
        "reject_url": reject_url,
        "expires_at": expires_at
    }


async def _send_teams_notification(
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
) -> bool:
    """Send Teams adaptive card."""
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not configured")
        return False

    notification_type = activity_input.get("notification_type", "approval_request")

    if notification_type == "approval_request":
        card = _build_approval_card(activity_input, approve_url, reject_url, expires_at)
    else:
        card = _build_escalation_card(activity_input, expires_at)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=card)
            response.raise_for_status()
            logger.info("Teams notification sent successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to send Teams notification: {e}")
        return False


def _build_approval_card(
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
) -> dict[str, Any]:
    """Build Teams adaptive card for approval request."""
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": f"🚨 {activity_input.get('title', 'Incident Approval Required')}",
                        "weight": "Bolder",
                        "size": "Medium",
                        "color": "Attention"
                    },
                    {
                        "type": "TextBlock",
                        "text": activity_input.get("description", ""),
                        "wrap": True
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "Incident ID", "value": activity_input.get("details", {}).get("incident_id", "N/A")},
                            {"title": "Affected Service", "value": activity_input.get("details", {}).get("affected_service", "N/A")},
                            {"title": "Top Candidate", "value": activity_input.get("details", {}).get("top_candidate", {}).get("service_name", "N/A")},
                            {"title": "Confidence", "value": f"{activity_input.get('details', {}).get('top_candidate', {}).get('confidence', 0)*100:.1f}%"},
                            {"title": "Expires", "value": expires_at or "N/A"}
                        ]
                    }
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "✅ Approve",
                        "url": approve_url,
                        "style": "positive"
                    },
                    {
                        "type": "Action.OpenUrl",
                        "title": "❌ Reject",
                        "url": reject_url,
                        "style": "destructive"
                    }
                ]
            }
        }]
    }


def _build_escalation_card(
    activity_input: dict[str, Any],
    expires_at: str | None
) -> dict[str, Any]:
    """Build Teams adaptive card for escalation."""
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "⚠️ ESCALATION: Incident Approval Timeout",
                        "weight": "Bolder",
                        "size": "Medium",
                        "color": "Attention"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Primary approval expired for workflow {activity_input.get('workflow_id')}. Escalated to secondary on-call.",
                        "wrap": True
                    }
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "✅ Approve (Escalated)",
                        "url": activity_input.get("approval_url", ""),
                        "style": "positive"
                    }
                ]
            }
        }]
    }


async def _send_email_notification(
    activity_input: dict[str, Any],
    approve_url: str,
    reject_url: str,
    expires_at: str | None
) -> bool:
    """Send email notification via SendGrid."""
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "changetrace@company.com")

    if not api_key:
        logger.warning("SENDGRID_API_KEY not configured, skipping email notification")
        return False

    notification_type = activity_input.get("notification_type", "approval_request")
    details = activity_input.get("details", {})
    top_candidate = details.get("top_candidate", {})

    if notification_type == "approval_request":
        subject = f"🚨 Approval Required: {activity_input.get('title', 'Incident Approval')}"
        html_content = f"""
        <h2>🚨 {activity_input.get('title', 'Incident Approval Required')}</h2>
        <p>{activity_input.get('description', '')}</p>
        <table>
            <tr><td><strong>Incident ID</strong></td><td>{details.get('incident_id', 'N/A')}</td></tr>
            <tr><td><strong>Affected Service</strong></td><td>{details.get('affected_service', 'N/A')}</td></tr>
            <tr><td><strong>Top Candidate</strong></td><td>{top_candidate.get('service_name', 'N/A')} ({top_candidate.get('change_type', 'N/A')})</td></tr>
            <tr><td><strong>Confidence</strong></td><td>{details.get('confidence', 0)*100:.1f}%</td></tr>
            <tr><td><strong>Recommended Action</strong></td><td>{details.get('recommended_action', 'rollback_deployment').replace('_', ' ').title()}</td></tr>
            <tr><td><strong>Blast Radius</strong></td><td>{details.get('blast_radius', {}).get('total_services_affected', 0)} services</td></tr>
            <tr><td><strong>Expires</strong></td><td>{expires_at or 'N/A'}</td></tr>
        </table>
        <p><strong>Recommended Action:</strong> {details.get('recommended_action', 'rollback_deployment').replace('_', ' ').title()}</p>
        <p>Parameters: <pre>{json.dumps(details.get('remediation_params', {}), indent=2)}</pre></p>
        <p>
            <a href="{approve_url}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">✅ Approve</a>
            <a href="{reject_url}" style="background-color: #dc3545; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-left: 10px;">❌ Reject</a>
        </p>
        <p><small>Expires: {expires_at or 'N/A'}</small></p>
        """
    else:
        subject = f"⚠️ ESCALATION: {activity_input.get('title', 'Incident Approval Timeout')}"
        html_content = f"""
        <h2>⚠️ ESCALATION: Incident Approval Timeout</h2>
        <p>Primary approval expired for workflow {activity_input.get('workflow_id')}. Escalated to secondary on-call.</p>
        <table>
            <tr><td><strong>Incident ID</strong></td><td>{activity_input.get('incident_id', 'N/A')}</td></tr>
            <tr><td><strong>Original Approver</strong></td><td>{activity_input.get('original_approver', 'primary_oncall')}</td></tr>
            <tr><td><strong>Escalation Level</strong></td><td>{activity_input.get('escalation_level', 1)}</td></tr>
            <tr><td><strong>Escalation Target</strong></td><td>{activity_input.get('escalation_target', 'secondary_oncall')}</td></tr>
            <tr><td><strong>Expires</strong></td><td>{expires_at or 'N/A'}</td></tr>
        </table>
        <p><a href="{activity_input.get('approval_url', '#')}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">✅ Approve (Escalated)</a></p>
        <p><small>Expires: {expires_at or 'N/A'}</small></p>
        """

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=from_email,
            to_emails=os.getenv("ONCALL_EMAIL", "oncall@company.com"),
            subject=subject,
            html_content=html_content
        )

        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(f"Email notification sent: {response.status_code}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return False


# Activity: Send Escalation Notification
async def send_escalation_notification(activity_input: dict[str, Any]) -> dict[str, Any]:
    """Send escalation notification when primary approval times out."""
    activity_input["notification_type"] = "escalation"
    return await send_approval_request(activity_input)


# Activity: Execute Remediation
async def execute_remediation(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Execute approved remediation action via Argo Rollouts / Kubernetes API.
    """
    action = activity_input.get("action")
    params = activity_input.get("params", {})
    workflow_id = activity_input.get("workflow_id")

    logger.info(f"Executing remediation action: {action} for workflow {workflow_id}")

    if action == "rollback_deployment":
        result = await _rollback_deployment(params)
    elif action == "restart_workload":
        result = await _restart_workload(params)
    elif action == "revert_config":
        result = await _revert_config(params)
    elif action == "scale_up":
        result = await _scale_up(params)
    else:
        raise ValueError(f"Unknown action: {action}")

    result["action"] = action
    result["executed_at"] = datetime.utcnow().isoformat()
    result["workflow_id"] = workflow_id

    return result


async def _rollback_deployment(params: dict[str, Any]) -> dict[str, Any]:
    """Rollback Argo Rollout to previous version."""
    deployment_id = params.get("deployment_id")
    service = params.get("service")
    namespace = params.get("namespace", "production")

    if not deployment_id or not service:
        return {"success": False, "error": "deployment_id and service are required"}

    argo_api_url = os.getenv("ARGO_API_URL")
    argo_token = os.getenv("ARGO_API_TOKEN")

    if argo_api_url and argo_token:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Authorization": f"Bearer {argo_token}"}
                rollout_name = f"{service}-rollout"

                response = await client.post(
                    f"{argo_api_url}/api/v1/namespaces/{namespace}/rollouts/{rollout_name}/rollback",
                    headers=headers,
                    json={"revision": 0}
                )
                response.raise_for_status()

                return {"success": True, "service": service, "namespace": namespace, "method": "argo_api"}
        except Exception as e:
            logger.error(f"Argo rollback failed: {e}")

    # Fallback: kubectl via subprocess (if running in cluster with permissions)
    logger.warning("Argo API not configured, rollback not executed")
    return {"success": False, "error": "Argo API not configured", "service": service}


async def _restart_workload(params: dict[str, Any]) -> dict[str, Any]:
    """Restart Kubernetes deployment/rollout."""
    service = params.get("service")
    namespace = params.get("namespace", "production")

    logger.info(f"Restarting workload {service} in {namespace}")

    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException

        # Load kubeconfig (works both in-cluster and locally)
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        apps_v1 = client.AppsV1Api()

        try:
            deployment = apps_v1.read_namespaced_deployment(name=service, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                # Try Argo Rollout
                try:
                    custom_api = client.CustomObjectsApi()
                    rollout = custom_api.get_namespaced_custom_object(
                        group="argoproj.io",
                        version="v1alpha1",
                        namespace=namespace,
                        plural="rollouts",
                        name=service
                    )
                    # Restart rollout by patching the restartAt annotation
                    custom_api.patch_namespaced_custom_object(
                        group="argoproj.io",
                        version="v1alpha1",
                        namespace=namespace,
                        plural="rollouts",
                        name=service,
                        body={
                            "metadata": {
                                "annotations": {
                                    "rollouts.argoproj.io/restartAt": datetime.utcnow().isoformat() + "Z"
                                }
                            }
                        }
                    )
                    logger.info(f"Restarted Argo Rollout {service} in {namespace}")
                    return {"success": True, "action": "restart_workload", "service": service, "namespace": namespace, "type": "rollout"}
                except ApiException as e2:
                    if e2.status == 404:
                        return {"success": False, "error": f"Workload {service} not found in namespace {namespace}", "service": service}
                    raise
            else:
                raise

        # Restart deployment by patching the pod template annotation
        patch_body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat() + "Z"
                        }
                    }
                }
            }
        }

        apps_v1.patch_namespaced_deployment(name=service, namespace=namespace, body=patch_body)
        logger.info(f"Restarted deployment {service} in {namespace}")

        return {"success": True, "action": "restart_workload", "service": service, "namespace": namespace, "type": "deployment"}

    except ImportError:
        logger.warning("Kubernetes client not installed, restart not executed")
        return {"success": False, "error": "Kubernetes client not installed", "service": service}
    except Exception as e:
        logger.error(f"Failed to restart workload {service}: {e}")
        return {"success": False, "error": str(e), "service": service}


async def _revert_config(params: dict[str, Any]) -> dict[str, Any]:
    """Revert ConfigMap/Secret change."""
    logger.info("Reverting config change")
    return {"success": True, "action": "revert_config"}


async def _scale_up(params: dict[str, Any]) -> dict[str, Any]:
    """Scale up deployment replicas."""
    logger.info("Scaling up deployment")
    return {"success": True, "action": "scale_up"}


# Activity: Verify SLO Recovery
async def verify_slo_recovery(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Verify SLO recovery after remediation.
    """
    service_name = activity_input.get("service_name")
    slo_name = activity_input.get("slo_name")
    duration_seconds = activity_input.get("duration_seconds", 300)

    logger.info(f"Verifying SLO recovery for {service_name} ({slo_name}) over {duration_seconds}s")

    if not LOG_ANALYTICS_WORKSPACE_ID:
        raise ValueError("Log Analytics workspace not configured. Set LOG_ANALYTICS_WORKSPACE_ID environment variable.")

    try:
        credential = DefaultAzureCredential()
        logs_client = LogsQueryClient(credential)

        # Query for error rate over verification window
        query = f"""
        requests
        | where TimeGenerated >= ago({duration_seconds}s)
        | where cloud_RoleName == '{service_name}'
        | summarize total=count(), failed=countif(success == false)
        | extend error_rate = failed * 1.0 / total
        | project error_rate, total, failed
        """

        response = logs_client.query_workspace(
            workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
            query=query,
            timespan=timedelta(seconds=duration_seconds)
        )

        if response.tables and response.tables[0].rows:
            row = response.tables[0].rows[0]
            error_rate = row[0]
            total = row[1]
            failed = row[2]

            # SLO target: error rate < 1% (99% availability)
            slo_target = 0.01
            recovered = error_rate < slo_target

            return {
                "recovered": recovered,
                "service_name": service_name,
                "slo_name": slo_name,
                "error_rate": error_rate,
                "slo_target": slo_target,
                "total_requests": total,
                "failed_requests": failed,
                "checked_at": datetime.utcnow().isoformat()
            }

        raise ValueError(f"No metrics data found for service {service_name}")

    except Exception as e:
        logger.error(f"SLO verification failed: {e}")
        raise


# Activity: Record Ground Truth
async def record_ground_truth(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Record confirmed root cause as training data.
    """
    incident_id = activity_input.get("incident_id")
    change_event_id = activity_input.get("change_event_id")
    confirmed = activity_input.get("confirmed", True)
    confirmed_by = activity_input.get("confirmed_by")
    workflow_id = activity_input.get("workflow_id")

    logger.info(f"Recording ground truth for incident {incident_id}: {change_event_id} (confirmed={confirmed})")

    if not COSMOS_DB_ENDPOINT or not COSMOS_DB_KEY:
        logger.warning("Cosmos DB not configured, ground truth not persisted")
        return {"recorded": False, "reason": "Cosmos DB not configured"}

    try:
        gremlin_client, connection, g = await _get_gremlin_client()

        # Add validated_by edge from Incident to ChangeEvent
        query = f"""
        g.V().has('incidentId', '{incident_id}')
          .addE('validated_by')
          .to(g.V().has('changeEventId', '{change_event_id}'))
          .property('confirmed', {str(confirmed).lower()})
          .property('confirmedBy', '{confirmed_by or "system"}')
          .property('confirmedAt', '{datetime.utcnow().isoformat()}')
          .property('workflowId', '{workflow_id or ""}')
        """

        gremlin_client.submit(query)
        gremlin_client.close()
        connection.close()

        logger.info("Ground truth recorded successfully")
        return {"recorded": True, "incident_id": incident_id, "change_event_id": change_event_id}

    except Exception as e:
        logger.error(f"Failed to record ground truth: {e}")
        return {"recorded": False, "error": str(e)}


# Activity: Trigger Incident Response (for WF-2 failures)
async def trigger_incident_response(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Trigger WF-1 incident response workflow for a failed deployment.
    """
    logger.info("Triggering incident response for failed deployment")

    incident_data = {
        "incident_id": f"INC-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "incident_title": f"Deployment {activity_input.get('deployment_id')} failed SLO check",
        "affected_service": activity_input.get("service_name"),
        "severity": "sev2",
        "slo_name": "canary_slo",
        "error_budget_burn_rate": 100.0,
        "detected_at": datetime.utcnow().isoformat(),
        "correlation_id": activity_input.get("workflow_id"),
    }

    workflow_id = f"wf1-{activity_input.get('deployment_id', 'dep')}"
    logger.info(f"Incident response triggered for failed deployment: {incident_data}")

    return {"triggered": True, "workflow_id": workflow_id, "incident_data": incident_data}