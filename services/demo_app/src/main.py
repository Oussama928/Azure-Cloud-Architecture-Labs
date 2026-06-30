"""Parameterized demo microservice for the ChangeTrace demo application:
a single container image per "app" service that emits OTel spans, calls
downstream dependencies, and exposes fault-injection endpoints."""

import asyncio
import json
import logging
import os
import time
from typing import List

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.propagate import inject
try:
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
except ImportError:  # older opentelemetry-api (<1.30)
    from opentelemetry.propagators.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace import SpanKind, Status, StatusCode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("demo_app")

SERVICE_NAME = os.getenv("SERVICE_NAME", "demo-service")
PORT = int(os.getenv("PORT", "8080"))
OTEL_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://otel-collector.changetrace.svc.cluster.local:4318",
).rstrip("/")
BASE_LATENCY_MS = float(os.getenv("BASE_LATENCY_MS", "40"))
CALL_INTERVAL_SECONDS = float(os.getenv("CALL_INTERVAL_SECONDS", "4"))
DEPENDENCIES: List[str] = []
try:
    DEPENDENCIES = json.loads(os.getenv("DEPENDENCIES", "[]"))
except (ValueError, TypeError):
    DEPENDENCIES = [d.strip() for d in os.getenv("DEPENDENCIES", "").split(",") if d.strip()]

provider = TracerProvider(
    resource=Resource.create({"service.name": SERVICE_NAME}),
)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces"))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE_NAME)

app = FastAPI(title=f"{SERVICE_NAME}", version="1.0.0")

_extra_latency_ms = 0.0
_failing = False
_peer_lock = asyncio.Lock()


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(_traffic_loop())
    logger.info(
        "%s started on port %s (deps=%s, otel=%s)",
        SERVICE_NAME, PORT, DEPENDENCIES, OTEL_ENDPOINT,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": SERVICE_NAME}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/invoke")
async def invoke(request: Request) -> JSONResponse:
    """Handle an inbound request, continuing the propagated trace context."""
    parent = TraceContextTextMapPropagator().extract(
        {"traceparent": request.headers.get("traceparent", ""),
         "tracestate": request.headers.get("tracestate", "")}
    )
    with tracer.start_as_current_span(f"{SERVICE_NAME}/invoke", kind=SpanKind.SERVER, context=parent) as span:
        global _failing, _extra_latency_ms
        async with _peer_lock:
            failing = _failing
            latency_ms = _extra_latency_ms + BASE_LATENCY_MS

        if failing:
            span.set_attribute("demo.fault", "failure")
            span.set_status(Status(StatusCode.ERROR, "injected failure"))
            return JSONResponse({"error": "injected failure", "service": SERVICE_NAME}, status_code=503)

        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)
        span.set_attribute("demo.latency_ms", latency_ms)
        return JSONResponse({"ok": True, "service": SERVICE_NAME, "latency_ms": latency_ms})


@app.post("/fault/latency/{ms}")
async def fault_latency(ms: float) -> dict:
    global _extra_latency_ms
    async with _peer_lock:
        _extra_latency_ms = max(0.0, float(ms))
    logger.warning("%s: injected latency +%sms", SERVICE_NAME, ms)
    return {"service": SERVICE_NAME, "extra_latency_ms": _extra_latency_ms}


@app.post("/fault/fail")
async def fault_fail() -> dict:
    global _failing
    async with _peer_lock:
        _failing = True
    logger.warning("%s: injected failure mode", SERVICE_NAME)
    return {"service": SERVICE_NAME, "failing": True}


@app.post("/fault/reset")
async def fault_reset() -> dict:
    global _failing, _extra_latency_ms
    async with _peer_lock:
        _failing = False
        _extra_latency_ms = 0.0
    logger.warning("%s: faults cleared", SERVICE_NAME)
    return {"service": SERVICE_NAME, "failing": False, "extra_latency_ms": 0.0}


@app.get("/fault")
async def fault_state() -> dict:
    return {"service": SERVICE_NAME, "failing": _failing, "extra_latency_ms": _extra_latency_ms}


async def _call_dependency(client: httpx.AsyncClient, dep: str) -> None:
    """Call a downstream service with a client span carrying ``peer.service``."""
    with tracer.start_as_current_span(f"{dep} call", kind=SpanKind.CLIENT) as span:
        span.set_attribute("peer.service", dep)
        carrier: dict = {}
        TraceContextTextMapPropagator().inject(carrier)
        url = f"http://{dep}/invoke"
        try:
            resp = await client.get(url, headers={"traceparent": carrier.get("traceparent", "")}, timeout=10.0)
            if resp.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            else:
                span.set_status(Status(StatusCode.OK))
        except Exception as exc:  # network errors surface as failed calls
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR))
            logger.debug("%s -> %s call failed: %s", SERVICE_NAME, dep, exc)


async def _traffic_loop() -> None:
    """Periodically fan out to downstream services to generate trace traffic."""
    await asyncio.sleep(3)
    async with httpx.AsyncClient() as client:
        while True:
            for dep in DEPENDENCIES:
                try:
                    await _call_dependency(client, dep)
                except Exception as exc:
                    logger.debug("background call error: %s", exc)
            await asyncio.sleep(CALL_INTERVAL_SECONDS)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
