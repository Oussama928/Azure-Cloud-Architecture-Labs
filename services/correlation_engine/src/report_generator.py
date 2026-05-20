"""
Report Generator for ChangeTrace Correlation Engine

Generates human-readable incident correlation reports.
Uses LLM only for natural language phrasing
"""

import json
import logging
from datetime import datetime
from typing import Any

from .models.correlation import CorrelationResponse, Incident

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generates incident correlation reports.

    The LLM is used ONLY for natural language phrasing of deterministic findings.
    """

    def __init__(self, use_llm: bool = False, llm_client: Any = None):
        self.use_llm = use_llm
        self.llm_client = llm_client

    def generate_report(self, response: CorrelationResponse, incident: Incident) -> str:
        """
        Generate a full incident correlation report.

        Args:
            response: Correlation response with ranked candidates
            incident: Incident details

        Returns:
            Formatted report string
        """
        sections = []

        # Header
        sections.append(self._generate_header(incident))

        # Executive Summary
        sections.append(self._generate_executive_summary(response, incident))

        # Incident Details
        sections.append(self._generate_incident_details(incident))

        # Top Candidates
        sections.append(self._generate_candidates_section(response))

        # Evidence Summary
        sections.append(self._generate_evidence_section(response))

        # Recommendations
        sections.append(self._generate_recommendations(response, incident))

        # Technical Details
        sections.append(self._generate_technical_details(response))

        return "\n\n".join(sections)

    def _generate_header(self, incident: Incident) -> str:
        """Generate report header"""
        return f"""# Incident Correlation Report

**Incident ID:** {incident.incident_id}
**Title:** {incident.title}
**Severity:** {incident.severity.value}
**Status:** {incident.status.value}
**Generated:** {datetime.utcnow().isoformat()}Z
**Affected Service:** {incident.affected_service}
**Namespace:** {incident.affected_namespace or 'N/A'}"""

    def _generate_executive_summary(self, response: CorrelationResponse, incident: Incident) -> str:
        """Generate executive summary"""
        if not response.candidates:
            return """## Executive Summary

No candidate root causes were identified within the analysis window. This could indicate:
- The root cause is outside the lookback period
- The change was not captured by our change sources
- The incident was caused by an external factor (e.g., cloud provider issue)

**Recommendation:** Expand lookback window and verify all change sources are configured."""

        top = response.candidates[0]
        confidence_pct = top.confidence_score * 100

        summary = f"""## Executive Summary

**Top Candidate:** {top.evidence.get('description', 'Unknown change')} (Confidence: {confidence_pct:.1f}%)

**Change Details:**
- **Type:** {top.change_type.replace('_', ' ').title()}
- **Service:** {top.service_name}
- **Source:** {top.source.value}
- **Time:** {top.timestamp.isoformat()}Z
- **Author:** {top.evidence.get('author', 'Unknown')}

**Assessment:** """

        if top.confidence_score >= 0.75:
            summary += "High confidence. This change is the likely root cause and warrants immediate investigation."
        elif top.confidence_score >= 0.5:
            summary += "Moderate confidence. This change is a strong candidate but should be verified before action."
        else:
            summary += "Low confidence. Multiple candidates exist; manual investigation recommended."

        if len(response.candidates) > 1:
            summary += f"\n\n**Alternative Candidates:** {len(response.candidates) - 1} other changes were identified and ranked."

        return summary

    def _generate_incident_details(self, incident: Incident) -> str:
        """Generate incident details section"""
        details = f"""## Incident Details

**SLO Breach:** {incident.slo_name or 'Not specified'}
**Error Budget Burn Rate:** {incident.error_budget_burn_rate or 'N/A'}
**Detected At:** {incident.detected_at.isoformat()}Z
**Started At:** {incident.started_at.isoformat() if incident.started_at else 'Unknown'}

**Blast Radius Services:** {', '.join(incident.blast_radius_services) if incident.blast_radius_services else 'Not computed'}

