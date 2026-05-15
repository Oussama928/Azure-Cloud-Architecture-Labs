"""
Shared Activities for Durable Functions

These are the activity functions called by the orchestrators.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import azure.functions as func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# WF-1 Incident Response Activities
# ============================================================

def gather_recent_changes(activity_input: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Gather recent changes for affected service.
    
    Queries Cosmos DB change-history graph for changes in lookback window.
    """
    affected_service = activity_input.get("affected_service")
    lookback_hours = activity_input.get("lookback_hours", 2)
    
    logger.info(f"Gathering recent changes for {affected_service} (lookback: {lookback_hours}h)")
    
    # TODO: Implement actual Cosmos DB Gremlin query
    # For now, return mock data
    return [
        {
            "change_event_id": "evt-001",
            "service_name": affected_service,
            "change_type": "code_deployment",
            "source": "github",
            "timestamp": datetime.utcnow().isoformat(),
            "author": "john.doe",
            "description": "Deploy v1.2.3 - fix payment timeout",
            "deployment_id": "deploy-12345",
            "new_version": "v1.2.3",
            "pipeline_name": "github/payments-service",
        },
        {
            "change_event_id": "evt-002",
            "service_name": "checkout-service",
            "change_type": "config_change",
            "source": "kubernetes",
            "timestamp": datetime.utcnow().isoformat(),
            "author": "jane.smith",
            "description": "Update retry timeout for payment calls",
            "pipeline_name": "k8s/checkout-service",
        },
    ]


