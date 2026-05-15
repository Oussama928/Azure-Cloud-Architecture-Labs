"""
Main Collector Service for ChangeTrace

Orchestrates all change event sources:
- GitHub (commits, PRs, releases)
- Terraform (plans, applies)
- Kubernetes (deployments, configmaps, secrets)
- Azure Resource Graph (resource changes)

Normalizes events to unified schema and writes to Cosmos DB Gremlin.
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import uvicorn

from .models.change_event import (
    ChangeEvent,
    ChangeEventBatch,
    ChangeSource,
    ChangeType,
)
from .sources.github_source import GitHubSource, GitHubConfig
from .sources.terraform_source import TerraformSource, TerraformConfig
from .sources.k8s_source import K8sSource, K8sConfig
from .sources.azure_resource_graph_source import AzureResourceGraphSource, AzureResourceGraphConfig

# Shared utilities
from services.shared.circuit_breaker import (
    CircuitBreaker,
    get_cosmos_breaker,
    get_eventgrid_breaker,
    get_keyvault_breaker,
)
from services.shared.structured_logging import (
    setup_structured_logging,
    get_logger,
    LogContextManager,
)
from services.shared.health_checks import (
    HealthCheckRegistry,
    create_health_endpoint,
    CosmosDBHealthCheck,
    KeyVaultHealthCheck,
)
from services.shared.config import (
    ServiceSettings,
    CollectorConfig as SharedCollectorConfig,
    load_settings_from_keyvault,
)

# Configure structured logging
logger = setup_structured_logging("collector", level=logging.INFO)


class CollectorConfig(BaseModel):
    """Main collector configuration"""
    # Cosmos DB
    cosmos_connection_string: str
    cosmos_database: str = "changetrace-graph"
    cosmos_graph: str = "change-history"
    
    # Event Grid (for publishing events)
    eventgrid_endpoint: Optional[str] = None
    eventgrid_key: Optional[str] = None
    
    # Source configurations
    github: Optional[GitHubConfig] = None
    terraform: Optional[TerraformConfig] = None
    kubernetes: Optional[K8sConfig] = None
    azure_resource_graph: Optional[AzureResourceGraphConfig] = None
    
    # Processing
    batch_size: int = 100
    flush_interval_seconds: int = 30
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    
    # Health check
    health_check_interval_seconds: int = 60


class CollectorService:
    """
    Main collector service that orchestrates all change event sources.
    """
    
    def __init__(self, config: CollectorConfig):
        self.config = config
        self._sources: Dict[ChangeSource, Any] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._event_buffer: List[ChangeEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._cosmos_client = None
        self._eventgrid_client = None
        
        # Circuit breakers
        self._cosmos_breaker = get_cosmos_breaker()
        self._eventgrid_breaker = get_eventgrid_breaker()
        self._keyvault_breaker = get_keyvault_breaker()
        
        # Health checks
        self._health_registry = HealthCheckRegistry("collector", "1.0.0")
        
        # Structured logger with context
        self.logger = get_logger("collector")
    
    async def initialize(self) -> None:
        """Initialize all sources and connections"""
        with LogContextManager(service_name="collector", operation_name="initialize"):
            self.logger.info("Initializing collector service")
            
            # Initialize Cosmos DB client
            await self._init_cosmos()
            
            # Initialize Event Grid client
            await self._init_eventgrid()
            
            # Initialize sources
            if self.config.github:
                self._sources[ChangeSource.GITHUB] = GitHubSource(self.config.github)
                await self._sources[ChangeSource.GITHUB].initialize()
                self.logger.info("Initialized GitHub source")
            
            if self.config.terraform:
                self._sources[ChangeSource.TERRAFORM] = TerraformSource(self.config.terraform)
                await self._sources[ChangeSource.TERRAFORM].initialize()
                self.logger.info("Initialized Terraform source")
            
            if self.config.kubernetes:
                self._sources[ChangeSource.KUBERNETES] = K8sSource(self.config.kubernetes)
                await self._sources[ChangeSource.KUBERNETES].initialize()
                self.logger.info("Initialized Kubernetes source")
            
            if self.config.azure_resource_graph:
                self._sources[ChangeSource.AZURE_RESOURCE_GRAPH] = AzureResourceGraphSource(
                    self.config.azure_resource_graph
                )
                await self._sources[ChangeSource.AZURE_RESOURCE_GRAPH].initialize()
                self.logger.info("Initialized Azure Resource Graph source")
            
            # Set up health checks
            self._setup_health_checks()
            
            self.logger.info(f"Collector initialized with {len(self._sources)} sources")
    
    def _setup_health_checks(self) -> None:
        """Set up health checks for dependencies"""
        # Cosmos DB health check
        if self._cosmos_client:
            self._health_registry.add_check(
                CosmosDBHealthCheck(
                    "cosmos-db",
                    lambda: self._cosmos_client,
                    query="g.V().limit(1)",
                )
            )
        
        # Key Vault health check (if configured)
        # self._health_registry.add_check(KeyVaultHealthCheck(...))
        
        # Source health checks
        for source_type, source in self._sources.items():
            if hasattr(source, 'health_check'):
                self._health_registry.add_check(
                    DependencyHealthCheck(
                        f"source-{source_type.value}",
                        source.health_check,
                    )
                )
        
        # Create health endpoints
        create_health_endpoint(app, self._health_registry)
    
    async def _init_cosmos(self) -> None:
        """Initialize Cosmos DB Gremlin client"""
        from gremlin_python.driver import client, serializer
        
        # Parse connection string for Gremlin endpoint
        import urllib.parse
        parsed = urllib.parse.urlparse(self.config.cosmos_connection_string)
        
        # For now, use the connection string directly
        # In production, use managed identity
        self._cosmos_client = client.Client(
            self.config.cosmos_connection_string,
            'g',
            username=f"/dbs/{self.config.cosmos_database}/colls/{self.config.cosmos_graph}",
            password="",  # Will use connection string auth
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        
        self.logger.info("Initialized Cosmos DB Gremlin client")
    
    async def _init_eventgrid(self) -> None:
        """Initialize Event Grid publisher client"""
        if self.config.eventgrid_endpoint and self.config.eventgrid_key:
            from azure.eventgrid import EventGridPublisherClient
            from azure.core.credentials import AzureKeyCredential
            
            self._eventgrid_client = EventGridPublisherClient(
                self.config.eventgrid_endpoint,
                AzureKeyCredential(self.config.eventgrid_key)
            )
            self.logger.info("Initialized Event Grid publisher")
        else:
            self.logger.warning("Event Grid not configured, events will not be published")
    
    async def close(self) -> None:
        """Shutdown all sources and connections"""
        with LogContextManager(service_name="collector", operation_name="shutdown"):
            self.logger.info("Shutting down collector service")
            self._running = False
            
            # Cancel all tasks
            for task in self._tasks:
                task.cancel()
            
            # Wait for tasks to complete
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            
            # Close sources
            for source in self._sources.values():
                if hasattr(source, 'close'):
                    await source.close()
            
            # Flush remaining events
            await self._flush_buffer()
            
            # Close clients
            if self._cosmos_client:
                self._cosmos_client.close()
            
            if self._eventgrid_client:
                await self._eventgrid_client.close()
            
            self.logger.info("Collector service shutdown complete")
    
    async def start(self) -> None:
        """Start collecting from all sources"""
        with LogContextManager(service_name="collector", operation_name="start"):
            self._running = True
            
            # Start source polling tasks
            for source_type, source in self._sources.items():
                if hasattr(source, 'start_polling'):
                    task = asyncio.create_task(self._run_source_polling(source_type, source))
                    self._tasks.append(task)
                elif hasattr(source, 'start_watching'):
                    task = asyncio.create_task(self._run_source_watching(source_type, source))
                    self._tasks.append(task)
            
            # Start buffer flush task
            flush_task = asyncio.create_task(self._periodic_flush())
            self._tasks.append(flush_task)
            
            # Start health check task
            health_task = asyncio.create_task(self._periodic_health_check())
            self._tasks.append(health_task)
            
            self.logger.info("Collector service started")
    
    async def _run_source_polling(self, source_type: ChangeSource, source: Any) -> None:
        """Run polling loop for a source"""
        self.logger.info(f"Starting polling for {source_type.value}")
        
        while self._running:
            try:
                events = await source.poll_all()
                if events:
                    await self._buffer_events(events)
                    self.logger.info(f"Collected {len(events)} events from {source_type.value}")
            except Exception as e:
                self.logger.error(f"Error polling {source_type.value}: {e}", exc_info=True)
            
            # Wait before next poll
            await asyncio.sleep(self.config.flush_interval_seconds)
    
    async def _run_source_watching(self, source_type: ChangeSource, source: Any) -> None:
        """Run watch loop for a source"""
        self.logger.info(f"Starting watch for {source_type.value}")
        
        try:
            async for event in source.start_watching():
                if not self._running:
                    break
                await self._buffer_events([event])
        except Exception as e:
            self.logger.error(f"Error watching {source_type.value}: {e}", exc_info=True)
    
    async def _buffer_events(self, events: List[ChangeEvent]) -> None:
        """Add events to buffer"""
        async with self._buffer_lock:
            self._event_buffer.extend(events)
            
            # Flush if buffer is full
            if len(self._event_buffer) >= self.config.batch_size:
                await self._flush_buffer()
    
    async def _flush_buffer(self) -> None:
        """Flush event buffer to Cosmos DB and Event Grid"""
        async with self._buffer_lock:
            if not self._event_buffer:
                return
            
            events = self._event_buffer[:]
            self._event_buffer.clear()
        
        if not events:
            return
        
        self.logger.info(f"Flushing {len(events)} events to storage")
        
        # Write to Cosmos DB with circuit breaker
        await self._write_to_cosmos(events)
        
        # Publish to Event Grid with circuit breaker
        await self._publish_to_eventgrid(events)
    
    async def _write_to_cosmos(self, events: List[ChangeEvent]) -> None:
        """Write events to Cosmos DB Gremlin with circuit breaker"""
        if not self._cosmos_client:
            self.logger.warning("Cosmos DB client not initialized, skipping write")
            return
        
        # Use circuit breaker for Cosmos DB writes
        @self._cosmos_breaker
        async def write_event(event: ChangeEvent):
            vertex_props = event.to_gremlin_vertex()
            query = self._build_upsert_query(vertex_props)
            
            # Execute with retry
            for attempt in range(self.config.max_retries):
                try:
                    result = self._cosmos_client.submit(query).all().result()
                    return result
                except Exception as e:
                    if attempt == self.config.max_retries - 1:
                        raise
                    await asyncio.sleep(self.config.retry_backoff_seconds * (attempt + 1))
        
        for event in events:
            try:
                await write_event(event)
            except Exception as e:
                self.logger.error(f"Failed to write event {event.id} to Cosmos DB: {e}", exc_info=True)
    
    def _build_upsert_query(self, props: Dict[str, Any]) -> str:
        """Build Gremlin upsert query for change event vertex"""
        # Filter out None values
        props = {k: v for k, v in props.items() if v is not None}
        
        # Build property assignments
        prop_assignments = []
        for key, value in props.items():
            if isinstance(value, str):
                escaped_value = value.replace("'", "\\'")
                prop_assignments.append(f".property('{key}', '{escaped_value}')")
            elif isinstance(value, (int, float)):
                prop_assignments.append(f".property('{key}', {value})")
            elif isinstance(value, bool):
                prop_assignments.append(f".property('{key}', {str(value).lower()})")
            elif isinstance(value, list):
                # For lists, store as JSON string
                import json
                json_str = json.dumps(value).replace("'", "\\'")
                prop_assignments.append(f".property('{key}', '{json_str}')")
            elif value is not None:
                escaped_value = str(value).replace("'", "\\'")
                prop_assignments.append(f".property('{key}', '{escaped_value}')")
        
        query = f"g.V().has('eventId', '{props['eventId']}').fold().coalesce(unfold(), addV('ChangeEvent'))"
        query += "".join(prop_assignments)
        
        return query
    
    async def _publish_to_eventgrid(self, events: List[ChangeEvent]) -> None:
        """Publish events to Event Grid with circuit breaker"""
        if not self._eventgrid_client:
            return
        
        @self._eventgrid_breaker
        async def publish_batch(eg_events):
            self._eventgrid_client.send(eg_events)
        
        try:
            from azure.eventgrid import EventGridEvent
            
            eg_events = []
            for event in events:
                eg_event = EventGridEvent(
                    id=event.event_id,
                    subject=f"change/{event.source.value}/{event.service_name}",
                    data=event.to_gremlin_vertex(),
                    event_type=f"ChangeTrace.{event.change_type.value}",
                    event_time=event.timestamp,
                    data_version="1.0"
                )
                eg_events.append(eg_event)
            
            await publish_batch(eg_events)
            self.logger.info(f"Published {len(eg_events)} events to Event Grid")
            
        except Exception as e:
            self.logger.error(f"Failed to publish to Event Grid: {e}", exc_info=True)
    
    async def _periodic_flush(self) -> None:
        """Periodically flush event buffer"""
        while self._running:
            await asyncio.sleep(self.config.flush_interval_seconds)
            await self._flush_buffer()
    
    async def _periodic_health_check(self) -> None:
        """Periodic health check"""
        while self._running:
            await asyncio.sleep(self.config.health_check_interval_seconds)
            
            # Check source health
            for source_type, source in self._sources.items():
                if hasattr(source, 'health_check'):
                    try:
                        healthy = await source.health_check()
                        if not healthy:
                            self.logger.warning(f"Source {source_type.value} health check failed")
                    except Exception as e:
                        self.logger.error(f"Health check failed for {source_type.value}: {e}")
            
            # Log buffer status
            async with self._buffer_lock:
                self.logger.debug(f"Event buffer size: {len(self._event_buffer)}")
    
    async def handle_webhook(self, source: ChangeSource, payload: bytes, headers: Dict[str, str]) -> List[ChangeEvent]:
        """Handle incoming webhook from a source"""
        source_obj = self._sources.get(source)
        if not source_obj:
            raise HTTPException(status_code=404, detail=f"Source {source.value} not configured")
        
        if not hasattr(source_obj, 'parse_webhook'):
            raise HTTPException(status_code=400, detail=f"Source {source.value} does not support webhooks")
        
        parsed = await source_obj.parse_webhook(payload, headers)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid webhook payload")
        
        events = await source_obj.process_webhook(parsed)
        await self._buffer_events(events)
        
        return events
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get collector statistics"""
        return {
            "running": self._running,
            "sources": list(self._sources.keys()),
            "buffer_size": len(self._event_buffer),
            "tasks": len(self._tasks),
            "circuit_breakers": {
                "cosmos": self._cosmos_breaker.get_stats(),
                "eventgrid": self._eventgrid_breaker.get_stats(),
                "keyvault": self._keyvault_breaker.get_stats(),
            },
            "health": (await self._health_registry.run_all()).to_dict(),
        }