**Labels:** {json.dumps(incident.labels, indent=2) if incident.labels else 'None'}"""

        return details

    def _generate_candidates_section(self, response: CorrelationResponse) -> str:
        """Generate ranked candidates section"""
        if not response.candidates:
            return "## Ranked Candidates\n\nNo candidates found."

        lines = ["## Ranked Root Cause Candidates\n"]

        for i, candidate in enumerate(response.candidates, 1):
            confidence_pct = candidate.confidence_score * 100

            lines.append(f"### {i}. {candidate.service_name} — {confidence_pct:.1f}% Confidence")
            lines.append(f"**Change ID:** {candidate.change_event_id}")
            lines.append(f"**Change Type:** {candidate.change_type.replace('_', ' ').title()}")
            lines.append(f"**Source:** {candidate.source.value}")
            lines.append(f"**Timestamp:** {candidate.timestamp.isoformat()}Z")
            lines.append(f"**Author:** {candidate.evidence.get('author', 'Unknown')}")
            lines.append(f"**Pipeline:** {candidate.evidence.get('pipelineName', 'N/A')}")

            if candidate.evidence.get('deploymentId'):
                lines.append(f"**Deployment ID:** {candidate.evidence['deploymentId']}")
            if candidate.evidence.get('newVersion'):
                lines.append(f"**Version:** {candidate.evidence['newVersion']}")

            lines.append(f"\n**Description:** {candidate.evidence.get('description', 'No description')}")

            # Score breakdown
            lines.append("\n**Score Breakdown:**")
            lines.append(f"- Graph Distance: {candidate.graph_distance_score:.2f}")
            lines.append(f"- Temporal Proximity: {candidate.temporal_proximity_score:.2f}")
            lines.append(f"- Change Type: {candidate.change_type_score:.2f}")
            lines.append(f"- Historical Base Rate: {candidate.historical_base_rate_score:.2f}")

            if candidate.evidence.get('ground_truth'):
                lines.append("\n **Confirmed as root cause in validation**")

            lines.append("")  # Empty line between candidates

        return "\n".join(lines)

    def _generate_evidence_section(self, response: CorrelationResponse) -> str:
        """Generate evidence summary section"""
        lines = ["## Evidence Summary\n"]

        for candidate in response.candidates[:3]:  # Top 3
            lines.append(f"### {candidate.service_name}")

            # Graph evidence
            if candidate.graph_distance_score > 0:
                lines.append(f"- **Graph Distance:** {candidate.graph_distance_score:.2f} (closer = more likely)")

            # Temporal evidence
            if candidate.temporal_proximity_score > 0:
                lines.append(f"- **Time Since Change:** {candidate.temporal_proximity_score:.2f} (more recent = more likely)")

            # Change type evidence
            lines.append(f"- **Change Type:** {candidate.change_type} (weight: {candidate.change_type_score:.2f})")

            # Historical evidence
            if candidate.historical_base_rate_score > 0:
                lines.append(f"- **Historical Failure Rate:** {candidate.historical_base_rate_score:.2f}")

            # Blast radius
            if candidate.blast_radius_services:
                lines.append(f"- **Blast Radius:** {', '.join(candidate.blast_radius_services)}")

            lines.append("")

        return "\n".join(lines)

    def _generate_recommendations(self, response: CorrelationResponse, incident: Incident) -> str:
        """Generate actionable recommendations"""
        lines = ["## Recommendations\n"]

        if not response.candidates:
            lines.append("1. **Expand investigation window** - Increase lookback period to 24-48 hours")
            lines.append("2. **Verify change source coverage** - Ensure all CI/CD, Git, and infrastructure sources are configured")
            lines.append("3. **Check external dependencies** - Investigate cloud provider status, DNS, CDN, etc.")
            return "\n".join(lines)

        top = response.candidates[0]

        if top.confidence_score >= 0.75:
            lines.append(f"1. **Immediate Action:** Investigate {top.service_name} change ({top.change_event_id}) as primary root cause")
            lines.append("2. **Rollback Consideration:** If change is a deployment, prepare rollback to previous version")
            lines.append("3. **Validation:** Verify SLO recovery after any remediation action")
        elif top.confidence_score >= 0.5:
            lines.append(f"1. **Priority Investigation:** Focus on {top.service_name} change ({top.change_event_id})")
            lines.append("2. **Parallel Investigation:** Review alternative candidates:")
            for c in response.candidates[1:4]:
                lines.append(f"   - {c.service_name} ({c.confidence_score*100:.0f}% confidence)")
            lines.append("3. **Verification:** Confirm hypothesis before taking remediation action")
        else:
            lines.append("1. **Manual Investigation Required:** Low confidence across all candidates")
            lines.append("2. **Review Top Candidates:**")
            for c in response.candidates[:5]:
                lines.append(f"   - {c.service_name} ({c.confidence_score*100:.0f}%) - {c.change_type}")
            lines.append("3. **Expand Data Sources:** Check logs, metrics, and traces directly")

        lines.append("")
        lines.append("**Standard Remediation Actions (require human approval):**")
        lines.append("- Rollback deployment (if deployment-related)")
        lines.append("- Restart affected workload")
        lines.append("- Revert configuration change")
        lines.append("- Scale up affected service")

        return "\n".join(lines)

    def _generate_technical_details(self, response: CorrelationResponse) -> str:
        """Generate technical details section"""
        return f"""## Technical Details

