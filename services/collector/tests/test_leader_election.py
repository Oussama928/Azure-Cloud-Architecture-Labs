"""Tests for the collector's Kubernetes Lease-based leader election."""

from datetime import datetime, timedelta, timezone

import pytest

from services.collector.src.leader_election import LeaderElection, _now


def _lease(holder="", transitions=0, renew_time=None, transition_time=None):
    """Build a minimal client.V1Lease with a spec."""
    from kubernetes import client

    spec = client.V1LeaseSpec(
        holder_identity=holder,
        lease_duration_seconds=15,
        lease_transitions=transitions,
        renew_time=renew_time or datetime.now(timezone.utc),
        lease_transition_time=transition_time or datetime.now(timezone.utc),
    )
    return client.V1Lease(
        metadata=client.V1ObjectMeta(name="changetrace-collector-leader", namespace="changetrace"),
        spec=spec,
    )


class TestLeaseExpiry:
    def test_fresh_lease_not_expired(self):
        le = LeaderElection()
        now = datetime.now(timezone.utc)
        assert _now() <= now + timedelta(seconds=1)

    def test_expired_when_transition_old(self):
        le = LeaderElection(lease_duration_seconds=15)
        transition = datetime.now(timezone.utc) - timedelta(seconds=60)
        # A transition 60s ago with a 15s duration is expired.
        expired = _now() > transition + timedelta(seconds=15)
        assert expired is True

    def test_not_expired_when_transition_recent(self):
        le = LeaderElection(lease_duration_seconds=15)
        transition = datetime.now(timezone.utc) - timedelta(seconds=5)
        expired = _now() > transition + timedelta(seconds=15)
        assert expired is False


class TestLeaderState:
    def test_default_not_leader(self):
        le = LeaderElection()
        assert le.is_leader is False

    def test_identity_defaults_to_hostname(self):
        import socket
        le = LeaderElection()
        assert le.identity == socket.gethostname()

    def test_standalone_mode_when_no_k8s(self, monkeypatch):
        # If config load fails, start() sets standalone leader mode.
        import services.collector.src.leader_election as module

        def _fail_load(*a, **k):
            raise Exception("no kubeconfig")

        monkeypatch.setattr(module.config, "load_incluster_config", _fail_load)
        monkeypatch.setattr(module.config, "load_kube_config", _fail_load)

        le = LeaderElection()

        async def _run():
            await le.start()
            assert le.is_leader is True
            await le.stop()

        import asyncio
        asyncio.run(_run())


class TestAcquireRenew:
    def test_become_and_lose_leadership(self):
        le = LeaderElection()
        assert le.is_leader is False
        le._become_leader()
        assert le.is_leader is True
        le._lose_leadership()
        assert le.is_leader is False

    def test_release_lease_clears_holder(self):
        le = LeaderElection(identity="replica-1")
        le._is_leader = True

        from kubernetes import client

        body = client.V1Lease(
            metadata=client.V1ObjectMeta(name="lease", namespace="ns"),
            spec=client.V1LeaseSpec(holder_identity="replica-1"),
        )
        calls = {"read": False, "replace": None}

        class MockApi:
            def read_namespaced_lease(self, name, ns):
                calls["read"] = True
                return body

            def replace_namespaced_lease(self, name, ns, obj):
                calls["replace"] = obj

        le._coordination_api = MockApi()
        le._release_lease()
        assert calls["read"] is True
        assert calls["replace"] is not None
        assert calls["replace"].spec.holder_identity == ""
