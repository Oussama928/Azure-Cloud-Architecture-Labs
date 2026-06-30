import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DISABLE_AUTH", "true")

_NOW = datetime.now(timezone.utc)


class AsyncMockIterator:
    """Mimics gremlin_python ResultSet: supports async iteration AND .all().result()"""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item

    def all(self):
        items = list(self.items)

        class Result:
            def result(self):
                return items

        return Result()


class MockGremlinClient:
    def __init__(self):
        self.submitted_queries = []

    def submit(self, query):
        self.submitted_queries.append(query)
        return AsyncMockIterator(self._mock_results(query))

    def close(self):
        pass

    def _mock_results(self, query):
        if "hasLabel('Service')" in query:
            return [
                {"id": ["s1"], "serviceName": ["payment-service"], "namespace": ["production"], "criticality": ["critical"], "sloTarget": [99.99], "currentSLO": [99.95], "errorBudgetRemaining": [45.3], "incidentCount24h": [1], "deploymentCount24h": [3]},
                {"id": ["s2"], "serviceName": ["checkout-service"], "namespace": ["production"], "criticality": ["high"], "sloTarget": [99.95], "currentSLO": [99.92], "errorBudgetRemaining": [45.3], "incidentCount24h": [0], "deploymentCount24h": [2]},
            ]
        elif "hasLabel('depends_on')" in query:
            return [
                {"outV": ["s1"], "inV": ["s2"], "type": ["depends_on"], "latencyP99": [120], "errorRate": [0.005], "requestVolume": [8000]},
            ]
        elif "hasLabel('Incident')" in query or "has('incidentId'" in query:
            return [
                {"incidentId": ["INC-001"], "title": ["Payment Latency"], "severity": ["sev2"], "status": ["resolved"], "affectedService": ["payment-service"], "detectedAt": [(_NOW - timedelta(days=2)).isoformat()], "resolvedAt": [(_NOW - timedelta(days=1)).isoformat()], "rootCauseCandidate": ["deploy-v1.2.3"], "confidence": [0.87], "remediationAction": ["rollback_deployment"], "trueCauseRank": [1]},
                {"incidentId": ["INC-002"], "title": ["Checkout Timeout"], "severity": ["sev3"], "status": ["resolved"], "affectedService": ["checkout-service"], "detectedAt": [(_NOW - timedelta(days=1)).isoformat()], "resolvedAt": [(_NOW - timedelta(hours=2)).isoformat()], "rootCauseCandidate": ["deploy-v2.1.0"], "confidence": [0.65], "remediationAction": ["rollback_deployment"], "trueCauseRank": [3]},
            ]
        elif "hasLabel('ChangeEvent')" in query:
            return [
                {"changeEventId": ["evt-001"], "serviceName": ["payment-service"], "changeType": ["code_deployment"], "source": ["github"], "timestamp": ["2024-01-15T14:25:00Z"], "author": ["john.doe"], "description": ["Deploy v1.2.3"], "deploymentId": ["deploy-12345"], "newVersion": ["v1.2.3"], "pipelineName": ["github/payment-service"]},
            ]
        elif "hasLabel('SLOMetric')" in query:
            return [
                {"timestamp": ["2024-01-15T14:25:00Z"], "service": ["payment-service"], "sloName": ["availability"], "target": [99.9], "actual": [99.95], "burnRate": [1.2], "errorBudgetRemaining": [85.2]},
            ]
        elif "hasLabel('RiskScore')" in query:
            return [
                {"timestamp": ["2024-01-15T14:25:00Z"], "service": ["payment-service"], "deploymentId": ["deploy-12345"], "riskScore": [0.72], "riskLevel": ["high"], "factors": [{"change_size": 0.6, "service_criticality": 0.9, "recent_incidents": 0.3, "dependency_risk": 0.5}]},
            ]
        elif "hasLabel('CorrelationAccuracy')" in query or "hasLabel('EvaluationRecord')" in query:
            return []
        return []


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def mock_gremlin_client():
    return MockGremlinClient()


@pytest.fixture
def client(mock_gremlin_client):
    from services.dashboard_api.src.main import app

    app.router.lifespan_context = _noop_lifespan
    with patch("services.dashboard_api.src.main.gremlin_client", mock_gremlin_client):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
