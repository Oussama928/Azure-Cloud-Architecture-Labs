"""
Shared Activities for Durable Functions

These are the activity functions called by the orchestrators.
Real implementations in wf1_activities.py and wf2_activities.py
"""

import logging
from typing import Any

import azure.functions as func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Import Real Implementations
# ============================================================
from .wf1_activities import (
    gather_recent_changes,
    get_blast_radius,
    get_service_metrics,
    get_recent_logs,
    correlate_incident,
    send_approval_request,
    send_escalation_notification,
    execute_remediation,
    verify_slo_recovery,
    record_ground_truth,
    trigger_incident_response,
)

from .wf2_activities import (
    assess_deployment_risk,
    send_deployment_approval,
    execute_canary,
    check_canary_slo,
    execute_rollback,
    record_deployment_outcome,
    trigger_incident_response as trigger_incident_response_wf2,
)

# ============================================================
# Azure Function Entry Points (Activity Triggers)
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
SendDeploymentApproval = func.FunctionApp().activity_trigger(arg_name="activity_input")(send_deployment_approval)
UpdateArgoRollout = func.FunctionApp().activity_trigger(arg_name="activity_input")(execute_canary)
CheckSLOs = func.FunctionApp().activity_trigger(arg_name="activity_input")(check_canary_slo)
ExecuteRollback = func.FunctionApp().activity_trigger(arg_name="activity_input")(execute_rollback)
RecordDeploymentOutcome = func.FunctionApp().activity_trigger(arg_name="activity_input")(record_deployment_outcome)
TriggerIncidentResponse = func.FunctionApp().activity_trigger(arg_name="activity_input")(trigger_incident_response_wf2)

__all__ = [
    # WF-1
    "GatherRecentChanges",
    "GetBlastRadius",
    "GetServiceMetrics",
    "GetRecentLogs",
    "CorrelateIncident",
    "SendApprovalRequest",
    "SendEscalationNotification",
    "ExecuteRemediation",
    "VerifySLORecovery",
    "RecordGroundTruth",
    "TriggerIncidentResponse",
    # WF-2
    "AssessDeploymentRisk",
    "SendDeploymentApproval",
    "UpdateArgoRollout",
    "CheckSLOs",
    "ExecuteRollback",
    "RecordDeploymentOutcome",
    "TriggerIncidentResponseWF2",
]
