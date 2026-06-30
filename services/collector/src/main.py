"""
Main Collector Service for ChangeTrace.

Orchestrates all change event sources, normalizes events to a unified schema,
and writes to Cosmos DB Gremlin.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import dotenv

dotenv.load_dotenv()

from services.shared.circuit_breaker import (
    get_cosmos_breaker,
    get_eventgrid_breaker,
    get_keyvault_breaker,
)
from services.shared.health_checks import (
    CosmosDBHealthCheck,
    DependencyHealthCheck,
    HealthCheckRegistry,
    create_health_endpoint,
)
from services.shared.structured_logging import (
    LogContextManager,
    get_logger,
    setup_structured_logging,
)

from .models.change_event import (
    ChangeEvent,
    ChangeSource,
)
from .sources.azure_resource_graph_source import AzureResourceGraphConfig, AzureResourceGraphSource
from .sources.github_source import GitHubConfig, GitHubSource
from .sources.k8s_source import K8sConfig, K8sSource
from .sources.terraform_source import TerraformConfig, TerraformSource
from .sources.url_source import UrlSource, UrlSourceConfig
from services.shared.secrets import get_secret
from .sources.gitlab_source import GitLabConfig, GitLabSource
from .sources.jenkins_source import JenkinsConfig, JenkinsSource
from .sources.argocd_source import ArgoCDConfig, ArgoCDSource

logger = setup_structured_logging("collector", level=logging.INFO)


class CollectorConfig(BaseModel):
    """Main collector configuration"""
    # Cosmos DB
    cosmos_connection_string: str = ""
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "changetrace-graph"
    cosmos_graph: str = "change-history"

    # Event Grid (for publishing events)
    eventgrid_endpoint: str | None = None
    eventgrid_key: str | None = None

    # Graph-builder (auto-triggers graph rebuild after events are flushed)
    graph_builder_url: str = ""

    # Source configurations
    github: GitHubConfig | None = None
    terraform: TerraformConfig | None = None
    kubernetes: K8sConfig | None = None
    azure_resource_graph: AzureResourceGraphConfig | None = None

    # Processing
    batch_size: int = 100
    flush_interval_seconds: int = 30
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    # Health check
    health_check_interval_seconds: int = 60


class CollectorService:
    """Main collector service that orchestrates all change event sources."""

    def __init__(self, config: CollectorConfig):
        self.config = config
        self._sources: dict[ChangeSource, Any] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._event_buffer: list[ChangeEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._cosmos_config = None
        self._eventgrid_client = None
        self._tenant_url_sources: dict[str, UrlSource] = {}
        self._tenant_source_tasks: dict[str, asyncio.Task] = {}
        self._tenant_github_sources: dict[str, Any] = {}
        self._tenant_github_tasks: dict[str, asyncio.Task] = {}
        self._tenant_native_sources: dict[str, dict[str, Any]] = {}
        self._tenant_native_tasks: dict[str, dict[str, asyncio.Task]] = {}
        self._tenant_sync_lock = asyncio.Lock()
        self._leader: Any = None
        # Rolling 24h event counters per (tenant, source)
        self._event_counters: dict[tuple[str, str], list[tuple[float, int]]] = {}

        self._cosmos_breaker = get_cosmos_breaker()
        self._eventgrid_breaker = get_eventgrid_breaker()
        self._keyvault_breaker = get_keyvault_breaker()

        self._health_registry = HealthCheckRegistry("collector", "1.0.0")

        self.logger = get_logger("collector")

    async def initialize(self) -> None:
        """Initialize all sources and connections"""
        with LogContextManager(service_name="collector", operation_name="initialize"):
            self.logger.info("Initializing collector service")

            await self._init_cosmos()

            await self._init_eventgrid()

            if self.config.github:
                self._sources[ChangeSource.GITHUB] = GitHubSource(self.config.github)
                await self._sources[ChangeSource.GITHUB].initialize()
                self.logger.info("Initialized GitHub source")

            if self.config.terraform:
                self._sources[ChangeSource.TERRAFORM] = TerraformSource(self.config.terraform)
                await self._sources[ChangeSource.TERRAFORM].initialize()
                self.logger.info("Initialized Terraform source")

            if self.config.kubernetes:
                self._sources[ChangeSource.KUBERNETES] = K8sSource(self.config.kubernetes)
                await self._sources[ChangeSource.KUBERNETES].initialize()
                self.logger.info("Initialized Kubernetes source")

            if self.config.azure_resource_graph:
                self._sources[ChangeSource.AZURE_RESOURCE_GRAPH] = AzureResourceGraphSource(
                    self.config.azure_resource_graph
                )
                await self._sources[ChangeSource.AZURE_RESOURCE_GRAPH].initialize()
                self.logger.info("Initialized Azure Resource Graph source")

            self._setup_health_checks()

            await self.sync_tenant_sources()

            self.logger.info(f"Collector initialized with {len(self._sources)} sources")

    def _setup_health_checks(self) -> None:
        """Set up health checks for dependencies"""
        if self._cosmos_config:
            self._health_registry.add_check(
                DependencyHealthCheck(
                    "cosmos-db",
                    self._check_cosmos_health,
                )
            )

        # Key Vault health check (if configured)
        for source_type, source in self._sources.items():
            if hasattr(source, 'health_check'):
                self._health_registry.add_check(
                    DependencyHealthCheck(
                        f"source-{source_type.value}",
                        source.health_check,
                    )
                )

        create_health_endpoint(app, self._health_registry)

    async def _init_cosmos(self) -> None:
        from services.shared.cosmos import get_cosmos_config_from_env
        self._cosmos_config = get_cosmos_config_from_env()
        if not self._cosmos_config.get("endpoint") or not self._cosmos_config.get("key"):
            self.logger.warning("Cosmos DB not configured - events will only buffer")
            self._cosmos_config = None
            return
        self.logger.info("Initialized Cosmos DB config")

    async def _load_tenant_settings(self) -> dict[str, dict]:
        """Load per-tenant Settings vertices from Cosmos (tenant_id -> settings)."""
        if not self._cosmos_config:
            return {}

        query = "g.V().hasLabel('Settings').valueMap(true)"
        try:
            result = await self._exec_gremlin(query)
        except Exception as e:
            self.logger.error(f"Failed to load tenant settings: {e}")
            return {}

        import json

        tenants: dict[str, dict] = {}
        for row in result or []:
            props = {k: v[0] if isinstance(v, list) else v for k, v in row.items()}
            tenant_id = props.get("tenantId")
            if not tenant_id:
                continue
            src = props.get("sourceUrls")
            cfg = props.get("sourceConfigs")
            tenants[tenant_id] = {
                "sourceUrls": json.loads(src) if isinstance(src, str) else (src or {}),
                "sourceConfigs": json.loads(cfg) if isinstance(cfg, str) else (cfg or {}),
            }
        return tenants

    async def sync_tenant_sources(self) -> None:
        """Reconcile per-tenant URL polling sources with Cosmos Settings."""
        if not self._cosmos_config:
            return

        async with self._tenant_sync_lock:
            tenants = await self._load_tenant_settings()
            default_tenant = os.getenv("DEFAULT_TENANT_ID", "demo-tenant")

            active_tenants = set(tenants) | {default_tenant}
            desired: dict[str, UrlSourceConfig] = {}
            for tenant_id in active_tenants:
                urls = dict(tenants.get(tenant_id, {}).get("sourceUrls", {}))
                if not urls:
                    continue
                desired[tenant_id] = UrlSourceConfig(
                    tenant_id=tenant_id,
                    urls=urls,
                    poll_interval_seconds=self.config.flush_interval_seconds,
                )

            # Remove sources for tenants that no longer have config
            for tenant_id in list(self._tenant_url_sources):
                if tenant_id not in desired:
                    source = self._tenant_url_sources.pop(tenant_id)
                    task = self._tenant_source_tasks.pop(tenant_id, None)
                    if task:
                        task.cancel()
                    await source.close()
                    self.logger.info(f"Removed URL source for tenant {tenant_id}")

            # Add/update sources
            for tenant_id, cfg in desired.items():
                existing = self._tenant_url_sources.get(tenant_id)
                if existing and existing.config.urls == cfg.urls:
                    # Ensure a polling task is running for this tenant (leader only)
                    if self._running and self._is_leader() and tenant_id not in self._tenant_source_tasks:
                        task = asyncio.create_task(
                            self._run_tenant_url_polling(tenant_id, existing)
                        )
                        self._tenant_source_tasks[tenant_id] = task
                        self.logger.info(
                            f"Started URL source for tenant {tenant_id} "
                            f"({len(cfg.urls)} endpoints)"
                        )
                    continue
                if existing:
                    await existing.close()
                    if tenant_id in self._tenant_source_tasks:
                        self._tenant_source_tasks[tenant_id].cancel()
                source = UrlSource(cfg)
                await source.initialize()
                self._tenant_url_sources[tenant_id] = source
                if not (self._running and self._is_leader()):
                    continue
                task = asyncio.create_task(
                    self._run_tenant_url_polling(tenant_id, source)
                )
                self._tenant_source_tasks[tenant_id] = task
                self.logger.info(
                    f"Started URL source for tenant {tenant_id} "
                    f"({len(cfg.urls)} endpoints)"
                )

            await self._sync_tenant_github_sources(tenants)
            await self._sync_tenant_native_sources(tenants)

    async def _sync_tenant_github_sources(self, tenants: dict[str, dict]) -> None:
        """Create/update per-tenant GitHub pollers from stored source configs."""
        if not self._cosmos_config:
            return

        desired: dict[str, GitHubConfig] = {}
        for tenant_id, settings in tenants.items():
            cfg = (settings.get("sourceConfigs") or {}).get("github")
            if not cfg:
                continue
            token = cfg.get("token") or get_secret(cfg.get("token_secret_name", ""))
            webhook_secret = cfg.get("webhook_secret") or get_secret(cfg.get("webhook_secret_name", ""))
            if not token:
                continue
            repos = cfg.get("repositories") or []
            orgs = cfg.get("organizations") or []
            if isinstance(repos, str):
                repos = [repos]
            if isinstance(orgs, str):
                orgs = [orgs]
            desired[tenant_id] = GitHubConfig(
                personal_access_token=token,
                webhook_secret=webhook_secret,
                repositories=[r for r in repos if r],
                organizations=[o for o in orgs if o],
                branches=cfg.get("branches") or ["main", "master", "production"],
            )

        # Remove tenants no longer configured
        for tenant_id in list(self._tenant_github_sources):
            if tenant_id not in desired:
                source = self._tenant_github_sources.pop(tenant_id)
                task = self._tenant_github_tasks.pop(tenant_id, None)
                if task:
                    task.cancel()
                try:
                    await source.close()
                except Exception:
                    pass
                self.logger.info(f"Removed GitHub source for tenant {tenant_id}")

        # Add/start new sources
        for tenant_id, gh_config in desired.items():
            existing = self._tenant_github_sources.get(tenant_id)
            try:
                if existing is None:
                    existing = GitHubSource(gh_config)
                    await existing.initialize()
                    self._tenant_github_sources[tenant_id] = existing
                    self.logger.info(f"Initialized GitHub source for tenant {tenant_id}")
            except Exception as e:
                self.logger.error(f"Failed to init GitHub for tenant {tenant_id}: {e}")
                continue

            if self._running and self._is_leader() and tenant_id not in self._tenant_github_tasks:
                task = asyncio.create_task(
                    self._run_tenant_github_polling(tenant_id, existing)
                )
                self._tenant_github_tasks[tenant_id] = task

    async def _run_tenant_github_polling(self, tenant_id: str, source: Any) -> None:
        """Poll a tenant's configured GitHub repositories."""
        self.logger.info(f"Starting GitHub polling for tenant {tenant_id}")
        while self._running:
            if not self._is_leader():
                await asyncio.sleep(source.config.poll_interval_seconds)
                continue
            try:
                events = await source.poll_all_repositories()
                if events:
                    for event in events:
                        event.tenant_id = tenant_id
                    await self._buffer_events(events)
                    self.logger.info(
                        f"Collected {len(events)} GitHub events for tenant {tenant_id}"
                    )
                await self._record_source_status(tenant_id, "github", "connected", None, len(events))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(
                    f"Error polling GitHub for tenant {tenant_id}: {e}", exc_info=True
                )
                await self._record_source_status(tenant_id, "github", "authentication_failed", str(e), 0)
            await asyncio.sleep(source.config.poll_interval_seconds)

    async def _sync_tenant_native_sources(self, tenants: dict[str, dict]) -> None:
        """Create/update per-tenant native connectors (GitLab, Jenkins, ArgoCD) from Settings."""
        if not self._cosmos_config:
            return

        # Map of connector kind -> (config factory, ChangeSource)
        _NATIVE = {
            "gitlab": (GitLabConfig, "gitlab"),
            "jenkins": (JenkinsConfig, "jenkins"),
            "argocd": (ArgoCDConfig, "argocd"),
        }

        desired: dict[str, dict[str, Any]] = {}
        for tenant_id, settings in tenants.items():
            configs = settings.get("sourceConfigs") or {}
            for key, (cfg_cls, label) in _NATIVE.items():
                cfg = configs.get(key)
                if not cfg:
                    continue
                base_url = cfg.get("base_url") or cfg.get("baseUrl") or ""
                token = cfg.get("token") or get_secret(cfg.get("token_secret_name", "")) or ""
                if not base_url or not token:
                    continue
                try:
                    desired.setdefault(tenant_id, {})[key] = cfg_cls(
                        base_url=base_url,
                        token=token,
                        username=cfg.get("username") or None,
                        webhook_secret=cfg.get("webhook_secret") or get_secret(cfg.get("webhook_secret_name", "")) or None,
                        password=cfg.get("password") or None,
                        groups=cfg.get("groups") or cfg.get("organizations") or [],
                        projects=cfg.get("projects") or cfg.get("repositories") or [],
                        applications=cfg.get("applications") or [],
                        app_projects=cfg.get("app_projects") or [],
                        jobs=cfg.get("jobs") or [],
                        job_folders=cfg.get("job_folders") or [],
                        branches=cfg.get("branches") or ["main", "master", "production"],
                        poll_interval_seconds=int(cfg.get("poll_interval_seconds", 300) or 300),
                    )
                except Exception as e:
                    self.logger.error(f"Failed to build {key} config for {tenant_id}: {e}")

        # Remove tenants/connectors no longer desired
        for tenant_id in list(self._tenant_native_sources):
            tenant_sources = self._tenant_native_sources[tenant_id]
            for key in list(tenant_sources):
                if key not in (desired.get(tenant_id) or {}):
                    source = tenant_sources.pop(key)
                    task = self._tenant_native_tasks.get(tenant_id, {}).pop(key, None)
                    if task:
                        task.cancel()
                    try:
                        await source.close()
                    except Exception:
                        pass
                    self.logger.info(f"Removed {key} source for tenant {tenant_id}")
            if not tenant_sources:
                self._tenant_native_sources.pop(tenant_id, None)

        # Add/start new connectors
        for tenant_id, connectors in desired.items():
            for key, cfg in connectors.items():
                existing = self._tenant_native_sources.get(tenant_id, {}).get(key)
                try:
                    if existing is None:
                        existing = self._native_source_for(cfg_cls=None, key=key, cfg=cfg)
                        await existing.initialize()
                        self._tenant_native_sources.setdefault(tenant_id, {})[key] = existing
                        self.logger.info(f"Initialized {key} source for tenant {tenant_id}")
                except Exception as e:
                    self.logger.error(f"Failed to init {key} for tenant {tenant_id}: {e}")
                    continue

                if self._running and self._is_leader() and tenant_id not in self._tenant_native_tasks.get(tenant_id, {}) and existing is not None:
                    task = asyncio.create_task(
                        self._run_tenant_native_polling(tenant_id, key, existing)
                    )
                    self._tenant_native_tasks.setdefault(tenant_id, {})[key] = task

    def _native_source_for(self, cfg_cls, key: str, cfg: Any):
        """Construct the correct source instance from the validated config."""
        if isinstance(cfg, GitLabConfig):
            return GitLabSource(cfg)
        if isinstance(cfg, JenkinsConfig):
            return JenkinsSource(cfg)
        if isinstance(cfg, ArgoCDConfig):
            return ArgoCDSource(cfg)
        raise ValueError(f"Unknown native connector: {key}")

    async def _run_tenant_native_polling(self, tenant_id: str, key: str, source: Any) -> None:
        """Poll a tenant's configured native connector."""
        self.logger.info(f"Starting {key} polling for tenant {tenant_id}")
        poll_all = getattr(source, "poll_all_projects", None) or getattr(
            source, "poll_all_jobs", None
        ) or getattr(source, "poll_all_applications", None)
        if not poll_all:
            return
        while self._running:
            if not self._is_leader():
                await asyncio.sleep(source.config.poll_interval_seconds)
                continue
            try:
                events = await poll_all()
                if events:
                    for event in events:
                        event.tenant_id = tenant_id
                    await self._buffer_events(events)
                    self.logger.info(f"Collected {len(events)} {key} events for tenant {tenant_id}")
                await self._record_source_status(tenant_id, key, "connected", None, len(events))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Error polling {key} for tenant {tenant_id}: {e}", exc_info=True)
                await self._record_source_status(tenant_id, key, "authentication_failed", str(e), 0)
            await asyncio.sleep(source.config.poll_interval_seconds)

    async def _record_source_status(
        self, tenant_id: str, source: str, state: str, error: str | None, event_count: int
    ) -> None:
        """Persist operational source status (rolling history + 24h event counts)."""
        if not self._cosmos_config:
            return

        now_ts = time.time()
        # Track 24h rolling event count per source.
        key = (tenant_id, source)
        samples = self._event_counters.setdefault(key, [])
        if event_count > 0:
            samples.append((now_ts, event_count))
        cutoff = now_ts - 86400
        self._event_counters[key] = [s for s in samples if s[0] >= cutoff]
        events_24h = sum(c for _, c in self._event_counters[key])

        now_iso = datetime.utcnow().isoformat()
        status = {
            "state": state,
            "lastSuccessfulPoll": now_iso if state == "connected" else None,
            "lastError": error,
            "eventsLastPoll": event_count,
            "eventsLast24h": events_24h,
            "updatedAt": now_iso,
        }
        # Keep a bounded rolling history per source (for the dashboard timeline).
        sample = {"ts": now_iso, "state": state, "events": event_count}
        escaped = json.dumps({source: status}).replace("'", "\\'")
        escaped_sample = json.dumps(sample).replace("'", "\\'")
        query = (
            "g.V().hasLabel('Settings').has('tenantId', '" + tenant_id + "').fold()"
            ".coalesce("
            "unfold()"
            ".property('integrationStatuses', '" + escaped + "')"
            ".property('integrationHistory', '" + escaped_sample + "'),"
            "addV('Settings')"
            ".property('tenantId', '" + tenant_id + "')"
            ".property('serviceName', 'settings')"
            ".property('integrationStatuses', '" + escaped + "')"
            ".property('integrationHistory', '" + escaped_sample + "'))"
        )
        try:
            await self._exec_gremlin(query)
        except Exception as exc:
            self.logger.warning(f"Could not persist {source} status for {tenant_id}: {exc}")

    async def _run_tenant_url_polling(self, tenant_id: str, source: UrlSource) -> None:
        """Poll a tenant's configured source URLs."""
        self.logger.info(f"Starting URL polling for tenant {tenant_id}")

        while self._running:
            if not self._is_leader():
                await asyncio.sleep(source.config.poll_interval_seconds)
                continue
            try:
                events = await source.poll_all()
                if events:
                    for event in events:
                        event.tenant_id = tenant_id
                    await self._buffer_events(events)
                    self.logger.info(
                        f"Collected {len(events)} events for tenant {tenant_id}"
                    )
                for source_key in source.config.urls:
                    await self._record_source_status(tenant_id, source_key, "connected", None, len(events))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(
                    f"Error polling URLs for tenant {tenant_id}: {e}", exc_info=True
                )
                for source_key in source.config.urls:
                    await self._record_source_status(tenant_id, source_key, "authentication_failed", str(e), 0)

            await asyncio.sleep(source.config.poll_interval_seconds)

    async def _init_eventgrid(self) -> None:
        """Initialize Event Grid publisher client"""
        if self.config.eventgrid_endpoint and self.config.eventgrid_key:
            from azure.core.credentials import AzureKeyCredential
            from azure.eventgrid import EventGridPublisherClient

            self._eventgrid_client = EventGridPublisherClient(
                self.config.eventgrid_endpoint,
                AzureKeyCredential(self.config.eventgrid_key)
            )
            self.logger.info("Initialized Event Grid publisher")
        else:
            self.logger.warning("Event Grid not configured, events will not be published")

    async def close(self) -> None:
        """Shutdown all sources and connections"""
        with LogContextManager(service_name="collector", operation_name="shutdown"):
            self.logger.info("Shutting down collector service")
            self._running = False

            for task in self._tasks:
                task.cancel()

            for task in self._tenant_source_tasks.values():
                task.cancel()

            for task in self._tenant_github_tasks.values():
                task.cancel()

            for tenant_tasks in self._tenant_native_tasks.values():
                for task in tenant_tasks.values():
                    task.cancel()

            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

            for source in self._sources.values():
                if hasattr(source, 'close'):
                    await source.close()

            for source in self._tenant_url_sources.values():
                if hasattr(source, 'close'):
                    await source.close()

            for source in self._tenant_github_sources.values():
                try:
                    await source.close()
                except Exception:
                    pass

            for tenant_sources in self._tenant_native_sources.values():
                for source in tenant_sources.values():
                    try:
                        await source.close()
                    except Exception:
                        pass

            await self._flush_buffer()

            if self._leader is not None:
                try:
                    await self._leader.stop()
                except Exception as e:
                    self.logger.warning(f"Leader election stop error: {e}")
                self._leader = None

            # Close clients (thread-local clients are closed by their respective threads)

            if self._eventgrid_client:
                await self._eventgrid_client.close()

            self.logger.info("Collector service shutdown complete")

    async def start(self) -> None:
        """Start collecting from all sources"""
        with LogContextManager(service_name="collector", operation_name="start"):
            self._running = True

            # Start leader election so that only one replica polls sources.
            try:
                from .leader_election import LeaderElection
                self._leader = LeaderElection()
                await self._leader.start()
            except Exception as e:
                self.logger.error(f"Failed to start leader election: {e}")
                self._leader = None

            # Start buffer flush task (safe on every replica; idempotent)
            flush_task = asyncio.create_task(self._periodic_flush())
            self._tasks.append(flush_task)

            # Start health check task (safe on every replica)
            health_task = asyncio.create_task(self._periodic_health_check())
            self._tasks.append(health_task)

            # Start tenant settings sync task (only the leader reconciles sources)
            sync_task = asyncio.create_task(self._periodic_tenant_sync())
            self._tasks.append(sync_task)

            self.logger.info("Collector service started")

    def _is_leader(self) -> bool:
        """True when this replica should perform polling/source reconciliation."""
        if self._leader is None:
            return True  # standalone mode (no k8s) — always poll
        return self._leader.is_leader

    async def _run_source_polling(self, source_type: ChangeSource, source: Any) -> None:
        """Run polling loop for a source"""
        self.logger.info(f"Starting polling for {source_type.value}")
        default_tenant = os.getenv("DEFAULT_TENANT_ID", "demo-tenant")

        while self._running:
            if not self._is_leader():
                await asyncio.sleep(self.config.flush_interval_seconds)
                continue
            try:
                events = await source.poll_all()
                if events:
                    for event in events:
                        if not event.tenant_id:
                            event.tenant_id = default_tenant
                    await self._buffer_events(events)
                    self.logger.info(f"Collected {len(events)} events from {source_type.value}")
            except Exception as e:
                self.logger.error(f"Error polling {source_type.value}: {e}", exc_info=True)

            await asyncio.sleep(self.config.flush_interval_seconds)

    async def _run_source_watching(self, source_type: ChangeSource, source: Any) -> None:
        """Run watch loop for a source"""
        self.logger.info(f"Starting watch for {source_type.value}")

        try:
            async for event in source.start_watching():
                if not self._running:
                    break
                await self._buffer_events([event])
        except Exception as e:
            self.logger.error(f"Error watching {source_type.value}: {e}", exc_info=True)

    async def _buffer_events(self, events: list[ChangeEvent]) -> None:
        """Add events to buffer"""
        async with self._buffer_lock:
            self._event_buffer.extend(events)

            if len(self._event_buffer) >= self.config.batch_size:
                await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush event buffer to Cosmos DB and Event Grid"""
        async with self._buffer_lock:
            if not self._event_buffer:
                return

            events = self._event_buffer[:]
            self._event_buffer.clear()

        if not events:
            return

        self.logger.info(f"Flushing {len(events)} events to storage")

        await self._write_to_cosmos(events)

        await self._publish_to_eventgrid(events)

        # Auto-trigger graph rebuild for affected tenants (non-blocking)
        asyncio.create_task(self._notify_graph_build(events))

    async def _check_cosmos_health(self) -> dict:
        """Health check for Cosmos DB"""
        if not self._cosmos_config:
            return {
                "healthy": False,
                "error": "Cosmos DB not configured",
            }
        try:
            result = await self._exec_gremlin("g.V().limit(1)")
            return {
                "healthy": True,
                "result": result,
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }

    async def _write_to_cosmos(self, events: list[ChangeEvent]) -> None:
        """Write events to Cosmos DB Gremlin with circuit breaker"""
        if not self._cosmos_config:
            self.logger.warning("Cosmos DB not configured, skipping write")
            return

        @self._cosmos_breaker
        async def write_event(event: ChangeEvent):
            vertex_props = event.to_gremlin_vertex()
            query = self._build_upsert_query(vertex_props)
            for attempt in range(self.config.max_retries):
                try:
                    result = await self._exec_gremlin(query)
                    return result
                except Exception:
                    if attempt == self.config.max_retries - 1:
                        raise
                    await asyncio.sleep(self.config.retry_backoff_seconds * (attempt + 1))

        for event in events:
            try:
                await write_event(event)
            except Exception as e:
                self.logger.error(f"Failed to write event {event.id} to Cosmos DB: {e}", exc_info=True)

    def _new_gremlin_client(self):
        """Create a new Gremlin client (must be called from a thread)"""
        from gremlin_python.driver import client, serializer
        cfg = self._cosmos_config
        username = f"/dbs/{cfg['database']}/colls/{cfg['graph']}"
        return client.Client(
            cfg["endpoint"], "g",
            username=username, password=cfg["key"],
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )

    async def _exec_gremlin(self, query: str) -> Any:
        """Execute Gremlin query in a thread pool to avoid event loop conflicts"""
        loop = asyncio.get_running_loop()
        cfg = self._cosmos_config

        def _run():
            c = self._new_gremlin_client()
            try:
                return c.submit(query).all().result()
            finally:
                c.close()

        try:
            return await loop.run_in_executor(None, _run)
        except Exception:
            self.logger.error(f"Gremlin query failed: {query[:500]}")
            raise

    def _build_upsert_query(self, props: dict[str, Any]) -> str:
        """Build Gremlin insert/upsert query deduped on a stable natural key."""
        _RESERVED = {"id", "gremlin_id", "partitionKey", "__partitionKey"}
        # Cosmos Gremlin partition key is readonly after addV; the update branch
        # must never write it.
        _PARTITION_KEYS = {"serviceName"}

        props = {k: v for k, v in props.items() if v is not None and k not in _RESERVED}

        # Build property assignments (update branch skips the readonly partition key)
        add_assignments = []
        update_assignments = []
        for key, value in props.items():
            if isinstance(value, str):
                escaped_value = value.replace("'", "\\'")
                prop = f".property('{key}', '{escaped_value}')"
            elif isinstance(value, (int, float)):
                prop = f".property('{key}', {value})"
            elif isinstance(value, bool):
                prop = f".property('{key}', {str(value).lower()})"
            elif isinstance(value, list):
                import json
                json_str = json.dumps(value).replace("'", "\\'")
                prop = f".property('{key}', '{json_str}')"
            else:
                escaped_value = str(value).replace("'", "\\'")
                prop = f".property('{key}', '{escaped_value}')"
            add_assignments.append(prop)
            if key not in _PARTITION_KEYS:
                update_assignments.append(prop)

        tenant = props.get("tenantId", "")
        service = props.get("serviceName", "")
        deployment_id = props.get("deploymentId", "")
        event_id = props.get("eventId", "")

        if not tenant:
            raise ValueError("ChangeEvent tenantId is required")

        if deployment_id:
            match = (
                f"g.V().hasLabel('ChangeEvent')"
                f".has('tenantId', '{tenant}')"
                f".has('serviceName', '{service}')"
                f".has('deploymentId', '{deployment_id}')"
            )
        else:
            match = (
                f"g.V().hasLabel('ChangeEvent').has('tenantId', '{tenant}')"
                f".has('eventId', '{event_id}')"
            )

        add_updates = "".join(add_assignments)
        update_updates = "".join(update_assignments)

        # Coalesce: update the matched vertex, else add a new one
        query = (
            f"{match}.fold().coalesce("
            f"unfold(){update_updates},"
            f"addV('ChangeEvent'){add_updates}"
            f")"
        )

        return query

    async def _publish_to_eventgrid(self, events: list[ChangeEvent]) -> None:
        """Publish events to Event Grid with circuit breaker"""
        if not self._eventgrid_client:
            return

        @self._eventgrid_breaker
        async def publish_batch(eg_events):
            self._eventgrid_client.send(eg_events)

        try:
            from azure.eventgrid import EventGridEvent

            eg_events = []
            for event in events:
                eg_event = EventGridEvent(
                    id=event.event_id,
                    subject=f"change/{event.source.value}/{event.service_name}",
                    data=event.to_gremlin_vertex(),
                    event_type=f"ChangeTrace.{event.change_type.value}",
                    event_time=event.timestamp,
                    data_version="1.0"
                )
                eg_events.append(eg_event)

            await publish_batch(eg_events)
            self.logger.info(f"Published {len(eg_events)} events to Event Grid")

        except Exception as e:
            self.logger.error(f"Failed to publish to Event Grid: {e}", exc_info=True)

    async def _notify_graph_build(self, events: list[ChangeEvent]) -> None:
        """Trigger a graph rebuild for each tenant that produced new events."""
        if not self.config.graph_builder_url:
            return

        tenant_ids = {e.tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant") for e in events}
        if not tenant_ids:
            return

        internal_token = os.getenv("INTERNAL_AUTH_TOKEN", "")

        try:
            import httpx

            headers = (
                {"Authorization": f"Bearer {internal_token}"}
                if internal_token
                else {}
            )
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                for tenant_id in tenant_ids:
                    try:
                        resp = await client.get(
                            f"{self.config.graph_builder_url.rstrip('/')}/api/v1/graph/build-from-events",
                            params={"tenant_id": tenant_id, "lookback_hours": 24},
                        )
                        if resp.status_code >= 400:
                            self.logger.warning(
                                f"Graph build notification for tenant {tenant_id} "
                                f"returned {resp.status_code}: {resp.text[:200]}"
                            )
                        else:
                            self.logger.info(
                                f"Auto-triggered graph rebuild for tenant {tenant_id} "
                                f"({resp.text[:200]})"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to notify graph-builder for tenant {tenant_id}: {e}"
                        )
        except Exception as e:
            self.logger.error(f"Graph build notification failed: {e}", exc_info=True)

    async def _periodic_flush(self) -> None:
        """Periodically flush event buffer"""
        while self._running:
            await asyncio.sleep(self.config.flush_interval_seconds)
            await self._flush_buffer()

    async def _periodic_tenant_sync(self) -> None:
        """Periodically reconcile per-tenant sources with Cosmos Settings."""
        while self._running:
            await asyncio.sleep(self.config.flush_interval_seconds)
            if not self._is_leader():
                continue
            try:
                await self.sync_tenant_sources()
            except Exception as e:
                self.logger.error(f"Tenant source sync failed: {e}", exc_info=True)

    async def _periodic_health_check(self) -> None:
        """Periodic health check"""
        while self._running:
            await asyncio.sleep(self.config.health_check_interval_seconds)

            for source_type, source in self._sources.items():
                if hasattr(source, 'health_check'):
                    try:
                        healthy = await source.health_check()
                        if not healthy:
                            self.logger.warning(f"Source {source_type.value} health check failed")
                    except Exception as e:
                        self.logger.error(f"Health check failed for {source_type.value}: {e}")

            async with self._buffer_lock:
                self.logger.debug(f"Event buffer size: {len(self._event_buffer)}")

    async def handle_webhook(self, source: ChangeSource, payload: bytes, headers: dict[str, str], tenant_id: str | None = None) -> list[ChangeEvent]:
        """Handle incoming webhook from a source"""
        if not tenant_id:
            raise HTTPException(status_code=401, detail="Tenant authentication is required")
        source_obj = self._tenant_github_sources.get(tenant_id) if source == ChangeSource.GITHUB else self._sources.get(source)
        if not source_obj:
            raise HTTPException(status_code=404, detail=f"Source {source.value} not configured")

        if not hasattr(source_obj, 'parse_webhook'):
            raise HTTPException(status_code=400, detail=f"Source {source.value} does not support webhooks")

        parsed = await source_obj.parse_webhook(payload, headers)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid webhook payload")

        events = await source_obj.process_webhook(parsed)

        # Tag events with the tenant for multi-tenant isolation
        for event in events:
            event.tenant_id = tenant_id

        await self._buffer_events(events)

        return events

    async def resolve_github_webhook(self, payload: bytes, headers: dict[str, str]) -> tuple[str, list[ChangeEvent]]:
        """Resolve a GitHub webhook by its tenant-specific HMAC and repository."""
        for tenant_id, source in self._tenant_github_sources.items():
            parsed = await source.parse_webhook(payload, headers)
            if not parsed:
                continue
            events = await source.process_webhook(parsed)
            for event in events:
                event.tenant_id = tenant_id
            await self._buffer_events(events)
            await self._record_source_status(tenant_id, "github", "connected", None, len(events))
            return tenant_id, events
        raise HTTPException(status_code=401, detail="Webhook signature or repository is not registered")

    async def get_stats(self) -> dict[str, Any]:
        """Get collector statistics"""
        return {
            "running": self._running,
            "sources": list(self._sources.keys()),
            "tenant_url_sources": list(self._tenant_url_sources.keys()),
            "tenant_native_sources": {
                tenant: list(srcs.keys())
                for tenant, srcs in self._tenant_native_sources.items()
            },
            "buffer_size": len(self._event_buffer),
            "tasks": len(self._tasks),
            "circuit_breakers": {
                "cosmos": self._cosmos_breaker.get_stats(),
                "eventgrid": self._eventgrid_breaker.get_stats(),
                "keyvault": self._keyvault_breaker.get_stats(),
            },
            "health": (await self._health_registry.run_all()).to_dict(),
        }


# FastAPI app for webhook endpoints
app = FastAPI(title="ChangeTrace Collector", version="1.0.0")

collector: CollectorService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global collector

    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        cosmos_connection_string: str = ""
        cosmos_endpoint: str = ""
        cosmos_key: str = ""
        cosmos_database: str = "changetrace-graph"
        cosmos_graph: str = "change-history"
        eventgrid_endpoint: str | None = None
        eventgrid_key: str | None = None

        # GitHub
        github_app_id: int | None = None
        github_private_key: str | None = None
        github_installation_id: int | None = None
        github_pat: str | None = None
        github_webhook_secret: str | None = None
        github_organizations: list[str] = []
        github_repositories: list[str] = []
        github_branches: list[str] = ["main", "master", "production"]
        github_poll_interval: int = 300

        # Terraform
        terraform_hostname: str = "app.terraform.io"
        terraform_organization: str | None = None
        terraform_token: str | None = None
        terraform_workspaces: list[str] = []
        terraform_poll_interval: int = 300

        # Kubernetes
        k8s_kubeconfig: str | None = None
        k8s_context: str | None = None
        k8s_in_cluster: bool = False
        k8s_namespaces: list[str] = ["default", "production", "staging"]
        k8s_poll_interval: int = 60

        # Azure Resource Graph
        arg_subscription_ids: list[str] = []
        arg_lookback_hours: int = 24
        arg_poll_interval: int = 300

        # Graph-builder notification
        graph_builder_url: str = ""

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"

    settings = Settings()

    github_config = None
    if settings.github_app_id and settings.github_private_key and settings.github_installation_id:
        github_config = GitHubConfig(
            app_id=settings.github_app_id,
            private_key=settings.github_private_key,
            installation_id=settings.github_installation_id,
            webhook_secret=settings.github_webhook_secret,
            organizations=settings.github_organizations,
            repositories=settings.github_repositories,
            branches=settings.github_branches,
            poll_interval_seconds=settings.github_poll_interval,
        )
    elif settings.github_pat:
        github_config = GitHubConfig(
            personal_access_token=settings.github_pat,
            webhook_secret=settings.github_webhook_secret,
            organizations=settings.github_organizations,
            repositories=settings.github_repositories,
            branches=settings.github_branches,
            poll_interval_seconds=settings.github_poll_interval,
        )

    terraform_config = None
    if settings.terraform_organization and settings.terraform_token:
        terraform_config = TerraformConfig(
            hostname=settings.terraform_hostname,
            organization=settings.terraform_organization,
            token=settings.terraform_token,
            workspaces=settings.terraform_workspaces,
            poll_interval_seconds=settings.terraform_poll_interval,
        )

    k8s_config = None
    if settings.k8s_in_cluster or settings.k8s_kubeconfig:
        k8s_config = K8sConfig(
            tenant_id=os.getenv("DEFAULT_TENANT_ID", "demo-tenant"),
            cluster_id=os.getenv("K8S_CLUSTER_ID", "default-cluster"),
            kubeconfig_path=settings.k8s_kubeconfig,
            context=settings.k8s_context,
            in_cluster=settings.k8s_in_cluster,
            namespaces=settings.k8s_namespaces,
            poll_interval_seconds=settings.k8s_poll_interval,
        )

    arg_config = None
    if settings.arg_subscription_ids:
        arg_config = AzureResourceGraphConfig(
            subscription_ids=settings.arg_subscription_ids,
            lookback_hours=settings.arg_lookback_hours,
            poll_interval_seconds=settings.arg_poll_interval,
        )

    config = CollectorConfig(
        cosmos_connection_string=settings.cosmos_connection_string,
        cosmos_endpoint=settings.cosmos_endpoint,
        cosmos_key=settings.cosmos_key,
        cosmos_database=settings.cosmos_database,
        cosmos_graph=settings.cosmos_graph,
        eventgrid_endpoint=settings.eventgrid_endpoint,
        eventgrid_key=settings.eventgrid_key,
        graph_builder_url=settings.graph_builder_url,
        github=github_config,
        terraform=terraform_config,
        kubernetes=k8s_config,
        azure_resource_graph=arg_config,
    )

    collector = CollectorService(config)
    await collector.initialize()
    await collector.start()

    yield

    await collector.close()


app.router.lifespan_context = lifespan


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    stats = await collector.get_stats()
    return {
        "status": "healthy" if collector._running else "unhealthy",
        "stats": stats,
    }


async def _authenticate_tenant_key(request: Request) -> str | None:
    """Resolve the tenant_id from an Authorization Bearer API key."""
    if not collector or not collector._cosmos_config:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    api_key = auth_header[7:].strip()
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    query = f"g.V().hasLabel('TenantKey').has('apiKeyHash', '{key_hash}').values('tenantId')"
    try:
        result = await collector._exec_gremlin(query)
        if isinstance(result, list) and result:
            return result[0]
        if result:
            return result
        # Backward-compatible migration lookup for keys created by older builds.
        legacy = (
            f"g.V().hasLabel('TenantKey').has('apiKey', '{api_key}')"
            f".values('tenantId')"
        )
        result = await collector._exec_gremlin(legacy)
        if isinstance(result, list) and result:
            return result[0]
        if result:
            return result
    except Exception as e:
        collector.logger.error(f"API key lookup failed: {e}")
    return None


@app.post("/webhook/github")
async def github_webhook(request: Request):
    """GitHub webhook endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    payload = await request.body()
    headers = dict(request.headers)
    tenant_id = await _authenticate_tenant_key(request)
    if tenant_id:
        events = await collector.handle_webhook(ChangeSource.GITHUB, payload, headers, tenant_id)
    else:
        _, events = await collector.resolve_github_webhook(payload, headers)
    return {"received": len(events)}


