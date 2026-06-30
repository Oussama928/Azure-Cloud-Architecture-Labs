from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.dashboard_api.src.main import (
    CorrelationAccuracy,
    DependencyEdge,
    DependencyGraph,
    IncidentSummary,
    RiskScoreHistory,
    ServiceNode,
    SLOBurnData,
)
from services.dashboard_api.tests.conftest import AsyncMockIterator, _noop_lifespan


class MockGremlinClientWithResults:
    def __init__(self, results=None):
        self.submitted_queries = []
        self._fixed_results = results

    def submit(self, query):
        self.submitted_queries.append(query)
        return AsyncMockIterator(self._fixed_results or [])

    def close(self):
        pass


class TestModels:
    def test_service_node_model(self):
        node = ServiceNode(
            id="svc-1",
            name="payment-service",
            namespace="production",
            criticality="critical",
            slo_target=99.99,
            current_slo=99.95,
            error_budget_remaining=45.3,
            incident_count_24h=1,
            deployment_count_24h=3,
        )
        assert node.id == "svc-1"
        assert node.criticality == "critical"

    def test_dependency_edge_model(self):
        edge = DependencyEdge(
            source="svc-1",
            target="svc-2",
            type="depends_on",
            latency_p99=120.0,
            error_rate=0.005,
            request_volume=8000,
        )
        assert edge.source == "svc-1"
        assert edge.error_rate == 0.005

    def test_dependency_graph_model(self):
        graph = DependencyGraph(
            nodes=[],
            edges=[],
            updated_at=datetime.utcnow(),
        )
        assert isinstance(graph.updated_at, datetime)

    def test_incident_summary_model(self):
        incident = IncidentSummary(
            incident_id="INC-001",
            title="Test Incident",
            severity="sev2",
            status="resolved",
            affected_service="payment-service",
            detected_at=datetime.utcnow(),
            resolved_at=datetime.utcnow(),
            root_cause_candidate="deploy-v1.2.3",
            confidence=0.87,
            remediation_action="rollback_deployment",
        )
        assert incident.incident_id == "INC-001"
        assert incident.confidence == 0.87


