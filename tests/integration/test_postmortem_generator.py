"""Integration tests for the Postmortem Generator service."""


import pytest

from services.postmortem_generator.src.main import PostmortemGenerator


class TestPostmortemGenerator:
    def setup_method(self):
        self.generator = PostmortemGenerator()

    @pytest.mark.asyncio
    async def test_generate_postmortem(self):
        incident_data = {
            "incident_id": "INC-001",
            "title": "Payment Service Latency Spike",
            "severity": "sev2",
            "affected_service": "payment-service",
        }
        correlation_results = {
            "top_candidate": {
                "service_name": "payment-service",
                "change_type": "code_deployment",
                "source": "github",
                "timestamp": "2024-01-15T14:25:00Z",
                "confidence_score": 0.87,
                "evidence": {"description": "Deploy v1.2.3"},
            },
            "top_confidence": 0.87,
            "model_version": "1.0",
            "candidates": [],
        }
        workflow_state = {
            "audit_log": [
                {"timestamp": "2024-01-15T14:30:00Z", "action": "incident_detected"},
                {"timestamp": "2024-01-15T14:32:00Z", "action": "acknowledged"},
                {"timestamp": "2024-01-15T15:00:00Z", "action": "remediation_started"},
                {"timestamp": "2024-01-15T15:15:00Z", "action": "resolved"},
            ],
            "status": "resolved",
            "remediation_action": "rollback_deployment",
            "remediation_params": {"target_version": "v1.2.2"},
            "remediation_success": True,
            "remediation_result": {"rollbacks": 1},
            "approval_decision": "approved",
            "approver": "on-call-engineer",
            "slo_recovered": True,
            "ground_truth": {"confirmed": True, "change_event_id": "evt-001"},
            "detected_at": "2024-01-15T14:30:22Z",
            "resolved_at": "2024-01-15T15:15:00Z",
        }

        result = await self.generator.generate_postmortem(
            incident_data, correlation_results, workflow_state
        )

        assert result["incident_id"] == "INC-001"
        assert "postmortem_markdown" in result
        assert "structured_data" in result

        markdown = result["postmortem_markdown"]
        assert "INC-001" in markdown
        assert "Payment Service Latency Spike" in markdown
        assert "SEV2" in markdown
        assert "Root Cause Analysis" in markdown
        assert "Remediation" in markdown
        assert "Lessons Learned" in markdown
        assert "Action Items" in markdown

    @pytest.mark.asyncio
    async def test_generate_postmortem_minimal_data(self):
        incident_data = {"incident_id": "INC-003"}
        correlation_results = {}
        workflow_state = {}

        result = await self.generator.generate_postmortem(
            incident_data, correlation_results, workflow_state
        )

        assert result["incident_id"] == "INC-003"
        assert "postmortem_markdown" in result
        markdown = result["postmortem_markdown"]
        assert "INC-003" in markdown

    def test_render_postmortem(self):
        from services.postmortem_generator.src.template_renderer import TemplateRenderer

        renderer = TemplateRenderer(
            template_dir="services/postmortem_generator/src/templates"
        )

        postmortem_data = {
            "metadata": {
                "incident_id": "INC-TEST",
                "title": "Test Incident",
                "severity": "sev3",
                "status": "resolved",
                "affected_service": "test-service",
                "model_version": "1.0",
                "generated_at": "2024-01-15T14:30:00Z",
            },
            "timeline": [
                {"timestamp": "2024-01-15T14:30:00Z", "event": "detected", "details": {}},
            ],
            "root_cause_analysis": {
                "top_candidate": None,
                "correlation_confidence": 0.0,
                "model_version": "1.0",
                "all_candidates": [],
            },
            "impact": {
                "affected_service": "test-service",
                "blast_radius": {"total_services_affected": 1},
                "slo_breach": "availability",
                "error_budget_burn_rate": 1.5,
                "duration_minutes": 45,
            },
            "remediation": {
                "action": "rollback",
                "parameters": {},
                "approved_by": "operator",
                "approval_decision": "approved",
                "success": True,
                "result": {},
            },
            "verification": {"slo_recovered": True, "details": {}},
            "lessons_learned": {"went_well": [], "can_improve": []},
            "action_items": [],
        }

        markdown = renderer.render_postmortem(postmortem_data)
        assert "INC-TEST" in markdown
        assert "Root Cause Analysis" in markdown
        assert "Action Items" in markdown
