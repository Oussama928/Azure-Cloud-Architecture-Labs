"""
WF-1: Incident Response Orchestrator

Durable Function orchestrator for incident root cause analysis and remediation.
Implements fan-out/fan-in, wait-for-external-event, and durable timer patterns.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import azure.durable_functions as df
import azure.functions as func

from shared.models.workflow_state import (
    IncidentWorkflowState,
    WorkflowStatus,
    ApprovalDecision,
    RemediationAction,
    WorkflowTimeouts,
    ApprovalRequest,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def orchestrator_function(context: df.DurableOrchestrationContext):
    """
    Main orchestrator for WF-1 Incident Response workflow.
    
    Flow:
    1. Fan-out: Gather evidence (changes, graph, metrics, logs)
    2. Fan-in: Correlate and rank candidates
    3. Branch: If confidence >= 0.75, request human approval
    4. Wait for approval (with 15-min timer + 30-min escalation)
    5. Execute approved remediation action
    6. Verify SLO recovery for 5 minutes
    7. Record ground truth for training
    """
    # Get input
    incident_data = context.get_input()
    if not incident_data:
        raise ValueError("No incident data provided")
    
    # Initialize state
    state = IncidentWorkflowState(**incident_data)
    state.status = WorkflowStatus.RUNNING
    state.add_audit_entry("workflow_started", {"incident_id": state.incident_id})
    
    # Set custom status for monitoring
    context.set_custom_status(state.model_dump())
    
    try:
        # ============================================================
        # PHASE 1: Fan-out evidence gathering
        # ============================================================
        state.status = WorkflowStatus.RUNNING
        state.add_audit_entry("evidence_gathering_started")
        context.set_custom_status(state.model_dump())
        
        # Fan-out: Call multiple activities in parallel
        evidence_tasks = [
            context.call_activity("GatherRecentChanges", {
                "affected_service": state.affected_service,
                "lookback_hours": 2,
            }),
            context.call_activity("GetBlastRadius", {
                "service_name": state.affected_service,
                "max_hops": 3,
            }),
            context.call_activity("GetServiceMetrics", {
                "service_name": state.affected_service,
                "duration_minutes": 30,
            }),
            context.call_activity("GetRecentLogs", {
                "service_name": state.affected_service,
                "duration_minutes": 30,
            }),
        ]
        
        # Wait for all evidence gathering to complete
        evidence_results = yield context.task_all(evidence_tasks)
        
        recent_changes = evidence_results[0]
        blast_radius = evidence_results[1]
        service_metrics = evidence_results[2]
        recent_logs = evidence_results[3]
        
        state.add_audit_entry("evidence_gathering_completed", {
            "changes_found": len(recent_changes),
            "blast_radius_services": len(blast_radius.get("affected_services", [])),
        })
        
        # ============================================================
        # PHASE 2: Correlation and ranking
        # ============================================================
        state.add_audit_entry("correlation_started")
        context.set_custom_status(state.model_dump())
        
        correlation_result = yield context.call_activity("CorrelateIncident", {
            "incident_id": state.incident_id,
            "affected_service": state.affected_service,
            "recent_changes": recent_changes,
            "blast_radius": blast_radius,
            "service_metrics": service_metrics,
            "recent_logs": recent_logs,
        })
        
        state.candidates = correlation_result.get("candidates", [])
        state.top_candidate = correlation_result.get("top_candidate")
        state.correlation_confidence = correlation_result.get("top_confidence", 0.0)
        state.correlation_model_version = correlation_result.get("model_version", "unknown")
        
        state.add_audit_entry("correlation_completed", {
            "candidates_found": len(state.candidates),
            "top_confidence": state.correlation_confidence,
        })
        
        # ============================================================
        # PHASE 3: Decision - 3: Decision branching based on confidence
        # ============================================================
        CONFIDENCE_THRESHOLD = 0.75
        
        if state.correlation_confidence >= CONFIDENCE_THRESHOLD and state.top_candidate:
            # High confidence - request human approval
            state.status = WorkflowStatus.WAITING_FOR_APPROVAL
            state.approval_required = True
            
            # Generate approval token and URL
            import secrets
            state.approval_token = secrets.token_urlsafe(32)
            state.approval_url = f"{context.get_input().get('approval_base_url', '')}/approve/{state.approval_token}"
            state.approval_requested_at = datetime.utcnow()
            
            # Create approval request
            approval_request = ApprovalRequest(
                workflow_id=state.workflow_id,
                workflow_type="incident_response",
                title=f"Incident {state.incident_id}: Approve remediation for {state.affected_service}",
                description=f"Top candidate: {state.top_candidate.get('service_name')} ({state.top_candidate.get('change_type')}) with {state.correlation_confidence*100:.1f}% confidence",
                details={
                    "incident_id": state.incident_id,
                    "affected_service": state.affected_service,
                    "top_candidate": state.top_candidate,
                    "all_candidates": state.candidates[:5],
                    "blast_radius": blast_radius,
                },
                expires_at=datetime.utcnow() + timedelta(minutes=WorkflowTimeouts.APPROVAL_TIMEOUT_MINUTES),
                callback_url=f"{context.get_input().get('callback_base_url', '')}/api/approval/{state.approval_token}",
                token=state.approval_token,
            )
            
            # Send approval notification (Teams, email, etc.)
            yield context.call_activity("SendApprovalRequest", approval_request.model_dump())
            
            state.add_audit_entry("approval_requested", {
                "token": state.approval_token,
                "expires_at": approval_request.expires_at.isoformat(),
            })
            context.set_custom_status(state.model_dump())
            
            # ============================================================
            # PHASE 4: Wait for approval with durable timer
            # ============================================================
            # Create timer for approval timeout
            approval_timeout = context.create_timer(
                context.current_utc_datetime + timedelta(minutes=WorkflowTimeouts.APPROVAL_TIMEOUT_MINUTES),
                "approval_timeout"
            )
            
            # Wait for either approval or timeout
            approval_event = context.wait_for_external_event("ApprovalDecision")
            
            # Race between approval and timeout
            winner = yield context.task_any([approval_event, approval_timeout])
            
            if winner == approval_event:
                # Approval received
                approval_result = approval_event.result
                state.approval_decision = ApprovalDecision(approval_result.get("decision", "rejected"))
                state.approval_decided_at = datetime.utcnow()
                state.approver = approval_result.get("decided_by")
                state.approval_reason = approval_result.get("reason")
                
                state.add_audit_entry("approval_received", {
                    "decision": state.approval_decision.value,
                    "approver": state.approver,
                })
                
                if state.approval_decision != ApprovalDecision.APPROVED:
                    state.status = WorkflowStatus.CANCELLED
                    state.add_audit_entry("workflow_cancelled", {"reason": "Approval rejected"})
                    context.set_custom_status(state.model_dump())
                    return state.model_dump()
            else:
                # Timeout - escalate
                state.status = WorkflowStatus.WAITING_FOR_ESCALATION
                state.escalation_level = 1
                state.escalated_at = datetime.utcnow()
                
                state.add_audit_entry("approval_timeout_escalated", {
                    "escalation_level": state.escalation_level,
                })
                
                # Send escalation notification
                yield context.call_activity("SendEscalationNotification", {
                    "workflow_id": state.workflow_id,
                    "incident_id": state.incident_id,
                    "escalation_level": state.escalation_level,
                    "original_approver": "primary",
                })
                
                # Wait for escalation response (30 more minutes)
                escalation_timeout = context.create_timer(
                    context.current_utc_datetime + timedelta(minutes=WorkflowTimeouts.ESCALATION_TIMEOUT_MINUTES),
                    "escalation_timeout"
                )
                
                escalation_event = context.wait_for_external_event("EscalationDecision")
                esc_winner = yield context.task_any([escalation_event, escalation_timeout])
                
                if esc_winner == escalation_event:
                    esc_result = escalation_event.result
                    state.approval_decision = ApprovalDecision(esc_result.get("decision", "rejected"))
                    state.approval_decided_at = datetime.utcnow()
                    state.approver = esc_result.get("decided_by")
                    
                    if state.approval_decision != ApprovalDecision.APPROVED:
                        state.status = WorkflowStatus.UNACTIONED
                        state.add_audit_entry("workflow_unactioned", {"reason": "Escalation rejected or expired"})
                        context.set_custom_status(state.model_dump())
                        return state.model_dump()
                else:
                    # Escalation timeout - mark as unactioned
                    state.status = WorkflowStatus.UNACTIONED
                    state.add_audit_entry("workflow_unactioned", {"reason": "Escalation timeout"})
                    context.set_custom_status(state.model_dump())
                    return state.model_dump()
        
        else:
            # Low confidence - no automated action, human triage needed
            state.status = WorkflowStatus.COMPLETED
            state.add_audit_entry("low_confidence_no_action", {
                "confidence": state.correlation_confidence,
                "threshold": CONFIDENCE_THRESHOLD,
            })
            context.set_custom_status(state.model_dump())
            return state.model_dump()
        
        # ============================================================
        # PHASE 5: Execute remediation action
        # ============================================================
        state.status = WorkflowStatus.EXECUTING_ACTION
        state.remediation_action = RemediationAction.ROLLBACK_DEPLOYMENT  # Default
        state.remediation_params = {
            "deployment_id": state.top_candidate.get("deployment_id"),
            "service_name": state.top_candidate.get("service_name"),
            "namespace": state.top_candidate.get("namespace", "production"),
        }
        state.remediation_started_at = datetime.utcnow()
        
        state.add_audit_entry("remediation_started", {
            "action": state.remediation_action.value,
            "params": state.remediation_params,
        })
        context.set_custom_status(state.model_dump())
        
        remediation_result = yield context.call_activity("ExecuteRemediation", {
            "action": state.remediation_action.value,
            "params": state.remediation_params,
        })
        
        state.remediation_completed_at = datetime.utcnow()
        state.remediation_result = remediation_result
        state.remediation_success = remediation_result.get("success", False)
        
        state.add_audit_entry("remediation_completed", {
            "success": state.remediation_success,
            "result": remediation_result,
        })
        
        if not state.remediation_success:
            state.status = WorkflowStatus.FAILED
            state.last_error = remediation_result.get("error", "Remediation failed")
            state.add_audit_entry("remediation_failed", {"error": state.last_error})
            context.set_custom_status(state.model_dump())
            return state.model_dump()
        
        # ============================================================
        # PHASE 6: Verify SLO recovery
        # ============================================================
        state.status = WorkflowStatus.VERIFYING
        state.verification_started_at = datetime.utcnow()
        
        state.add_audit_entry("verification_started", {
            "duration_seconds": WorkflowTimeouts.VERIFICATION_DURATION_SECONDS,
        })
        context.set_custom_status(state.model_dump())
        
        # Wait for verification period
        yield context.create_timer(
            context.current_utc_datetime + timedelta(seconds=WorkflowTimeouts.VERIFICATION_DURATION_SECONDS),
            "verification_wait"
        )
        
        # Check SLO status
        verification_result = yield context.call_activity("VerifySLORecovery", {
            "service_name": state.affected_service,
            "slo_name": state.slo_name,
            "duration_seconds": WorkflowTimeouts.VERIFICATION_DURATION_SECONDS,
        })
        
        state.verification_completed_at = datetime.utcnow()
        state.slo_recovered = verification_result.get("recovered", False)
        
        state.add_audit_entry("verification_completed", {
            "recovered": state.slo_recovered,
            "details": verification_result,
        })
        
        # ============================================================
        # PHASE 7: Complete and record ground truth
        # ============================================================
        if state.slo_recovered:
            state.status = WorkflowStatus.COMPLETED
            state.completed_at = datetime.utcnow()
            
            # Record ground truth for training
            if state.top_candidate:
                yield context.call_activity("RecordGroundTruth", {
                    "incident_id": state.incident_id,
                    "change_event_id": state.top_candidate.get("change_event_id"),
                    "confirmed": True,
                    "confirmed_by": state.approver or "auto",
                    "workflow_id": state.workflow_id,
                })
            
            state.add_audit_entry("workflow_completed_success", {
                "root_cause_confirmed": state.top_candidate.get("change_event_id") if state.top_candidate else None,
            })
        else:
            state.status = WorkflowStatus.FAILED
            state.last_error = "SLO did not recover after remediation"
            state.add_audit_entry("workflow_failed_verification", {
                "error": state.last_error,
            })
        
        context.set_custom_status(state.model_dump())
        return state.model_dump()
        
    except Exception as e:
        logger.exception("Workflow failed with exception")
        state.status = WorkflowStatus.FAILED
        state.last_error = str(e)
        state.add_audit_entry("workflow_exception", {"error": str(e)})
        context.set_custom_status(state.model_dump())
        raise


main = df.Orchestrator.create(orchestrator_function)