"""
Tests for Correlation Engine
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.correlation_engine.src.confidence_model import (
    ConfidenceModel,
    HeuristicConfidenceModel,
)
from services.correlation_engine.src.correlator import Correlator
from services.correlation_engine.src.models.correlation import (
    BlastRadiusResult,
    CandidateRanking,
    CorrelationRequest,
    CorrelationResponse,
    FeatureVector,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    ModelMetrics,
    TrainingExample,
)


class TestModels:
    """Test data models"""

    def test_incident_creation(self):
        """Test incident creation with defaults"""
        incident = Incident(
            title="Test Incident",
            affected_service="payment-service",
        )

        assert incident.incident_id is not None
        assert incident.title == "Test Incident"
        assert incident.affected_service == "payment-service"
        assert incident.severity == IncidentSeverity.SEV3
        assert incident.status == IncidentStatus.OPEN
        assert incident.detected_at is not None

    def test_incident_with_all_fields(self):
        """Test incident with all fields"""
        incident = Incident(
            incident_id="INC-20240101-123456",
            title="Payment Service Latency",
            severity=IncidentSeverity.SEV1,
            status=IncidentStatus.INVESTIGATING,
            affected_service="payment-service",
            affected_namespace="production",
            slo_name="latency_p99",
            error_budget_burn_rate=15.5,
            blast_radius_services=["checkout-service", "order-service"],
            labels={"team": "payments", "priority": "high"},
        )

        assert incident.incident_id == "INC-20240101-123456"
        assert incident.severity == IncidentSeverity.SEV1
        assert incident.error_budget_burn_rate == 15.5
        assert len(incident.blast_radius_services) == 2

    def test_candidate_ranking(self):
        """Test candidate ranking model"""
        candidate = CandidateRanking(
            change_event_id="evt-123",
            service_name="payment-service",
            change_type="code_deployment",
            source="github",
            timestamp=datetime.utcnow(),
            confidence_score=0.85,
            graph_distance_score=0.9,
            temporal_proximity_score=0.8,
            change_type_score=0.85,
            historical_base_rate_score=0.7,
            evidence={"author": "john", "description": "Deploy v1.2.3"},
            blast_radius_services=["checkout-service"],
        )

        assert candidate.confidence_score == 0.85
        assert candidate.service_name == "payment-service"
        assert candidate.evidence["author"] == "john"

    def test_feature_vector(self):
        """Test feature vector conversion"""
        fv = FeatureVector(
            change_event_id="evt-123",
            incident_id="inc-456",
            graph_distance=1,
            shortest_path_length=1,
            num_paths=2,
            shared_dependencies=1,
            blast_radius_overlap=0.8,
            time_delta_hours=0.5,
            time_delta_minutes=30,
            is_within_lookback=True,
            change_type_encoded=0,
            is_deployment=True,
            is_config_change=False,
            is_infra_change=False,
            is_rollback=False,
            deployment_size=1000,
            files_changed=50,
            service_incident_rate_7d=0.1,
            service_incident_rate_30d=0.05,
            change_failure_rate_7d=0.02,
            change_failure_rate_30d=0.01,
            same_change_type_failure_rate=0.03,
            service_criticality=1.0,
            service_dependency_count=5,
            service_dependent_count=3,
        )

        arr = fv.to_array()
        assert len(arr) == len(FeatureVector.feature_names())
        assert arr[0] == 1.0  # graph_distance
        assert arr[9] == 1.0  # is_deployment (index 9)

    def test_feature_names_order(self):
        """Test feature names are in correct order"""
        names = FeatureVector.feature_names()
        assert names[0] == "graph_distance"
        assert names[9] == "is_deployment"
        assert len(names) == 23

    def test_correlation_request(self):
        """Test correlation request"""
        request = CorrelationRequest(
            incident_id="inc-123",
            affected_service="payment-service",
            affected_namespace="production",
            lookback_hours=4,
            max_candidates=5,
            min_confidence_threshold=0.2,
        )

        assert request.incident_id == "inc-123"
        assert request.lookback_hours == 4
        assert request.max_candidates == 5

    def test_correlation_response(self):
        """Test correlation response"""
        candidates = [
            CandidateRanking(
                change_event_id="evt-1",
                service_name="payment-service",
                change_type="code_deployment",
                source="github",
                timestamp=datetime.utcnow(),
                confidence_score=0.9,
                graph_distance_score=0.9,
                temporal_proximity_score=0.8,
                change_type_score=0.85,
                historical_base_rate_score=0.7,
            ),
            CandidateRanking(
                change_event_id="evt-2",
                service_name="checkout-service",
                change_type="config_change",
                source="kubernetes",
                timestamp=datetime.utcnow(),
                confidence_score=0.3,
                graph_distance_score=0.3,
                temporal_proximity_score=0.4,
                change_type_score=0.3,
                historical_base_rate_score=0.2,
            ),
        ]

        response = CorrelationResponse(
            incident_id="inc-123",
            candidates=candidates,
            analysis_time_ms=150.5,
            model_version="1.0-test",
            features_used=FeatureVector.feature_names(),
        )

        assert len(response.candidates) == 2
        assert response.candidates[0].confidence_score > response.candidates[1].confidence_score
        assert response.analysis_time_ms == 150.5

    def test_blast_radius_result(self):
        """Test blast radius result"""
        result = BlastRadiusResult(
            source_service="payment-service",
            affected_services=["checkout-service", "order-service", "notification-service"],
            hop_count=2,
            paths=[
                ["payment-service", "checkout-service"],
                ["payment-service", "order-service"],
                ["payment-service", "checkout-service", "notification-service"],
            ],
            total_services_affected=3,
            critical_services_affected=["checkout-service"],
        )

        assert result.source_service == "payment-service"
        assert len(result.affected_services) == 3
        assert len(result.paths) == 3
        assert result.critical_services_affected == ["checkout-service"]

    def test_training_example(self):
        """Test training example"""
        fv = FeatureVector(
            change_event_id="evt-123",
            incident_id="inc-456",
            graph_distance=1,
            time_delta_hours=0.5,
            is_deployment=True,
        )

        example = TrainingExample(
            incident_id="inc-456",
            change_event_id="evt-123",
            features=fv,
            label=True,
            weight=1.0,
        )

        assert example.label is True
        assert example.weight == 1.0
        assert example.features.change_event_id == "evt-123"

    def test_model_metrics(self):
        """Test model metrics"""
        metrics = ModelMetrics(
            model_version="1.0-test",
            precision_at_1=0.85,
            precision_at_3=0.92,
            recall=0.78,
            f1_score=0.81,
            auc_roc=0.91,
            auc_pr=0.88,
            calibration_error=0.02,
            brier_score=0.08,
            num_samples=1000,
            num_positive=150,
            num_negative=850,
        )

        assert metrics.precision_at_1 == 0.85
        assert metrics.num_samples == 1000

        d = metrics.to_dict()
        assert d["precision_at_1"] == 0.85


class TestHeuristicModel:
    """Test heuristic confidence model"""

    @pytest.fixture
    def model(self):
        return HeuristicConfidenceModel()

    @pytest.fixture
    def incident(self):
        return Incident(
            incident_id="inc-123",
            title="Test",
            affected_service="payment-service",
        )

    @pytest.fixture
    def candidates(self):
        return [
            CandidateRanking(
                change_event_id="evt-1",
                service_name="payment-service",
                change_type="code_deployment",
                source="github",
                timestamp=datetime.utcnow() - timedelta(minutes=30),
                confidence_score=0.0,
                graph_distance_score=0.0,
                temporal_proximity_score=0.0,
                change_type_score=0.0,
                historical_base_rate_score=0.0,
            ),
            CandidateRanking(
                change_event_id="evt-2",
                service_name="checkout-service",
                change_type="config_change",
                source="kubernetes",
                timestamp=datetime.utcnow() - timedelta(hours=1),
                confidence_score=0.0,
                graph_distance_score=0.0,
                temporal_proximity_score=0.0,
                change_type_score=0.0,
                historical_base_rate_score=0.0,
            ),
            CandidateRanking(
                change_event_id="evt-3",
                service_name="notification-service",
                change_type="infrastructure_change",
                source="terraform",
                timestamp=datetime.utcnow() - timedelta(hours=2),
                confidence_score=0.0,
                graph_distance_score=0.0,
                temporal_proximity_score=0.0,
                change_type_score=0.0,
                historical_base_rate_score=0.0,
            ),
        ]

    @pytest.fixture
    def feature_vectors(self):
        return [
            FeatureVector(
                change_event_id="evt-1",
                incident_id="inc-123",
                graph_distance=0,
                time_delta_hours=0.5,
                is_deployment=True,
                is_within_lookback=True,
                service_incident_rate_7d=0.1,
                change_failure_rate_7d=0.02,
            ),
            FeatureVector(
                change_event_id="evt-2",
                incident_id="inc-123",
                graph_distance=1,
                time_delta_hours=1.0,
                is_config_change=True,
                is_within_lookback=True,
                service_incident_rate_7d=0.05,
                change_failure_rate_7d=0.01,
            ),
            FeatureVector(
                change_event_id="evt-3",
                incident_id="inc-123",
                graph_distance=2,
                time_delta_hours=2.0,
                is_infra_change=True,
                is_within_lookback=True,
                service_incident_rate_7d=0.02,
                change_failure_rate_7d=0.005,
            ),
        ]

    def test_heuristic_ranking(self, model, incident, candidates, feature_vectors):
        """Test heuristic ranking produces reasonable scores"""
        ranked = model.rank_candidates(incident, candidates, feature_vectors)

        # Should return all candidates
        assert len(ranked) == 3

        # Should be sorted by confidence descending
        assert ranked[0].confidence_score >= ranked[1].confidence_score
        assert ranked[1].confidence_score >= ranked[2].confidence_score

        # Deployment at distance 0 should rank highest
        assert ranked[0].change_event_id == "evt-1"
        assert ranked[0].confidence_score > 0.5

        # All should have scores set
        for c in ranked:
            assert c.confidence_score > 0
            assert c.model_version == "heuristic-1.0"
            assert c.ranked_at is not None

    def test_heuristic_predict_proba(self, model, feature_vectors):
        """Test heuristic probability prediction"""
        probas = model.predict_proba(feature_vectors)

        assert len(probas) == 3
        assert all(0 <= p <= 1 for p in probas)
        # First should be highest (deployment at distance 0)
        assert probas[0] > probas[1]
        assert probas[1] > probas[2]

    def test_feature_importance(self, model):
        """Test feature importance"""
        importance = model.get_feature_importance()

        assert "graph_distance" in importance
        assert "temporal_proximity" in importance
        assert "change_type" in importance
        assert "historical_base_rate" in importance
        assert abs(sum(importance.values()) - 1.0) < 0.01


class TestConfidenceModel:
    """Test ML confidence model"""

    def test_model_initialization(self):
        """Test model initialization"""
        model = ConfidenceModel(
            n_estimators=10,
            learning_rate=0.1,
            max_depth=3,
        )

        assert model.base_params["n_estimators"] == 10
        assert model.base_params["learning_rate"] == 0.1
        assert model.base_params["max_depth"] == 3
        assert not model.is_trained

    def test_model_save_load(self, tmp_path):
        """Test model save and load"""
        model = ConfidenceModel(n_estimators=5)
        model_path = tmp_path / "test_model.pkl"

        # Can't save untrained model
        with pytest.raises(ValueError):
            model.save(str(model_path))

        # Train with sufficient data for validation split and calibration
        examples = []
        for i in range(50):
            fv = FeatureVector(
                change_event_id=f"evt-{i}",
                incident_id="inc-1",
                graph_distance=i % 3,
                time_delta_hours=float(i % 5),
                is_deployment=(i % 2 == 0),
                is_config_change=(i % 2 == 1),
            )
            examples.append(TrainingExample(
                incident_id="inc-1",
                change_event_id=f"evt-{i}",
                features=fv,
                label=(i % 3 == 0),  # Some positive labels
            ))

        metrics = model.train(examples)

        assert model.is_trained
        # Metrics are computed on validation set (20% of 50 = 10)
        assert metrics.num_samples == 10

        # Save and load
        model.save(str(model_path))
        loaded = ConfidenceModel.load(str(model_path))

        assert loaded.is_trained
        assert loaded.model_version == model.model_version
        assert loaded.feature_names == model.feature_names

    def test_model_training_insufficient_data(self):
        """Test training with insufficient data"""
        model = ConfidenceModel()

        # Only 5 examples - should fail
        examples = [
            TrainingExample(
                incident_id="inc-1",
                change_event_id=f"evt-{i}",
                features=FeatureVector(
                    change_event_id=f"evt-{i}",
                    incident_id="inc-1",
                ),
                label=(i == 0),
            )
            for i in range(5)
        ]

        with pytest.raises(ValueError, match="at least 10"):
            model.train(examples)


class TestCorrelator:
    """Test correlator (mocked)"""

    @pytest.fixture
    def mock_gremlin_client(self):
        """Mock Gremlin client"""
        client = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_correlator_initialization(self, mock_gremlin_client):
        """Test correlator initialization"""
        # Mock submit to return a ResultSet-like object
        class MockResultSet:
            def __iter__(self):
                return iter([])

        mock_gremlin_client.submit.return_value = MockResultSet()

        with patch('services.correlation_engine.src.correlator.client.Client', return_value=mock_gremlin_client):
            with patch('services.correlation_engine.src.correlator.DriverRemoteConnection'):
                correlator = Correlator(
                    cosmos_connection_string="AccountEndpoint=https://test.gremlin.cosmos.azure.com:443/;AccountKey=test",
                    model=HeuristicConfidenceModel(),
                )
                await correlator.initialize()

                assert correlator._gremlin_client is not None
                await correlator.close()

    @pytest.mark.asyncio
    async def test_compute_blast_radius(self, mock_gremlin_client):
        """Test blast radius computation"""
        # Mock query results - submit is sync, returns a ResultSet-like object
        class MockResultSet:
            def __iter__(self):
                return iter(["checkout-service", "order-service"])

        mock_gremlin_client.submit.return_value = MockResultSet()

        with patch('services.correlation_engine.src.correlator.client.Client', return_value=mock_gremlin_client):
            with patch('services.correlation_engine.src.correlator.DriverRemoteConnection'):
                correlator = Correlator(
                    cosmos_connection_string="AccountEndpoint=https://test.gremlin.cosmos.azure.com:443/;AccountKey=test",
                    model=HeuristicConfidenceModel(),
                )
                await correlator.initialize()

                result = await correlator.compute_blast_radius("payment-service")

                assert result.source_service == "payment-service"
                assert "checkout-service" in result.affected_services
                assert "order-service" in result.affected_services

                await correlator.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
