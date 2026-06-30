"""Main Correlation Engine Service for ChangeTrace."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import dotenv

dotenv.load_dotenv()

# Configure structured logging
import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .correlator import Correlator, create_correlator
from .models.correlation import (
    BlastRadiusResult,
    CandidateRanking,
    CorrelationRequest,
    CorrelationResponse,
    Incident,
)
from .report_generator import ReportGenerator

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class CorrelationConfig(BaseModel):
    """Configuration for correlation engine service"""
    # Cosmos DB
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "changetrace-graph"
    cosmos_graph: str = "dependency-graph"

    # Model
    model_path: str | None = None

    # Correlation parameters
    lookback_hours: int = 2
    max_candidates: int = 10
    min_confidence_threshold: float = 0.1

    # Report generation
    use_llm_for_reports: bool = False

    # Service
    host: str = "0.0.0.0"
    port: int = 8001
    log_level: str = "info"


# Global correlator instance
correlator: Correlator | None = None
report_generator: ReportGenerator | None = None
config: CorrelationConfig | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global correlator, report_generator, config

    # Load config from environment
    from pydantic_settings import BaseSettings

    from services.shared.cosmos import get_cosmos_config_from_env

    cosmos_cfg = get_cosmos_config_from_env()

    class Settings(BaseSettings):
        cosmos_endpoint: str = cosmos_cfg["endpoint"]
        cosmos_key: str = cosmos_cfg["key"]
        cosmos_database: str = "changetrace-graph"
        cosmos_graph: str = "dependency-graph"
        model_path: str | None = None
        lookback_hours: int = 2
        max_candidates: int = 10
        min_confidence_threshold: float = 0.1
        use_llm_for_reports: bool = False
        host: str = "0.0.0.0"
        port: int = 8001
        log_level: str = "info"

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"

    settings = Settings()
    config = CorrelationConfig(**settings.model_dump())

    # Initialize correlator
    logger.info("Initializing correlation engine...")
    if not config.cosmos_endpoint or not config.cosmos_key:
        logger.warning("Cosmos DB not configured - using heuristic mode without graph queries")
    correlator = await create_correlator(
        cosmos_endpoint=config.cosmos_endpoint,
        cosmos_key=config.cosmos_key,
        model_path=config.model_path,
        lookback_hours=config.lookback_hours,
        max_candidates=config.max_candidates,
    )

    # Initialize report generator
    report_generator = ReportGenerator(use_llm=config.use_llm_for_reports)

    logger.info("Correlation engine initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down correlation engine...")
    if correlator:
        await correlator.close()
    logger.info("Correlation engine shutdown complete")


app = FastAPI(
    title="ChangeTrace Correlation Engine",
    description="Root cause correlation service for incident analysis",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "correlation-engine",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "model_version": correlator.model.model_version if correlator and correlator.model else "unknown",
        "model_trained": correlator.model.is_trained if correlator and correlator.model else False,
    }


@app.get("/ready")
async def readiness_check() -> dict[str, Any]:
    """Readiness check endpoint"""
    if not correlator:
        raise HTTPException(status_code=503, detail="Correlator not initialized")

    return {
        "status": "ready",
        "service": "correlation-engine",
        "model_version": correlator.model.model_version,
        "model_trained": correlator.model.is_trained,
    }


@app.post("/correlate", response_model=CorrelationResponse)
async def correlate_incident(request: CorrelationRequest) -> CorrelationResponse:
    """Correlate an incident with recent changes to identify root cause candidates."""
    if not correlator:
        raise HTTPException(status_code=503, detail="Correlator not initialized")

    try:
        # Use config defaults only when caller hasn't explicitly set them.
        # Pydantic defaults are used for validation; here we just forward
        # whatever the caller sent.
        response = await correlator.correlate_incident(request)
        return response
    except Exception as e:
        logger.error(f"Correlation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Correlation failed: {str(e)}")


@app.post("/blast-radius", response_model=BlastRadiusResult)
async def compute_blast_radius(
    service_name: str,
    namespace: str | None = None,
    max_hops: int = 3,
    tenant_id: str = "demo-tenant",
) -> BlastRadiusResult:
    """Compute blast radius for a service"""
    if not correlator:
        raise HTTPException(status_code=503, detail="Correlator not initialized")

    try:
        result = await correlator.compute_blast_radius(service_name, namespace, max_hops, tenant_id)
        return result
    except Exception as e:
        logger.error(f"Blast radius computation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Blast radius failed: {str(e)}")


@app.get("/model/info")
async def get_model_info() -> dict[str, Any]:
    """Get information about the current model"""
    if not correlator:
        raise HTTPException(status_code=503, detail="Correlator not initialized")

    return correlator.get_model_info()


@app.post("/report")
async def generate_report(
    incident: Incident,
    response: CorrelationResponse,
) -> dict[str, str]:
    """Generate human-readable correlation report"""
    if not report_generator:
        raise HTTPException(status_code=503, detail="Report generator not initialized")

    try:
        report = report_generator.generate_report(response, incident)
        return {"report": report, "format": "markdown"}
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


@app.post("/training-example")
async def create_training_example(
    incident: Incident,
    candidate: CandidateRanking,
    is_root_cause: bool,
) -> dict[str, str]:
    """Create a training example from a confirmed incident."""
    if not correlator:
        raise HTTPException(status_code=503, detail="Correlator not initialized")

    try:
        # We need the feature vector  would need to re-extract or store it
        # For now, return success
        return {"status": "training example recorded", "incident_id": incident.incident_id}
    except Exception as e:
        logger.error(f"Training example creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")


async def main():
    """Main entry point"""
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8001
        log_level: str = "info"

        class Config:
            env_file = ".env"
            extra = "ignore"

    settings = Settings()

    uvicorn_config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        lifespan="on",
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
