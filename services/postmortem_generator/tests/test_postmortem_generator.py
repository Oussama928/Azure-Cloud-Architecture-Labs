"""Unit tests for the Postmortem Generator service."""

import os
from datetime import datetime, timezone

import pytest

from services.postmortem_generator.src.main import PostmortemGenerator
from services.postmortem_generator.src.template_renderer import TemplateRenderer
from services.postmortem_generator.src.llm_phraser import LLMPhraser


FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..", "..", "services", "postmortem_generator", "src", "templates",
)


class TestTemplateRenderer:
    def setup_method(self):
        self.renderer = TemplateRenderer(template_dir=FIXTURE_DIR)

    def test_render_postmortem(self):
        data = {
            "metadata": {
                "incident_id": "INC-100",
                "title": "API Timeout",
                "severity": "sev1",
                "status": "resolved",
                "affected_service": "api-gateway",
                "model_version": "2.0",
                "generated_at": "2024-06-01T12:00:00Z",
            },
            "timeline": [],
            "root_cause_analysis": {
                "top_candidate": None,
                "correlation_confidence": 0.0,
                "model_version": "2.0",
                "all_candidates": [],
            },
            "impact": {
                "affected_service": "api-gateway",
                "blast_radius": {"total_services_affected": 3},
                "slo_breach": "availability",
                "error_budget_burn_rate": 2.1,
                "duration_minutes": 30,
            },
            "remediation": {
                "action": "rollback",
                "parameters": {"version": "v1.0.0"},
                "approved_by": "sre-oncall",
                "approval_decision": "approved",
                "success": True,
                "result": {},
            },
            "verification": {"slo_recovered": True, "details": {}},
            "lessons_learned": {
                "went_well": ["Quick detection"],
                "can_improve": ["Better alerting"],
            },
            "action_items": [
                {
                    "id": 1,
                    "action": "Add test",
                    "owner": "Team",
                    "due_date": "TBD",
                    "status": "open",
                    "priority": "high",
                }
            ],
        }
        result = self.renderer.render_postmortem(data)
        assert "INC-100" in result
        assert "API Timeout" in result
        assert "SEV1" in result
        assert "Root Cause Analysis" in result
        assert "Quick detection" in result
        assert "Add test" in result

    def test_render_slack_summary(self):
        data = {
            "metadata": {
                "incident_id": "INC-200",
                "severity": "sev2",
                "status": "investigating",
                "title": "DB Latency",
                "affected_service": "db-proxy",
            },
            "root_cause_analysis": {
                "top_candidate": {"service_name": "db-proxy"},
                "correlation_confidence": 0.82,
            },
            "remediation": {"action": "restart"},
            "verification": {"slo_recovered": False},
        }
        result = self.renderer.render_slack_summary(data)
        assert "INC-200" in result
        assert "SEV2" in result
        assert "82%" in result

    def test_render_approval_request(self):
        data = {
            "approval": {
                "incident_id": "INC-300",
                "service_name": "payment-service",
                "action": "rollback_deployment",
                "risk_level": "high",
                "confidence": 0.91,
                "description": "Rollback due to latency",
                "parameters": {"target_version": "v1.0.0"},
                "requested_by": "sre-bot",
                "expires_at": "2024-06-01T13:00:00Z",
                "decision": "pending",
            }
        }
        result = self.renderer.render_approval_request(data)
        assert "INC-300" in result
        assert "rollback_deployment" in result
        assert "91%" in result
        assert "payment-service" in result

    def test_render_postmortem_missing_template(self):
        renderer = TemplateRenderer(template_dir="/nonexistent/path")
        result = renderer._render_with_template("missing.j2", {})
        assert result == ""

    def test_datetime_format_filter(self):
        result = self.renderer._datetime_format("2024-06-01T12:00:00Z")
        assert "2024" in result
        assert "06" in result

    def test_percentage_filter(self):
        result = self.renderer._percentage(0.856, decimals=1)
        assert result == "85.6%"

    def test_duration_minutes_filter(self):
        result = self.renderer._duration_minutes(
            "2024-06-01T12:00:00Z", "2024-06-01T12:45:00Z"
        )
        assert result == 45


class TestLLMPhraser:
    def test_init_disabled_by_default(self):
        phraser = LLMPhraser()
        assert phraser.enabled is False

    @pytest.mark.asyncio
    async def test_enhance_postmortem_disabled(self):
        phraser = LLMPhraser()
        result = await phraser.enhance_postmortem("original", {})
        assert result == "original"

    @pytest.mark.asyncio
    async def test_enhance_slack_summary_disabled(self):
        phraser = LLMPhraser()
        result = await phraser.enhance_slack_summary("original", {})
        assert result == "original"

    @pytest.mark.asyncio
    async def test_enhance_approval_request_disabled(self):
        phraser = LLMPhraser()
        result = await phraser.enhance_approval_request({"description": "test"})
        assert result["description"] == "test"

    def test_build_enhancement_prompt(self):
        phraser = LLMPhraser()
        prompt = phraser._build_enhancement_prompt("markdown content", {"key": "val"})
        assert "markdown content" in prompt
        assert "STRICT RULES" in prompt