class TestHealthEndpoints:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "dashboard-api"
        assert data["version"] == "1.0.0"
        assert "timestamp" in data

    def test_readiness_check_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    def test_readiness_check_not_ready(self, mock_gremlin_client):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        with patch("services.dashboard_api.src.main.gremlin_client", None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ready")
                assert resp.status_code == 503
                assert "not initialized" in resp.json()["detail"]


class TestDependencyGraphEndpoints:
    def test_get_dependency_graph(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/graph/dependency")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "updated_at" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["nodes"][0]["name"] == "payment-service"
        assert data["edges"][0]["source"] == "s1"

    def test_get_dependency_graph_with_namespace_filter(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/graph/dependency", params={"namespace": "staging"})
        assert resp.status_code == 200
        assert "staging" in mock_gremlin_client.submitted_queries[0]

    def test_get_dependency_graph_no_gremlin(self):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        with patch("services.dashboard_api.src.main.gremlin_client", None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/v1/graph/dependency")
                assert resp.status_code == 503

    def test_get_blast_radius(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/graph/blast-radius/payment-service")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_service"] == "payment-service"
        assert "affected_services" in data
        assert data["hop_count"] == 3

    def test_get_blast_radius_no_gremlin(self):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        with patch("services.dashboard_api.src.main.gremlin_client", None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/v1/graph/blast-radius/payment-service")
                assert resp.status_code == 503


class TestIncidentEndpoints:
    def test_get_incidents(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["incident_id"] == "INC-001"
        assert data[0]["severity"] == "sev2"

    def test_get_incident_detail(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/incidents/INC-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == "INC-001"

    def test_get_incident_detail_not_found(self, client):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        empty_client = MockGremlinClientWithResults([])

        with patch("services.dashboard_api.src.main.gremlin_client", empty_client):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/v1/incidents/NOTFOUND")
                assert resp.status_code == 404

    def test_get_incidents_no_gremlin(self):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        with patch("services.dashboard_api.src.main.gremlin_client", None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/v1/incidents")
                assert resp.status_code == 503


class TestSLOEndpoints:
    def test_get_slo_burn_rate(self, client):
        resp = client.get("/api/v1/slo/burn-rate", params={"service": "payment-service", "slo_name": "availability", "hours": 24, "interval_minutes": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]["service"] == "payment-service"
        assert data[0]["slo_name"] == "availability"
        assert "burn_rate" in data[0]
        assert "error_budget_remaining" in data[0]

    def test_get_slo_status(self, client):
        resp = client.get("/api/v1/slo/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        assert len(data["services"]) >= 1
        assert data["services"][0]["name"] == "payment-service"
        assert "slos" in data["services"][0]


class TestRiskEndpoints:
    def test_get_risk_history(self, client):
        resp = client.get("/api/v1/risk/history", params={"service": "payment-service", "hours": 24, "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "risk_score" in data[0]
        assert "risk_level" in data[0]
        assert "factors" in data[0]

    def test_get_current_risk_scores(self, client):
        resp = client.get("/api/v1/risk/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "scores" in data
        assert len(data["scores"]) >= 1
        assert data["scores"][0]["service"] == "payment-service"
        assert "risk_score" in data["scores"][0]


class TestCorrelationEndpoints:
    def test_get_correlation_accuracy(self, client):
        resp = client.get("/api/v1/correlation/accuracy", params={"days": 30})
        assert resp.status_code == 200
        data = resp.json()
        # 2 resolved mock incidents (trueCauseRank 1 and 3) but fewer than 5 -> precision 0
        assert data["total_incidents"] == 2
        assert data["precision_at_1"] == 0.0
        assert "model_version" in data

    def test_get_correlation_accuracy_history(self, client):
        resp = client.get("/api/v1/correlation/accuracy/history", params={"days": 90})
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert isinstance(data["history"], list)
        assert len(data["history"]) == 2
        assert "precision_at_1" in data["history"][0]


class TestChangesEndpoint:
    def test_get_changes(self, client, mock_gremlin_client):
        resp = client.get("/api/v1/changes", params={"service": "payment-service", "source": "github", "change_type": "code_deployment"})
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert data["count"] == 1
        assert data["changes"][0]["serviceName"] == "payment-service"
        assert data["changes"][0]["source"] == "github"

    def test_get_changes_no_gremlin(self):
        from services.dashboard_api.src.main import app

        app.router.lifespan_context = _noop_lifespan
        with patch("services.dashboard_api.src.main.gremlin_client", None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/v1/changes")
                assert resp.status_code == 503


class TestMetricsEndpoint:
    def test_metrics_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


class TestNativeSourceTestEndpoint:
    """Tests for the generic connector connectivity probe POST /settings/sources/{kind}/test."""

    def _post(self, client, kind, body):
        return client.post(f"/api/v1/settings/sources/{kind}/test", json=body)

    def test_unsupported_kind(self, client):
        resp = self._post(client, "slack", {"base_url": "https://x", "token": "t"})
        assert resp.status_code == 400

    def test_missing_credentials(self, client):
        resp = self._post(client, "gitlab", {})
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is False
        assert "base URL and token" in data["error"]

    def test_gitlab_success(self, client):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"username": "alice"}
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                return FakeResp()
        with patch("httpx.AsyncClient", return_value=FakeClient()):
            resp = self._post(client, "gitlab", {"base_url": "https://gitlab.com", "token": "glpat-x"})
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["username"] == "alice"

    def test_gitlab_rejected(self, client):
        class FakeResp:
            status_code = 401
            def json(self):
                return {}
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                return FakeResp()
        with patch("httpx.AsyncClient", return_value=FakeClient()):
            resp = self._post(client, "gitlab", {"base_url": "https://gitlab.com", "token": "bad"})
        data = resp.json()
        assert data["ok"] is False
        assert "401" in data["error"]

    def test_jenkins_success(self, client):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"user": {"fullName": "Jenkins Admin"}}
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                return FakeResp()
        with patch("httpx.AsyncClient", return_value=FakeClient()):
            resp = self._post(client, "jenkins", {"base_url": "https://jenkins.example.com", "token": "tok", "username": "admin"})
        data = resp.json()
        assert data["ok"] is True
        assert data["username"] == "Jenkins Admin"

    def test_terraform_requires_org(self, client):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"data": {"attributes": {"name": "acme"}}}
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                return FakeResp()
        with patch("httpx.AsyncClient", return_value=FakeClient()):
            resp = self._post(client, "terraform", {"base_url": "https://app.terraform.io", "token": "tok", "organization": "acme"})
        data = resp.json()
        assert data["ok"] is True
        assert data["organization"] == "acme"
