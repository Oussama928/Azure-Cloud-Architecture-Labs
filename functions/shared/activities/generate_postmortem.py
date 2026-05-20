"""
Activity: Generate Postmortem from Incident Data

Creates a structured blameless postmortem document from incident workflow data.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


async def main(activity_input: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a blameless postmortem document.

    Input: IncidentWorkflowState (serialized)
    Output: Postmortem document (markdown)
    """
    workflow_state = activity_input.get("workflow_state")
    if not workflow_state:
        raise ValueError("workflow_state is required")

    logger.info(f"Generating postmortem for incident {workflow_state.get('incident_id')}")

    postmortem = _generate_postmortem(workflow_state)

    return {
        "postmortem_markdown": postmortem,
        "generated_at": datetime.utcnow().isoformat(),
        "incident_id": workflow_state.get("incident_id")
    }


def _generate_postmortem(state: dict[str, Any]) -> str:
    """Generate markdown postmortem from workflow state."""

    incident_id = state.get("incident_id", "UNKNOWN")
    title = state.get("incident_title", "Untitled Incident")
    affected_service = state.get("affected_service", "unknown")
    severity = state.get("severity", "sev3")
    status = state.get("status", "unknown")

    detected_at = state.get("detected_at")
    started_at = state.get("started_at")
    resolved_at = state.get("resolved_at")
    completed_at = state.get("completed_at")

    candidates = state.get("candidates", [])
    top_candidate = state.get("top_candidate")
    correlation_confidence = state.get("correlation_confidence", 0)
    correlation_model_version = state.get("correlation_model_version", "unknown")

    approval_decision = state.get("approval_decision")
    approver = state.get("approver")
    approval_reason = state.get("approval_reason")

    remediation_action = state.get("remediation_action")
    remediation_params = state.get("remediation_params", {})
    remediation_success = state.get("remediation_success", False)
    remediation_result = state.get("remediation_result", {})

    slo_recovered = state.get("slo_recovered", False)
    verification_details = state.get("verification_details", {})

    ground_truth = state.get("ground_truth", {})
    audit_log = state.get("audit_log", [])

    lines = []

    # Header
    lines.append(f"# Postmortem: {incident_id}")
    lines.append(f"**Title:** {title}")
    lines.append(f"**Severity:** {severity.upper()}")
    lines.append(f"**Status:** {status}")
    lines.append(f"**Affected Service:** {affected_service}")
    lines.append("")

    # Timeline
    lines.append("## Timeline")
    lines.append("")
    lines.append("| Time (UTC) | Event |")
    lines.append("|------------|-------|")

    if detected_at:
        lines.append(f"| {detected_at} | Incident detected (SLO breach) |")
    if started_at:
        lines.append(f"| {started_at} | Investigation started |")
    if state.get("approval_requested_at"):
        lines.append(f"| {state['approval_requested_at']} | Approval requested (confidence: {correlation_confidence:.1%}) |")
    if state.get("approval_decided_at"):
        lines.append(f"| {state['approval_decided_at']} | Approval {approval_decision} by {approver} |")
    if state.get("remediation_started_at"):
        lines.append(f"| {state['remediation_started_at']} | Remediation started: {remediation_action} |")
    if state.get("remediation_completed_at"):
        lines.append(f"| {state['remediation_completed_at']} | Remediation {'succeeded' if remediation_success else 'failed'} |")
    if state.get("verification_started_at"):
        lines.append(f"| {state['verification_started_at']} | SLO verification started |")
    if state.get("verification_completed_at"):
        lines.append(f"| {state['verification_completed_at']} | SLO {'recovered' if slo_recovered else 'NOT recovered'} |")
    if resolved_at:
        lines.append(f"| {resolved_at} | Incident resolved |")
    if completed_at:
        lines.append(f"| {completed_at} | Workflow completed |")

    lines.append("")

    # Root Cause Analysis
    lines.append("## Root Cause Analysis")
    lines.append("")

    if top_candidate:
        lines.append(f"**Top Candidate:** {top_candidate.get('service_name')} ({top_candidate.get('change_type')})")
        lines.append(f"**Confidence:** {correlation_confidence:.1%}")
        lines.append(f"**Model Version:** {correlation_model_version}")
        lines.append(f"**Change Details:** {top_candidate.get('evidence', {}).get('description', 'N/A')}")
        lines.append("")

    lines.append("### All Candidates Ranked")
    lines.append("")
    lines.append("| Rank | Service | Change Type | Source | Time | Confidence |")
    lines.append("|------|---------|-------------|--------|------|------------|")

    for i, c in enumerate(candidates, 1):
        lines.append(f"| {i} | {c.get('service_name')} | {c.get('change_type')} | {c.get('source')} | {c.get('timestamp')} | {c.get('confidence_score', 0):.1%} |")

    lines.append("")

    # Ground Truth
    if ground_truth:
        lines.append("## Ground Truth (Validation)")
        lines.append("")
        lines.append(f"**Confirmed Root Cause:** {ground_truth.get('change_event_id')}")
        lines.append(f"**Fault Type:** {ground_truth.get('fault_type')}")
        lines.append(f"**Confirmed By:** {ground_truth.get('confirmed_by')}")
        lines.append(f"**Confirmed At:** {ground_truth.get('confirmed_at')}")
        lines.append("")

    # Remediation
    lines.append("## Remediation")
    lines.append("")
    lines.append(f"**Action:** {remediation_action}")
    lines.append(f"**Parameters:** {remediation_params}")
    lines.append(f"**Approved By:** {approver} ({approval_decision})")
    if approval_reason:
        lines.append(f"**Approval Reason:** {approval_reason}")
    lines.append(f"**Result:** {'Success' if remediation_success else 'Failed'}")
    if remediation_result:
        lines.append(f"**Details:** {remediation_result}")
    lines.append("")

    # Verification
    lines.append("## Verification")
    lines.append("")
    lines.append(f"**SLO Recovered:** {'Yes' if slo_recovered else 'No'}")
    if verification_details:
        lines.append(f"**Details:** {verification_details}")
    lines.append("")

    # Lessons Learned
    lines.append("## Lessons Learned")
    lines.append("")
    lines.append("### What Went Well")
    lines.append("- Automated correlation identified root cause candidate")
    lines.append("- Human-in-the-loop approval prevented unauthorized action")
    lines.append("- SLO-based verification confirmed recovery")
    lines.append("")
    lines.append("### What Can Be Improved")
    if correlation_confidence < 0.75:
        lines.append("- Correlation confidence was below approval threshold; consider expanding lookback window")
    if not remediation_success:
        lines.append("- Remediation failed; need better rollback automation")
    if not slo_recovered:
        lines.append("- SLO did not recover within verification window; investigate residual issues")
    lines.append("")

    # Action Items
    lines.append("## Action Items")
    lines.append("")
    lines.append("| # | Action Item | Owner | Due Date | Status |")
    lines.append("|---|-------------|-------|----------|--------|")
    lines.append("| 1 | Add integration test for this failure mode | Team | TBD | Open |")
    lines.append("| 2 | Update runbook with this scenario | Team | TBD | Open |")
    lines.append("| 3 | Review correlation model features | ML Team | TBD | Open |")
    lines.append("")

    # Audit Log
    lines.append("## Audit Log")
    lines.append("")
    lines.append("| Time | Action | Details |")
    lines.append("|------|--------|---------|")
    for entry in audit_log:
        lines.append(f"| {entry.get('timestamp')} | {entry.get('action')} | {entry.get('details')} |")

    return "\n".join(lines)
