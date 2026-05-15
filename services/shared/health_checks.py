"""
Health Check Framework for ChangeTrace Services.

Provides standardized health checks for all services with dependency verification.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from azure import common
from fastapi import FastAPI, Response
from prometheus_client import registry
from pydantic import BaseModel


class HealthStatus(str, Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    name: str
    status: HealthStatus
    message: str = ""
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class ServiceHealth:
    """Overall service health status."""
    service_name: str
    status: HealthStatus
    checks: List[HealthCheckResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "unknown"
    uptime_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_name": self.service_name,
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
        }


class HealthCheck(ABC):
    """Abstract base class for health checks."""
    
    def __init__(self, name: str, timeout: float = 5.0):
        self.name = name
        self.timeout = timeout
    
    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """Execute the health check."""
        pass
    
    async def run(self) -> HealthCheckResult:
        """Run the check with timeout."""
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.check(), timeout=self.timeout)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check timed out after {self.timeout}s",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )


class HTTPHealthCheck(HealthCheck):
    """Health check for HTTP endpoints."""
    
    def __init__(
        self,
        name: str,
        url: str,
        expected_status: int = 200,
        timeout: float = 5.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(name, timeout)
        self.url = url
        self.expected_status = expected_status
        self.headers = headers or {}
    
    async def check(self) -> HealthCheckResult:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url, headers=self.headers) as response:
                if response.status == self.expected_status:
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.HEALTHY,
                        message=f"HTTP {response.status}",
                        metadata={"url": self.url, "status": response.status},
                    )
                else:
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.UNHEALTHY,
                        message=f"Unexpected status: {response.status}",
                        metadata={"url": self.url, "status": response.status},
                    )


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connections."""
    
    def __init__(
        self,
        name: str,
        connection_factory: Callable,
        query: str = "SELECT 1",
        timeout: float = 5.0,
    ):
        super().__init__(name, timeout)
        self.connection_factory = connection_factory
        self.query = query
    
    async def check(self) -> HealthCheckResult:
        try:
            conn = await self.connection_factory()
            async with conn.cursor() as cursor:
                await cursor.execute(self.query)
                await cursor.fetchone()
            await conn.close()
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Database connection successful",
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {str(e)}",
            )


class CosmosDBHealthCheck(HealthCheck):
    """Health check for Cosmos DB (Gremlin API)."""
    
    def __init__(
        self,
        name: str,
        client_factory: Callable,
        query: str = "g.V().limit(1)",
        timeout: float = 10.0,
    ):
        super().__init__(name, timeout)
        self.client_factory = client_factory
        self.query = query
    
    async def check(self) -> HealthCheckResult:
        try:
            client = self.client_factory()
            result_set = client.submit(self.query)
            # Consume first result to verify connection
            async for _ in result_set:
                break
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Cosmos DB Gremlin connection successful",
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Cosmos DB check failed: {str(e)}",
            )


class KeyVaultHealthCheck(HealthCheck):
    """Health check for Azure Key Vault."""
    
    def __init__(
        self,
        name: str,
        secret_client_factory: Callable,
        test_secret: str = "health-check-test",
        timeout: float = 10.0,
    ):
        super().__init__(name, timeout)
        self.secret_client_factory = secret_client_factory
        self.test_secret = test_secret
    
    async def check(self) -> HealthCheckResult:
        try:
            client = self.secret_client_factory()
            # Try to get a secret (or list secrets)
            secret = client.get_secret(self.test_secret)
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Key Vault connection successful",
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Key Vault check failed: {str(e)}",
            )


class DependencyHealthCheck(HealthCheck):
    """Health check for external service dependencies."""
    
    def __init__(
        self,
        name: str,
        check_func: Callable,
        timeout: float = 10.0,
    ):
        super().__init__(name, timeout)
        self.check_func = check_func
    
    async def check(self) -> HealthCheckResult:
        try:
            result = await self.check_func()
            if isinstance(result, HealthCheckResult):
                return result
            elif isinstance(result, bool):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                    message="Dependency check passed" if result else "Dependency check failed",
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="Dependency check completed",
                    metadata={"result": str(result)},
                )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Dependency check failed: {str(e)}",
            )


