"""Real-time OpenTelemetry span ingestion for Graph Builder."""

import asyncio
import hashlib
import logging
import os
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
from gremlin_python.process.graph_traversal import __

from services.shared.auto_incident import (
    maybe_resolve_recovered,
    open_incident_for_breach,
)
from services.shared.cosmos import get_cosmos_config_from_env

logger = logging.getLogger(__name__)

_thread_local = threading.local()
_executor: Optional[ThreadPoolExecutor] = None

_TENANT_ID = os.getenv("OTEL_RECEIVER_TENANT_ID", "demo-tenant")


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4)
    return _executor


def _hash_api_key(api_key: str) -> str:
    """Hash an API key the same way dashboard_api stores it (sha256 hex)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _resolve_tenant_from_api_key(api_key: str) -> str:
    """Resolve a tenant API key to its tenant id (matches TenantKey vertices).

    Uses the same sha256 apiKeyHash lookup the collector uses for webhooks, so
    a client's `Authorization: Bearer <api_key>` works identically for trace
    ingestion as it does for change-event ingestion.

    This runs inside an executor worker thread, so it calls _run_gremlin_query
    directly (no asyncio loop available in that thread).
    """
    key_hash = _hash_api_key(api_key)
    query = f"g.V().hasLabel('TenantKey').has('apiKeyHash', '{key_hash}').values('tenantId')"
    try:
        result = _run_gremlin_query(query)
        if isinstance(result, list) and result:
            return str(result[0])
        if result:
            return str(result)
        # Backward-compatible migration lookup for keys created by older builds.
        legacy = f"g.V().hasLabel('TenantKey').has('apiKey', '{api_key}').values('tenantId')"
        result = _run_gremlin_query(legacy)
        if isinstance(result, list) and result:
            return str(result[0])
        if result:
            return str(result)
    except Exception as e:
        logger.error(f"API key tenant lookup failed: {e}")
    return ""


def _connect_client():
    """Create and return a new Gremlin client (used within thread executor)."""
    config = get_cosmos_config_from_env()
    if not config["endpoint"] or not config["key"]:
        raise ValueError("Cosmos DB credentials not configured")
    parsed = urllib.parse.urlparse(config["endpoint"])
    host = parsed.netloc
    return gremlin_client.Client(
        f"wss://{host}/gremlin",
        "g",
        username=f"/dbs/{config['database']}/colls/{config['graph']}",
        password=config["key"],
        message_serializer=serializer.GraphSONSerializersV2d0()
    )


def _run_gremlin_query(query: str) -> list:
    """Run a Gremlin query in a thread and return all results."""
    if not hasattr(_thread_local, "client") or _thread_local.client is None:
        _thread_local.client = _connect_client()
    rs = _thread_local.client.submit(query)
    return rs.all().result()


def _decode_value(value) -> str:
    """Convert an OTLP AnyValue protobuf to a plain string."""
    if value is None:
        return ""
    field = value.WhichOneof("value")
    if field == "string_value":
        return value.string_value
    if field == "bool_value":
        return "true" if value.bool_value else "false"
    if field == "int_value":
        return str(value.int_value)
    if field == "double_value":
        return str(value.double_value)
    if field == "array_value":
        return ",".join(_decode_value(v) for v in value.array_value.values)
    if field == "kvlist_value":
        return ",".join(f"{kv.key}={_decode_value(kv.value)}" for kv in value.kvlist_value.values)
    return ""


def _attr_map(attributes) -> Dict[str, str]:
    """Flatten protobuf repeated KeyValue attributes into a dict."""
    result: Dict[str, str] = {}
    for attr in attributes:
        key = attr.key
        value = _decode_value(attr.value)
        if key and value:
            result[key] = value
    return result


def _span_duration_ms(span) -> Optional[float]:
    """Compute span duration in ms from start/end nanos, or None if unavailable."""
    if not span.start_time_unix_nano or not span.end_time_unix_nano:
        return None
    try:
        return (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000.0
    except Exception:
        return None


def _span_is_error(span) -> bool:
    """Determine whether a span represents a failed request.

    OTLP span.status.code: 0=unset, 1=ok, 2=error.
    Also honors the http.status_code attribute as a secondary signal.
    """
    try:
        code = span.status.code
        if code == 2:
            return True
        if code == 1:
            return False
    except Exception:
        pass
    attrs = _attr_map(span.attributes)
    try:
        http = int(attrs.get("http.status_code", 0))
        if http >= 400:
            return True
        if 200 <= http < 400:
            return False
    except (ValueError, TypeError):
        pass
    return False


def _compute_service_slos(payload) -> Dict[str, Dict[str, Any]]:
    """Compute REAL per-service SLO metrics from the spans in this payload.

    For each resource's service.name, collect span durations + success/error,
    then derive:
      - latency_p99 (ms) from the actual span durations
      - error_rate   = errors / total
      - availability = 1 - error_rate
      - sample count
    Returns {service_name: {latency_p99, error_rate, availability, count}}.
    """
    services: Dict[str, Dict[str, Any]] = {}
    for resource_spans in payload.resource_spans:
        attrs = _attr_map(resource_spans.resource.attributes)
        source = attrs.get("service.name", "")
        if not source:
            continue
        durations: List[float] = []
        errors = 0
        total = 0
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                total += 1
                if _span_is_error(span):
                    errors += 1
                d = _span_duration_ms(span)
                if d is not None:
                    durations.append(d)
        if total == 0:
            continue
        # p99 of real durations (default to a sane value if none recorded).
        latency_p99 = 0.0
        if durations:
            durations_sorted = sorted(durations)
            idx = min(len(durations_sorted) - 1, int(0.99 * len(durations_sorted)))
            latency_p99 = round(durations_sorted[idx], 2)
        error_rate = round(errors / total, 6)
        availability = round(1 - error_rate, 6)
        services[source] = {
            "latency_p99": latency_p99,
            "error_rate": error_rate,
            "availability": availability,
            "count": total,
        }
    return services


def _extract_edges(payload, tenant_id: str) -> List[Dict[str, Any]]:
    """Extract source -> target edges from an ExportTraceServiceRequest.

    source = resource attribute service.name
    target = span attribute peer.service (only spans that make an outbound call)
    tenant_id = per-request tenant (from header or resource attribute), so each
    account's traces land in their own graph instead of a global hardcoded tenant.
    """
    edges: List[Dict[str, Any]] = []
    for resource_spans in payload.resource_spans:
        resource_attrs = _attr_map(resource_spans.resource.attributes)
        source = resource_attrs.get("service.name", "")
        if not source:
            continue

        # Resource attribute can carry the tenant too (e.g. changetrace.tenant.id).
        attr_tenant = resource_attrs.get("changetrace.tenant.id", "") or resource_attrs.get(
            "changetrace.tenant_id", ""
        )
        span_tenant = tenant_id or attr_tenant or _TENANT_ID

        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                span_attrs = _attr_map(span.attributes)
                target = span_attrs.get("peer.service", "")
                if not target:
                    continue
                edges.append({
                    "source": source,
                    "target": target,
                    "tenant_id": span_tenant,
                    "timestamp": datetime.utcnow().isoformat(),
                })
    return edges


async def _upsert_edge(edge: Dict[str, Any], count: int) -> None:
    """Upsert a Service vertex pair + depends_on edge into Cosmos."""
    tenant_id = edge["tenant_id"]
    source = edge["source"]
    target = edge["target"]
    now = datetime.utcnow().isoformat()
    loop = asyncio.get_running_loop()
    executor = _get_executor()

    for service in (source, target):
        query = f"""
        g.V().hasLabel('Service').has('serviceName', '{service}').has('tenantId', '{tenant_id}').fold().
        coalesce(unfold(), addV('Service').
            property('serviceName', '{service}').
            property('tenantId', '{tenant_id}')).
        property('updatedAt', '{now}').
        coalesce(properties('criticality'), property('criticality', 'medium')).
        coalesce(properties('namespace'), property('namespace', 'production'))
        """
        try:
            await loop.run_in_executor(executor, _run_gremlin_query, query)
        except Exception as e:
            logger.error(f"Failed to upsert vertex {service}: {e}")

    # 1) Create the edge only if it does not already exist, applying
    #    properties inside the addE branch (Cosmos rejects
    #    coalesce(...).property(...) on a produced edge).
    create_query = f"""
    g.V().hasLabel('Service').has('serviceName', '{source}').has('tenantId', '{tenant_id}').as('s').
    V().hasLabel('Service').has('serviceName', '{target}').has('tenantId', '{tenant_id}').as('t').
    coalesce(
        __.inE('depends_on').where(__.outV().as('s')),
        __.addE('depends_on').from('s').to('t').
            property('tenantId', '{tenant_id}').
            property('callCount', {count}).
            property('latencyP99', 0).
            property('updatedAt', '{now}')
    )
    """
    try:
        await loop.run_in_executor(executor, _run_gremlin_query, create_query)
    except Exception as e:
        logger.error(f"Failed to upsert edge {source}->{target}: {e} | query={create_query}")
        return

    # 2) Update properties on the (now existing) edge.
    update_query = f"""
    g.V().hasLabel('Service').has('serviceName', '{source}').has('tenantId', '{tenant_id}').
    outE('depends_on').
    where(otherV().hasLabel('Service').has('serviceName', '{target}').has('tenantId', '{tenant_id}')).
    property('callCount', {count}).
    property('latencyP99', 0).
    property('updatedAt', '{now}')
    """
    try:
        await loop.run_in_executor(executor, _run_gremlin_query, update_query)
    except Exception as e:
        logger.error(f"Failed to update edge {source}->{target}: {e} | query={update_query}")


def _upsert_slo_metric(service: str, tenant_id: str, metrics: Dict[str, Any]) -> None:
    """Persist a SLOMetric vertex computed from REAL observed spans.

    Writes an availability + latency_p99 SLOMetric record keyed by tenant so the
    dashboard's SLO / burn-rate views reflect actual app behavior, not mocks.

    Values follow the dashboard's existing convention: availability/error budget
    are stored as PERCENTAGES (e.g. 99.9 = 99.9%), matching the demo driver.
    """
    if not tenant_id:
        return
    now = datetime.utcnow().isoformat()
    latency_p99 = metrics.get("latency_p99", 0.0)
    error_rate = metrics.get("error_rate", 0.0)
    availability_pct = round(metrics.get("availability", 1.0) * 100, 2)
    count = metrics.get("count", 1)
    # Error budget: availability SLO target of 99.9% (percentage convention).
    target_pct = 99.9
    error_budget_total = 100.0 - target_pct
    error_budget_consumed = max(0.0, target_pct - availability_pct)
    error_budget_remaining = max(0.0, error_budget_total - error_budget_consumed)
    burn_rate = error_budget_consumed / error_budget_total if error_budget_total > 0 else 0.0

    for slo_name, actual, tgt in (
        ("availability", availability_pct, target_pct),
        ("latency_p99", latency_p99, None),
    ):
        query = (
            f"g.addV('SLOMetric')"
            f".property('id','{service}-{slo_name}-{now}')"
            f".property('tenantId','{tenant_id}')"
            f".property('serviceName','{service}')"
            f".property('service','{service}')"
            f".property('sloName','{slo_name}')"
            f".property('target',{tgt if tgt is not None else 500.0})"
            f".property('actual',{actual})"
            f".property('burnRate',{round(burn_rate,4)})"
            f".property('errorBudgetRemaining',{round(error_budget_remaining,2)})"
            f".property('count',{count})"
            f".property('timestamp','{now}')"
        )
        try:
            _run_gremlin_query(query)
        except Exception as e:
            logger.error(f"Failed to upsert SLOMetric {service}/{slo_name}: {e}")

    # Automatic incident detection: a REAL SLO breach (availability below the
    # 99.9% target, or p99 latency above its target) opens an Incident and runs
    # correlation against this tenant's real ChangeEvents — no explicit step.
    # Deduped per service, so one open incident per degradation episode.
    try:
        open_incident_for_breach(
            tenant_id, service, "availability",
            availability_pct, target_pct,
            fault="slo_degradation", lookback_hours=24,
        )
        open_incident_for_breach(
            tenant_id, service, "latency_p99",
            latency_p99, 500.0,
            fault="latency_spike", lookback_hours=24,
        )
        # Healthy observation -> auto-resolve incidents whose episode has ended
        # (sustained recovery), so the incident lifecycle is fully automatic.
        if availability_pct >= target_pct and latency_p99 <= 500.0:
            maybe_resolve_recovered(tenant_id, service)
    except Exception as e:
        logger.error(f"Auto-incident check failed for {service}/{tenant_id}: {e}")


async def ingest_otlp_payload(
    body: bytes,
    content_type: str,
    content_encoding: str = "",
    tenant_id: str | None = None,
    api_key: str | None = None,
) -> Dict[str, Any]:
    """Parse an OTLP traces payload and upsert real spans into the graph.

    Tenant attribution, in priority order:
      1. api_key  -> resolved to a tenant via TenantKey lookup (client-facing,
                     replicable method, same as webhook auth).
      2. tenant_id -> a per-request tenant id (from header / resource attr).
      3. global OTEL_RECEIVER_TENANT_ID env fallback.
    """
    if api_key:
        resolved = await asyncio.get_running_loop().run_in_executor(
            _get_executor(), _resolve_tenant_from_api_key, api_key
        )
        if resolved:
            tenant_id = resolved

    try:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError:
        raise RuntimeError("opentelemetry-proto is not installed")

    if content_encoding and "gzip" in content_encoding.lower():
        import gzip
        body = gzip.decompress(body)

    payload = ExportTraceServiceRequest()
    payload.ParseFromString(body)

    edges = _extract_edges(payload, tenant_id=tenant_id or "")
    if not edges:
        # Still persist SLO metrics even if no peer.service edges were found
        # (a service may emit its own spans without an outbound call).
        if tenant_id:
            await _persist_slos(payload, tenant_id)
        return {"spans_processed": 0, "edges_processed": 0, "edges": []}

    # Aggregate per batch so callCount reflects real spans seen in this batch.
    counts: Dict[str, int] = {}
    for edge in edges:
        key = f"{edge['source']}|{edge['target']}|{edge['tenant_id']}"
        counts[key] = counts.get(key, 0) + 1

    for edge in edges:
        key = f"{edge['source']}|{edge['target']}|{edge['tenant_id']}"
        await _upsert_edge(edge, counts[key])

    await _persist_slos(payload, tenant_id or "")

    return {
        "spans_processed": len(edges),
        "edges_processed": len(counts),
        "edges": [{"source": e["source"], "target": e["target"]} for e in edges],
    }


async def _persist_slos(payload, tenant_id: str) -> None:
    """Compute and persist SLOMetric vertices from real spans for a tenant."""
    if not tenant_id:
        return
    loop = asyncio.get_running_loop()
    executor = _get_executor()
    services = _compute_service_slos(payload)
    for service, metrics in services.items():
        try:
            await loop.run_in_executor(
                executor, _upsert_slo_metric, service, tenant_id, metrics
            )
        except Exception as e:
            logger.error(f"Failed to persist SLO for {service}/{tenant_id}: {e}")