**Model Version:** {response.model_version}
**Analysis Time:** {response.analysis_time_ms:.1f}ms
**Features Used:** {len(response.features_used)}
**Lookback Window:** 2 hours (configurable)
**Max Candidates:** {len(response.candidates)}

**Feature Names:**
{json.dumps(response.features_used, indent=2)}

**Model Info:**
- Type: Gradient Boosted Trees (LightGBM) with calibration
- Features: Graph topology, temporal proximity, change characteristics, historical patterns
- Training: Requires 200+ labeled examples for ML mode; uses heuristics until then

---
*This report was generated by ChangeTrace Correlation Engine.
Confidence scores are produced by a deterministic ML model, not an LLM.
LLM is used only for natural language phrasing of deterministic findings.*"""

    def generate_slack_summary(self, response: CorrelationResponse, incident: Incident) -> str:
        """Generate concise Slack-friendly summary"""
        if not response.candidates:
            return f"🔍 *Incident {incident.incident_id}*: No root cause candidates found. Manual investigation needed."

        top = response.candidates[0]
        confidence_pct = top.confidence_score * 100

        emoji = "🔴" if confidence_pct >= 75 else "🟡" if confidence_pct >= 50 else "🟢"

        return f"""{emoji} *Incident {incident.incident_id}* - {incident.title}
*Top Candidate:* {top.service_name} ({confidence_pct:.0f}% confidence)
*Change:* {top.change_type.replace('_', ' ').title()} by {top.evidence.get('author', 'unknown')} at {top.timestamp.strftime('%H:%M UTC')}
*Action:* {'High confidence - investigate immediately' if confidence_pct >= 75 else 'Moderate confidence - verify before action' if confidence_pct >= 50 else 'Low confidence - manual investigation needed'}"""

    def generate_approval_request(self, response: CorrelationResponse, incident: Incident) -> dict[str, Any]:
        """Generate structured approval request for human-in-the-loop"""
        if not response.candidates:
            return {
                "incident_id": incident.incident_id,
                "requires_approval": False,
                "reason": "No candidates found",
            }

        top = response.candidates[0]

        # Only request approval for high-confidence candidates
        if top.confidence_score < 0.75:
            return {
                "incident_id": incident.incident_id,
                "requires_approval": False,
                "reason": f"Confidence {top.confidence_score*100:.0f}% below approval threshold (75%)",
                "top_candidate": {
                    "service": top.service_name,
                    "confidence": top.confidence_score,
                    "change_type": top.change_type,
                },
            }

        # Determine recommended action
        if top.change_type == "code_deployment":
            action = "rollback_deployment"
            action_params = {
                "deployment_id": top.evidence.get('deploymentId'),
                "service": top.service_name,
            }
        elif top.change_type in ["config_change", "infrastructure_change"]:
            action = "revert_change"
            action_params = {
                "change_id": top.change_event_id,
                "service": top.service_name,
            }
        else:
            action = "restart_workload"
            action_params = {
                "service": top.service_name,
            }

        return {
            "incident_id": incident.incident_id,
            "requires_approval": True,
            "confidence": top.confidence_score,
            "top_candidate": {
                "service": top.service_name,
                "change_type": top.change_type,
                "change_id": top.change_event_id,
                "timestamp": top.timestamp.isoformat(),
                "author": top.evidence.get('author'),
                "description": top.evidence.get('description'),
            },
            "recommended_action": action,
            "action_params": action_params,
            "alternative_candidates": [
                {
                    "service": c.service_name,
                    "confidence": c.confidence_score,
                    "change_type": c.change_type,
                }
                for c in response.candidates[1:4]
            ],
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat() + "Z",
        }


# Import timedelta for approval request
from datetime import timedelta
