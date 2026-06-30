"""Tests for the generic per-tenant URL source collector."""

import json
from datetime import datetime

import httpx
import pytest

from services.collector.src.models.change_event import (
    ChangeSource,
    ChangeStatus,
    ChangeType,
)
from services.collector.src.sources.url_source import (
    UrlSource,
    UrlSourceConfig,
)


@pytest.fixture
def url_source():
    config = UrlSourceConfig(
        tenant_id="tenant-alpha",
        urls={
            "github": "https://example.com/changes/github",
            "terraform": "https://example.com/changes/terraform",
        },
        poll_interval_seconds=60,
    )
    return UrlSource(config)


@pytest.mark.asyncio
async def test_poll_url_parses_event_list(url_source: UrlSource):
    payload = [
        {
            "serviceName": "checkout-service",
            "changeType": "code_deployment",
            "status": "succeeded",
            "timestamp": "2026-07-31T10:00:00Z",
            "pipeline_name": "checkout/ci",
            "deployment_id": "dep-123",
        },
        {
            "service_name": "legacy-api",
            "change_type": "infrastructure_change",
            "author": "alice",
        },
    ]
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(200, json=payload)
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_url("github", "https://example.com/changes/github")

    assert len(events) == 2
    first = events[0]
    assert first.service_name == "checkout-service"
    assert first.change_type == ChangeType.CODE_DEPLOYMENT
    assert first.status == ChangeStatus.SUCCEEDED
    assert first.source == ChangeSource.GITHUB
    assert first.tenant_id == "tenant-alpha"
    assert first.timestamp.year == 2026

    second = events[1]
    assert second.source == ChangeSource.GITHUB
    assert second.author == "alice"


@pytest.mark.asyncio
async def test_poll_url_accepts_wrapped_events(url_source: UrlSource):
    payload = {"events": [{"serviceName": "auth-service"}]}
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(200, json=payload)
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_url("argocd", "https://example.com/argo")

    assert len(events) == 1
    assert events[0].service_name == "auth-service"
    assert events[0].source == ChangeSource.ARGO_ROLLOUTS
    assert events[0].tenant_id == "tenant-alpha"


@pytest.mark.asyncio
async def test_poll_url_skips_missing_service_name(url_source: UrlSource):
    payload = [{"changeType": "code_deployment"}]
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(200, json=payload)
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_url("github", "https://example.com/x")

    assert events == []


@pytest.mark.asyncio
async def test_poll_url_handles_http_error(url_source: UrlSource):
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(500, json={})
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_url("github", "https://example.com/error")

    assert events == []


@pytest.mark.asyncio
async def test_poll_all_fetches_every_url(url_source: UrlSource):
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(
            200,
            json=[{"serviceName": request.url.path.strip("/")}],
        )
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_all()

    assert len(events) == 2
    services = {e.service_name for e in events}
    assert services == {"changes/github", "changes/terraform"}


@pytest.mark.asyncio
async def test_poll_url_preserves_blast_radius(url_source: UrlSource):
    payload = [
        {
            "serviceName": "checkout-service",
            "changeType": "code_deployment",
            "blastRadiusServices": ["order-service", "api-gateway"],
        }
    ]
    async with httpx.MockTransport(
        handler=lambda request: httpx.Response(200, json=payload)
    ) as transport:
        url_source._client = httpx.AsyncClient(transport=transport)
        events = await url_source.poll_url("github", "https://example.com/changes/github")

    assert len(events) == 1
    assert events[0].blast_radius_services == ["order-service", "api-gateway"]


def test_source_key_mapping_unknown():
    config = UrlSourceConfig(
        tenant_id="t",
        urls={"custom_tool": "https://example.com/x"},
    )
    source = UrlSource(config)
    assert source._resolve_source("custom_tool") == ChangeSource.CI_CD_PIPELINE