@app.post("/webhook/terraform")
async def terraform_webhook(request: Request):
    """Terraform webhook endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    tenant_id = await _authenticate_tenant_key(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="A valid tenant API key is required")
    payload = await request.body()
    headers = dict(request.headers)

    events = await collector.handle_webhook(ChangeSource.TERRAFORM, payload, headers, tenant_id)
    return {"received": len(events)}


@app.post("/webhook/kubernetes")
async def kubernetes_webhook(request: Request):
    """Kubernetes webhook endpoint (for admission webhooks, etc.)"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    tenant_id = await _authenticate_tenant_key(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="A valid tenant API key is required")
    payload = await request.body()
    headers = dict(request.headers)

    events = await collector.handle_webhook(ChangeSource.KUBERNETES, payload, headers, tenant_id)
    return {"received": len(events)}


class IngestRequest(BaseModel):
    """Generic per-tenant change event ingestion payload"""
    tenant_id: str
    events: list[ChangeEvent]


@app.post("/ingest")
async def ingest_events(request: Request, body: IngestRequest):
    """Ingest change events for a specific tenant (requires tenant API key auth)."""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    if not body.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    authed_tenant = await _authenticate_tenant_key(request)
    if not authed_tenant:
        raise HTTPException(
            status_code=401,
            detail="A valid tenant API key is required (Authorization: Bearer <api_key>)",
        )
    if authed_tenant != body.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="API key does not grant access to the requested tenant_id",
        )

    events = body.events
    for event in events:
        event.tenant_id = body.tenant_id

    await collector._buffer_events(events)
    return {"received": len(events)}


