"""
Shared Activities for Durable Functions

Activity functions called by the orchestrators.
"""

import logging
from typing import Any

import azure.functions as func

logger = logging.getLogger(__name__)

# Import Real Implementations
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

# Azure Function Entry Points (Activity Triggers)

app = func.FunctionApp()

# WF-1 Activities
GatherRecentChanges = app.activity_trigger(arg_name="activity_input")(gather_recent_changes)
GetBlastRadius = app.activity_trigger(arg_name="activity_input")(get_blast_radius)
GetServiceMetrics = app.activity_trigger(arg_name="activity_input")(get_service_metrics)
GetRecentLogs = app.activity_trigger(arg_name="activity_input")(get_recent_logs)
CorrelateIncident = app.activity_trigger(arg_name="activity_input")(correlate_incident)
SendApprovalRequest = app.activity_trigger(arg_name="activity_input")(send_approval_request)
SendEscalationNotification = app.activity_trigger(arg_name="activity_input")(send_escalation_notification)
ExecuteRemediation = app.activity_trigger(arg_name="activity_input")(execute_remediation)
VerifySLORecovery = app.activity_trigger(arg_name="activity_input")(verify_slo_recovery)
RecordGroundTruth = app.activity_trigger(arg_name="activity_input")(record_ground_truth)
TriggerIncidentResponse = app.activity_trigger(arg_name="activity_input")(trigger_incident_response)

# WF-2 Activities
AssessDeploymentRisk = app.activity_trigger(arg_name="activity_input")(assess_deployment_risk)
SendDeploymentApproval = app.activity_trigger(arg_name="activity_input")(send_deployment_approval)
UpdateArgoRollout = app.activity_trigger(arg_name="activity_input")(execute_canary)
CheckSLOs = app.activity_trigger(arg_name="activity_input")(check_canary_slo)
ExecuteRollback = app.activity_trigger(arg_name="activity_input")(execute_rollback)
RecordDeploymentOutcome = app.activity_trigger(arg_name="activity_input")(record_deployment_outcome)
TriggerIncidentResponseWF2 = app.activity_trigger(arg_name="activity_input")(trigger_incident_response_wf2)

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