class HealthCheckRegistry:
    """Registry for managing multiple health checks."""
    
    def __init__(self, service_name: str, version: str = "unknown"):
        self.service_name = service_name
        self.version = version
        self.checks: List[HealthCheck] = []
        self.start_time = time.time()
    
    def add_check(self, check: HealthCheck) -> "HealthCheckRegistry":
        """Add a health check to the registry."""
        self.checks.append(check)
        return self
    
    def add_http_check(
        self,
        name: str,
        url: str,
        expected_status: int = 200,
        timeout: float = 5.0,
    ) -> "HealthCheckRegistry":
        """Add an HTTP health check."""
        return self.add_check(HTTPHealthCheck(name, url, expected_status, timeout))
    
    def add_database_check(
        self,
        name: str,
        connection_factory: Callable,
        query: str = "SELECT 1",
        timeout: float = 5.0,
    ) -> "HealthCheckRegistry":
        """Add a database health check."""
        return self.add_check(DatabaseHealthCheck(name, connection_factory, query, timeout))
    
    def add_cosmos_check(
        self,
        name: str,
        client_factory: Callable,
        query: str = "g.V().limit(1)",
        timeout: float = 10.0,
    ) -> "HealthCheckRegistry":
        """Add a Cosmos DB Gremlin health check."""
        return self.add_check(CosmosDBHealthCheck(name, client_factory, query, timeout))
    
    def add_keyvault_check(
        self,
        name: str,
        secret_client_factory: Callable,
        test_secret: str = "health-check-test",
        timeout: float = 10.0,
    ) -> "HealthCheckRegistry":
        """Add a Key Vault health check."""
        return self.add_check(KeyVaultHealthCheck(name, secret_client_factory, test_secret, timeout))
    
    def add_dependency_check(
        self,
        name: str,
        check_func: Callable,
        timeout: float = 10.0,
    ) -> "HealthCheckRegistry":
        """Add a custom dependency check."""
        return self.add_check(DependencyHealthCheck(name, check_func, timeout))
    
    async def run_all(self) -> ServiceHealth:
        """Run all health checks and return overall status."""
        results = await asyncio.gather(
            *[check.run() for check in self.checks],
            return_exceptions=True,
        )
        
        check_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                check_results.append(HealthCheckResult(
                    name=self.checks[i].name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check raised exception: {str(result)}",
                ))
            else:
                check_results.append(result)
        
        # Determine overall status
        if all(r.status == HealthStatus.HEALTHY for r in check_results):
            overall_status = HealthStatus.HEALTHY
        elif any(r.status == HealthStatus.UNHEALTHY for r in check_results):
            overall_status = HealthStatus.UNHEALTHY
        else:
            overall_status = HealthStatus.DEGRADED
        
        return ServiceHealth(
            service_name=self.service_name,
            status=overall_status,
            checks=check_results,
            version=self.version,
            uptime_seconds=time.time() - self.start_time,
        )


def create_health_endpoint(app: FastAPI, registry: HealthCheckRegistry) -> None:
    """Add health check endpoints to a FastAPI app."""
    
    @app.get("/health", response_model=Dict[str, Any])
    async def health_check():
        """Full health check with all dependencies."""
        health = await registry.run_all()
        return health.to_dict()
    
    @app.get("/health/live", response_model=Dict[str, Any])
    async def liveness_check():
        """Kubernetes liveness probe - only checks if service is running."""
        return {
            "status": "alive",
            "service": registry.service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    @app.get("/health/ready", response_model=Dict[str, Any])
    async def readiness_check():
        """Kubernetes readiness probe - checks critical dependencies."""
        health = await registry.run_all()
        
        # For readiness, we only care about critical checks
        critical_checks = [c for c in health.checks if c.metadata.get("critical", True)]
        ready = all(c.status == HealthStatus.HEALTHY for c in critical_checks)
        
        return Response(
            content=health.to_dict().__str__(),
            media_type="application/json",
            status_code=200 if ready else 503,
        )





"""

# Example usage
def create_default_registry(service_name: str, version: str = "1.0.0") -> HealthCheckRegistry:

    registry = HealthCheckRegistry(service_name, version)
    
    # Add  service-specific checks here
    # registry.add_cosmos_check("cosmos-db", get_cosmos_client)
    # registry.add_keyvault_check("key-vault", get_secret_client)
    # registry.add_http_check("downstream-api", "https://api.example.com/health")
    
    return registry

"""