class TestPostmortemGenerator:
    def setup_method(self):
        self.gen = PostmortemGenerator()

    def test_build_structured_postmortem(self):
        incident = {
            "incident_id": "INC-400",
            "title": "Disk Full",
            "severity": "sev3",
            "affected_service": "storage-worker",
        }
        result = self.gen._build_structured_postmortem(incident, {}, {})
        assert result["metadata"]["incident_id"] == "INC-400"
        assert result["impact"]["affected_service"] == "storage-worker"
        assert result["remediation"]["action"] is None

    def test_build_timeline(self):
        audit_log = [
            {"timestamp": "2024-01-01T00:00:00Z", "action": "detected", "details": {"msg": "alert"}},
            {"timestamp": "2024-01-01T00:05:00Z", "action": "resolved", "details": {}},
        ]
        timeline = self.gen._build_timeline(audit_log)
        assert len(timeline) == 2
        assert timeline[0]["event"] == "detected"
        assert timeline[1]["event"] == "resolved"

    def test_calculate_duration(self):
        state = {
            "detected_at": "2024-06-01T12:00:00Z",
            "resolved_at": "2024-06-01T12:30:00Z",
        }
        assert self.gen._calculate_duration(state) == 30

    def test_calculate_duration_missing(self):
        assert self.gen._calculate_duration({}) is None

    def test_calculate_duration_completed_at(self):
        state = {
            "detected_at": "2024-06-01T12:00:00Z",
            "completed_at": "2024-06-01T14:00:00Z",
        }
        assert self.gen._calculate_duration(state) == 120

    def test_extract_lessons_learned_high_confidence(self):
        lessons = self.gen._extract_lessons_learned(
            {"approval_decision": "approved"},
            {"top_confidence": 0.9},
            True,
            True,
        )
        assert any("high confidence" in x for x in lessons["went_well"])

    def test_extract_lessons_learned_low_confidence(self):
        lessons = self.gen._extract_lessons_learned(
            {"approval_decision": "rejected"},
            {"top_confidence": 0.3},
            False,
            False,
        )
        assert any("low" in x for x in lessons["can_improve"])
        assert any("rejected" in x for x in lessons["can_improve"])

    def test_extract_lessons_expired_approval(self):
        lessons = self.gen._extract_lessons_learned(
            {"approval_decision": "expired"}, {}, False, False
        )
        assert any("expired" in x for x in lessons["can_improve"])

    def test_generate_action_items_minimum(self):
        items = self.gen._generate_action_items({}, {"top_confidence": 0.9}, True, True)
        assert len(items) >= 2
        assert items[0]["priority"] == "high"
        assert items[1]["priority"] == "high"

    def test_generate_action_items_failure_path(self):
        items = self.gen._generate_action_items(
            {"ground_truth": {"confirmed": False}},
            {"top_confidence": 0.3},
            False,
            False,
        )
        priorities = [i["priority"] for i in items]
        assert "critical" in priorities
        assert any("correlation" in i["action"].lower() for i in items)

    @pytest.mark.asyncio
    async def test_generate_postmortem_full(self):
        result = await self.gen.generate_postmortem(
            {"incident_id": "INC-500", "title": "Test"},
            {
                "top_confidence": 0.8,
                "top_candidate": {
                    "service_name": "svc",
                    "change_type": "deploy",
                    "source": "github",
                    "evidence": {"description": "deployed v2.0"},
                },
            },
            {
                "status": "resolved",
                "remediation_action": "rollback",
                "remediation_success": True,
                "slo_recovered": True,
            },
        )
        assert result["incident_id"] == "INC-500"
        assert "postmortem_markdown" in result
        assert len(result["postmortem_markdown"]) > 0

    @pytest.mark.asyncio
    async def test_generate_postmortem_with_ground_truth(self):
        result = await self.gen.generate_postmortem(
            {"incident_id": "INC-600"},
            {
                "top_confidence": 0.95,
                "candidates": [],
                "top_candidate": {
                    "service_name": "x",
                    "change_type": "config",
                    "source": "terraform",
                    "evidence": {"description": "changed config"},
                },
            },
            {
                "ground_truth": {"confirmed": True, "change_event_id": "evt-1"},
                "slo_recovered": True,
                "remediation_success": True,
                "approval_decision": "approved",
            },
        )
        assert "INC-600" in result["postmortem_markdown"]
        assert "Ground Truth" in result["postmortem_markdown"]
