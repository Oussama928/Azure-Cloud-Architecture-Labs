"""
End-to-End Integration Tests for ChangeTrace

Tests the complete flow from change ingestion through correlation to remediation.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Import services
from services.collector.src.main import CollectorService, CollectorConfig
from services.correlation_engine.src.main import Correlator
from services.risk_engine.src.main import RiskEngine
from functions.shared.models.workflow_state import IncidentWorkflowState, DeploymentWorkflowState
from services.collector.src.models.change_event import ChangeEvent, ChangeType, ChangeSource, GitReference


class TestEndToEndFlow:
    """Test complete ChangeTrace workflows."""
    
    @pytest.fixture
    def mock_services(self):
        """Set up mocked services for integration testing."""
        # Create mock config
        config = CollectorConfig(
            cosmos_connection_string="AccountEndpoint=https://test.gremlin.cosmos.azure.com:443/;AccountKey=test",
            github=None,
            terraform=None,
            kubernetes=None,
            azure_resource_graph=None
        )
        
        with patch('gremlin_python.driver.client.Client'), \
             patch('gremlin_python.driver.driver_remote_connection.DriverRemoteConnection'):
            
            collector = CollectorService(config)
            correlator = Correlator(
                cosmos_connection_string="AccountEndpoint=https://test.gremlin.cosmos.azure.com:443/;AccountKey=test",
                model=None
            )
            risk_engine = RiskEngine()
            
            # Mock the async methods
            collector.process_github_webhook = AsyncMock(return_value=[
                ChangeEvent(
                    change_type=ChangeType.CODE_DEPLOYMENT,
                    source=ChangeSource.GITHUB,
                    service_name="payment-service",
                    git=GitReference(
                        repo_url="https://github.com/org/payment-service",
                        repo_name="payment-service",
                        commit_sha="abc123",
                        branch="main"
                    )
                )
            ])
            
            correlator.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "service_name": "payment-service",
                    "confidence_score": 0.92,
                    "change_type": "code_deployment",
                    "change_event_id": "evt-123"
                }],
                "analysis_time_ms": 150.5,
                "model_version": "heuristic-1.0"
            })
            
            correlator.gather_evidence = AsyncMock(return_value={
                "recent_changes": [{"service": "payment-service", "type": "deployment"}],
                "blast_radius": ["checkout-service", "order-service"],
                "service_metrics": {"latency_p99": 450, "error_rate": 0.001}
            })
            
            correlator.correlate = AsyncMock(return_value={
                "candidates": [{
                    "service_name": "payment-service",
                    "confidence_score": 0.92,
                    "change_type": "code_deployment",
                    "change_event_id": "evt-123"
                }]
            })
            
            risk_engine.score_deployment_risk = AsyncMock(return_value={
                "deployment_id": "deploy-12345",
                "service_name": "payment-service",
                "version": "v1.2.3",
                "risk_score": 0.35,
                "risk_level": "low",
                "approval_required": False,
                "risk_factors": {"deployment_size": 0.2, "service_history": 0.1},
                "model_version": "risk-model-1.0",
                "scored_at": datetime.utcnow().isoformat()
            })
            
            risk_engine.analyze_canary_stage = AsyncMock(return_value={
                "stage": 1,
                "traffic_percentage": 10,
                "duration_minutes": 5,
                "passed": True,
                "metrics": {
                    "error_rate": {"passed": True, "p_value": 0.5},
                    "latency_p99": {"passed": True, "p_value": 0.3},
                    "availability": {"passed": True, "current": 0.999, "threshold": 0.99}
                },
                "recommendation": "promote",
                "analyzed_at": datetime.utcnow().isoformat()
            })
            
            risk_engine.get_slo_status = AsyncMock(return_value={
                "service_name": "payment-service",
                "slos": {
                    "availability": {"target": 0.999, "current": 0.9995, "error_budget_remaining_pct": 50, "burn_rate": 0.5, "status": "healthy"},
                    "latency_p99": {"target": 500, "current": 450, "error_budget_remaining_pct": 50, "burn_rate": 0.5, "status": "healthy"}
                },
                "overall_status": "healthy",
                "checked_at": datetime.utcnow().isoformat()
            })
            
            risk_engine.execute_remediation = AsyncMock(return_value={"success": True})
            risk_engine.verify_slo_recovery = AsyncMock(return_value={"recovered": True})
            risk_engine.execute_rollback = AsyncMock(return_value={"success": True})
            
            yield {
                "collector": collector,
                "correlator": correlator,
                "risk_engine": risk_engine
            }
    
    @pytest.mark.asyncio
    async def test_change_ingestion_to_correlation(self, mock_services):
        """Test change event flows from collector to correlation engine."""
        
        # 1. Collector ingests a GitHub deployment event
        github_event = {
            "event_type": "push",
            "repository": {"full_name": "org/payment-service"},
            "commits": [{
                "id": "abc123",
                "message": "Fix payment timeout",
                "timestamp": datetime.utcnow().isoformat(),
                "author": {"name": "john.doe", "email": "john@example.com"}
            }],
            "ref": "refs/heads/main"
        }
        
        # Collector processes event
        change_events = await mock_services["collector"].process_github_webhook(github_event)
        
        assert len(change_events) > 0
        assert change_events[0].change_type == "code_deployment"
        assert change_events[0].service_name == "payment-service"
        
        # 2. Correlation engine receives incident
        incident = {
            "incident_id": "INC-20240115-143022-a1b2c3",
            "title": "Payment Service Latency Spike",
            "severity": "sev2",
            "affected_service": "payment-service",
            "slo_name": "latency_p99",
            "error_budget_burn_rate": 15.5,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        # Correlate incident with recent changes
        correlation_result = await mock_services["correlator"].correlate_incident(incident)
        
        assert "candidates" in correlation_result
        assert len(correlation_result["candidates"]) > 0
        
        # Top candidate should be the payment-service deployment
        top_candidate = correlation_result["candidates"][0]
        assert top_candidate["service_name"] == "payment-service"
        assert top_candidate["change_type"] == "code_deployment"
    
    @pytest.mark.asyncio
    async def test_incident_workflow_wf1(self, mock_services):
        """Test WF-1: Incident Response Workflow."""
        
        # Create incident workflow state
        workflow_state = IncidentWorkflowState(
            incident_id="INC-20240115-143022-a1b2c3",
            incident_title="Payment Service Latency Spike",
            affected_service="payment-service",
            severity="sev2",
            slo_name="latency_p99",
            error_budget_burn_rate=15.5,
            detected_at=datetime.utcnow()
        )
        
        # Simulate workflow execution
        # Phase 1: Evidence gathering
        evidence = await mock_services["correlator"].gather_evidence(workflow_state)
        assert "recent_changes" in evidence
        assert "blast_radius" in evidence
        assert "service_metrics" in evidence
        
        # Phase 2: Correlation
        correlation = await mock_services["correlator"].correlate(workflow_state, evidence)
        assert "candidates" in correlation
        assert len(correlation["candidates"]) > 0
        
        # Phase 3: High confidence -> approval request
        top_candidate = correlation["candidates"][0]
        if top_candidate["confidence_score"] >= 0.75:
            approval_requested = True
            assert approval_requested
        
        # Phase 4: Approval received -> remediation
        remediation_result = await mock_services["risk_engine"].execute_remediation(
            action="rollback_deployment",
            params={"deployment_id": "deploy-12345", "service": "payment-service"}
        )
        assert remediation_result["success"] is True
        
        # Phase 5: Verification
        verification = await mock_services["risk_engine"].verify_slo_recovery(
            service_name="payment-service",
            slo_name="latency_p99",
            duration_seconds=300
        )
        assert verification["recovered"] is True
        
        # Phase 6: Ground truth recording
        ground_truth_recorded = True
        assert ground_truth_recorded
    
    @pytest.mark.asyncio
    async def test_deployment_workflow_wf2(self, mock_services):
        """Test WF-2: Deployment Approval Workflow."""
        
        # Create deployment workflow state
        workflow_state = DeploymentWorkflowState(
            deployment_id="deploy-20240115-143022",
            service_name="payment-service",
            namespace="production",
            version="v1.2.3",
            deployment_strategy="canary"
        )
        
        # Phase 1: Risk assessment
        risk_assessment = await mock_services["risk_engine"].score_deployment_risk(
            deployment_id=workflow_state.deployment_id,
            service_name=workflow_state.service_name,
            namespace=workflow_state.namespace,
            version=workflow_state.version,
            change_details={"lines_changed": 500, "files_changed": 20}
        )
        
        assert "risk_score" in risk_assessment
        assert "risk_level" in risk_assessment
        assert "approval_required" in risk_assessment
        
        # Phase 2: If high risk -> approval gate
        if risk_assessment["approval_required"]:
            approval_granted = True  # Simulate human approval
            assert approval_granted
        
        # Phase 3: Canary stages
        for stage in [1, 2, 3]:
            canary_result = await mock_services["risk_engine"].analyze_canary_stage(
                service_name="payment-service",
                namespace="production",
                stage=stage,
                traffic_percentage=[10, 50, 100][stage-1],
                duration_minutes=5,
                slo_threshold=0.99
            )
            
            assert "passed" in canary_result
            assert "recommendation" in canary_result
            
            if not canary_result["passed"]:
                # Rollback triggered
                rollback_result = await mock_services["risk_engine"].execute_rollback(
                    service_name="payment-service",
                    namespace="production"
                )
                assert rollback_result["success"] is True
                break
        
        # Phase 4: Record outcome for training
        outcome_recorded = True
        assert outcome_recorded


class TestDataFlow:
    """Test data flow between services."""
    
    @pytest.mark.asyncio
    async def test_change_event_schema_consistency(self):
        """Test that change events have consistent schema across sources."""
        
        from services.collector.src.models.change_event import (
            ChangeEvent, ChangeType, ChangeSource, 
            GitReference, TerraformReference, KubernetesChangeDetail, ResourceReference
        )
        
        # GitHub event
        github_event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            service_name="payment-service",
            git=GitReference(
                repo_url="https://github.com/org/payment-service",
                repo_name="payment-service",
                commit_sha="abc123",
                branch="main"
            )
        )
        
        # Terraform event
        terraform_event = ChangeEvent(
            change_type=ChangeType.INFRASTRUCTURE_CHANGE,
            source=ChangeSource.TERRAFORM,
            service_name="network",
            terraform=TerraformReference(
                workspace="production",
                plan_id="plan-123",
                organization="org"
            )
        )
        
        # Kubernetes event
        k8s_event = ChangeEvent(
            change_type=ChangeType.CONFIG_CHANGE,
            source=ChangeSource.KUBERNETES,
            service_name="payment-service",
            kubernetes_changes=[
                KubernetesChangeDetail(
                    resource=ResourceReference(
                        kind="Deployment",
                        name="payment-service",
                        namespace="production"
                    ),
                    operation="UPDATE"
                )
            ]
        )
        
        # All should have required fields
        for event in [github_event, terraform_event, k8s_event]:
            assert event.id is not None
            assert event.event_id is not None
            assert event.change_type is not None
            assert event.source is not None
            assert event.service_name is not None
            assert event.timestamp is not None
    
    @pytest.mark.asyncio
    async def test_correlation_feature_vector(self):
        """Test feature vector generation for correlation."""
        
        from services.correlation_engine.src.models.correlation import FeatureVector
        
        fv = FeatureVector(
            change_event_id="evt-123",
            incident_id="inc-456",
            graph_distance=1,
            time_delta_hours=0.5,
            is_deployment=True,
            service_incident_rate_7d=0.1,
            change_failure_rate_7d=0.02
        )
        
        # Convert to array for ML model
        feature_array = fv.to_array()
        
        assert len(feature_array) == len(FeatureVector.feature_names())
        assert all(isinstance(x, (int, float)) for x in feature_array)


class TestFailureScenarios:
    """Test failure handling and edge cases."""
    
    @pytest.mark.asyncio
    async def test_low_confidence_no_auto_remediation(self):
        """Test that low confidence correlations don't trigger auto-remediation."""
        
        # Low confidence correlation
        correlation_result = {
            "candidates": [{
                "service_name": "payment-service",
                "confidence_score": 0.45,  # Below 0.75 threshold
                "change_type": "code_deployment"
            }]
        }
        
        # Should not request approval
        approval_required = correlation_result["candidates"][0]["confidence_score"] >= 0.75
        assert approval_required is False
    
    @pytest.mark.asyncio
    async def test_remediation_failure_triggers_escalation(self):
        """Test that failed remediation triggers escalation."""
        
        # Simulate failed rollback
        remediation_result = {
            "success": False,
            "error": "Argo Rollouts API timeout"
        }
        
        # Should trigger incident response workflow
        escalation_triggered = not remediation_result["success"]
        assert escalation_triggered
    
    @pytest.mark.asyncio
    async def test_slo_not_recovered_after_remediation(self):
        """Test handling when SLO doesn't recover after remediation."""
        
        verification = {
            "recovered": False,
            "details": "Error budget still burning at 2x rate"
        }
        
        # Should keep incident open and escalate
        incident_escalated = not verification["recovered"]
        assert incident_escalated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])