class K8sIngestEvent(BaseModel):
    """A single Kubernetes resource change event from a customer-side agent."""
    event_type: str  # ADDED, MODIFIED, DELETED
    resource_type: str  # Deployment, ConfigMap, Service, etc.
    namespace: str = "default"
    name: str
    uid: str | None = None
    resource_version: str | None = None
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    spec: dict[str, Any] = {}
    timestamp: str | None = None
    cluster_id: str | None = None


class K8sIngestRequest(BaseModel):
    """Batch of K8s events from a customer's cluster agent."""
    cluster_id: str
    events: list[K8sIngestEvent]


@app.post("/k8s/events")
async def ingest_k8s_events(request: Request, body: K8sIngestRequest):
    """Ingest Kubernetes change events from a customer's in-cluster agent."""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    if not body.cluster_id:
        raise HTTPException(status_code=400, detail="cluster_id is required")

    authed_tenant = await _authenticate_tenant_key(request)
    if not authed_tenant:
        raise HTTPException(
            status_code=401,
            detail="A valid tenant API key is required (Authorization: Bearer <api_key>)",
        )

    from .sources.k8s_source import K8sResourceEvent, k8s_resource_event_to_change_event

    change_events = []
    for raw in body.events:
        ts = raw.timestamp
        from datetime import datetime
        timestamp = (
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts else datetime.utcnow()
        )
        k8s_event = K8sResourceEvent(
            event_type=raw.event_type,
            resource_type=raw.resource_type,
            namespace=raw.namespace,
            name=raw.name,
            uid=raw.uid or raw.name,
            resource_version=raw.resource_version or "",
            labels=raw.labels,
            annotations=raw.annotations,
            spec=raw.spec,
            timestamp=timestamp,
            tenant_id=authed_tenant,
            cluster_id=raw.cluster_id or body.cluster_id,
        )
        # Reuse the pure conversion (excludes kube-system system namespaces).
        converted = k8s_resource_event_to_change_event(k8s_event)
        if converted:
            converted.tenant_id = authed_tenant
            converted.labels["changetrace.tenant_id"] = authed_tenant
            converted.labels["changetrace.cluster_id"] = body.cluster_id
            change_events.append(converted)

    await collector._buffer_events(change_events)
    await collector._record_source_status(authed_tenant, "kubernetes", "connected", None, len(change_events))
    return {"received": len(change_events), "tenant_id": authed_tenant, "cluster_id": body.cluster_id}


