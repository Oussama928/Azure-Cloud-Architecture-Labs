"""
Kubernetes Lease-based leader election for the ChangeTrace collector.
Requires coordination.k8s.io/v1 Lease RBAC on the collector's ClusterRole.
"""

import asyncio
import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone

from kubernetes import client, config

logger = logging.getLogger(__name__)

DEFAULT_LEASE_NAME = "changetrace-collector-leader"
DEFAULT_LEASE_NAMESPACE = "changetrace"
DEFAULT_LEASE_DURATION_SECONDS = 15
DEFAULT_RENEW_INTERVAL_SECONDS = 5
DEFAULT_SYNC_INTERVAL_SECONDS = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LeaderElection:
    """Distributed leader election using a Kubernetes Lease."""

    def __init__(
        self,
        lease_name: str | None = None,
        lease_namespace: str | None = None,
        lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
        renew_interval_seconds: int = DEFAULT_RENEW_INTERVAL_SECONDS,
        sync_interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS,
        identity: str | None = None,
    ) -> None:
        self._lease_name = lease_name or os.getenv("LEADER_LEASE_NAME", DEFAULT_LEASE_NAME)
        self._lease_namespace = lease_namespace or os.getenv(
            "LEADER_LEASE_NAMESPACE", DEFAULT_LEASE_NAMESPACE
        )
        self._lease_duration = lease_duration_seconds or int(
            os.getenv("LEADER_LEASE_DURATION_SECONDS", DEFAULT_LEASE_DURATION_SECONDS)
        )
        self._renew_interval = renew_interval_seconds or int(
            os.getenv("LEADER_RENEW_INTERVAL_SECONDS", DEFAULT_RENEW_INTERVAL_SECONDS)
        )
        self._sync_interval = sync_interval_seconds or int(
            os.getenv("LEADER_SYNC_INTERVAL_SECONDS", DEFAULT_SYNC_INTERVAL_SECONDS)
        )
        self._identity = identity or os.getenv(
            "POD_NAME", socket.gethostname()
        ) or f"collector-{os.getpid()}"

        self._coordination_api: client.CoordinationV1Api | None = None
        self._is_leader = False
        self._running = False
        self._task: asyncio.Task | None = None
        self._lease_holder = ""
        self._acquire_time: datetime | None = None

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def identity(self) -> str:
        return self._identity

    async def start(self) -> None:
        """Initialize the k8s client and start the leader-election loop."""
        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config()
            except Exception:
                logger.warning(
                    "Could not load k8s config; defaulting to standalone (leader) mode"
                )
                self._is_leader = True
                return

        self._coordination_api = client.CoordinationV1Api()
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            f"Leader election started (identity={self._identity}, "
            f"lease={self._lease_namespace}/{self._lease_name})"
        )

    async def stop(self) -> None:
        """Stop the leader-election loop (best-effort release of the lease)."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Best-effort release so a new leader can acquire quickly.
        if self._is_leader and self._coordination_api:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._release_lease
                )
            except Exception as e:
                logger.warning(f"Failed to release lease on shutdown: {e}")
        self._is_leader = False

    async def _run(self) -> None:
        """Main loop: attempt to acquire/renew the lease and maintain leadership."""
        last_sync = 0.0
        while self._running:
            try:
                now = time.time()
                if now - last_sync >= self._sync_interval:
                    await asyncio.get_running_loop().run_in_executor(
                        None, self._sync_lease
                    )
                    last_sync = now
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Leader election sync error: {e}")

            await asyncio.sleep(self._renew_interval)

    def _sync_lease(self) -> None:
        """Acquire or renew the lease (blocking, runs in a thread)."""
        if not self._coordination_api:
            return
        try:
            body = self._coordination_api.read_namespaced_lease(
                self._lease_name, self._lease_namespace
            )
        except client.ApiException as e:
            if e.status != 404:
                logger.error(f"Failed to read lease: {e}")
                return
            self._create_lease()
            return

        spec = body.spec or client.V1LeaseSpec()
        holder = spec.holder_identity or ""
        now = _now()
        # A lease is expired when now > renew_time + lease_duration.
        expired = False
        renew_time = getattr(spec, "renew_time", None)
        if renew_time is not None:
            try:
                renew = renew_time if renew_time.tzinfo else renew_time.replace(tzinfo=timezone.utc)
                if now > renew + timedelta(seconds=self._lease_duration):
                    expired = True
            except Exception:
                expired = True
        else:
            # No renew time recorded — treat a holder's lease conservatively as
            # expired so we can attempt acquisition.
            expired = not holder or True

        if holder == self._identity:
            # We hold it — renew to extend our tenure.
            self._renew_lease(body, now)
            self._become_leader()
        elif expired or not holder:
            # Vacant or expired — attempt to acquire.
            self._try_acquire(body, now)
        else:
            # Another holder holds a fresh lease.
            self._lose_leadership()
            self._lease_holder = holder

    def _try_acquire(self, lease: client.V1Lease, now: datetime) -> None:
        """Optimistically update the lease to claim leadership."""
        spec = lease.spec or client.V1LeaseSpec()
        # Fresh value for a compare-and-set style guard on renew time.
        acquire_time = now.isoformat()
        spec.holder_identity = self._identity
        spec.lease_duration_seconds = self._lease_duration
        spec.acquire_time = now
        spec.renew_time = now
        spec.lease_transitions = (spec.lease_transitions or 0) + 1
        try:
            self._coordination_api.replace_namespaced_lease(
                self._lease_name, self._lease_namespace, lease
            )
            self._become_leader()
            self.log_elected(acquire_time)
        except client.ApiException as e:
            logger.info(f"Failed to acquire lease (will retry): {e.status}")
            self._lose_leadership()

    def _renew_lease(self, lease: client.V1Lease, now: datetime) -> None:
        try:
            spec = lease.spec or client.V1LeaseSpec()
            spec.renew_time = now
            self._coordination_api.replace_namespaced_lease(
                self._lease_name, self._lease_namespace, lease
            )
        except client.ApiException as e:
            logger.warning(f"Failed to renew lease: {e.status}")

    def _create_lease(self) -> None:
        try:
            now = _now()
            body = client.V1Lease(
                metadata=client.V1ObjectMeta(name=self._lease_name, namespace=self._lease_namespace),
                spec=client.V1LeaseSpec(
                    holder_identity=self._identity,
                    lease_duration_seconds=self._lease_duration,
                    acquire_time=now,
                    renew_time=now,
                    lease_transitions=1,
                ),
            )
            self._coordination_api.create_namespaced_lease(
                self._lease_namespace, body
            )
            self._become_leader()
            self.log_elected(now.isoformat())
        except client.ApiException as e:
            if e.status == 409:
                # Race: someone else created it concurrently. Will reconcile.
                logger.info("Lease already exists; will reconcile on next sync")
            else:
                logger.error(f"Failed to create lease: {e.status}")

    def _release_lease(self) -> None:
        try:
            body = self._coordination_api.read_namespaced_lease(
                self._lease_name, self._lease_namespace
            )
            if (body.spec or {}).holder_identity == self._identity:
                spec = body.spec or client.V1LeaseSpec()
                spec.holder_identity = ""
                self._coordination_api.replace_namespaced_lease(
                    self._lease_name, self._lease_namespace, body
                )
        except Exception as e:
            logger.warning(f"Error releasing lease: {e}")

    def _become_leader(self) -> None:
        if not self._is_leader:
            self._is_leader = True
            self._acquire_time = _now()
            logger.info(f"Collector {self._identity} became leader")

    def _lose_leadership(self) -> None:
        if self._is_leader:
            self._is_leader = False
            logger.info(f"Collector {self._identity} lost leadership")

    def log_elected(self, acquire_time: str) -> None:
        logger.info(f"Collector {self._identity} acquired lease at {acquire_time}")
