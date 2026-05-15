"""
WF-2: Deployment Approval Orchestrator

Durable Function orchestrator for risk-gated deployment with canary analysis.
Implements approval gates, staged canary rollout, SLO checks, and automatic rollback.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import azure.durable_functions as df
import azure.functions as func

from shared.models.workflow_state import (
    DeploymentWorkflowState,
    WorkflowStatus,
    ApprovalDecision,
    WorkflowTimeouts,
    DEFAULT_CANARY_STAGES,
    ApprovalRequest,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def orchestrator_function(context: df.DurableOrchestrationContext):
    """
    Main orchestrator for WF-2 Deployment Approval workflow.
    
    Flow:
    1. Score deployment risk
    2. If risk >= 0.70, request human approval (15-min timeout)
    3. Execute canary stages (10% -> 50% -> 100%)
    4. At each stage: wait 5 min, check SLOs
    5. If SLO breach: automatic rollback + trigger WF-1
    6. Record outcome for risk model training
    """
    # Get input
    deployment_data = context.get_input()
    if not deployment_data:
        raise ValueError("No deployment data provided")
    
    # Initialize state
    state = DeploymentWorkflowState(**deployment_data)
    state.status = WorkflowStatus.RUNNING
    state.add_audit_entry("workflow_started", {"deployment_id": state.deployment_id})
    
    # Initialize canary stages
    state.canary_stages = deployment_data.get("canary_stages", DEFAULT_CANARY_STAGES)
    for stage in state.canary_stages:
        stage["status"] = "pending"
        stage["started_at"] = None
        stage["completed_at"] = None
        stage["slo_check_passed"] = None
    
    context.set_custom_status(state.model_dump())
    
    try:
        # ============================================================
        # PHASE 1: Risk Assessment
        # ============================================================
        state.add_audit_entry("risk_assessment_started")
        context.set_custom_status(state.model_dump())
        
        risk_result = yield context.call_activity("AssessDeploymentRisk", {
            "deployment_id": state.deployment_id,
            "service_name": state.service_name,
            "namespace": state.namespace,
            "version": state.version,
            "deployment_strategy": state.deployment_strategy,
        })
        
        state.risk_score = risk_result.get("risk_score", 0.0)
        state.risk_factors = risk_result.get("risk_factors", {})
        state.risk_model_version = risk_result.get("model_version", "unknown")
        
        # Determine if approval required
        RISK_THRESHOLD = 0.70
        state.approval_required = state.risk_score >= RISK_THRESHOLD
        
        state.add_audit_entry("risk_assessment_completed", {
            "risk_score": state.risk_score,
            "threshold": RISK_THRESHOLD,
            "approval_required": state.approval_required,
        })
        
        # ============================================================
        # PHASE 2: Approval Gate (if required)
        # ============================================================
        if state.approval_required:
            state.status = WorkflowStatus.WAITING_FOR_APPROVAL
            
            # Generate approval token
            import secrets
            state.approval_token = secrets.token_urlsafe(32)
            state.approval_url = f"{context.get_input().get('approval_base_url', '')}/approve/{state.approval_token}"
            state.approval_requested_at = datetime.utcnow()
            
            # Create approval request
            approval_request = ApprovalRequest(
                workflow_id=state.workflow_id,
                workflow_type="deployment_approval",
                title=f"Deployment {state.deployment_id}: Approve {state.service_name} v{state.version}",
                description=f"Risk score: {state.risk_score*100:.1f}% (threshold: {RISK_THRESHOLD*100:.0f}%). Risk factors: {', '.join(state.risk_factors.keys())}",
                details={
                    "deployment_id": state.deployment_id,
                    "service_name": state.service_name,
                    "namespace": state.namespace,
                    "version": state.version,
                    "risk_score": state.risk_score,
                    "risk_factors": state.risk_factors,
                    "canary_stages": state.canary_stages,
                },
                expires_at=datetime.utcnow() + timedelta(minutes=WorkflowTimeouts.DEPLOYMENT_APPROVAL_TIMEOUT_MINUTES),
                callback_url=f"{context.get_input().get('callback_base_url', '')}/api/approval/{state.approval_token}",
                token=state.approval_token,
            )
            
            # Send approval notification
            yield context.call_activity("SendApprovalRequest", approval_request.model_dump())
            
            state.add_audit_entry("approval_requested", {
                "token": state.approval_token,
                "risk_score": state.risk_score,
            })
            context.set_custom_status(state.model_dump())
            
            # Wait for approval with timeout
            approval_timeout = context.create_timer(
                context.current_utc_datetime + timedelta(minutes=WorkflowTimeouts.DEPLOYMENT_APPROVAL_TIMEOUT_MINUTES),
                "approval_timeout"
            )
            
            approval_event = context.wait_for_external_event("ApprovalDecision")
            winner = yield context.task_any([approval_event, approval_timeout])
            
            if winner == approval_event:
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
                    state.add_audit_entry("deployment_cancelled", {"reason": "Approval rejected"})
                    context.set_custom_status(state.model_dump())
                    return state.model_dump()
            else:
                # Timeout - reject deployment
                state.approval_decision = ApprovalDecision.EXPIRED
                state.approval_decided_at = datetime.utcnow()
                state.status = WorkflowStatus.CANCELLED
                state.add_audit_entry("deployment_cancelled", {"reason": "Approval timeout"})
                context.set_custom_status(state.model_dump())
                return state.model_dump()
        
        # ============================================================
        # PHASE 3: Execute Canary Rollout
        # ============================================================
        state.status = WorkflowStatus.RUNNING
        state.add_audit_entry("canary_rollout_started")
        context.set_custom_status(state.model_dump())
        
        for i, stage in enumerate(state.canary_stages):
            state.current_stage = i + 1
            stage["status"] = "running"
            stage["started_at"] = datetime.utcnow().isoformat()
            state.stage_started_at = datetime.utcnow()
            
            state.add_audit_entry("canary_stage_started", {
                "stage": state.current_stage,
                "traffic_percentage": stage["traffic_percentage"],
            })
            context.set_custom_status(state.model_dump())
            
            # Update Argo Rollout with new traffic weight
            rollout_result = yield context.call_activity("UpdateArgoRollout", {
                "service_name": state.service_name,
                "namespace": state.namespace,
                "traffic_percentage": stage["traffic_percentage"],
                "version": state.version,
            })
            
            if not rollout_result.get("success", False):
                state.status = WorkflowStatus.FAILED
                state.last_error = f"Failed to update rollout: {rollout_result.get('error')}"
                state.add_audit_entry("rollout_update_failed", {"error": state.last_error})
                context.set_custom_status(state.model_dump())
                return state.model_dump()
            
            # Wait for stage duration
            stage_duration = timedelta(minutes=stage["duration_minutes"])
            yield context.create_timer(
                context.current_utc_datetime + stage_duration,
                f"stage_{state.current_stage}_wait"
            )
            
            # Check SLOs
            slo_result = yield context.call_activity("CheckSLOs", {
                "service_name": state.service_name,
                "namespace": state.namespace,
                "duration_minutes": stage["duration_minutes"],
                "threshold": stage["slo_threshold"],
            })
            
            stage["completed_at"] = datetime.utcnow().isoformat()
            stage["slo_check_passed"] = slo_result.get("passed", False)
            stage["slo_details"] = slo_result
            
            if not slo_result.get("passed", False):
                # SLO breach - trigger rollback
                state.add_audit_entry("slo_breach_detected", {
                    "stage": state.current_stage,
                    "details": slo_result,
                })
                
                # Execute rollback
                state.rollback_triggered = True
                state.rollback_reason = f"SLO breach at stage {state.current_stage}: {slo_result.get('details', {})}"
                state.rollback_started_at = datetime.utcnow()
                
                rollback_result = yield context.call_activity("ExecuteRollback", {
                    "service_name": state.service_name,
                    "namespace": state.namespace,
                    "reason": state.rollback_reason,
                })
                
                state.rollback_completed_at = datetime.utcnow()
                state.rollback_success = rollback_result.get("success", False)
                
                state.add_audit_entry("rollback_executed", {
                    "success": state.rollback_success,
                    "reason": state.rollback_reason,
                })
                
                # Trigger WF-1 incident response for the failed deployment
                yield context.call_activity("TriggerIncidentResponse", {
                    "incident_title": f"Deployment {state.deployment_id} failed SLO check",
                    "affected_service": state.service_name,
                    "severity": "sev2",
                    "slo_name": "canary_slo",
                    "error_budget_burn_rate": 100.0,
                    "detected_at": datetime.utcnow().isoformat(),
                    "correlation_id": state.workflow_id,
                })
                
                state.status = WorkflowStatus.FAILED
                state.last_error = state.rollback_reason
                context.set_custom_status(state.model_dump())
                return state.model_dump()
            
            # Stage passed
            stage["status"] = "passed"
            state.add_audit_entry("canary_stage_passed", {
                "stage": state.current_stage,
                "traffic_percentage": stage["traffic_percentage"],
            })
        
        # ============================================================
        # PHASE 4: Deployment Complete
        # ============================================================
        state.status = WorkflowStatus.COMPLETED
        state.completed_at = datetime.utcnow()
        
        # Record outcome for risk model training
        yield context.call_activity("RecordDeploymentOutcome", {
            "deployment_id": state.deployment_id,
            "service_name": state.service_name,
            "risk_score": state.risk_score,
            "risk_factors": state.risk_factors,
            "outcome": "success",
            "rollback_triggered": state.rollback_triggered,
            "canary_stages": state.canary_stages,
            "workflow_id": state.workflow_id,
        })
        
        state.add_audit_entry("deployment_completed_success", {
            "stages_completed": len(state.canary_stages),
        })
        context.set_custom_status(state.model_dump())
        
        return state.model_dump()
        
    except Exception as e:
        logger.exception("Deployment workflow failed with exception")
        state.status = WorkflowStatus.FAILED
        state.last_error = str(e)
        state.add_audit_entry("workflow_exception", {"error": str(e)})
        context.set_custom_status(state.model_dump())
        raise


main = df.Orchestrator.create(orchestrator_function)