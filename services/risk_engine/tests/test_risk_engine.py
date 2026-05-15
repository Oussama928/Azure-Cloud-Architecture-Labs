"""
Tests for Risk Engine
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.risk_engine.src.risk_scorer import RiskScorer
from services.risk_engine.src.canary_analyzer import CanaryAnalyzer
from services.risk_engine.src.slo_tracker import SLOTracker


class TestRiskScorer:
    """Test risk scoring functionality."""
    
    @pytest.fixture
    def scorer(self):
        return RiskScorer()
    
    @pytest.mark.asyncio
    async def test_score_deployment_risk(self, scorer):
        """Test deployment risk scoring."""
        result = scorer.score_deployment(
            service_name="payment-service",
            namespace="production",
            version="v1.2.3",
            change_details={
                "lines_changed": 500,
                "files_changed": 10,
                "services_affected": 1,
            }
        )
        
        assert "risk_score" in result
        assert 0 <= result["risk_score"] <= 1
        assert "risk_level" in result
        assert result["risk_level"] in ["minimal", "low", "medium", "high", "critical"]
        assert "approval_required" in result
        assert "risk_factors" in result
        assert "approval_required" in result
        assert "risk_factors" in result
    
    @pytest.mark.asyncio
    async def test_risk_categorization(self, scorer):
        """Test risk score categorization."""
        assert scorer._categorize_risk(0.95) == "critical"
        assert scorer._categorize_risk(0.8) == "high"
        assert scorer._categorize_risk(0.5) == "medium"
        assert scorer._categorize_risk(0.3) == "low"
        assert scorer._categorize_risk(0.1) == "minimal"
    
    @pytest.mark.asyncio
    async def test_heuristic_risk_score(self, scorer):
        """Test heuristic risk scoring."""
        features = {
            "change_size": 0.5,
            "files_changed": 0.2,
            "services_affected": 0.2,
            "service_criticality": 1.0,
            "dependency_count": 0.3,
            "dependent_count": 0.2,
            "recent_incidents_7d": 0.0,
            "recent_incidents_30d": 0.05,
            "change_failure_rate_7d": 0.02,
            "change_failure_rate_30d": 0.01,
            "time_since_last_deploy_hours": 0.1,
            "is_weekend": 0.0,
            "is_business_hours": 1.0,
            "team_experience_score": 0.7,
        }
        
        score = scorer._heuristic_risk_score(features)
        assert 0 <= score <= 1
    
    def test_service_criticality(self, scorer):
        """Test service criticality mapping."""
        assert scorer._get_service_criticality("payment-service") == 1.0
        assert scorer._get_service_criticality("api-gateway") == 0.9
        assert scorer._get_service_criticality("unknown-service") == 0.5


class TestCanaryAnalyzer:
    """Test canary analysis functionality."""
    
    @pytest.fixture
    def analyzer(self):
        return CanaryAnalyzer()
    
    def test_cliffs_delta(self, analyzer):
        """Test Cliff's delta effect size calculation."""
        # Identical distributions
        x = [1, 2, 3, 4, 5]
        y = [1, 2, 3, 4, 5]
        assert analyzer._cliffs_delta(x, y) == 0.0
        
        # x > y
        x = [10, 20, 30]
        y = [1, 2, 3]
        assert analyzer._cliffs_delta(x, y) == 1.0
        
        # x < y
        x = [1, 2, 3]
        y = [10, 20, 30]
        assert analyzer._cliffs_delta(x, y) == -1.0
    
    @pytest.mark.asyncio
    async def test_analyze_canary_stage(self, analyzer):
        """Test canary stage analysis."""
        result = await analyzer.analyze_canary_stage(
            service_name="payment-service",
            namespace="production",
            stage=1,
            traffic_percentage=10,
            duration_minutes=5,
            slo_threshold=0.99
        )
        
        assert result["stage"] == 1
        assert result["traffic_percentage"] == 10
        assert "passed" in result
        assert "metrics" in result
        assert "recommendation" in result
        assert result["recommendation"] in ["promote", "rollback"]


class TestSLOTracker:
    """Test SLO tracking functionality."""
    
    @pytest.fixture
    def tracker(self):
        return SLOTracker()
    
    @pytest.mark.asyncio
    async def test_get_slo_status(self, tracker):
        """Test getting SLO status for a service."""
        result = await tracker.get_slo_status("payment-service")
        
        assert result["service_name"] == "payment-service"
        assert "slos" in result
        assert "overall_status" in result
        assert result["overall_status"] in ["healthy", "degraded"]
        
        # Check SLO structure
        for slo_name, slo_data in result["slos"].items():
            assert "target" in slo_data
            assert "current" in slo_data
            assert "error_budget_remaining_pct" in slo_data
            assert "burn_rate" in slo_data
            assert "status" in slo_data
    
    @pytest.mark.asyncio
    async def test_get_all_slo_status(self, tracker):
        """Test getting SLO status for all services."""
        result = await tracker.get_all_slo_status()
        
        assert "services" in result
        assert "updated_at" in result
        assert len(result["services"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_slo_burn_rate(self, tracker):
        """Test getting SLO burn rate time series."""
        result = await tracker.get_slo_burn_rate(
            service_name="payment-service",
            slo_name="availability",
            hours=24,
            interval_minutes=5
        )
        
        assert isinstance(result, list)
        assert len(result) > 0
        for point in result:
            assert "timestamp" in point
            assert "burn_rate" in point
            assert "error_budget_remaining" in point


if __name__ == "__main__":
    pytest.main([__file__, "-v"])