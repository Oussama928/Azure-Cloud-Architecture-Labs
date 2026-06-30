"""Unit tests for the shared auto-incident logic (breach gating + lifecycle)."""

from unittest.mock import patch

from services.shared.auto_incident import (
    maybe_resolve_recovered,
    open_incident_for_breach,
    resolve_open_incidents,
)


class TestBreachGating:
    def test_availability_healthy_no_incident(self):
        with patch("services.shared.auto_incident.open_incident") as mock_open:
            result = open_incident_for_breach(
                "t1", "api-gateway", "availability", 100.0, 99.9
            )
        assert result is None
        mock_open.assert_not_called()

    def test_availability_breach_opens_incident(self):
        with patch("services.shared.auto_incident.open_incident") as mock_open:
            mock_open.return_value = "INC-123"
            result = open_incident_for_breach(
                "t1", "api-gateway", "availability", 98.5, 99.9
            )
        assert result == "INC-123"
        mock_open.assert_called_once()
        kwargs = mock_open.call_args.kwargs
        assert kwargs["slo_name"] == "availability"
        assert kwargs["actual"] == 98.5

    def test_latency_healthy_no_incident(self):
        with patch("services.shared.auto_incident.open_incident") as mock_open:
            result = open_incident_for_breach(
                "t1", "payment-service", "latency_p99", 35.0, 500.0
            )
        assert result is None
        mock_open.assert_not_called()

    def test_latency_breach_opens_incident(self):
        with patch("services.shared.auto_incident.open_incident") as mock_open:
            mock_open.return_value = "INC-456"
            result = open_incident_for_breach(
                "t1", "payment-service", "latency_p99", 1500.0, 500.0
            )
        assert result == "INC-456"
        kwargs = mock_open.call_args.kwargs
        assert kwargs["slo_name"] == "latency_p99"
        assert kwargs["actual"] == 1500.0

    def test_unknown_slo_no_op(self):
        with patch("services.shared.auto_incident.open_incident") as mock_open:
            result = open_incident_for_breach(
                "t1", "api-gateway", "error_rate", 0.9, 0.001
            )
        assert result is None
        mock_open.assert_not_called()


class TestResolve:
    def test_resolve_queries_open_statuses(self):
        with patch("services.shared.auto_incident._run") as mock_run:
            mock_run.return_value = [2]
            count = resolve_open_incidents("t1", "payment-service")
        assert count == 2
        query = mock_run.call_args.args[0]
        assert "within('open','investigating'" in query
        assert ".property('status','resolved')" in query


class TestMaybeResolve:
    def test_no_open_incident_returns_zero(self):
        with patch("services.shared.auto_incident._run") as mock_run:
            mock_run.return_value = []
            assert maybe_resolve_recovered("t1", "payment-service") == 0

    def test_recent_incident_not_resolved(self):
        from datetime import datetime, timedelta, timezone
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with patch("services.shared.auto_incident._run") as mock_run, \
                patch("services.shared.auto_incident.resolve_open_incidents") as mock_res:
            mock_run.return_value = [recent]
            assert maybe_resolve_recovered("t1", "payment-service") == 0
        mock_res.assert_not_called()

    def test_old_incident_resolved(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        with patch("services.shared.auto_incident._run") as mock_run, \
                patch("services.shared.auto_incident.resolve_open_incidents") as mock_res:
            mock_run.return_value = [old]
            mock_res.return_value = 1
            assert maybe_resolve_recovered("t1", "payment-service") == 1
        mock_res.assert_called_once()
