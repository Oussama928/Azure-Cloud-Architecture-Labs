"""Graph Builder HTTP Server for Docker deployment."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import dotenv

dotenv.load_dotenv()

from .main import GraphBuilder
from .otel_receiver import ingest_otlp_payload
from services.shared.auth import auth_handler, get_simple_auth_secret

logger = logging.getLogger(__name__)

SIMPLE_AUTH_SECRET = get_simple_auth_secret()
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "")

app = FastAPI(
    title="ChangeTrace Graph Builder",
    description="Builds and maintains the live service dependency graph from OpenTelemetry traces",
    version="1.0.0",
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["WWW-Authenticate"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if auth_handler.disabled:
        return await call_next(request)

    public_paths = ["/health", "/ready", "/docs", "/openapi.json", "/redoc", "/v1/traces"]
    if request.url.path in public_paths:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")

    # Internal service-to-service calls authenticate with a shared token
    if INTERNAL_AUTH_TOKEN:
        if auth_header == f"Bearer {INTERNAL_AUTH_TOKEN}":
            request.state.user = {"sub": "collector", "roles": ["internal"], "name": "Collector"}
            return await call_next(request)

    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authorization header missing"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = auth_header[7:]
        if SIMPLE_AUTH_SECRET:
            try:
                import jwt as pyjwt
                payload = pyjwt.decode(token, SIMPLE_AUTH_SECRET, algorithms=["HS256"])
            except Exception:
                payload = None
            if payload is not None:
                request.state.user = payload
                return await call_next(request)
        payload = auth_handler.decode_token(token)
        request.state.user = payload
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": f"Invalid token: {e}"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


builder = GraphBuilder()


class BuildResult(BaseModel):
    edges_processed: int
    vertices_updated: int
    edges_updated: int
    timestamp: str


class BlastRadiusResult(BaseModel):
    source_service: str
    affected_services: list[str]
    paths: list[list[str]]
    hop_count: int
    total_affected: int


class DependenciesResult(BaseModel):
    upstream: list[str]
    downstream: list[str]


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "graph-builder",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/ready")
async def readiness_check():
    return {"status": "ready"}


@app.post("/v1/traces")
async def ingest_traces(request: Request):
    """Real-time OTLP/HTTP trace ingestion (bypasses App Insights).

    Tenant attribution, in priority order:
      1. `Authorization: Bearer <api_key>` -> resolved to the tenant via the
         TenantKey lookup (same as webhook auth). This is the client-facing,
         replicable wiring method.
      2. `changetrace-tenant-id` / `x-changetrace-tenant-id` header (fallback).
      3. Receiver's global OTEL_RECEIVER_TENANT_ID.
    """
    try:
        body = await request.body()
        if not body:
            return JSONResponse(status_code=200, content={"spans_processed": 0, "edges_processed": 0})

        api_key = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:].strip()

        tenant_id = (
            request.headers.get("changetrace-tenant-id")
            or request.headers.get("x-changetrace-tenant-id")
            or ""
        )
        result = await ingest_otlp_payload(
            body,
            request.headers.get("content-type", ""),
            request.headers.get("content-encoding", ""),
            tenant_id=tenant_id or None,
            api_key=api_key or None,
        )
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        logger.error(f"OTLP ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/graph/build")
async def build_graph(
    lookback_hours: int = Query(1, ge=1, le=168),
    min_spans: int = Query(10, ge=1),
    tenant_id: str = Query(default=None),
):
    try:
        result = await builder.build_from_traces(
            lookback_hours=lookback_hours,
            min_spans=min_spans,
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        logger.error(f"Graph build failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/graph/build-from-events")
async def build_graph_from_events(
    lookback_hours: int = Query(24, ge=1, le=720),
    tenant_id: str = Query(..., description="Tenant id to build the graph for"),
):
    try:
        result = await builder.build_from_change_events(
            tenant_id=tenant_id,
            lookback_hours=lookback_hours,
        )
        return result
    except Exception as e:
        logger.error(f"Graph build from events failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/graph/blast-radius/{service_name}")
async def get_blast_radius(
    service_name: str,
    max_hops: int = Query(3, ge=1, le=5),
    tenant_id: str = Query(default=None),
):
    try:
        result = await builder.compute_blast_radius(service_name, max_hops, tenant_id=tenant_id)
        return result
    except Exception as e:
        logger.error(f"Blast radius computation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/graph/dependencies/{service_name}")
async def get_dependencies(
    service_name: str,
    direction: str = Query("both", regex="^(in|out|both)$"),
    tenant_id: str = Query(default=None),
):
    try:
        result = await builder.get_service_dependencies(service_name, direction, tenant_id=tenant_id)
        return result
    except Exception as e:
        logger.error(f"Failed to get dependencies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def main():
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8004
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
