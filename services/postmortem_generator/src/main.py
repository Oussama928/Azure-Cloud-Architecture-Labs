"""
Postmortem Generator Service for ChangeTrace

Generates blameless postmortems from incident data.
Uses LLM only for natural language phrasing.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import azure.functions as func

logger = logging.getLogger(__name__)


class PostmortemGenerator:
    """Generates structured postmortem documents."""
    
    def __init__(self):
        self.use_llm = os.getenv("USE_LLM_FOR_REPORTS", "false").lower() == "true"
        self.llm_endpoint = os.getenv("LLM_ENDPOINT")
        self.llm_key = os.getenv("LLM_KEY")
    
    async def generate_postmortem(
        self,
        incident_data: Dict[str, Any],
        correlation_results: Dict[str, Any],
        workflow_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a complete postmortem document.
        
        """
        logger.info(f"Generating postmortem for incident {incident_data.get('incident_id')}")
        
        # Build structured postmortem
        postmortem = self._build_structured_postmortem(
            incident_data, correlation_results, workflow_state
        )
        
        # Generate markdown
        markdown = self._render_markdown(postmortem)
        
        # Optionally enhance with LLM phrasing
        if self.use_llm and self.llm_endpoint:
            markdown = await self._enhance_with_llm(markdown, postmortem)
        
        return {
            "incident_id": incident_data.get("incident_id"),
            "postmortem_markdown": markdown,
            "structured_data": postmortem,
            "generated_at": datetime.utcnow().isoformat(),
            "llm_enhanced": self.use_llm
        }
    
    def _build_structured_postmortem(
        self,
        incident_data: Dict[str, Any],
        correlation_results: Dict[str, Any],
        workflow_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build structured postmortem from deterministic data."""
        
        incident_id = incident_data.get("incident_id", "UNKNOWN")
        title = incident_data.get("title", "Untitled Incident")
        severity = incident_data.get("severity", "sev3")
        affected_service = incident_data.get("affected_service", "unknown")
        
        # Timeline from workflow audit log
        audit_log = workflow_state.get("audit_log", [])
        
        # Correlation results
        candidates = correlation_results.get("candidates", [])
        top_candidate = correlation_results.get("top_candidate")
        model_version = correlation_results.get("model_version", "unknown")
        
        # Remediation
        remediation_action = workflow_state.get("remediation_action")
        remediation_params = workflow_state.get("remediation_params", {})
        remediation_success = workflow_state.get("remediation_success", False)
        remediation_result = workflow_state.get("remediation_result", {})
        
        # Verification
        slo_recovered = workflow_state.get("slo_recovered", False)
        verification_details = workflow_state.get("verification_details", {})
        
        # Ground truth
        ground_truth = workflow_state.get("ground_truth", {})
        
        return {
            "metadata": {
                "incident_id": incident_id,
                "title": title,
                "severity": severity,
                "affected_service": affected_service,
                "status": workflow_state.get("status", "unknown"),
                "model_version": model_version,
                "generated_at": datetime.utcnow().isoformat()
            },
            "timeline": self._build_timeline(audit_log),
            "root_cause_analysis": {
                "top_candidate": top_candidate,
                "all_candidates": candidates,
                "correlation_confidence": correlation_results.get("top_confidence", 0),
                "model_version": model_version,
                "ground_truth": ground_truth
            },
            "impact": {
                "affected_service": affected_service,
                "blast_radius": workflow_state.get("blast_radius", {}),
                "slo_breach": incident_data.get("slo_name"),
                "error_budget_burn_rate": incident_data.get("error_budget_burn_rate"),
                "duration_minutes": self._calculate_duration(workflow_state)
            },
            "remediation": {
                "action": remediation_action,
                "parameters": remediation_params,
                "approved_by": workflow_state.get("approver"),
                "approval_decision": workflow_state.get("approval_decision"),
                "success": remediation_success,
                "result": remediation_result
            },
            "verification": {
                "slo_recovered": slo_recovered,
                "details": verification_details
            },
            "lessons_learned": self._extract_lessons_learned(
                workflow_state, correlation_results, remediation_success, slo_recovered
            ),
            "action_items": self._generate_action_items(
                workflow_state, correlation_results, remediation_success, slo_recovered
            )
        }
    
    def _build_timeline(self, audit_log: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build timeline from audit log."""
        timeline = []
        for entry in audit_log:
            timeline.append({
                "timestamp": entry.get("timestamp"),
                "event": entry.get("action"),
                "details": entry.get("details", {})
            })
        return timeline
    
    def _calculate_duration(self, workflow_state: Dict[str, Any]) -> Optional[int]:
        """Calculate incident duration in minutes."""
        detected = workflow_state.get("detected_at")
        resolved = workflow_state.get("resolved_at") or workflow_state.get("completed_at")
        if detected and resolved:
            try:
                d1 = datetime.fromisoformat(detected.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                return int((d2 - d1).total_seconds() / 60)
            except:
                pass
        return None
    
    def _extract_lessons_learned(
        self,
        workflow_state: Dict[str, Any],
        correlation_results: Dict[str, Any],
        remediation_success: bool,
        slo_recovered: bool
    ) -> Dict[str, List[str]]:
        """Extract lessons learned from incident data."""
        
        went_well = []
        can_improve = []
        
        # Correlation confidence
        confidence = correlation_results.get("top_confidence", 0)
        if confidence >= 0.75:
            went_well.append("Automated correlation identified root cause with high confidence")
        elif confidence >= 0.5:
            can_improve.append("Correlation confidence was moderate; consider expanding lookback window or adding more change sources")
        else:
            can_improve.append("Correlation confidence was low; manual investigation was required")
        
        # Approval process
        if workflow_state.get("approval_decision") == "approved":
            went_well.append("Human-in-the-loop approval worked as designed")
        elif workflow_state.get("approval_decision") == "rejected":
            can_improve.append("Approval was rejected; review approval criteria")
        elif workflow_state.get("approval_decision") == "expired":
            can_improve.append("Approval request expired; consider longer timeout or better on-call coverage")
        
        # Remediation
        if remediation_success:
            went_well.append("Automated remediation executed successfully")
        else:
            can_improve.append("Remediation failed; review rollback automation and runbooks")
        
        # Verification
        if slo_recovered:
            went_well.append("SLO-based verification confirmed recovery")
        else:
            can_improve.append("SLO did not recover within verification window; investigate residual issues")
        
        # Ground truth
        if workflow_state.get("ground_truth", {}).get("confirmed"):
            went_well.append("Ground truth confirmed for model training")
        else:
            can_improve.append("No ground truth recorded; ensure validation step is completed")
        
        return {
            "went_well": went_well,
            "can_improve": can_improve
        }
    
    def _generate_action_items(
        self,
        workflow_state: Dict[str, Any],
        correlation_results: Dict[str, Any],
        remediation_success: bool,
        slo_recovered: bool
    ) -> List[Dict[str, Any]]:
        """Generate actionable follow-up items."""
        
        items = []
        item_id = 1
        
        # Always add these
        items.append({
            "id": item_id,
            "action": "Add integration test for this failure mode",
            "owner": "Engineering Team",
            "due_date": "TBD",
            "status": "open",
            "priority": "high"
        })
        item_id += 1
        
        items.append({
            "id": item_id,
            "action": "Update runbook with this incident scenario",
            "owner": "SRE Team",
            "due_date": "TBD",
            "status": "open",
            "priority": "high"
        })
        item_id += 1
        
        # Conditional items
        confidence = correlation_results.get("top_confidence", 0)
        if confidence < 0.75:
            items.append({
                "id": item_id,
                "action": "Review correlation model features and training data",
                "owner": "ML Team",
                "due_date": "TBD",
                "status": "open",
                "priority": "medium"
            })
            item_id += 1
        
        if not remediation_success:
            items.append({
                "id": item_id,
                "action": "Investigate and fix remediation automation failure",
                "owner": "Platform Team",
                "due_date": "TBD",
                "status": "open",
                "priority": "critical"
            })
            item_id += 1
        
        if not slo_recovered:
            items.append({
                "id": item_id,
                "action": "Root cause analysis for incomplete SLO recovery",
                "owner": "SRE Team",
                "due_date": "TBD",
                "status": "open",
                "priority": "high"
            })
            item_id += 1
        
        if not workflow_state.get("ground_truth", {}).get("confirmed"):
            items.append({
                "id": item_id,
                "action": "Complete ground truth validation for model training",
                "owner": "SRE Team",
                "due_date": "TBD",
                "status": "open",
                "priority": "medium"
            })
        
        return items
    
    def _render_markdown(self, postmortem: Dict[str, Any]) -> str:
        """Render structured postmortem as markdown."""
        
        meta = postmortem["metadata"]
        lines = []
        
        # Header
        lines.append(f"# Postmortem: {meta['incident_id']}")
        lines.append(f"**Title:** {meta['title']}")
        lines.append(f"**Severity:** {meta['severity'].upper()}")
        lines.append(f"**Status:** {meta['status']}")
        lines.append(f"**Affected Service:** {meta['affected_service']}")
        lines.append(f"**Model Version:** {meta['model_version']}")
        lines.append(f"**Generated:** {meta['generated_at']}")
        lines.append("")
        
        # Timeline
        lines.append("## Timeline")
        lines.append("")
        lines.append("| Time (UTC) | Event | Details |")
        lines.append("|------------|-------|---------|")
        for event in postmortem["timeline"]:
            details = event.get("details", {})
            detail_str = ", ".join(f"{k}: {v}" for k, v in details.items()) if details else ""
            lines.append(f"| {event['timestamp']} | {event['event']} | {detail_str} |")
        lines.append("")
        
        # Root Cause Analysis
        lines.append("## Root Cause Analysis")
        lines.append("")
        rca = postmortem["root_cause_analysis"]
        top = rca.get("top_candidate")
        if top:
            lines.append(f"**Top Candidate:** {top.get('service_name')} ({top.get('change_type')})")
            lines.append(f"**Confidence:** {rca.get('correlation_confidence', 0):.1%}")
            lines.append(f"**Model Version:** {rca.get('model_version')}")
            lines.append(f"**Change Details:** {top.get('evidence', {}).get('description', 'N/A')}")
            lines.append("")
        
        lines.append("### All Candidates Ranked")
        lines.append("")
        lines.append("| Rank | Service | Change Type | Source | Time | Confidence |")
        lines.append("|------|---------|-------------|--------|------|------------|")
        for i, c in enumerate(rca.get("all_candidates", []), 1):
            lines.append(f"| {i} | {c.get('service_name')} | {c.get('change_type')} | {c.get('source')} | {c.get('timestamp')} | {c.get('confidence_score', 0):.1%} |")
        lines.append("")
        
        # Ground truth
        gt = rca.get("ground_truth")
        if gt and gt.get("confirmed"):
            lines.append("### Ground Truth (Validation)")
            lines.append("")
            lines.append(f"**Confirmed Root Cause:** {gt.get('change_event_id')}")
            lines.append(f"**Fault Type:** {gt.get('fault_type')}")
            lines.append(f"**Confirmed By:** {gt.get('confirmed_by')}")
            lines.append(f"**Confirmed At:** {gt.get('confirmed_at')}")
            lines.append("")
        
        # Impact
        lines.append("## Impact")
        lines.append("")
        impact = postmortem["impact"]
        lines.append(f"**Affected Service:** {impact['affected_service']}")
        lines.append(f"**Blast Radius:** {impact['blast_radius'].get('total_services_affected', 'N/A')} services")
        lines.append(f"**SLO Breach:** {impact['slo_breach'] or 'N/A'}")
        lines.append(f"**Error Budget Burn Rate:** {impact['error_budget_burn_rate'] or 'N/A'}")
        lines.append(f"**Duration:** {impact['duration_minutes'] or 'N/A'} minutes")
        lines.append("")
        
        # Remediation
        lines.append("## Remediation")
        lines.append("")
        rem = postmortem["remediation"]
        lines.append(f"**Action:** {rem['action']}")
        lines.append(f"**Parameters:** {rem['parameters']}")
        lines.append(f"**Approved By:** {rem['approved_by']} ({rem['approval_decision']})")
        lines.append(f"**Success:** {'Yes' if rem['success'] else 'No'}")
        if rem['result']:
            lines.append(f"**Result Details:** {rem['result']}")
        lines.append("")
        
        # Verification
        lines.append("## Verification")
        lines.append("")
        ver = postmortem["verification"]
        lines.append(f"**SLO Recovered:** {'Yes' if ver['slo_recovered'] else 'No'}")
        if ver['details']:
            lines.append(f"**Details:** {ver['details']}")
        lines.append("")
        
        # Lessons Learned
        lines.append("## Lessons Learned")
        lines.append("")
        ll = postmortem["lessons_learned"]
        lines.append("### What Went Well")
        for item in ll["went_well"]:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("### What Can Be Improved")
        for item in ll["can_improve"]:
            lines.append(f"- {item}")
        lines.append("")
        
        # Action Items
        lines.append("## Action Items")
        lines.append("")
        lines.append("| # | Action Item | Owner | Due Date | Status | Priority |")
        lines.append("|---|-------------|-------|----------|--------|----------|")
        for item in postmortem["action_items"]:
            lines.append(f"| {item['id']} | {item['action']} | {item['owner']} | {item['due_date']} | {item['status']} | {item['priority']} |")
        lines.append("")
        
        # Footer
        lines.append("---")
        lines.append("*This postmortem was generated by ChangeTrace. Confidence scores are produced by a deterministic ML model, not an LLM. LLM is used only for natural language phrasing.*")
        
        return "\n".join(lines)
    
    async def _enhance_with_llm(self, markdown: str, structured: Dict[str, Any]) -> str:
        """Use LLM to improve natural language phrasing only."""
        
        # This would call the LLM with a prompt like:
        # "Rewrite the following postmortem for clarity and professional tone.
        # Do NOT change any facts, numbers, causal claims, or recommendations.
        # Only improve readability and flow."
        
        # For now, return original
        return markdown


# Azure Function entry point
async def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger for postmortem generation."""
    
    generator = PostmortemGenerator()
    
    try:
        body = req.get_json()
        
        incident_data = body.get("incident_data", {})
        correlation_results = body.get("correlation_results", {})
        workflow_state = body.get("workflow_state", {})
        
        result = await generator.generate_postmortem(
            incident_data, correlation_results, workflow_state
        )
        
        return func.HttpResponse(
            body=str(result),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Postmortem generation error: {e}")
        return func.HttpResponse(str(e), status_code=500)