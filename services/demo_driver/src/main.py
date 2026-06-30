"""Live demo driver for ChangeTrace: trigger-based endpoints that keep the
dashboard visibly alive during a client demo and inject real faults into
the running demo services."""

import asyncio
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from gremlin_python.driver import client as gremlin_client, serializer
from gremlin_python.driver.protocol import GremlinServerError
from pydantic import BaseModel, Field

from services.shared.auto_incident import open_incident_for_breach, resolve_open_incidents

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("demo_driver")

SERVICES = {
    "api-gateway":       {"criticality": "high",     "slo": 99.9,  "deps": ["auth-service", "payment-service", "order-service"]},
    "auth-service":      {"criticality": "high",     "slo": 99.95, "deps": []},
    "payment-service":   {"criticality": "critical", "slo": 99.99, "deps": ["api-gateway", "order-service", "fraud-service"]},
    "order-service":     {"criticality": "high",     "slo": 99.9,  "deps": ["payment-service", "inventory-service"]},
    "inventory-service": {"criticality": "medium",   "slo": 99.9,  "deps": []},
    "fraud-service":     {"criticality": "high",     "slo": 99.9,  "deps": ["payment-service"]},
    "notification-service": {"criticality": "medium", "slo": 99.5, "deps": []},
}

DEFAULT_TENANT = os.getenv("DEMO_TENANT_ID", "tenant-e5f171a28217")
CORRELATION_URL = os.getenv("CORRELATION_ENGINE_URL", "http://changetrace-correlation-engine:8003")
DEMO_SVC_PORT = os.getenv("DEMO_SVC_PORT", "8080")
DEMO_SVC_NAMESPACE = os.getenv("DEMO_SVC_NAMESPACE", "store")
AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "changetrace-docker-token")
FAULT_TYPES = ["pod_failure", "network_latency", "cpu_pressure", "memory_pressure", "dns_failure"]

app = FastAPI(title="ChangeTrace Demo Driver", version="1.0.0")

_cosmos_cfg: dict[str, str] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def q(v: str) -> str:
    return v.replace("'", "\\'")


def _cosmos_config() -> dict[str, str]:
    global _cosmos_cfg
    if _cosmos_cfg:
        return _cosmos_cfg
    from services.shared.cosmos import get_cosmos_config_from_env
    _cosmos_cfg = get_cosmos_config_from_env()
    return _cosmos_cfg


def _client() -> gremlin_client.Client:
    cfg = _cosmos_config()
    if not cfg.get("endpoint") or not cfg.get("key"):
        raise HTTPException(status_code=500, detail="Cosmos DB credentials not configured")
    return gremlin_client.Client(
        cfg["endpoint"], "g",
        username=f"/dbs/{cfg['database']}/colls/{cfg['graph']}",
        password=cfg["key"],
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


async def run(query: str, retries: int = 5) -> Any:
    """Execute a Gremlin query in a thread pool; a fresh client per query binds the aiohttp transport to the worker thread's loop."""

    def _run_blocking() -> Any:
        c = _client()
        try:
            for attempt in range(retries):
                try:
                    return c.submit(query).all().result()
                except GremlinServerError as e:
                    if "429" in str(e) or "RequestRateTooLarge" in str(e) or "TooManyRequests" in str(e):
                        wait = min(2 ** attempt * 2, 30)
                        logger.warning("429 from Cosmos, retrying in %ss", wait)
                        time.sleep(wait)
                        continue
                    raise
            raise RuntimeError(f"Query failed after {retries} retries:\n{query[:200]}")
        finally:
            c.close()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_blocking)


def _require_auth(x_internal_auth_token: str | None) -> None:
    if not AUTH_TOKEN:
        return
    if x_internal_auth_token != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _service_or_400(service: str | None) -> str:
    if not service or service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"service must be one of {list(SERVICES.keys())}")
    return service


async def _call_demo_svc(service: str, path: str, method: str = "POST") -> None:
    host = f"{service}.{DEMO_SVC_NAMESPACE}.svc.cluster.local"
    url = f"http://{host}:{DEMO_SVC_PORT}{path}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as ac:
            if method == "POST":
                resp = await ac.post(url)
            else:
                resp = await ac.get(url)
            if resp.status_code >= 400:
                logger.warning("demo svc %s %s -> %s", service, path, resp.status_code)
    except Exception as exc:
        logger.warning("demo svc %s %s failed: %s", service, path, exc)


