"""Postmortem Generator Service for ChangeTrace."""

import logging
import os
from datetime import datetime
from typing import Any

import azure.functions as func

from services.postmortem_generator.src.template_renderer import TemplateRenderer

logger = logging.getLogger(__name__)


class PostmortemGenerator:
    """Generates structured postmortem documents."""

    def __init__(self):
        self.use_llm = os.getenv("USE_LLM_FOR_REPORTS", "false").lower() == "true"
        self.llm_endpoint = os.getenv("LLM_ENDPOINT")
        self.llm_key = os.getenv("LLM_KEY")

    async def generate_postmortem(
        self,
        incident_data: dict[str, Any],
        correlation_results: dict[str, Any],
        workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a complete postmortem document."""
        logger.info(f"Generating postmortem for incident {incident_data.get('incident_id')}")

        postmortem = self._build_structured_postmortem(
            incident_data, correlation_results, workflow_state
        )

        markdown = self._render_markdown(postmortem)

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
        incident_data: dict[str, Any],
        correlation_results: dict[str, Any],
        workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Build structured postmortem from deterministic data."""

        incident_id = incident_data.get("incident_id", "UNKNOWN")
        title = incident_data.get("title", "Untitled Incident")
        severity = incident_data.get("severity", "sev3")
        affected_service = incident_data.get("affected_service", "unknown")

        audit_log = workflow_state.get("audit_log", [])

        candidates = correlation_results.get("candidates", [])
        top_candidate = correlation_results.get("top_candidate")
        model_version = correlation_results.get("model_version", "unknown")

        remediation_action = workflow_state.get("remediation_action")
        remediation_params = workflow_state.get("remediation_params", {})
        remediation_success = workflow_state.get("remediation_success", False)
        remediation_result = workflow_state.get("remediation_result", {})

        slo_recovered = workflow_state.get("slo_recovered", False)
        verification_details = workflow_state.get("verification_details", {})

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

    def _build_timeline(self, audit_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build timeline from audit log."""
        timeline = []
        for entry in audit_log:
            timeline.append({
                "timestamp": entry.get("timestamp"),
                "event": entry.get("action"),
                "details": entry.get("details", {})
            })
        return timeline

    def _calculate_duration(self, workflow_state: dict[str, Any]) -> int | None:
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
        workflow_state: dict[str, Any],
        correlation_results: dict[str, Any],
        remediation_success: bool,
        slo_recovered: bool
    ) -> dict[str, list[str]]:
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
        workflow_state: dict[str, Any],
        correlation_results: dict[str, Any],
        remediation_success: bool,
        slo_recovered: bool
    ) -> list[dict[str, Any]]:
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

    def _render_markdown(self, postmortem: dict[str, Any]) -> str:
        """Render structured postmortem as markdown using Jinja2 templates."""
        template_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "templates",
        )
        renderer = TemplateRenderer(template_dir=template_dir)
        return renderer.render_postmortem(postmortem)

    async def _enhance_with_llm(self, markdown: str, structured: dict[str, Any]) -> str:
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


# FastAPI wrapper for Kubernetes deployment
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any

app = FastAPI(title="ChangeTrace Postmortem Generator", version="1.0.0")

class PostmortemRequest(BaseModel):
    incident_data: Dict[str, Any]
    correlation_results: Dict[str, Any]
    workflow_state: Dict[str, Any]

@app.post("/generate")
async def generate_postmortem(request: PostmortemRequest):
    """Generate postmortem via FastAPI"""
    generator = PostmortemGenerator()
    result = await generator.generate_postmortem(
        request.incident_data,
        request.correlation_results,
        request.workflow_state
    )
    return result

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "postmortem-generator"}
