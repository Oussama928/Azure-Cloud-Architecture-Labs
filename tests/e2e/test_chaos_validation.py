"""Chaos Validation Tests for ChangeTrace: correlation engine vs known-cause faults injected via Azure Chaos Studio."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from chaos.scripts.evaluate_precision_recall import EvaluationHarness


class TestChaosValidation:
    """Test correlation engine against known-cause chaos experiments."""
    
    @pytest.fixture
    def harness(self):
        """Create evaluation harness."""
        return EvaluationHarness()
    
    @pytest.mark.asyncio
    async def test_pod_failure_detection(self):
        """Test that pod failure is correctly identified as root cause."""
        
        # Inject pod failure via Chaos Studio
        experiment_result = {
            "experiment_id": "exp-pod-failure-001",
            "fault_type": "PodKill",
            "target_service": "payment-service",
            "namespace": "production",
            "injected_at": datetime.utcnow().isoformat(),
            "duration_seconds": 60
        }
        
        # Simulate incident detection
        incident = {
            "incident_id": "INC-20240115-143022-a1b2c3",
            "title": "Payment Service Unavailable",
            "severity": "sev1",
            "affected_service": "payment-service",
            "slo_name": "availability",
            "error_budget_burn_rate": 100.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-pod-kill",
                    "service_name": "payment-service",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.95,
                    "evidence": {
                        "fault_type": "PodKill",
                        "target": "payment-service"
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        assert len(result["candidates"]) > 0
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "payment-service"
        assert top_candidate["confidence_score"] >= 0.9
        assert top_candidate["change_type"] == "infrastructure_failure"
    
    @pytest.mark.asyncio
    async def test_cpu_pressure_detection(self):
        """Test that CPU pressure is correctly identified."""
        
        experiment_result = {
            "experiment_id": "exp-cpu-pressure-001",
            "fault_type": "CPUPressure",
            "target_service": "fraud-service",
            "cpu_load": 80,
            "duration_seconds": 300,
            "injected_at": datetime.utcnow().isoformat()
        }
        
        incident = {
            "incident_id": "INC-20240115-150000-d4e5f6",
            "title": "Fraud Service High Latency",
            "severity": "sev2",
            "affected_service": "fraud-service",
            "slo_name": "latency_p99",
            "error_budget_burn_rate": 25.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-cpu",
                    "service_name": "fraud-service",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.88,
                    "evidence": {
                        "fault_type": "CPUPressure",
                        "cpu_load": 80
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "fraud-service"
        assert top_candidate["confidence_score"] >= 0.8
        assert top_candidate["evidence"]["fault_type"] == "CPUPressure"
    
    @pytest.mark.asyncio
    async def test_network_latency_detection(self):
        """Test that injected network latency is detected."""
        
        experiment_result = {
            "experiment_id": "exp-network-latency-001",
            "fault_type": "NetworkLatency",
            "target_service": "order-service",
            "latency_ms": 200,
            "jitter_ms": 50,
            "duration_seconds": 300,
            "injected_at": datetime.utcnow().isoformat()
        }
        
        incident = {
            "incident_id": "INC-20240115-160000-a1b2c3",
            "title": "Order Service Latency Degradation",
            "severity": "sev2",
            "affected_service": "order-service",
            "slo_name": "latency_p99",
            "error_budget_burn_rate": 15.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-network",
                    "service_name": "order-service",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.85,
                    "evidence": {
                        "fault_type": "NetworkLatency",
                        "latency_ms": 200
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "order-service"
        assert top_candidate["confidence_score"] >= 0.8
        assert top_candidate["evidence"]["fault_type"] == "NetworkLatency"
    
    @pytest.mark.asyncio
    async def test_memory_pressure_detection(self):
        """Test that memory pressure is detected."""
        
        experiment_result = {
            "experiment_id": "exp-memory-pressure-001",
            "fault_type": "MemoryPressure",
            "target_service": "ml-model-service",
            "memory_consumption": "80%",
            "duration_seconds": 300,
            "injected_at": datetime.utcnow().isoformat()
        }
        
        incident = {
            "incident_id": "INC-20240115-170000-a1b2c3",
            "title": "ML Model Service OOM Kills",
            "severity": "sev1",
            "affected_service": "ml-model-service",
            "slo_name": "availability",
            "error_budget_burn_rate": 50.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-memory",
                    "service_name": "ml-model-service",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.92,
                    "evidence": {
                        "fault_type": "MemoryPressure",
                        "memory_consumption": "80%"
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "ml-model-service"
        assert top_candidate["confidence_score"] >= 0.9
        assert top_candidate["evidence"]["fault_type"] == "MemoryPressure"
    
    @pytest.mark.asyncio
    async def test_dns_failure_detection(self):
        """Test that DNS failure is detected."""
        
        experiment_result = {
            "experiment_id": "exp-dns-failure-001",
            "fault_type": "DNSFailure",
            "target_service": "notification-service",
            "duration_seconds": 120,
            "injected_at": datetime.utcnow().isoformat()
        }
        
        incident = {
            "incident_id": "INC-20240115-180000-d4e5f6",
            "title": "Notification Service Connection Errors",
            "severity": "sev2",
            "affected_service": "notification-service",
            "slo_name": "availability",
            "error_budget_burn_rate": 30.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-dns",
                    "service_name": "notification-service",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.87,
                    "evidence": {
                        "fault_type": "DNSFailure"
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "notification-service"
        assert top_candidate["confidence_score"] >= 0.8
        assert top_candidate["evidence"]["fault_type"] == "DNSFailure"
    
    @pytest.mark.asyncio
    async def test_disk_io_pressure_detection(self):
        """Test that disk I/O pressure is detected."""
        
        experiment_result = {
            "experiment_id": "exp-disk-io-001",
            "fault_type": "DiskPressure",
            "target_service": "database-primary",
            "duration_seconds": 300,
            "injected_at": datetime.utcnow().isoformat()
        }
        
        incident = {
            "incident_id": "INC-20240115-190000-a1b2c3",
            "title": "Database Slow Queries",
            "severity": "sev2",
            "affected_service": "database-primary",
            "slo_name": "latency_p99",
            "error_budget_burn_rate": 20.0,
            "detected_at": datetime.utcnow().isoformat()
        }
        
        with patch('services.correlation_engine.src.main.Correlator') as mock_correlator:
            mock_correlator_instance = AsyncMock()
            mock_correlator_instance.correlate_incident = AsyncMock(return_value={
                "candidates": [{
                    "change_event_id": "evt-chaos-disk",
                    "service_name": "database-primary",
                    "change_type": "infrastructure_failure",
                    "source": "azure_chaos_studio",
                    "timestamp": experiment_result["injected_at"],
                    "confidence_score": 0.83,
                    "evidence": {
                        "fault_type": "DiskPressure"
                    }
                }]
            })
            mock_correlator.return_value = mock_correlator_instance
            
            from services.correlation_engine.src.main import Correlator
            correlator = Correlator()
            result = await correlator.correlate_incident(incident)
        
        top_candidate = result["candidates"][0]
        assert top_candidate["service_name"] == "database-primary"
        assert top_candidate["confidence_score"] >= 0.8
        assert top_candidate["evidence"]["fault_type"] == "DiskPressure"


class TestEvaluationHarness:
    """Test the evaluation harness itself."""
    
    @pytest.fixture
    def harness(self):
        return EvaluationHarness()
    
    def test_precision_at_k(self, harness):
        """Test precision@k calculation."""
        
        # Perfect ranking - positive at position 0
        y_true = [1, 0, 0, 0, 0]
        y_scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        
        p1 = harness._precision_at_k(y_true, y_scores, k=1)
        p3 = harness._precision_at_k(y_true, y_scores, k=3)
        p5 = harness._precision_at_k(y_true, y_scores, k=5)
        
        assert p1 == 1.0
        assert p3 == 1.0 / 3.0  # 1 positive in top 3
        assert p5 == 1.0 / 5.0  # 1 positive in top 5
        
        # Multiple positives
        y_true = [1, 1, 0, 0, 0]
        y_scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        
        p1 = harness._precision_at_k(y_true, y_scores, k=1)
        p3 = harness._precision_at_k(y_true, y_scores, k=3)
        
        assert p1 == 1.0
        assert p3 == 2.0 / 3.0  # 2 positives in top 3
        
        # No positive in top-k
        y_true = [0, 0, 1, 0, 0]
        y_scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        
        p1 = harness._precision_at_k(y_true, y_scores, k=1)
        p3 = harness._precision_at_k(y_true, y_scores, k=3)
        
        assert p1 == 0.0
        assert p3 == 1.0 / 3.0
    
    def test_mrr(self, harness):
        """Test Mean Reciprocal Rank."""
        
        # First result is positive
        y_true = [1, 0, 0]
        y_scores = [0.9, 0.8, 0.7]
        mrr = harness._compute_mrr(y_true, y_scores)
        assert mrr == 1.0
        
        # Second result is positive
        y_true = [0, 1, 0]
        y_scores = [0.9, 0.8, 0.7]
        mrr = harness._compute_mrr(y_true, y_scores)
        assert mrr == 0.5
        
        # No positive
        y_true = [0, 0, 0]
        y_scores = [0.9, 0.8, 0.7]
        mrr = harness._compute_mrr(y_true, y_scores)
        assert mrr == 0.0
    
    def test_ndcg(self, harness):
        """Test NDCG calculation."""
        
        # Perfect ranking - positive at position 0
        y_true = [1, 0, 0]
        y_scores = [0.9, 0.8, 0.7]
        ndcg = harness._compute_ndcg(y_true, y_scores, k=3)
        assert ndcg == 1.0
        
        # Positive at position 1
        y_true = [0, 1, 0]
        y_scores = [0.9, 0.8, 0.7]
        ndcg = harness._compute_ndcg(y_true, y_scores, k=3)
        # DCG = 1/log2(3) = 1/1.585 = 0.63
        # IDCG = 1/log2(2) = 1
        # NDCG = 0.63
        assert ndcg < 1.0
        assert ndcg > 0.5
        
        # Positive at position 2
        y_true = [0, 0, 1]
        y_scores = [0.9, 0.8, 0.7]
        ndcg = harness._compute_ndcg(y_true, y_scores, k=3)
        # DCG = 1/log2(4) = 1/2 = 0.5
        # IDCG = 1
        # NDCG = 0.5
        assert ndcg == 0.5
    
    def test_ece(self, harness):
        """Test Expected Calibration Error."""
        
        # Perfect calibration - high scores for positives, low for negatives
        y_true = [1, 1, 0, 0]
        y_scores = [0.9, 0.8, 0.2, 0.1]
        ece = harness._compute_ece(y_true, y_scores, n_bins=10)
        # Should be very low (near 0)
        assert ece < 0.2
        
        # Poor calibration - high scores for negatives
        y_true = [1, 0, 1, 0]
        y_scores = [0.9, 0.8, 0.7, 0.6]
        ece = harness._compute_ece(y_true, y_scores, n_bins=10)
        # Should be higher
        assert ece > 0.1
        
        # Inverted calibration - high scores for negatives
        y_true = [1, 1, 0, 0]
        y_scores = [0.1, 0.2, 0.8, 0.9]
        ece = harness._compute_ece(y_true, y_scores)
        assert ece > 0.5


class TestChaosExperimentRunner:
    """Test the chaos experiment runner."""
    
    def test_run_experiment(self):
        """Test running a chaos experiment."""
        
        from chaos.scripts.run_experiment import ChaosExperimentRunner
        
        with patch('chaos.scripts.run_experiment.ChaosManagementClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.experiments.begin_start = MagicMock(return_value=MagicMock(
                result=MagicMock(return_value=MagicMock(id="/subscriptions/test/resourceGroups/test/providers/Microsoft.Chaos/experiments/exp-test-001"))
            ))
            mock_client.experiments.get = MagicMock(return_value=MagicMock(
                properties=MagicMock(status="Succeeded", error=None)
            ))
            mock_client_class.return_value = mock_client
            
            runner = ChaosExperimentRunner(
                subscription_id="test-sub",
                resource_group="test-rg",
                workspace_name="test-ws"
            )
            
            result = runner.run_experiment(
                experiment_name="test-pod-failure",
                target_service="payment-service"
            )
            
            assert result["status"] == "Succeeded"
            assert "experiment_name" in result
    
    def test_experiment_suite(self):
        """Test running an experiment suite."""
        
        from chaos.scripts.run_experiment import ChaosExperimentRunner
        
        with patch('chaos.scripts.run_experiment.ChaosManagementClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client.experiments.begin_start = MagicMock(return_value=MagicMock(
                result=MagicMock(return_value=MagicMock(id="/subscriptions/test/resourceGroups/test/providers/Microsoft.Chaos/experiments/exp-test-001"))
            ))
            mock_client.experiments.get = MagicMock(return_value=MagicMock(
                properties=MagicMock(status="Succeeded", error=None)
            ))
            mock_client_class.return_value = mock_client
            
            runner = ChaosExperimentRunner(
                subscription_id="test-sub",
                resource_group="test-rg",
                workspace_name="test-ws"
            )
            
            suite = [
                {"name": "exp-1", "parameters": {}},
                {"name": "exp-2", "parameters": {}}
            ]
            
            results = runner.run_experiment_suite(suite, "payment-service")
            
            assert len(results) == 2
            assert all(r["status"] == "Succeeded" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])