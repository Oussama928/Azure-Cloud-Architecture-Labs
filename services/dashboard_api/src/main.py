"""
Dashboard API Service for ChangeTrace

Provides REST API for the dashboard UI:
- Dependency graph data
- Incident timeline
- SLO burn charts
- Risk score history
- Correlation accuracy metrics
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn

# Configure structured logging
import structlog
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


class DashboardConfig(BaseModel):
    """Dashboard API configuration"""
    # Cosmos DB
    cosmos_connection_string: str
    cosmos_database: str = "changetrace-graph"
    dependency_graph_name: str = "dependency-graph"
    change_history_name: str = "change-history"
    incidents_name: str = "incidents"
    
    # Azure Monitor
    log_analytics_workspace_id: Optional[str] = None
    
    # Service
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "info"


# Global state
config: Optional[DashboardConfig] = None
gremlin_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global config, gremlin_client
    
    # Load config
    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        cosmos_connection_string: str
        cosmos_database: str = "changetrace-graph"
        dependency_graph_name: str = "dependency-graph"
        change_history_name: str = "change-history"
        incidents_name: str = "incidents"
        log_analytics_workspace_id: Optional[str] = None
        host: str = "0.0.0.0"
        port: int = 8002
        log_level: str = "info"
        
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
    
    settings = Settings()
    config = DashboardConfig(**settings.model_dump())
    
    # Initialize Gremlin client
    import urllib.parse
    parsed = urllib.parse.urlparse(config.cosmos_connection_string)
    endpoint = None
    key = None
    for param in parsed.query.split(";"):
        if param.startswith("AccountEndpoint="):
            endpoint = param[16:]
        elif param.startswith("AccountKey="):
            key = param[11:]
    
    if not endpoint or not key:
        logger.warning("Cosmos DB connection string not fully parsed")
    else:
        from gremlin_python.driver import client, serializer
        gremlin_client = client.Client(
            endpoint,
            'g',
            username=f"/dbs/{config.cosmos_database}/colls/{config.dependency_graph_name}",
            password=key,
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        logger.info("Initialized Gremlin client")
    
    yield
    
    # Cleanup
    if gremlin_client:
        gremlin_client.close()
        logger.info("Closed Gremlin client")


app = FastAPI(
    title="ChangeTrace Dashboard API",
    description="API for ChangeTrace dashboard - dependency graphs, incidents, SLOs, risk scores",
    version="1.0.0",
    lifespan=lifespan,
)


# Response models
class ServiceNode(BaseModel):
    """Service node in dependency graph"""
    id: str
    name: str
    namespace: Optional[str] = None
    criticality: str = "medium"
    slo_target: Optional[float] = None
    current_slo: Optional[float] = None
    error_budget_remaining: Optional[float] = None
    incident_count_24h: int = 0
    deployment_count_24h: int = 0


class DependencyEdge(BaseModel):
    """Dependency edge between services"""
    source: str
    target: str
    type: str = "depends_on"
    latency_p99: Optional[float] = None
    error_rate: Optional[float] = None
    request_volume: Optional[int] = None


class DependencyGraph(BaseModel):
    """Full dependency graph"""
    nodes: List[ServiceNode]
    edges: List[DependencyEdge]
    updated_at: datetime


class IncidentSummary(BaseModel):
    """Incident summary for timeline"""
    incident_id: str
    title: str
    severity: str
    status: str
    affected_service: str
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    root_cause_candidate: Optional[str] = None
    confidence: Optional[float] = None
    remediation_action: Optional[str] = None


class SLOBurnData(BaseModel):
    """SLO burn rate data point"""
    timestamp: datetime
    service: str
    slo_name: str
    target: float
    actual: float
    burn_rate: float
    error_budget_remaining: float


class RiskScoreHistory(BaseModel):
    """Risk score history entry"""
    timestamp: datetime
    service: str
    deployment_id: Optional[str] = None
    risk_score: float
    risk_level: str  # low, medium, high, critical
    factors: Dict[str, float]


class CorrelationAccuracy(BaseModel):
    """Correlation accuracy metrics"""
    period_start: datetime
    period_end: datetime
    total_incidents: int
    precision_at_1: float
    precision_at_3: float
    recall: float
    mean_time_to_detection_seconds: float
    model_version: str


# Health endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "dashboard-api",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    return {"status": "ready"}


# Dependency Graph endpoints
@app.get("/api/v1/graph/dependency", response_model=DependencyGraph)
async def get_dependency_graph(
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
    include_metrics: bool = Query(True, description="Include SLO metrics"),
):
    """Get the full service dependency graph"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    
    try:
        # Query for all services
        query = f"g.V().hasLabel('Service')"
        if namespace:
            query += f".has('namespace', '{namespace}')"
        query += ".valueMap(true)"
        
        result_set = gremlin_client.submit(query)
        vertices = []
        async for result in result_set:
            vertices.append(result)
        
        # Query for dependencies
        edge_query = "g.E().hasLabel('depends_on').valueMap(true)"
        edge_result = gremlin_client.submit(edge_query)
        edges = []
        async for result in edge_result:
            edges.append(result)
        
        # Convert to response models
        nodes = []
        for v in vertices:
            props = {k: v[0] if isinstance(v, list) else v for k, v in v.items()}
            nodes.append(ServiceNode(
                id=props.get('id', ''),
                name=props.get('serviceName', props.get('name', '')),
                namespace=props.get('namespace'),
                criticality=props.get('criticality', 'medium'),
                slo_target=props.get('sloTarget'),
                current_slo=props.get('currentSLO'),
                error_budget_remaining=props.get('errorBudgetRemaining'),
                incident_count_24h=props.get('incidentCount24h', 0),
                deployment_count_24h=props.get('deploymentCount24h', 0),
            ))
        
        edge_list = []
        for e in edges:
            props = {k: v[0] if isinstance(v, list) else v for k, v in e.items()}
            edge_list.append(DependencyEdge(
                source=props.get('outV', ''),
                target=props.get('inV', ''),
                type=props.get('type', 'depends_on'),
                latency_p99=props.get('latencyP99'),
                error_rate=props.get('errorRate'),
                request_volume=props.get('requestVolume'),
            ))
        
        return DependencyGraph(
            nodes=nodes,
            edges=edge_list,
            updated_at=datetime.utcnow(),
        )
    except Exception as e:
        logger.error("Failed to fetch dependency graph", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch graph: {str(e)}")


@app.get("/api/v1/graph/blast-radius/{service_name}")
async def get_blast_radius(
    service_name: str,
    namespace: Optional[str] = Query(None),
    max_hops: int = Query(3, ge=1, le=5),
):
    """Get blast radius for a service"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    
    try:
        query = f"g.V().has('serviceName', '{service_name}')"
        if namespace:
            query += f".has('namespace', '{namespace}')"
        query += f".repeat(__.in('depends_on').simplePath()).times({max_hops}).emit().dedup().values('serviceName')"
        
        result_set = gremlin_client.submit(query)
        services = []
        async for result in result_set:
            services.append(result)
        
        # Remove the source service
        services = [s for s in services if s != service_name]
        
        return {
            "source_service": service_name,
            "affected_services": services,
            "hop_count": max_hops,
            "total_affected": len(services),
        }
    except Exception as e:
        logger.error("Failed to compute blast radius", service=service_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to compute blast radius: {str(e)}")


# Incident endpoints
@app.get("/api/v1/incidents", response_model=List[IncidentSummary])
async def get_incidents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
):
    """Get incident timeline"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    
    try:
        query = f"g.V().hasLabel('Incident').order().by('detectedAt', desc).range({offset}, {offset + limit})"
        
        filters = []
        if severity:
            filters.append(f"has('severity', '{severity}')")
        if status:
            filters.append(f"has('status', '{status}')")
        if service:
            filters.append(f"has('affectedService', '{service}')")
        if start_time:
            filters.append(f"has('detectedAt', gte('{start_time.isoformat()}'))")
        if end_time:
            filters.append(f"has('detectedAt', lte('{end_time.isoformat()}'))")
        
        if filters:
            query = query.replace("g.V().hasLabel('Incident')", f"g.V().hasLabel('Incident').{''.join(filters)}")
        
        query += ".valueMap(true)"
        
        result_set = gremlin_client.submit(query)
        incidents = []
        async for result in result_set:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            incidents.append(IncidentSummary(
                incident_id=props.get('incidentId', ''),
                title=props.get('title', ''),
                severity=props.get('severity', 'sev3'),
                status=props.get('status', 'open'),
                affected_service=props.get('affectedService', ''),
                detected_at=datetime.fromisoformat(props.get('detectedAt', datetime.utcnow().isoformat())),
                resolved_at=datetime.fromisoformat(props['resolvedAt']) if props.get('resolvedAt') else None,
                root_cause_candidate=props.get('rootCauseCandidate'),
                confidence=props.get('confidence'),
                remediation_action=props.get('remediationAction'),
            ))
        
        return incidents
    except Exception as e:
        logger.error("Failed to fetch incidents", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch incidents: {str(e)}")


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident_detail(incident_id: str):
    """Get detailed incident information"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    
    try:
        query = f"g.V().has('incidentId', '{incident_id}').valueMap(true)"
        result_set = gremlin_client.submit(query)
        
        async for result in result_set:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            return props
        
        raise HTTPException(status_code=404, detail="Incident not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch incident detail", incident_id=incident_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch incident: {str(e)}")


# SLO/Burn Rate endpoints
@app.get("/api/v1/slo/burn-rate", response_model=List[SLOBurnData])
async def get_slo_burn_rate(
    service: Optional[str] = Query(None),
    slo_name: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    interval_minutes: int = Query(5, ge=1, le=60),
):
    """Get SLO burn rate data for charts"""
    # This would typically query Log Analytics / Application Insights
    # For now, return mock data structure
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    # Generate mock data points
    data = []
    current = start_time
    while current <= end_time:
        data.append(SLOBurnData(
            timestamp=current,
            service=service or "payment-service",
            slo_name=slo_name or "availability",
            target=99.9,
            actual=99.95 - (hash(str(current)) % 100) / 10000,
            burn_rate=1.0 + (hash(str(current)) % 50) / 100,
            error_budget_remaining=95.0 - (hash(str(current)) % 200) / 100,
        ))
        current += timedelta(minutes=interval_minutes)
    
    return data


@app.get("/api/v1/slo/status")
async def get_slo_status(
    service: Optional[str] = Query(None),
):
    """Get current SLO status for all services"""
    # Mock response
    return {
        "services": [
            {
                "name": "payment-service",
                "namespace": "production",
                "slos": [
                    {
                        "name": "availability",
                        "target": 99.9,
                        "current": 99.95,
                        "error_budget_remaining": 85.2,
                        "burn_rate": 1.2,
                        "status": "healthy",
                    },
                    {
                        "name": "latency_p99",
                        "target": 500,
                        "current": 450,
                        "error_budget_remaining": 92.1,
                        "burn_rate": 0.8,
                        "status": "healthy",
                    },
                ],
            },
            {
                "name": "checkout-service",
                "namespace": "production",
                "slos": [
                    {
                        "name": "availability",
                        "target": 99.95,
                        "current": 99.92,
                        "error_budget_remaining": 45.3,
                        "burn_rate": 2.5,
                        "status": "warning",
                    },
                ],
            },
        ],
        "updated_at": datetime.utcnow().isoformat(),
    }


# Risk Score endpoints
@app.get("/api/v1/risk/history", response_model=List[RiskScoreHistory])
async def get_risk_history(
    service: Optional[str] = Query(None),
    hours: int = Query(168, ge=1, le=720),  # Up to 30 days
    limit: int = Query(100, ge=1, le=500),
):
    """Get risk score history"""
    # Mock data
    data = []
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    current = start_time
    while current <= end_time and len(data) < limit:
        data.append(RiskScoreHistory(
            timestamp=current,
            service=service or "payment-service",
            deployment_id=f"deploy-{hash(str(current)) % 10000}",
            risk_score=0.3 + (hash(str(current)) % 70) / 100,
            risk_level="medium",
            factors={
                "change_size": 0.4,
                "service_criticality": 0.8,
                "recent_incidents": 0.2,
                "dependency_risk": 0.3,
            },
        ))
        current += timedelta(hours=1)
    
    return data


@app.get("/api/v1/risk/current")
async def get_current_risk_scores(
    service: Optional[str] = Query(None),
):
    """Get current risk scores for all services"""
    return {
        "scores": [
            {
                "service": "payment-service",
                "risk_score": 0.72,
                "risk_level": "high",
                "last_deployment": "deploy-12345",
                "last_deployment_time": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                "factors": {
                    "change_size": 0.6,
                    "service_criticality": 0.9,
                    "recent_incidents": 0.3,
                    "dependency_risk": 0.5,
                },
            },
            {
                "service": "checkout-service",
                "risk_score": 0.45,
                "risk_level": "medium",
                "last_deployment": "deploy-12340",
                "last_deployment_time": (datetime.utcnow() - timedelta(hours=24)).isoformat(),
                "factors": {
                    "change_size": 0.3,
                    "service_criticality": 0.8,
                    "recent_incidents": 0.1,
                    "dependency_risk": 0.4,
                },
            },
        ],
        "updated_at": datetime.utcnow().isoformat(),
    }


# Correlation Accuracy endpoints
@app.get("/api/v1/correlation/accuracy", response_model=CorrelationAccuracy)
async def get_correlation_accuracy(
    days: int = Query(30, ge=1, le=90),
):
    """Get correlation accuracy metrics"""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    return CorrelationAccuracy(
        period_start=start_time,
        period_end=end_time,
        total_incidents=47,
        precision_at_1=0.72,
        precision_at_3=0.89,
        recall=0.78,
        mean_time_to_detection_seconds=145.3,
        model_version="1.0-20240115-143022",
    )


@app.get("/api/v1/correlation/accuracy/history")
async def get_correlation_accuracy_history(
    days: int = Query(90, ge=1, le=365),
):
    """Get correlation accuracy over time"""
    # Mock historical data
    data = []
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    current = start_time
    while current <= end_time:
        data.append({
            "date": current.date().isoformat(),
            "total_incidents": 2 + (hash(str(current)) % 5),
            "precision_at_1": 0.65 + (hash(str(current)) % 20) / 100,
            "precision_at_3": 0.80 + (hash(str(current)) % 15) / 100,
            "recall": 0.70 + (hash(str(current)) % 20) / 100,
            "model_version": "1.0",
        })
        current += timedelta(days=1)
    
    return {"history": data}


# Change History endpoints
@app.get("/api/v1/changes")
async def get_changes(
    service: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
):
    """Get recent changes"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    
    try:
        query = f"g.V().hasLabel('ChangeEvent').has('timestamp', gte('{(datetime.utcnow() - timedelta(hours=hours)).isoformat()}')).order().by('timestamp', desc).limit({limit})"
        
        filters = []
        if service:
            filters.append(f"has('serviceName', '{service}')")
        if source:
            filters.append(f"has('source', '{source}')")
        if change_type:
            filters.append(f"has('changeType', '{change_type}')")
        
        if filters:
            query = query.replace("g.V().hasLabel('ChangeEvent')", f"g.V().hasLabel('ChangeEvent').{''.join(filters)}")
        
        query += ".valueMap(true)"
        
        result_set = gremlin_client.submit(query)
        changes = []
        async for result in result_set:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            changes.append(props)
        
        return {"changes": changes, "count": len(changes)}
    except Exception as e:
        logger.error("Failed to fetch changes", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch changes: {str(e)}")


# Metrics endpoint for Prometheus
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def main():
    """Main entry point"""
    import os
    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8002
        log_level: str = "info"
        
        class Config:
            env_file = ".env"
    
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