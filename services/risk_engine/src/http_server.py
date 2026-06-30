"""Risk Engine HTTP Server for Docker deployment."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import dotenv

dotenv.load_dotenv()

from .main import RiskEngine
from services.shared.auth import auth_handler, get_simple_auth_secret

logger = logging.getLogger(__name__)

SIMPLE_AUTH_SECRET = get_simple_auth_secret()

app = FastAPI(
    title="ChangeTrace Risk Engine",
    description="Scores deployment risk, manages canary analysis, and tracks SLO/error budgets",
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

    public_paths = ["/health", "/ready", "/docs", "/openapi.json", "/redoc"]
    if request.url.path in public_paths:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
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


engine = RiskEngine()


class ScoreDeploymentRequest(BaseModel):
    deployment_id: str
    service_name: str
    namespace: str = "production"
    version: str
    change_details: Dict[str, Any] = {}
    tenant_id: Optional[str] = None


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "risk-engine",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/ready")
async def readiness_check():
    return {"status": "ready"}


@app.post("/api/v1/risk/score-deployment")
async def score_deployment(request: ScoreDeploymentRequest, req: Request):
    try:
        token_tenant = getattr(req.state, "user", {}).get("tenant_id")
        result = await engine.score_deployment_risk(
            deployment_id=request.deployment_id,
            service_name=request.service_name,
            namespace=request.namespace,
            version=request.version,
            change_details=request.change_details,
            tenant_id=request.tenant_id or token_tenant,
        )
        return result
    except Exception as e:
        logger.error(f"Risk scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/risk/slo-status")
async def get_slo_status(
    service: str = Query(..., description="Service name"),
):
    try:
        result = await engine.get_slo_status(service)
        return result
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"SLO status query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/risk/canary-analyze")
async def analyze_canary(
    service_name: str = Query(...),
    namespace: str = Query("production"),
    stage: int = Query(0, ge=0),
    traffic_percentage: int = Query(10, ge=1, le=100),
    duration_minutes: int = Query(5, ge=1),
    slo_threshold: float = Query(0.99, gt=0, le=1.0),
):
    try:
        result = await engine.analyze_canary_stage(
            service_name=service_name,
            namespace=namespace,
            stage=stage,
            traffic_percentage=traffic_percentage,
            duration_minutes=duration_minutes,
            slo_threshold=slo_threshold,
        )
        return result
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"Canary analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def main():
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8005
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