async def _correlate(incident_id: str, service: str, tenant_id: str, lookback_hours: int = 2) -> list[dict]:
    """Call the correlation engine and return ranked candidates."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as ac:
            resp = await ac.post(
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


async def _degrade_edges(service: str, tenant_id: str,
                         latency_ms: float, error_rate: float) -> int:
    """Set latencyP99/errorRate on depends_on edges touching the service."""
    updated = 0
    for direction in ["out", "in"]:
        query = (
            f"g.V().hasLabel('Service').has('serviceName','{service}').has('tenantId','{tenant_id}')"
            f".{direction}E('depends_on').property('latencyP99',{latency_ms})"
            f".property('errorRate',{error_rate}).property('updatedAt','{_ts(_now())}')"
        )
        try:
            r = await run(query)
            updated += len(r)
        except Exception as exc:
            logger.warning("edge degrade %s failed: %s", direction, exc)
    return updated


async def _restore_edges(service: str, tenant_id: str) -> int:
    """Reset depends_on edge metrics to healthy baselines."""
    updated = 0
    for direction in ["out", "in"]:
        query = (
            f"g.V().hasLabel('Service').has('serviceName','{service}').has('tenantId','{tenant_id}')"
            f".{direction}E('depends_on').property('latencyP99',{random.uniform(20,80):.1f})"
            f".property('errorRate',{random.uniform(0.001,0.02):.4f})"
            f".property('updatedAt','{_ts(_now())}')"
        )
        try:
            r = await run(query)
            updated += len(r)
        except Exception as exc:
            logger.warning("edge restore %s failed: %s", direction, exc)
    return updated


# Request models

class DeployRequest(BaseModel):
    service: str | None = None
    status: str = "succeeded"
    change_type: str = "code_deployment"
    tenant_id: str | None = None


class IncidentRequest(BaseModel):
    service: str | None = None
    fault: str | None = None
    severity: str = "sev2"
    lookback_hours: int = 2
    tenant_id: str | None = None


class IncidentStatusRequest(BaseModel):
    incident_id: str
    status: str = "investigating"
    tenant_id: str | None = None


class SloRequest(BaseModel):
    service: str | None = None
    mode: str = "healthy"  # healthy | burning | critical
    hours: int = 6


class RiskRequest(BaseModel):
    service: str | None = None
    score: float | None = None


class DegradeRequest(BaseModel):
    service: str | None = None
    latency_ms: float = 2000
    error_rate: float = 0.35
    fault_type: str | None = None


class RecoverRequest(BaseModel):
    service: str | None = None


class ScenarioRequest(BaseModel):
    service: str | None = None
    fault: str | None = None
    mode: str = "break"  # break | incident | recover


# Endpoints

@app.post("/api/v1/demo/deploy")
async def deploy(req: DeployRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    tenant_id = req.tenant_id or DEFAULT_TENANT
    now = _now()
    version = f"v{random.randint(2,5)}.{random.randint(0,9)}.{random.randint(0,9)}"
    event_id = str(uuid.uuid4())
    deployment_id = f"dep-acme-{random.randint(100000,999999)}"
    query = (
        f"g.addV('ChangeEvent')"
        f".property('id','{event_id}')"
        f".property('eventId','{event_id}')"
        f".property('tenantId','{tenant_id}')"
        f".property('serviceName','{service}')"
        f".property('changeType','{req.change_type}')"
        f".property('source','github')"
        f".property('status','{req.status}')"
        f".property('environment','production')"
        f".property('author','ci-bot')"
        f".property('description','Deploy {service} {version}')"
        f".property('pipelineName','acme/{service.replace('-','')}-ci')"
        f".property('deploymentId','{deployment_id}')"
        f".property('newVersion','{version}')"
        f".property('previousVersion','v{random.randint(1,4)}.{random.randint(0,9)}.{random.randint(0,9)}')"
        f".property('timestamp','{_ts(now)}')"
        f".property('blastRadiusServices','{json.dumps(SERVICES[service]['deps'])}')"
    )
    await run(query)
    return {"status": "ok", "event_id": event_id, "service": service, "version": version,
            "change_type": req.change_type, "status_field": req.status}


@app.post("/api/v1/demo/incident")
async def incident(req: IncidentRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    tenant_id = req.tenant_id or DEFAULT_TENANT
    fault = req.fault or random.choice(FAULT_TYPES)
    now = _now()
    incident_id = f"INC-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    title = fault.replace("_", " ").title() + " in " + service

    # Optionally inject the matching fault into the running demo service.
    if fault == "network_latency":
        await _call_demo_svc(service, "/fault/latency/2000")
    elif fault in ("pod_failure", "dns_failure"):
        await _call_demo_svc(service, "/fault/fail")

    detected_at = now - timedelta(minutes=random.uniform(0, 5))
    started_at = detected_at - timedelta(minutes=random.uniform(3, 10))
    query = (
        f"g.addV('Incident')"
        f".property('id','{incident_id}')"
        f".property('incidentId','{incident_id}')"
        f".property('tenantId','{tenant_id}')"
        f".property('serviceName','{service}')"
        f".property('title','{q(title)}')"
        f".property('description','SLO breach in {service} due to {fault}')"
        f".property('severity','{req.severity}')"
        f".property('status','investigating')"
        f".property('affectedService','{service}')"
        f".property('affectedNamespace','production')"
        f".property('sloName','availability')"
        f".property('errorBudgetBurnRate',{round(random.uniform(8,60),1)})"
        f".property('detectedAt','{_ts(detected_at)}')"
        f".property('startedAt','{_ts(started_at)}')"
    )
    await run(query)

    # Run correlation against the tenant's REAL ChangeEvents and persist any
    # candidates it returns. No mock synthesis: if the tenant has no matching
    # changes, correlation returns [] and we persist a real (empty) result.
    candidates = await _correlate(incident_id, service, tenant_id, req.lookback_hours)
    top_conf = 0.0
    top_label = ""
    top_svc = service
    for cand in candidates:
        cid = str(uuid.uuid4())
        conf = float(cand.get('confidence_score', 0.5))
        cand_svc = str(cand.get('service_name', service))
        cand_desc = str(cand.get('change_type', 'code_deployment'))
        if conf > top_conf:
            top_conf = conf
            top_label = f"{cand_desc.replace('_', ' ').title()} {cand_svc}"
            top_svc = cand_svc
        await run((
            f"g.V().has('Incident','incidentId','{incident_id}').as('i')"
            f".addV('Candidate')"
            f".property('id','{cid}')"
            f".property('changeEventId','{q(cand.get('change_event_id', cid))}')"
            f".property('tenantId','{tenant_id}')"
            f".property('serviceName','{q(cand_svc)}')"
            f".property('changeType','{q(cand.get('change_type', 'code_deployment'))}')"
            f".property('source','{q(cand.get('source', 'github'))}')"
            f".property('timestamp','{_ts(detected_at - timedelta(minutes=random.uniform(15,90)))}')"
            f".property('confidenceScore',{conf})"
            f".property('evidence','{json.dumps(cand.get('evidence', {}))}')"
            f".addE('has_candidate').from('i')"
            f".property('tenantId','{tenant_id}')"
        ))

    # Promote the top-ranked candidate onto the incident so the detail panel
    # renders root cause / confidence / remediation when real candidates exist.
    # Rollback only makes sense when a real ChangeEvent candidate was found;
    # otherwise the remediation points at the failure mode.
    if top_conf > 0 and top_label:
        remediation = f"rollback_{top_svc}"
    else:
        remediation = "investigate"
    await run((
        f"g.V().has('Incident','incidentId','{incident_id}').has('tenantId','{tenant_id}')"
        f".property('rootCauseCandidate','{q(top_label)}')"
        f".property('topCandidateConfidence',{round(top_conf,4)})"
        f".property('remediationAction','{remediation}')"
        f".property('remediationStatus','pending')"
    ))

    # Degrade the dependency edges so the graph reflects the incident.
    await _degrade_edges(service, tenant_id, random.uniform(800, 2500), random.uniform(0.2, 0.5))
    return {"status": "ok", "incident_id": incident_id, "service": service, "fault": fault,
            "candidates": len(candidates), "top_confidence": round(top_conf, 4)}


@app.post("/api/v1/demo/incident/status")
async def incident_status(req: IncidentStatusRequest, x_internal_auth_token: str | None = Header(default=None)):
    """Advance an incident through the remediation lifecycle, setting resolvedAt / remediationStatus when terminal."""
    _require_auth(x_internal_auth_token)
    tenant_id = req.tenant_id or DEFAULT_TENANT
    allowed = {"open", "investigating", "root_cause_identified", "remediating",
               "verifying", "resolved", "closed"}
    if req.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")

    now = _now()
    resolved_clause = ""
    if req.status in ("resolved", "closed"):
        resolved_clause = (
            f".property('resolvedAt','{_ts(now)}')"
            f".property('remediationStatus','completed')"
            f".property('remediatedAt','{_ts(now)}')"
        )
    elif req.status == "remediating":
        resolved_clause = f".property('remediationStatus','in_progress')"
    elif req.status == "verifying":
        resolved_clause = f".property('remediationStatus','verifying')"

    await run((
        f"g.V().has('Incident','incidentId','{q(req.incident_id)}').has('tenantId','{tenant_id}')"
        f".property('status','{req.status}')"
        f"{resolved_clause}"
    ))
    return {"status": "ok", "incident_id": req.incident_id, "new_status": req.status}


@app.post("/api/v1/demo/slo")
async def slo(req: SloRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    now = _now()
    base_slo = SERVICES[service]["slo"]
    mode_mult = {"healthy": (0, 0.05), "burning": (0.3, 2.0), "critical": (1.0, 6.0)}[req.mode]
    created = 0
    latest_actual = base_slo
    for i in range(req.hours):
        dip = random.uniform(*mode_mult)
        actual = round(max(base_slo - 10, base_slo - dip - random.uniform(0, 0.1)), 2)
        latest_actual = actual
        eb = max(0, round(100 - dip * random.uniform(20, 60), 1))
        br = round(dip / max(0.01, base_slo - actual + 0.01), 2) if dip > 0 else round(random.uniform(0.2, 0.8), 2)
        mid = str(uuid.uuid4())
        point_ts = now - timedelta(hours=req.hours - 1 - i)
        await run((
            f"g.addV('SLOMetric')"
            f".property('id','{mid}')"
            f".property('tenantId','{DEFAULT_TENANT}')"
            f".property('serviceName','{service}')"
            f".property('service','{service}')"
            f".property('sloName','availability')"
            f".property('target',{base_slo})"
            f".property('actual',{actual})"
            f".property('burnRate',{br})"
            f".property('errorBudgetRemaining',{eb})"
            f".property('timestamp','{_ts(point_ts)}')"
        ))
        created += 1
    loop = asyncio.get_running_loop()
    if req.mode in ("burning", "critical"):
        # SLO is degrading -> open an Incident automatically (deduped) and run
        # correlation against the tenant's real ChangeEvents.
        await loop.run_in_executor(
            None, open_incident_for_breach,
            DEFAULT_TENANT, service, "availability", latest_actual, base_slo,
            "slo_degradation", 24,
        )
    elif req.mode == "healthy":
        # Recovery -> close any open incidents for the service automatically.
        await loop.run_in_executor(None, resolve_open_incidents, DEFAULT_TENANT, service)
    return {"status": "ok", "service": service, "mode": req.mode, "points": created}


@app.post("/api/v1/demo/risk")
async def risk(req: RiskRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    now = _now()
    base = 0.7 if SERVICES[service]["criticality"] == "critical" else 0.4
    score = req.score if req.score is not None else round(min(1.0, base + random.uniform(0.1, 0.4)), 2)
    rid = str(uuid.uuid4())
    await run((
        f"g.addV('RiskScore')"
        f".property('id','{rid}')"
        f".property('tenantId','{DEFAULT_TENANT}')"
        f".property('serviceName','{service}')"
        f".property('service','{service}')"
        f".property('riskScore',{score})"
        f".property('timestamp','{_ts(now)}')"
        f".property('deploymentId','deploy-{uuid.uuid4().hex[:8]}')"
        f".property('changeSize',{round(random.uniform(0.1,0.9),2)})"
        f".property('serviceCriticality',{0.4 if SERVICES[service]['criticality'] == 'medium' else 0.7 if SERVICES[service]['criticality'] == 'high' else 1.0})"
        f".property('recentIncidents',{random.randint(0,3)})"
        f".property('dependencyRisk',{round(random.uniform(0.1,0.9),2)})"
    ))
    await run((
        f"g.V().hasLabel('Service').has('serviceName','{service}').has('tenantId','{DEFAULT_TENANT}').fold()"
        f".coalesce(unfold(), addV('Service')"
        f".property('serviceName','{service}').property('tenantId','{DEFAULT_TENANT}'))"
        f".property('currentRiskScore',{score})"
        f".property('criticality','{SERVICES[service]['criticality']}')"
        f".property('sloTarget',{SERVICES[service]['slo']})"
        f".property('namespace','production')"
        f".property('lastScoredAt','{_ts(now)}')"
    ))
    return {"status": "ok", "service": service, "risk_score": score}


@app.post("/api/v1/demo/degrade")
async def degrade(req: DegradeRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    if req.fault_type == "network_latency":
        await _call_demo_svc(service, f"/fault/latency/{int(req.latency_ms)}")
    elif req.fault_type in ("pod_failure", "dns_failure", "failure"):
        await _call_demo_svc(service, "/fault/fail")
    n = await _degrade_edges(service, DEFAULT_TENANT, req.latency_ms, req.error_rate)
    # Real degradation -> open an Incident automatically (deduped) + correlate.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, open_incident_for_breach,
        DEFAULT_TENANT, service, "availability",
        round((1.0 - req.error_rate) * 100, 2), SERVICES[service]["slo"],
        req.fault_type or "degradation", 24,
    )
    return {"status": "ok", "service": service, "edges_degraded": n,
            "latency_ms": req.latency_ms, "error_rate": req.error_rate}


@app.post("/api/v1/demo/recover")
async def recover(req: RecoverRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    services = [req.service] if req.service else list(SERVICES.keys())
    loop = asyncio.get_running_loop()
    for service in services:
        await _call_demo_svc(service, "/fault/reset")
        await _restore_edges(service, DEFAULT_TENANT)
        # Recovery -> close any open incidents for the service automatically.
        await loop.run_in_executor(None, resolve_open_incidents, DEFAULT_TENANT, service)
    return {"status": "ok", "services": services}


@app.post("/api/v1/demo/scenario")
async def scenario(req: ScenarioRequest, x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    service = _service_or_400(req.service)
    if req.mode == "break":
        # Inject a real fault and degrade the graph.
        fault = req.fault or random.choice(["network_latency", "pod_failure"])
        if fault == "network_latency":
            await _call_demo_svc(service, "/fault/latency/2000")
        else:
            await _call_demo_svc(service, "/fault/fail")
        await _degrade_edges(service, DEFAULT_TENANT, 2000, 0.4)
        # Also burn SLO + spike risk so the dashboard reacts immediately.
        await slo(SloRequest(service=service, mode="burning", hours=4), x_internal_auth_token)
        await risk(RiskRequest(service=service), x_internal_auth_token)
        return {"status": "ok", "phase": "break", "service": service, "fault": fault}
    if req.mode == "incident":
        inc = await incident(IncidentRequest(service=service, fault=req.fault),
                             x_internal_auth_token)
        # Also spike risk + SLO burn so the whole dashboard reacts.
        await risk(RiskRequest(service=service), x_internal_auth_token)
        await slo(SloRequest(service=service, mode="burning", hours=4), x_internal_auth_token)
        return {"status": "ok", "phase": "incident", **inc}
    if req.mode == "recover":
        await recover(RecoverRequest(service=service), x_internal_auth_token)
        await slo(SloRequest(service=service, mode="healthy", hours=3), x_internal_auth_token)
        await risk(RiskRequest(service=service, score=round(random.uniform(0.2, 0.4), 2)),
                   x_internal_auth_token)
        return {"status": "ok", "phase": "recover", "service": service}
    raise HTTPException(status_code=400, detail="mode must be break|incident|recover")


@app.get("/api/v1/demo/status")
async def status(x_internal_auth_token: str | None = Header(default=None)):
    _require_auth(x_internal_auth_token)
    counts = {}
    for label in ["ChangeEvent", "Incident", "SLOMetric", "RiskScore", "Candidate", "Service"]:
        try:
            r = await run(f"g.V().hasLabel('{label}').has('tenantId','{DEFAULT_TENANT}').count()")
            counts[label] = r[0] if r else 0
        except Exception:
            counts[label] = -1
    return {"status": "ok", "tenant": DEFAULT_TENANT, "counts": counts}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "demo-driver"}


@app.get("/ready")
async def ready():
    try:
        _cosmos_config()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"not ready: {exc}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DEMO_DRIVER_PORT", "8007")))