# FastAPI app for webhook endpoints
app = FastAPI(title="ChangeTrace Collector", version="1.0.0")

collector: Optional[CollectorService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global collector
    
    # Load config from environment
    import os
    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        cosmos_connection_string: str
        cosmos_database: str = "changetrace-graph"
        cosmos_graph: str = "change-history"
        eventgrid_endpoint: Optional[str] = None
        eventgrid_key: Optional[str] = None
        
        # GitHub
        github_app_id: Optional[int] = None
        github_private_key: Optional[str] = None
        github_installation_id: Optional[int] = None
        github_pat: Optional[str] = None
        github_webhook_secret: Optional[str] = None
        github_organizations: List[str] = []
        github_repositories: List[str] = []
        github_branches: List[str] = ["main", "master", "production"]
        github_poll_interval: int = 300
        
        # Terraform
        terraform_hostname: str = "app.terraform.io"
        terraform_organization: Optional[str] = None
        terraform_token: Optional[str] = None
        terraform_workspaces: List[str] = []
        terraform_poll_interval: int = 300
        
        # Kubernetes
        k8s_kubeconfig: Optional[str] = None
        k8s_context: Optional[str] = None
        k8s_in_cluster: bool = False
        k8s_namespaces: List[str] = ["default", "production", "staging"]
        k8s_poll_interval: int = 60
        
        # Azure Resource Graph
        arg_subscription_ids: List[str] = []
        arg_lookback_hours: int = 24
        arg_poll_interval: int = 300
        
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
    
    settings = Settings()
    
    # Build configs
    github_config = None
    if settings.github_app_id and settings.github_private_key and settings.github_installation_id:
        github_config = GitHubConfig(
            app_id=settings.github_app_id,
            private_key=settings.github_private_key,
            installation_id=settings.github_installation_id,
            webhook_secret=settings.github_webhook_secret,
            organizations=settings.github_organizations,
            repositories=settings.github_repositories,
            branches=settings.github_branches,
            poll_interval_seconds=settings.github_poll_interval,
        )
    elif settings.github_pat:
        github_config = GitHubConfig(
            personal_access_token=settings.github_pat,
            webhook_secret=settings.github_webhook_secret,
            organizations=settings.github_organizations,
            repositories=settings.github_repositories,
            branches=settings.github_branches,
            poll_interval_seconds=settings.github_poll_interval,
        )
    
    terraform_config = None
    if settings.terraform_organization and settings.terraform_token:
        terraform_config = TerraformConfig(
            hostname=settings.terraform_hostname,
            organization=settings.terraform_organization,
            token=settings.terraform_token,
            workspaces=settings.terraform_workspaces,
            poll_interval_seconds=settings.terraform_poll_interval,
        )
    
    k8s_config = None
    if settings.k8s_in_cluster or settings.k8s_kubeconfig:
        k8s_config = K8sConfig(
            kubeconfig_path=settings.k8s_kubeconfig,
            context=settings.k8s_context,
            in_cluster=settings.k8s_in_cluster,
            namespaces=settings.k8s_namespaces,
            poll_interval_seconds=settings.k8s_poll_interval,
        )
    
    arg_config = None
    if settings.arg_subscription_ids:
        arg_config = AzureResourceGraphConfig(
            subscription_ids=settings.arg_subscription_ids,
            lookback_hours=settings.arg_lookback_hours,
            poll_interval_seconds=settings.arg_poll_interval,
        )
    
    config = CollectorConfig(
        cosmos_connection_string=settings.cosmos_connection_string,
        cosmos_database=settings.cosmos_database,
        cosmos_graph=settings.cosmos_graph,
        eventgrid_endpoint=settings.eventgrid_endpoint,
        eventgrid_key=settings.eventgrid_key,
        github=github_config,
        terraform=terraform_config,
        kubernetes=k8s_config,
        azure_resource_graph=arg_config,
    )
    
    collector = CollectorService(config)
    await collector.initialize()
    await collector.start()
    
    yield
    
    await collector.close()


app.router.lifespan_context = lifespan


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    stats = await collector.get_stats()
    return {
        "status": "healthy" if collector._running else "unhealthy",
        "stats": stats,
    }


@app.post("/webhook/github")
async def github_webhook(request: Request):
    """GitHub webhook endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    payload = await request.body()
    headers = dict(request.headers)
    
    events = await collector.handle_webhook(ChangeSource.GITHUB, payload, headers)
    return {"received": len(events)}


@app.post("/webhook/terraform")
async def terraform_webhook(request: Request):
    """Terraform webhook endpoint"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    payload = await request.body()
    headers = dict(request.headers)
    
    events = await collector.handle_webhook(ChangeSource.TERRAFORM, payload, headers)
    return {"received": len(events)}


@app.post("/webhook/kubernetes")
async def kubernetes_webhook(request: Request):
    """Kubernetes webhook endpoint (for admission webhooks, etc.)"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    payload = await request.body()
    headers = dict(request.headers)
    
    events = await collector.handle_webhook(ChangeSource.KUBERNETES, payload, headers)
    return {"received": len(events)}


@app.get("/stats")
async def get_stats():
    """Get collector statistics"""
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    return await collector.get_stats()


async def main():
    """Main entry point"""
    import os
    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8000
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