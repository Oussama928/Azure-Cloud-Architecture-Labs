"""
ArgoCD Source Collector for ChangeTrace.

Collects change events from ArgoCD and authenticates against the ArgoCD API.
"""

import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    GitReference,
    KubernetesChangeDetail,
    ResourceReference,
)

logger = logging.getLogger(__name__)


class ArgoCDConfig(BaseModel):
    """Configuration for ArgoCD source"""
    base_url: str  # e.g. https://argocd.example.com
    username: str | None = None
    password: str | None = None
    token: str | None = None  # Direct API token (preferred over username/password)

    # Application filters
    applications: list[str] = Field(default_factory=list)  # Empty = all
    app_projects: list[str] = Field(default_factory=list)

    # Polling configuration
    poll_interval_seconds: int = 300
    lookback_hours: int = 24


class ArgoCDApplication(BaseModel):
    """ArgoCD application representation"""
    name: str
    project: str
    namespace: str | None = None
    destination: str
    repo_url: str | None = None
    path: str | None = None
    sync_status: str | None = None
    health_status: str | None = None
    revision: str | None = None
    sync_revision: str | None = None


class ArgoCDSource:
    """ArgoCD change event collector."""

    def __init__(self, config: ArgoCDConfig):
        self.config = config
        base_url = config.base_url.rstrip("/")
        headers: dict[str, str] = {"Accept": "application/json"}
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0)
        self._token: str | None = config.token
        self._last_poll_time: dict[str, datetime] = {}
        self._seen_syncs: set[str] = set()

    async def initialize(self) -> None:
        if not self._token and self.config.username and self.config.password:
            await self._login()
        logger.info("Initialized ArgoCD source")

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        """Obtain a session token via the login API."""
        try:
            resp = await self._client.post(
                "/api/v1/session",
                json={"username": self.config.username, "password": self.config.password},
            )
            resp.raise_for_status()
            token = resp.json().get("token")
            if token:
                self._token = token
                self._client.headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            logger.warning(f"ArgoCD login failed: {e}")

    async def _get(self, path: str, **params) -> Any:
        resp = await self._client.get(path, params=params)
        if resp.status_code == 401 and self.config.username and self.config.password and not self._token:
            await self._login()
            resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_applications(self) -> list[ArgoCDApplication]:
        try:
            data = await self._get("/api/v1/applications")
        except Exception as e:
            logger.warning(f"Failed to list ArgoCD applications: {e}")
            return []

        apps: list[ArgoCDApplication] = []
        for item in data.get("items", []):
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})
            name = metadata.get("name", "")
            if self.config.applications and name not in self.config.applications:
                continue
            project = spec.get("project", "default")
            if self.config.app_projects and project not in self.config.app_projects:
                continue
            dest = spec.get("destination", {})
            apps.append(ArgoCDApplication(
                name=name,
                project=project,
                namespace=dest.get("namespace"),
                destination=dest.get("server", ""),
                repo_url=spec.get("source", {}).get("repoURL"),
                path=spec.get("source", {}).get("path"),
                sync_status=status.get("sync", {}).get("status"),
                health_status=status.get("health", {}).get("status"),
                revision=status.get("sync", {}).get("revision"),
                sync_revision=status.get("sync", {}).get("revision"),
            ))
        return apps

    async def poll_application(self, app: ArgoCDApplication) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        try:
            data = await self._get(f"/api/v1/applications/{app.name}")
        except Exception as e:
            logger.warning(f"Failed to poll ArgoCD app {app.name}: {e}")
            return events

        status = data.get("status", {})
        sync = status.get("sync", {})
        revision = sync.get("revision", "")

        # Emit a deployment event on a new revision we haven't seen yet.
        key = f"{app.name}:{revision}"
        if revision and key not in self._seen_syncs:
            self._seen_syncs.add(key)
            events.append(self._sync_to_change_event(app, revision, sync.get("status", "Synced")))
        elif not revision and sync.get("status") != (app.sync_status or "OutOfSync"):
            events.append(self._sync_to_change_event(app, app.sync_revision or "", sync.get("status", "Synced")))
        return events

    def _sync_to_change_event(self, app: ArgoCDApplication, revision: str, sync_status: str) -> ChangeEvent:
        repo_url = app.repo_url or ""
        repo_name = repo_url.rstrip("/").split("/")[-1] if repo_url else app.name
        branch = None
        if app.path:
            branch = app.path.split("/")[-1]

        return ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.ARGO_ROLLOUTS,
            status=ChangeStatus.SUCCEEDED if sync_status == "Synced" else ChangeStatus.IN_PROGRESS,
            timestamp=datetime.utcnow(),
            service_name=app.name,
            namespace=app.namespace,
            environment=self._extract_environment(app.name),
            description=f"ArgoCD synced {app.name} to revision {revision[:8] if revision else 'latest'}",
            summary=f"ArgoCD sync: {app.name}",
            git=GitReference(
                repo_url=repo_url,
                repo_name=repo_name,
                commit_sha=revision or None,
            ),
            kubernetes_changes=[
                KubernetesChangeDetail(
                    resource=ResourceReference(kind="Application", name=app.name, namespace=app.namespace),
                    operation="UPDATE",
                    labels={"argocd.project": app.project},
                )
            ],
            pipeline_name=f"argocd/{app.name}",
            pipeline_run_id=f"{app.name}-{revision[:8] if revision else 'sync'}",
            pipeline_url=f"{self.config.base_url}/applications/{app.name}",
            deployment_strategy="rolling",
            new_version=revision or None,
            labels={
                "argocd.application": app.name,
                "argocd.project": app.project,
                "argocd.sync_status": sync_status,
                "argocd.revision": revision,
            },
            correlation_id=f"{app.name}:{revision}",
        )

    def _extract_environment(self, name: str) -> str:
        n = name.lower()
        if any(e in n for e in ["prod", "production"]):
            return "production"
        if any(e in n for e in ["staging", "stage"]):
            return "staging"
        if any(e in n for e in ["dev", "development"]):
            return "development"
        return "production"

    async def poll_all_applications(self) -> list[ChangeEvent]:
        all_events: list[ChangeEvent] = []
        apps = await self.get_applications()
        for app in apps:
            events = await self.poll_application(app)
            all_events.extend(events)
        return all_events

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/v1/applications", params={"name": ""})
            return resp.status_code in (200, 401)
        except Exception:
            return False
