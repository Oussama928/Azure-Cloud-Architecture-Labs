"""Automatic incident creation + correlation on SLO breach."""

import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
from gremlin_python.driver.protocol import GremlinServerError

from services.shared.cosmos import get_cosmos_config_from_env

logger = logging.getLogger(__name__)

CORRELATION_URL = os.getenv("CORRELATION_ENGINE_URL", "http://changetrace-correlation-engine:8003")

OPEN_STATUSES = ("open", "investigating", "root_cause_identified", "remediating", "verifying")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _esc(v: str) -> str:
    return str(v).replace("'", "\\'")


def _gremlin_client() -> gremlin_client.Client:
    cfg = get_cosmos_config_from_env()
    if not cfg.get("endpoint") or not cfg.get("key"):
        raise RuntimeError("Cosmos DB credentials not configured")
    return gremlin_client.Client(
        cfg["endpoint"], "g",
        username=f"/dbs/{cfg['database']}/colls/{cfg['graph']}",
        password=cfg["key"],
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


def _run(query: str, retries: int = 3):
    """Execute a Gremlin query with a fresh client + 429 backoff."""
    c = _gremlin_client()
    try:
        for attempt in range(retries):
            try:
                return c.submit(query).all().result()
            except GremlinServerError as e:
                if "429" in str(e) or "RequestRateTooLarge" in str(e) or "TooManyRequests" in str(e):
                    wait = min(2 ** attempt * 2, 10)
                    logger.warning("429 from Cosmos, retrying in %ss", wait)
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Query failed after {retries} retries:\n{query[:200]}")
    finally:
        c.close()


def _correlate(incident_id: str, service: str, tenant_id: str,
               lookback_hours: int = 24, timeout: float = 10.0) -> list:
    """Call the correlation engine and return ranked candidates (sync)."""
    try:
        with httpx.Client(timeout=timeout) as ac:
            resp = ac.post(
                f"{CORRELATION_URL}/correlate",
                json={
                    "incident_id": incident_id,
                    "affected_service": service,
                    "lookback_hours": lookback_hours,
                    "max_candidates": 10,
                    "min_confidence_threshold": 0.1,
                    "tenant_id": tenant_id,
                },
            )
            if resp.status_code != 200:
                logger.warning("correlation failed: %s %s", resp.status_code, resp.text[:200])
                return []
            return resp.json().get("candidates", [])
    except Exception as exc:
        logger.warning("correlation call error: %s", exc)
        return []


def _has_open_incident(tenant_id: str, service: str) -> bool:
    statuses = ",".join(f"'{s}'" for s in OPEN_STATUSES)
    query = (
        f"g.V().hasLabel('Incident').has('tenantId','{tenant_id}')"
        f".has('affectedService','{service}')"
        f".has('status', within({statuses})).count()"
    )
    try:
        r = _run(query)
        return int(r[0]) > 0 if r else False
    except Exception as exc:
        logger.warning("open-incident check failed: %s", exc)
        return True  # fail safe: don't spam duplicate incidents


def _create_incident(tenant_id: str, service: str, slo_name: str,
                     actual: float, target: float, fault: str | None,
                     severity: str, title: str | None, description: str | None) -> str:
    now = _now()
    incident_id = f"INC-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    if slo_name in ("latency_p99", "latency"):
        fault = fault or "latency_spike"
        title = title or f"Latency P99 Breach in {service}"
        description = description or f"p99 latency {actual}ms exceeds target {target}ms"
        error_budget_total = max(target * 0.1, 1.0)
        burn_rate = max(0.0, actual - target) / error_budget_total
    else:
        fault = fault or "availability_degradation"
        title = title or f"Availability SLO Breach in {service}"
        description = description or f"Availability {actual}% below target {target}%"
        error_budget_total = max(100.0 - target, 0.1)
        burn_rate = max(0.0, target - actual) / error_budget_total

    # Prefer a concrete fault type (pod_failure, dns_failure, cpu_pressure,
    # memory_pressure, network_latency) in the title so the incident names the
    # actual failure mode. Generic markers (slo_degradation / latency_spike)
    # fall back to the SLO-breach title.
    if fault not in ("slo_degradation", "latency_spike", "availability_degradation"):
        fault_label = fault.replace("_", " ").title()
        title = f"{fault_label} in {service}"
        if not description:
            description = f"{fault_label} in {service} (actual {actual} vs target {target})"

    detected_at = now - timedelta(minutes=random.uniform(0, 5))
    started_at = detected_at - timedelta(minutes=random.uniform(3, 10))
    query = (
        f"g.addV('Incident')"
        f".property('id','{incident_id}')"
        f".property('incidentId','{incident_id}')"
        f".property('tenantId','{tenant_id}')"
        f".property('serviceName','{service}')"
        f".property('title','{_esc(title)}')"
        f".property('description','{_esc(description)}')"
        f".property('severity','{severity}')"
        f".property('status','investigating')"
        f".property('affectedService','{service}')"
        f".property('affectedNamespace','production')"
        f".property('sloName','{slo_name}')"
        f".property('errorBudgetBurnRate',{round(min(burn_rate, 100.0), 1)})"
        f".property('detectedAt','{_ts(detected_at)}')"
        f".property('startedAt','{_ts(started_at)}')"
    )
    _run(query)
    return incident_id


def _persist_candidates(incident_id: str, service: str, tenant_id: str,
                        candidates: list, detected_at: datetime) -> tuple:
    top_conf = 0.0
    top_label = ""
    top_svc = service
    for cand in candidates:
        cid = str(uuid.uuid4())
        conf = float(cand.get("confidence_score", 0.5))
        cand_svc = str(cand.get("service_name", service))
        cand_desc = str(cand.get("change_type", "code_deployment"))
        if conf > top_conf:
            top_conf = conf
            top_label = f"{cand_desc.replace('_', ' ').title()} {cand_svc}"
            top_svc = cand_svc
        query = (
            f"g.V().has('Incident','incidentId','{incident_id}').as('i')"
            f".addV('Candidate')"
            f".property('id','{cid}')"
            f".property('changeEventId','{_esc(cand.get('change_event_id', cid))}')"
            f".property('tenantId','{tenant_id}')"
            f".property('serviceName','{_esc(cand_svc)}')"
            f".property('changeType','{_esc(cand.get('change_type', 'code_deployment'))}')"
            f".property('source','{_esc(cand.get('source', 'github'))}')"
            f".property('timestamp','{_ts(detected_at - timedelta(minutes=random.uniform(15, 90)))}')"
            f".property('confidenceScore',{conf})"
            f".property('evidence','{json.dumps(cand.get('evidence', {}))}')"
            f".addE('has_candidate').from('i')"
            f".property('tenantId','{tenant_id}')"
        )
        try:
            _run(query)
        except Exception as exc:
            logger.warning("failed to persist candidate: %s", exc)
    return top_conf, top_label, top_svc


def _promote_top(incident_id: str, tenant_id: str, top_conf: float,
                 top_label: str, top_svc: str, slo_name: str) -> None:
    # Rollback only makes sense when a real ChangeEvent candidate was found
    # (a deployment is the thing you'd roll back). Otherwise the remediation
    # points at the actual failure mode instead of a misleading rollback.
    if top_conf > 0 and top_label:
        remediation = f"rollback_{top_svc}"
    elif slo_name in ("latency_p99", "latency"):
        remediation = "investigate_latency_spike"
    else:
        remediation = "investigate_availability"
    try:
        _run((
            f"g.V().has('Incident','incidentId','{incident_id}').has('tenantId','{tenant_id}')"
            f".property('rootCauseCandidate','{_esc(top_label)}')"
            f".property('topCandidateConfidence',{round(top_conf, 4)})"
            f".property('remediationAction','{remediation}')"
            f".property('remediationStatus','pending')"
        ))
    except Exception as exc:
        logger.warning("failed to promote candidate: %s", exc)


def open_incident(tenant_id: str, service: str, slo_name: str = "availability",
                  actual: float = 0.0, target: float = 99.9, fault: str | None = None,
                  severity: str = "sev2", title: str | None = None,
                  description: str | None = None, lookback_hours: int = 24,
                  correlation_timeout: float = 10.0) -> str | None:
    """Open an Incident (deduped against open incidents) and run correlation."""
    if _has_open_incident(tenant_id, service):
        logger.info("auto-incident: %s already has an open incident; skipping", service)
        return None
    incident_id = _create_incident(tenant_id, service, slo_name, actual, target,
                                   fault, severity, title, description)
    candidates = _correlate(incident_id, service, tenant_id, lookback_hours,
                            correlation_timeout)
    top_conf, top_label, top_svc = _persist_candidates(
        incident_id, service, tenant_id, candidates, _now())
    _promote_top(incident_id, tenant_id, top_conf, top_label, top_svc, slo_name)
    logger.info("auto-incident: opened %s for %s (%d candidates, top %.2f)",
                incident_id, service, len(candidates), top_conf)
    return incident_id


def open_incident_for_breach(tenant_id: str, service: str, slo_name: str,
                             actual: float, target: float, fault: str | None = None,
                             lookback_hours: int = 24,
                             correlation_timeout: float = 10.0) -> str | None:
    """Open an incident only when the SLO is actually breached."""
    if slo_name in ("latency_p99", "latency"):
        if actual <= target:
            return None
    elif slo_name == "availability":
        if actual >= target:
            return None
    else:
        return None
    return open_incident(tenant_id, service, slo_name=slo_name, actual=actual,
                         target=target, fault=fault, lookback_hours=lookback_hours,
                         correlation_timeout=correlation_timeout)


def resolve_open_incidents(tenant_id: str, service: str) -> int:
    """Mark open incidents for a service as resolved (auto-heal lifecycle)."""
    statuses = ",".join(f"'{s}'" for s in OPEN_STATUSES)
    now = _ts(_now())
    count_query = (
        f"g.V().hasLabel('Incident').has('tenantId','{tenant_id}')"
        f".has('affectedService','{service}')"
        f".has('status', within({statuses})).count()"
    )
    try:
        r = _run(count_query)
        n = int(r[0]) if r else 0
        if n == 0:
            return 0
        update_query = (
            f"g.V().hasLabel('Incident').has('tenantId','{tenant_id}')"
            f".has('affectedService','{service}')"
            f".has('status', within({statuses}))"
            f".property('status','resolved')"
            f".property('resolvedAt','{now}')"
            f".property('remediationStatus','completed')"
            f".property('remediatedAt','{now}')"
        )
        _run(update_query)
        return n
    except Exception as exc:
        logger.warning("failed to resolve incidents for %s: %s", service, exc)
        return 0


def maybe_resolve_recovered(tenant_id: str, service: str,
                            grace_seconds: int = 120) -> int:
    """Auto-resolve a service's open incidents once it has stayed healthy."""
    statuses = ",".join(f"'{s}'" for s in OPEN_STATUSES)
    query = (
        f"g.V().hasLabel('Incident').has('tenantId','{tenant_id}')"
        f".has('affectedService','{service}')"
        f".has('status', within({statuses}))"
        ".order().by('detectedAt', decr).limit(1).values('detectedAt')"
    )
    try:
        r = _run(query)
        if not r:
            return 0
        detected = datetime.fromisoformat(str(r[0]).replace("Z", "+00:00"))
        if (_now() - detected).total_seconds() < grace_seconds:
            return 0
        return resolve_open_incidents(tenant_id, service)
    except Exception as exc:
        logger.warning("failed to auto-resolve for %s: %s", service, exc)
        return 0
