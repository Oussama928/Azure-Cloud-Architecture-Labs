"""
Generic URL Source Collector for ChangeTrace.

Polls arbitrary per-tenant source URLs (configured via the dashboard Settings)
and normalizes JSON responses into ChangeEvents.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
)

logger = logging.getLogger(__name__)

# Map dashboard source-url keys to ChangeSource enum values
_SOURCE_KEY_TO_ENUM = {
    "github": ChangeSource.GITHUB,
    "terraform": ChangeSource.TERRAFORM,
    "kubernetes": ChangeSource.KUBERNETES,
    "azure_resource_graph": ChangeSource.AZURE_RESOURCE_GRAPH,
    "argocd": ChangeSource.ARGO_ROLLOUTS,
    "jenkins": ChangeSource.CI_CD_PIPELINE,
    "gitlab": ChangeSource.CI_CD_PIPELINE,
}


class UrlSourceConfig(BaseModel):
    """Configuration for the generic URL source"""
    tenant_id: str
    urls: dict[str, str] = Field(default_factory=dict)  # source_key -> url
    poll_interval_seconds: int = 300
    timeout_seconds: float = 30.0
    headers: dict[str, str] = Field(default_factory=dict)


class UrlSource:
    """Generic per-tenant URL change-event collector."""

    def __init__(self, config: UrlSourceConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            headers={
                "Accept": "application/json",
                "User-Agent": "changetrace-collector/1.0",
                **config.headers,
            },
            timeout=config.timeout_seconds,
        )
        self._last_poll_time: datetime | None = None

    async def initialize(self) -> None:
        logger.info(
            f"Initialized URL source for tenant {self.config.tenant_id} "
            f"with {len(self.config.urls)} endpoints"
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _resolve_source(self, source_key: str) -> ChangeSource:
        return _SOURCE_KEY_TO_ENUM.get(source_key.lower(), ChangeSource.CI_CD_PIPELINE)

    async def poll_url(self, source_key: str, url: str) -> list[ChangeEvent]:
        """Poll a single URL and parse the response into ChangeEvents."""
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.warning(
                f"Failed to poll {source_key} for tenant {self.config.tenant_id}: {e}"
            )
            return []

        if isinstance(payload, dict) and "events" in payload:
            raw_events = payload["events"]
        elif isinstance(payload, list):
            raw_events = payload
        else:
            logger.warning(
                f"Unrecognized payload shape from {source_key} for tenant "
                f"{self.config.tenant_id}"
            )
            return []

        events: list[ChangeEvent] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            try:
                event = self._normalize_event(raw, source_key)
            except Exception as e:
                logger.warning(
                    f"Skipping malformed event from {source_key}: {e}"
                )
                continue
            if event:
                events.append(event)

        return events

    def _normalize_event(self, raw: dict[str, Any], source_key: str) -> ChangeEvent | None:
        """Build a ChangeEvent from a raw dict, tolerating partial payloads."""
        from ..models.change_event import ChangeStatus, ChangeType

        service_name = (
            raw.get("serviceName")
            or raw.get("service_name")
            or raw.get("service")
        )
        if not service_name:
            return None

        change_type_raw = (
            raw.get("changeType")
            or raw.get("change_type")
            or "infrastructure_change"
        )
        try:
            change_type = ChangeType(change_type_raw)
        except ValueError:
            change_type = ChangeType.INFRASTRUCTURE_CHANGE

        status_raw = raw.get("status", "succeeded")
        try:
            status = ChangeStatus(status_raw)
        except ValueError:
            status = ChangeStatus.SUCCEEDED

        timestamp_raw = raw.get("timestamp")
        timestamp = (
            datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
            if timestamp_raw
            else datetime.utcnow()
        )

        return ChangeEvent(
            change_type=change_type,
            source=self._resolve_source(source_key),
            status=status,
            timestamp=timestamp,
            service_name=service_name,
            environment=raw.get("environment", "production"),
            author=raw.get("author"),
            description=raw.get("description"),
            summary=raw.get("summary"),
            pipeline_name=raw.get("pipelineName") or raw.get("pipeline_name"),
            pipeline_run_id=raw.get("pipelineRunId") or raw.get("pipeline_run_id"),
            pipeline_url=raw.get("pipelineUrl") or raw.get("pipeline_url"),
            deployment_id=raw.get("deploymentId") or raw.get("deployment_id"),
            previous_version=raw.get("previousVersion") or raw.get("previous_version"),
            new_version=raw.get("newVersion") or raw.get("new_version"),
            blast_radius_services=(
                raw.get("blastRadiusServices")
                or raw.get("blast_radius_services")
                or raw.get("affectedServices")
                or raw.get("relatedServices")
                or []
            ),
            tenant_id=self.config.tenant_id,
        )

    async def poll_all(self) -> list[ChangeEvent]:
        """Poll all configured URLs for this tenant."""
        all_events: list[ChangeEvent] = []
        for source_key, url in self.config.urls.items():
            if not url:
                continue
            all_events.extend(await self.poll_url(source_key, url))

        self._last_poll_time = datetime.utcnow()
        return all_events

    async def health_check(self) -> bool:
        """Lightweight health check - report healthy if client is usable."""
        return True
