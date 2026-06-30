# Payment service for the ChangeTrace store demo.
#
# A real FastAPI microservice: charges/captures payments and persists them to
# Azure PostgreSQL. Emits OpenTelemetry spans (service.name + peer.service) so
# the ChangeTrace graph builder can discover the topology from real traces.
# Exposes fault-injection endpoints so the demo can break it later.
#
# Endpoints:
#   GET  /health              liveness
#   GET  /ready               readiness
#   POST /payments            create a payment for an order (captures it)
#   GET  /payments            list payments
#   GET  /payments/{id}       payment detail
#   POST /fault/latency/{ms}  inject latency
#   POST /fault/fail          inject hard failures
#   POST /fault/reset         clear faults
#   GET  /fault               current fault state

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode, SpanKind

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-service")

SERVICE_NAME = os.getenv("SERVICE_NAME", "payment-service")
PORT = int(os.getenv("PORT", "8080"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/store")
OTEL_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://otel-collector.changetrace.svc.cluster.local:4318",
).rstrip("/")
# Tenant attribution: the receiving graph-builder attributes these traces to
# this tenant. Prefer CHANGETRACE_API_KEY (client-facing, replicable method):
# the key is resolved to the tenant via TenantKey lookup, same as webhooks. The
# CHANGETRACE_TENANT_ID header remains a backward-compatible fallback.
CHANGETRACE_API_KEY = os.getenv("CHANGETRACE_API_KEY", "")
CHANGETRACE_TENANT_ID = os.getenv("CHANGETRACE_TENANT_ID", "tenant-e5f171a28217")
BASE_LATENCY_MS = float(os.getenv("BASE_LATENCY_MS", "15"))

_otlp_headers = {"changetrace-tenant-id": CHANGETRACE_TENANT_ID}
if CHANGETRACE_API_KEY:
    _otlp_headers["Authorization"] = f"Bearer {CHANGETRACE_API_KEY}"

provider = TracerProvider(
    resource=Resource.create({"service.name": SERVICE_NAME}),
)
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=f"{OTEL_ENDPOINT}/v1/traces",
            headers=_otlp_headers,
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE_NAME)

_pool: asyncpg.Pool | None = None
_extra_latency_ms = 0.0
_failing = False
_fault_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def ensure_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id           UUID PRIMARY KEY,
            order_id     UUID NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            amount_cents BIGINT NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await get_pool()
    await ensure_schema(await get_pool())
    yield


app = FastAPI(title=SERVICE_NAME, version="1.1.0", lifespan=lifespan)


async def _fault_state():
    async with _fault_lock:
        return _failing, _extra_latency_ms


async def _apply_faults(span):
    failing, latency_ms = await _fault_state()
    if failing:
        span.set_attribute("demo.fault", "failure")
        span.set_status(Status(StatusCode.ERROR, "injected failure"))
        return True
    if latency_ms > 0:
        await asyncio.sleep(latency_ms / 1000.0)
        span.set_attribute("demo.latency_ms", latency_ms)
    return False


@app.get("/health")
async def health():
    return {"status": "healthy", "service": SERVICE_NAME}


@app.get("/ready")
async def ready():
    pool = await get_pool()
    await pool.fetchval("SELECT 1")
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/payments")
async def create_payment(request: Request, payload: dict):
    order_id = payload.get("order_id")
    amount_cents = int(payload.get("amount_cents", 0))
    if not order_id:
        return JSONResponse({"error": "order_id is required"}, status_code=400)
    parent = extract(dict(request.headers))
    with tracer.start_as_current_span(f"{SERVICE_NAME}/create_payment", kind=SpanKind.SERVER, context=parent) as span:
        if await _apply_faults(span):
            return JSONResponse({"error": "injected failure", "service": SERVICE_NAME}, status_code=503)
        payment_id = str(uuid.uuid4())
        pool = await get_pool()
        await pool.execute(
            "INSERT INTO payments (id, order_id, status, amount_cents) VALUES ($1, $2, 'captured', $3)",
            payment_id, str(order_id), amount_cents,
        )
        span.set_attribute("payment.id", payment_id)
        span.set_attribute("payment.amount_cents", amount_cents)
        return {"id": payment_id, "order_id": str(order_id), "status": "captured", "amount_cents": amount_cents}


@app.get("/payments")
async def list_payments(limit: int = 50):
    with tracer.start_as_current_span(f"{SERVICE_NAME}/list_payments"):
        pool = await get_pool()
        rows = await pool.fetch("SELECT id, order_id, status, amount_cents, created_at FROM payments ORDER BY created_at DESC LIMIT $1", limit)
        return {"payments": [dict(r) for r in rows]}


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    with tracer.start_as_current_span(f"{SERVICE_NAME}/get_payment"):
        pool = await get_pool()
        row = await pool.fetchrow("SELECT id, order_id, status, amount_cents, created_at FROM payments WHERE id = $1", payment_id)
        if not row:
            return JSONResponse({"error": "payment not found"}, status_code=404)
        return dict(row)


@app.post("/fault/latency/{ms}")
async def fault_latency(ms: float):
    global _extra_latency_ms
    async with _fault_lock:
        _extra_latency_ms = max(0.0, float(ms))
    logger.warning("%s: injected latency +%sms", SERVICE_NAME, ms)
    return {"service": SERVICE_NAME, "extra_latency_ms": _extra_latency_ms}


@app.post("/fault/fail")
async def fault_fail():
    global _failing
    async with _fault_lock:
        _failing = True
    logger.warning("%s: injected failure mode", SERVICE_NAME)
    return {"service": SERVICE_NAME, "failing": True}


@app.post("/fault/reset")
async def fault_reset():
    global _failing, _extra_latency_ms
    async with _fault_lock:
        _failing = False
        _extra_latency_ms = 0.0
    logger.warning("%s: faults cleared", SERVICE_NAME)
    return {"service": SERVICE_NAME, "failing": False, "extra_latency_ms": 0.0}


@app.get("/fault")
async def fault_state():
    failing, latency_ms = await _fault_state()
    return {"service": SERVICE_NAME, "failing": failing, "extra_latency_ms": latency_ms}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
