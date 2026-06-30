"""
GitLab Source Collector for ChangeTrace.

Collects change events from GitLab using a personal/group access token.
"""

import hashlib
import hmac
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
)

logger = logging.getLogger(__name__)


class GitLabConfig(BaseModel):
    """Configuration for GitLab source"""
    # GitLab instance URL (e.g. https://gitlab.com or self-hosted)
    base_url: str = "https://gitlab.com/api/v4"
    # Personal / group access token
    token: str
    # Webhook secret token (X-Gitlab-Token) for validating webhooks
    webhook_secret: str | None = None

    # Repository filters
    groups: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)  # Format: "namespace/project"
    branches: list[str] = Field(default_factory=lambda: ["main", "master", "production"])

    # Polling configuration
    poll_interval_seconds: int = 300
    lookback_hours: int = 24

    # Event types
    collect_commits: bool = True
    collect_merge_requests: bool = True
    collect_releases: bool = True
    collect_pipelines: bool = True


class GitLabWebhookPayload(BaseModel):
    """Parsed GitLab webhook payload"""
    object_kind: str
    event_type: str | None = None
    payload: dict[str, Any]
    project: dict[str, Any] | None = None
    timestamp: datetime


class GitLabSource:
    """GitLab change event collector."""

    def __init__(self, config: GitLabConfig):
        self.config = config
        base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "PRIVATE-TOKEN": config.token,
                "Accept": "application/json",
            },
            timeout=60.0,
        )
        self._last_poll_time: dict[str, datetime] = {}

    async def initialize(self) -> None:
        logger.info("Initialized GitLab source")

    async def close(self) -> None:
        await self._client.aclose()

    def verify_webhook_signature(self, payload: bytes, token: str | None) -> bool:
        """Verify the X-Gitlab-Token header."""
        if not self.config.webhook_secret:
            logger.warning("No webhook secret configured, skipping verification")
            return True
        return hmac.compare_digest(token or "", self.config.webhook_secret)

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> GitLabWebhookPayload | None:
        token = headers.get("X-Gitlab-Token", "")
        if not self.verify_webhook_signature(payload, token):
            logger.warning("Invalid GitLab webhook token")
            return None

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GitLab webhook JSON: {e}")
            return None

        return GitLabWebhookPayload(
            object_kind=data.get("object_kind", ""),
            event_type=data.get("event_type"),
            payload=data,
            project=data.get("project"),
            timestamp=datetime.utcnow(),
        )

    async def process_webhook(self, event: GitLabWebhookPayload) -> list[ChangeEvent]:
        events = []

        if event.object_kind == "push" and self.config.collect_commits:
            events.extend(self._process_push_event(event))
        elif event.object_kind == "merge_request" and self.config.collect_merge_requests:
            events.extend(self._process_mr_event(event))
        elif event.object_kind == "release" and self.config.collect_releases:
            events.extend(self._process_release_event(event))
        elif event.object_kind == "pipeline" and self.config.collect_pipelines:
            events.extend(self._process_pipeline_event(event))

        return events

    def _should_process_project(self, project_path: str) -> bool:
        if self.config.groups:
            group = project_path.split("/")[0]
            if group not in self.config.groups:
                return False
        if self.config.projects:
            if project_path not in self.config.projects:
                return False
        return True

    def _process_push_event(self, event: GitLabWebhookPayload) -> list[ChangeEvent]:
        events = []
        payload = event.payload
        project_path = (event.project or {}).get("path_with_namespace", "")
        if not self._should_process_project(project_path):
            return events

        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "")
        if branch not in self.config.branches:
            return events

        user = payload.get("user_username", payload.get("user_name", "unknown"))
        project_url = (event.project or {}).get("web_url", "")

        for commit in payload.get("commits", []):
            commit_id = commit.get("id", "")
            service_name = self._extract_service_name(project_path, commit.get("message", ""))
            events.append(ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.CI_CD_PIPELINE,
                status=ChangeStatus.SUCCEEDED,
                timestamp=datetime.fromisoformat(commit.get("timestamp", "").replace("Z", "+00:00")) if commit.get("timestamp") else datetime.utcnow(),
                service_name=service_name,
                environment="production",
                author=user,
                description=commit.get("message", ""),
                summary=f"{project_path}: commit {commit_id[:8]}",
                git=GitReference(
                    repo_url=project_url,
                    repo_name=project_path,
                    commit_sha=commit_id,
                    commit_message=commit.get("message"),
                    branch=branch,
                    author=user,
                    commit_url=commit.get("url"),
                ),
                pipeline_name=f"gitlab/{project_path}",
                pipeline_run_id=commit_id,
                pipeline_url=commit.get("url"),
                labels={
                    "gitlab.event": "push",
                    "gitlab.project": project_path,
                    "gitlab.branch": branch,
                },
                correlation_id=event.payload.get("event_name", ""),
            ))
        return events

    def _process_mr_event(self, event: GitLabWebhookPayload) -> list[ChangeEvent]:
        events = []
        payload = event.payload
        project_path = (event.project or {}).get("path_with_namespace", "")
        if not self._should_process_project(project_path):
            return events

        attrs = payload.get("object_attributes", {})
        action = attrs.get("action", "")
        if action != "merge":
            return events

        base_branch = attrs.get("target_branch", "")
        if base_branch not in self.config.branches:
            return events

        mr_author = (attrs.get("author") or {}).get("username", "unknown")
        project_url = (event.project or {}).get("web_url", "")
        events.append(ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.CI_CD_PIPELINE,
            status=ChangeStatus.SUCCEEDED,
            timestamp=datetime.fromisoformat(attrs.get("updated_at", "").replace("Z", "+00:00")) if attrs.get("updated_at") else datetime.utcnow(),
            service_name=self._extract_service_name(project_path, attrs.get("title", "")),
            environment="production",
            author=mr_author,
            description=attrs.get("description") or attrs.get("title"),
            summary=f"MR !{attrs.get('iid')}: {attrs.get('title')}",
            git=GitReference(
                repo_url=project_url,
                repo_name=project_path,
                commit_sha=attrs.get("last_commit", {}).get("id"),
                branch=base_branch,
                pr_number=attrs.get("iid"),
                pr_title=attrs.get("title"),
                author=mr_author,
                commit_url=attrs.get("url"),
            ),
            pipeline_name=f"gitlab/{project_path}",
            pipeline_run_id=str(attrs.get("iid")),
            pipeline_url=attrs.get("url"),
            labels={
                "gitlab.event": "merge_request",
                "gitlab.action": "merge",
                "gitlab.project": project_path,
                "gitlab.branch": base_branch,
            },
            correlation_id=str(attrs.get("id")),
        ))
        return events

    def _process_release_event(self, event: GitLabWebhookPayload) -> list[ChangeEvent]:
        events = []
        payload = event.payload
        project_path = (event.project or {}).get("path_with_namespace", "")
        if not self._should_process_project(project_path):
            return events

        attrs = payload.get("release", {})
        project_url = (event.project or {}).get("web_url", "")
        events.append(ChangeEvent(
            change_type=ChangeType.RELEASE,
            source=ChangeSource.CI_CD_PIPELINE,
            status=ChangeStatus.SUCCEEDED,
            timestamp=datetime.utcnow(),
            service_name=self._extract_service_name(project_path, attrs.get("name", "")),
            environment="production",
            author=attrs.get("author", {}).get("name"),
            description=attrs.get("description"),
            summary=f"Release {attrs.get('tag_name')}: {attrs.get('name')}",
            git=GitReference(
                repo_url=project_url,
                repo_name=project_path,
                tag=attrs.get("tag_name"),
                commit_sha=attrs.get("commit", {}).get("id"),
            ),
            pipeline_name=f"gitlab/{project_path}",
            pipeline_run_id=attrs.get("tag_name"),
            pipeline_url=attrs.get("_links", {}).get("self"),
            new_version=attrs.get("tag_name"),
            labels={
                "gitlab.event": "release",
                "gitlab.project": project_path,
                "gitlab.tag": attrs.get("tag_name"),
            },
        ))
        return events

    def _process_pipeline_event(self, event: GitLabWebhookPayload) -> list[ChangeEvent]:
        events = []
        payload = event.payload
        project_path = (event.project or {}).get("path_with_namespace", "")
        if not self._should_process_project(project_path):
            return events

        attrs = payload.get("object_attributes", {})
        status = attrs.get("status", "")
        status_map = {
            "success": ChangeStatus.SUCCEEDED,
            "failed": ChangeStatus.FAILED,
            "canceled": ChangeStatus.CANCELLED,
            "running": ChangeStatus.IN_PROGRESS,
            "pending": ChangeStatus.PENDING,
        }
        change_status = status_map.get(status, ChangeStatus.IN_PROGRESS)
        project_url = (event.project or {}).get("web_url", "")

        events.append(ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.CI_CD_PIPELINE,
            status=change_status,
            timestamp=datetime.utcnow(),
            service_name=self._extract_service_name(project_path, attrs.get("ref", "")),
            environment="production",
            author=(payload.get("user") or {}).get("username"),
            description=f"Pipeline {attrs.get('id')} for {attrs.get('ref')}",
            summary=f"Pipeline #{attrs.get('id')}: {status}",
            git=GitReference(
                repo_url=project_url,
                repo_name=project_path,
                commit_sha=payload.get("commit", {}).get("id"),
                branch=attrs.get("ref"),
            ),
            pipeline_name=f"gitlab/{project_path}",
            pipeline_run_id=str(attrs.get("id")),
            pipeline_url=attrs.get("url"),
            labels={
                "gitlab.event": "pipeline",
                "gitlab.project": project_path,
                "gitlab.pipeline_id": str(attrs.get("id")),
                "gitlab.status": status,
            },
            correlation_id=str(attrs.get("id")),
        ))
        return events

    # Polling methods
    async def get_projects(self) -> list[dict[str, Any]]:
        """Get list of projects based on group/project filters."""
        params = {"simple": "true", "per_page": 100}
        projects: list[dict[str, Any]] = []

        if self.config.projects:
            for path in self.config.projects:
                try:
                    resp = await self._client.get(f"/projects/{path.replace('/', '%2F')}")
                    resp.raise_for_status()
                    projects.append(resp.json())
                except Exception as e:
                    logger.warning(f"Failed to fetch GitLab project {path}: {e}")
            return projects

        for group in self.config.groups:
            try:
                resp = await self._client.get(f"/groups/{group}/projects", params=params)
                resp.raise_for_status()
                projects.extend(resp.json())
            except Exception as e:
                logger.warning(f"Failed to fetch GitLab group {group}: {e}")

        return projects

    async def poll_project(self, project_id: int, path_with_namespace: str) -> list[ChangeEvent]:
        """Poll a project for new commits and pipelines."""
        events: list[ChangeEvent] = []
        since = self._last_poll_time.get(path_with_namespace) or (datetime.utcnow() - timedelta(hours=self.config.lookback_hours))

        try:
            if self.config.collect_pipelines:
                params = {"updated_after": since.isoformat(), "per_page": 50}
                resp = await self._client.get(f"/projects/{project_id}/pipelines", params=params)
                resp.raise_for_status()
                for pipeline in resp.json():
                    try:
                        detail = await self._client.get(f"/projects/{project_id}/pipelines/{pipeline['id']}")
                        detail.raise_for_status()
                        detail_json = detail.json()
                        self._append_pipeline_event(events, detail_json, path_with_namespace)
                    except Exception as e:
                        logger.warning(f"Failed to fetch pipeline detail: {e}")
        except Exception as e:
            logger.warning(f"Failed to poll GitLab pipelines for {path_with_namespace}: {e}")

        self._last_poll_time[path_with_namespace] = datetime.utcnow()
        return events

    def _append_pipeline_event(self, events: list[ChangeEvent], pipeline: dict[str, Any], path_with_namespace: str) -> None:
        status = pipeline.get("status", "")
        status_map = {
            "success": ChangeStatus.SUCCEEDED,
            "failed": ChangeStatus.FAILED,
            "canceled": ChangeStatus.CANCELLED,
            "running": ChangeStatus.IN_PROGRESS,
            "pending": ChangeStatus.PENDING,
        }
        change_status = status_map.get(status, ChangeStatus.IN_PROGRESS)
        ref = pipeline.get("ref", "")
        events.append(ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.CI_CD_PIPELINE,
            status=change_status,
            timestamp=datetime.utcnow(),
            service_name=self._extract_service_name(path_with_namespace, ref),
            environment="production",
            description=f"Pipeline {pipeline.get('id')} for {ref}",
            summary=f"Pipeline #{pipeline.get('id')}: {status}",
            git=GitReference(
                repo_url=f"{self.config.base_url.split('/api')[0]}/{path_with_namespace}",
                repo_name=path_with_namespace,
                commit_sha=pipeline.get("sha"),
                branch=ref,
            ),
            pipeline_name=f"gitlab/{path_with_namespace}",
            pipeline_run_id=str(pipeline.get("id")),
            pipeline_url=f"{self.config.base_url.split('/api')[0]}/{path_with_namespace}/-/pipelines/{pipeline.get('id')}",
            labels={
                "gitlab.event": "pipeline",
                "gitlab.project": path_with_namespace,
                "gitlab.pipeline_id": str(pipeline.get("id")),
                "gitlab.status": status,
            },
            correlation_id=str(pipeline.get("id")),
        ))

    def _extract_service_name(self, path: str, data: str) -> str:
        """Extract a service name from the project path."""
        project = path.split("/")[-1].lower()
        for suffix in ["-api", "-service", "-svc", "-app", "-backend", "-frontend", "-server", "-worker"]:
            if project.endswith(suffix):
                project = project[: -len(suffix)]
        return project

    async def poll_all_projects(self) -> list[ChangeEvent]:
        all_events: list[ChangeEvent] = []
        projects = await self.get_projects()
        for project in projects:
            pid = project.get("id")
            path = project.get("path_with_namespace", "")
            if not pid:
                continue
            events = await self.poll_project(pid, path)
            all_events.extend(events)
        return all_events

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/version")
            return resp.status_code == 200
        except Exception:
            return False