@app.get("/k8s/agent-manifest")
async def k8s_agent_manifest(request: Request):
    """Generate a customer-specific Kubernetes agent manifest."""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    authed_tenant = await _authenticate_tenant_key(request)
    if not authed_tenant:
        raise HTTPException(status_code=401, detail="A valid tenant API key is required")

    cluster_id = (request.query_params.get("cluster_id") or "").strip() or f"{authed_tenant}-cluster"
    collector_url = os.getenv("COLLECTOR_PUBLIC_URL", "").strip() or "https://collector.example.com"
    api_key_hash = hashlib.sha256(authed_tenant.encode()).hexdigest()[:8]

    yaml_doc = f"""# ChangeTrace Kubernetes agent — {authed_tenant}
# Generated by ChangeTrace. Apply in the customer's cluster:
#   kubectl apply -f this-file.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: changetrace-agent
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: changetrace-agent
  namespace: changetrace-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: changetrace-agent
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["configmaps", "secrets", "services", "pods", "events"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: changetrace-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: changetrace-agent
subjects:
  - kind: ServiceAccount
    name: changetrace-agent
    namespace: changetrace-agent
---
apiVersion: v1
kind: Secret
metadata:
  name: changetrace-agent-creds
  namespace: changetrace-agent
type: Opaque
stringData:
  TENANT_ID: "{authed_tenant}"
  CLUSTER_ID: "{cluster_id}"
  COLLECTOR_URL: "{collector_url}"
  API_KEY: "$(CHANGETRACE_API_KEY)"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: changetrace-agent
  namespace: changetrace-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: changetrace-agent
  template:
    metadata:
      labels:
        app: changetrace-agent
    spec:
      serviceAccountName: changetrace-agent
      containers:
        - name: agent
          image: changetrace29r2ywacr.azurecr.io/k8s-agent:latest
          env:
            - name: TENANT_ID
              valueFrom:
                secretKeyRef:
                  name: changetrace-agent-creds
                  key: TENANT_ID
            - name: CLUSTER_ID
              valueFrom:
                secretKeyRef:
                  name: changetrace-agent-creds
                  key: CLUSTER_ID
            - name: COLLECTOR_URL
              valueFrom:
                secretKeyRef:
                  name: changetrace-agent-creds
                  key: COLLECTOR_URL
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: changetrace-agent-creds
                  key: API_KEY
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
"""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        yaml_doc,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="changetrace-agent-{api_key_hash}.yaml"'},
    )


@app.get("/stats")
async def get_stats(request: Request):
    """Get collector statistics"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")

    internal_token = os.getenv("INTERNAL_AUTH_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    if not internal_token or not hmac.compare_digest(
        authorization.removeprefix("Bearer "), internal_token
    ):
        raise HTTPException(status_code=401, detail="Internal authentication required")

    return await collector.get_stats()


async def main():
    """Main entry point"""
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8000
        log_level: str = "info"

        class Config:
            env_file = ".env"

    settings = Settings()

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