def get_blast_radius(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get blast radius from dependency graph.
    
    Queries Cosmos DB dependency-graph for services depending on affected service.
    """
    service_name = activity_input.get("service_name")
    max_hops = activity_input.get("max_hops", 3)
    
    logger.info(f"Computing blast radius for {service_name} (max_hops: {max_hops})")
    
    # TODO: Implement actual Gremlin query
    return {
        "source_service": service_name,
        "affected_services": ["checkout-service", "order-service", "notification-service"],
        "hop_count": max_hops,
        "paths": [
            ["payment-service", "checkout-service"],
            ["payment-service", "order-service"],
            ["payment-service", "checkout-service", "notification-service"],
        ],
        "total_services_affected": 3,
        "critical_services_affected": ["checkout-service"],
    }


def get_service_metrics(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get recent service metrics from Azure Monitor / Application Insights.
    """
    service_name = activity_input.get("service_name")
    duration_minutes = activity_input.get("duration_minutes", 30)
    
    logger.info(f"Fetching metrics for {service_name} (last {duration_minutes} min)")
    
    # TODO: Implement actual Azure Monitor query
    return {
        "service_name": service_name,
        "error_rate": 0.05,
        "latency_p99": 1200,
        "request_volume": 15000,
        "cpu_usage": 0.75,
        "memory_usage": 0.60,
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_recent_logs(activity_input: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get recent error logs for the service.
    """
    service_name = activity_input.get("service_name")
    duration_minutes = activity_input.get("duration_minutes", 30)
    
    logger.info(f"Fetching logs for {service_name} (last {duration_minutes} min)")
    
    # TODO: Implement actual log query
    return [
        {
            "timestamp": datetime.utcnow().isoformat(),
            "level": "ERROR",
            "message": "Payment timeout after 30s",
            "service": service_name,
            "trace_id": "abc-123",
        },
        {
            "timestamp": datetime.utcnow().isoformat(),
            "level": "WARN",
            "message": "Retry attempt 2 for payment call",
            "service": service_name,
            "trace_id": "abc-123",
        },
    ]


def correlate_incident(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Correlate incident with recent changes using ML model.
    
    This is the core correlation logic that ranks candidate root causes.
    """
    incident_id = activity_input.get("incident_id")
    affected_service = activity_input.get("affected_service")
    recent_changes = activity_input.get("recent_changes", [])
    blast_radius = activity_input.get("blast_radius", {})
    service_metrics = activity_input.get("service_metrics", {})
    recent_logs = activity_input.get("recent_logs", [])
    
    logger.info(f"Correlating incident {incident_id} for {affected_service}")
    
    # TODO: Call actual correlation engine (correlation-engine service)
    # For now, return mock ranked candidates
    candidates = []
    for i, change in enumerate(recent_changes):
        # Simple heuristic scoring
        confidence = 0.9 - (i * 0.2)
        if change["service_name"] in blast_radius.get("affected_services", []):
            confidence += 0.1
        
        candidates.append({
            "change_event_id": change["change_event_id"],
            "service_name": change["service_name"],
            "change_type": change["change_type"],
            "source": change["source"],
            "timestamp": change["timestamp"],
            "confidence_score": min(confidence, 1.0),
            "evidence": change,
            "blast_radius_services": blast_radius.get("affected_services", []),
        })
    
    # Sort by confidence
    candidates.sort(key=lambda c: c["confidence_score"], reverse=True)
    
    top_candidate = candidates[0] if candidates else None
    
    return {
        "candidates": candidates,
        "top_candidate": top_candidate,
        "top_confidence": top_candidate["confidence_score"] if top_candidate else 0.0,
        "model_version": "heuristic-1.0",
    }


def send_approval_request(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send approval request to human (Teams, email, webhook).
    
    Creates signed approval URL with 15-minute expiry.
    """
    workflow_id = activity_input.get("workflow_id")
    token = activity_input.get("token")
    callback_url = activity_input.get("callback_url")
    expires_at = activity_input.get("expires_at")
    
    logger.info(f"Sending approval request for workflow {workflow_id}")
    
    # TODO: Implement actual notification (Teams webhook, email, etc.)
    # For now, just log
    approval_url = f"{callback_url}?token={token}&decision=approve"
    reject_url = f"{callback_url}?token={token}&decision=reject"
    
    logger.info(f"Approval URLs: Approve={approval_url}, Reject={reject_url}")
    
    return {
        "sent": True,
        "approval_url": approval_url,
        "reject_url": reject_url,
        "expires_at": expires_at,
    }


def send_escalation_notification(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send escalation notification to secondary on-call.
    """
    workflow_id = activity_input.get("workflow_id")
    incident_id = activity_input.get("incident_id")
    escalation_level = activity_input.get("escalation_level")
    escalation_target = activity_input.get("escalation_target")
    
    logger.info(f"Sending escalation for workflow {workflow_id} to {escalation_target}")
    
    # TODO: Implement actual escalation notification
    return {"sent": True, "target": escalation_target}


def execute_remediation(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute approved remediation action.
    
    Actions: rollback_deployment, restart_workload, revert_config
    """
    action = activity_input.get("action")
    params = activity_input.get("params", {})
    workflow_id = activity_input.get("workflow_id")
    
    logger.info(f"Executing remediation: {action} for workflow {workflow_id}")
    
    # TODO: Implement actual remediation via Argo Rollouts / Kubernetes API
    if action == "rollback_deployment":
        deployment_id = params.get("deployment_id")
        service = params.get("service")
        logger.info(f"Rolling back deployment {deployment_id} for {service}")
        return {"success": True, "action": action, "deployment_id": deployment_id}
    
    elif action == "restart_workload":
        service = params.get("service")
        logger.info(f"Restarting workload {service}")
        return {"success": True, "action": action, "service": service}
    
    return {"success": False, "error": f"Unknown action: {action}"}


def verify_slo_recovery(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify SLO recovery after remediation.
    
    Checks error budget burn rate over verification window.
    """
    service_name = activity_input.get("service_name")
    slo_name = activity_input.get("slo_name")
    duration_seconds = activity_input.get("duration_seconds", 300)
    
    logger.info(f"Verifying SLO recovery for {service_name} ({slo_name}) over {duration_seconds}s")
    
    # TODO: Implement actual SLO check via Azure Monitor
    return {
        "recovered": True,
        "service_name": service_name,
        "slo_name": slo_name,
        "error_budget_remaining": 85.0,
        "burn_rate": 0.5,
        "checked_at": datetime.utcnow().isoformat(),
    }


def record_ground_truth(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record confirmed root cause as training data.
    
    Called when incident is resolved with confirmed root cause.
    """
    incident_id = activity_input.get("incident_id")
    change_event_id = activity_input.get("change_event_id")
    confirmed = activity_input.get("confirmed", True)
    confirmed_by = activity_input.get("confirmed_by")
    workflow_id = activity_input.get("workflow_id")
    
    logger.info(f"Recording ground truth for incident {incident_id}: {change_event_id} (confirmed={confirmed})")
    
    # TODO: Store in Cosmos DB incidents graph with validated_by edge
    return {"recorded": True, "incident_id": incident_id, "change_event_id": change_event_id}


def trigger_incident_response(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger WF-1 incident response workflow for a failed deployment.
    """
    logger.info(f"Triggering incident response for failed deployment")
    
    # TODO: Start new orchestration instance
    return {"triggered": True, "workflow_id": "new-workflow-id"}


# ============================================================
# WF-2 Deployment Approval Activities
# ============================================================

def assess_deployment_risk(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess deployment risk using ML model.
    
    Factors: change size, service criticality, recent incidents, dependency risk.
    """
    deployment_id = activity_input.get("deployment_id")
    service_name = activity_input.get("service_name")
    version = activity_input.get("version")
    
    logger.info(f"Assessing risk for deployment {deployment_id} ({service_name} v{version})")
    
    # TODO: Call risk-engine service
    # Mock risk factors
    risk_factors = {
        "change_size": 0.6,
        "service_criticality": 0.9,
        "recent_incidents": 0.2,
        "dependency_risk": 0.4,
        "time_of_day": 0.3,
        "team_experience": 0.7,
    }
    
    # Weighted average
    weights = {
        "change_size": 0.25,
        "service_criticality": 0.20,
        "recent_incidents": 0.15,
        "dependency_risk": 0.15,
        "time_of_day": 0.10,
        "team_experience": 0.15,
    }
    
    risk_score = sum(risk_factors[k] * weights[k] for k in risk_factors)
    
    return {
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "model_version": "risk-model-1.0",
    }


def update_argo_rollout(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update Argo Rollout with new traffic percentage.
    """
    service_name = activity_input.get("service_name")
    namespace = activity_input.get("namespace")
    traffic_percentage = activity_input.get("traffic_percentage")
    version = activity_input.get("version")
    
    logger.info(f"Updating Argo Rollout: {service_name} to {traffic_percentage}% traffic for v{version}")
    
    # TODO: Implement actual Argo Rollouts API call
    return {"success": True, "traffic_percentage": traffic_percentage}


def check_slos(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check SLOs for canary stage.
    
    Returns pass/fail with details.
    """
    service_name = activity_input.get("service_name")
    namespace = activity_input.get("namespace")
    duration_minutes = activity_input.get("duration_minutes", 5)
    threshold = activity_input.get("threshold", 0.99)
    
    logger.info(f"Checking SLOs for {service_name} over {duration_minutes} min (threshold: {threshold})")
    
    # TODO: Implement actual SLO check via Azure Monitor
    # Mock: pass if error rate < 1%
    passed = True  # Would be based on actual metrics
    
    return {
        "passed": passed,
        "service_name": service_name,
        "duration_minutes": duration_minutes,
        "threshold": threshold,
        "details": {
            "availability": 0.999,
            "latency_p99": 450,
            "error_rate": 0.005,
        },
        "checked_at": datetime.utcnow().isoformat(),
    }


def execute_rollback(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute rollback via Argo Rollouts.
    """
    service_name = activity_input.get("service_name")
    namespace = activity_input.get("namespace")
    reason = activity_input.get("reason")
    
    logger.info(f"Executing rollback for {service_name}: {reason}")
    
    # TODO: Implement actual rollback via Argo Rollouts
    return {"success": True, "service": service_name, "reason": reason}


def record_deployment_outcome(activity_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record deployment outcome for risk model training.
    """
    deployment_id = activity_input.get("deployment_id")
    outcome = activity_input.get("outcome")  # "success" or "failure"
    rollback_triggered = activity_input.get("rollback_triggered", False)
    
    logger.info(f"Recording deployment outcome: {deployment_id} = {outcome}")
    
    # TODO: Store in training data store
    return {"recorded": True, "deployment_id": deployment_id}


# ============================================================
# Azure Function Entry Points
# ============================================================

# WF-1 Activities
GatherRecentChanges = func.FunctionApp().activity_trigger(arg_name="activity_input")(gather_recent_changes)
GetBlastRadius = func.FunctionApp().activity_trigger(arg_name="activity_input")(get_blast_radius)
GetServiceMetrics = func.FunctionApp().activity_trigger(arg_name="activity_input")(get_service_metrics)
GetRecentLogs = func.FunctionApp().activity_trigger(arg_name="activity_input")(get_recent_logs)
CorrelateIncident = func.FunctionApp().activity_trigger(arg_name="activity_input")(correlate_incident)
SendApprovalRequest = func.FunctionApp().activity_trigger(arg_name="activity_input")(send_approval_request)
SendEscalationNotification = func.FunctionApp().activity_trigger(arg_name="activity_input")(send_escalation_notification)
ExecuteRemediation = func.FunctionApp().activity_trigger(arg_name="activity_input")(execute_remediation)
VerifySLORecovery = func.FunctionApp().activity_trigger(arg_name="activity_input")(verify_slo_recovery)
RecordGroundTruth = func.FunctionApp().activity_trigger(arg_name="activity_input")(record_ground_truth)
TriggerIncidentResponse = func.FunctionApp().activity_trigger(arg_name="activity_input")(trigger_incident_response)

# WF-2 Activities
AssessDeploymentRisk = func.FunctionApp().activity_trigger(arg_name="activity_input")(assess_deployment_risk)
UpdateArgoRollout = func.FunctionApp().activity_trigger(arg_name="activity_input")(update_argo_rollout)
CheckSLOs = func.FunctionApp().activity_trigger(arg_name="activity_input")(check_slos)
ExecuteRollback = func.FunctionApp().activity_trigger(arg_name="activity_input")(execute_rollback)
RecordDeploymentOutcome = func.FunctionApp().activity_trigger(arg_name="activity_input")(record_deployment_outcome)