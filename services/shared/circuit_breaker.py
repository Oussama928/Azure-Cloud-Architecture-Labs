"""
Circuit Breaker Pattern Implementation for ChangeTrace.

Provides fault tolerance for external service calls (Cosmos DB, Event Grid, ML endpoints, etc.)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Failing, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5          # Failures before opening
    success_threshold: int = 2          # Successes in half-open before closing
    timeout: float = 30.0               # Seconds before half-open
    excluded_exceptions: tuple = ()     # Exceptions that don't count as failures


@dataclass
class CircuitBreakerStats:
    """Runtime statistics for circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_state_change: float = field(default_factory=time.time)
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreaker:
    """
    Circuit breaker for protecting external service calls.
    
    Usage:
        breaker = CircuitBreaker("cosmos-db", failure_threshold=5, timeout=30)
        
        @breaker
        async def call_cosmos():
            return await cosmos_client.query(...)
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        return self.stats.state
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open."""
        if self.stats.state != CircuitState.OPEN:
            return False
        return (time.time() - self.stats.last_failure_time) >= self.config.timeout
    
    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self.stats.total_calls += 1
            self.stats.total_successes += 1
            
            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                if self.stats.success_count >= self.config.success_threshold:
                    self.stats.state = CircuitState.CLOSED
                    self.stats.failure_count = 0
                    self.stats.success_count = 0
                    logger.info(f"Circuit '{self.name}' CLOSED after recovery")
            elif self.stats.state == CircuitState.CLOSED:
                self.stats.failure_count = 0  # Reset on success
    
    async def _on_failure(self, exc: Exception) -> None:
        """Handle failed call."""
        async with self._lock:
            self.stats.total_calls += 1
            self.stats.total_failures += 1
            self.stats.failure_count += 1
            self.stats.last_failure_time = time.time()
            
            if self.stats.state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self.stats.state = CircuitState.OPEN
                self.stats.success_count = 0
                logger.warning(f"Circuit '{self.name}' reopened after half-open failure")
            elif self.stats.state == CircuitState.CLOSED:
                if self.stats.failure_count >= self.config.failure_threshold:
                    self.stats.state = CircuitState.OPEN
                    self.stats.last_state_change = time.time()
                    logger.warning(
                        f"Circuit '{self.name}' OPENED after "
                        f"{self.stats.failure_count} failures"
                    )
    
    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap a function with circuit breaker."""
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Check if we should attempt reset
            if self._should_attempt_reset():
                async with self._lock:
                    if self.stats.state == CircuitState.OPEN:
                        self.stats.state = CircuitState.HALF_OPEN
                        self.stats.success_count = 0
                        logger.info(f"Circuit '{self.name}' entering HALF_OPEN state")
            
            # If open, fail fast
            if self.stats.state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN. "
                    f"Last failure: {self.stats.last_failure_time}"
                )
            
            try:
                result = await func(*args, **kwargs)
                await self._on_success()
                return result
            except self.config.excluded_exceptions:
                # Don't count excluded exceptions as failures
                raise
            except Exception as exc:
                await self._on_failure(exc)
                raise
        
        return wrapper
    
    def get_stats(self) -> dict:
        """Get current circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "success_count": self.stats.success_count,
            "total_calls": self.stats.total_calls,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "failure_rate": (
                self.stats.total_failures / self.stats.total_calls 
                if self.stats.total_calls > 0 else 0
            ),
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting calls."""
    pass


# Pre-configured circuit breakers for common services
def get_cosmos_breaker() -> CircuitBreaker:
    """Circuit breaker for Cosmos DB calls."""
    return CircuitBreaker(
        "cosmos-db",
        CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout=30.0,
        )
    )


def get_eventgrid_breaker() -> CircuitBreaker:
    """Circuit breaker for Event Grid publishing."""
    return CircuitBreaker(
        "event-grid",
        CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout=15.0,
        )
    )


def get_ml_endpoint_breaker() -> CircuitBreaker:
    """Circuit breaker for ML scoring endpoints."""
    return CircuitBreaker(
        "ml-endpoint",
        CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout=60.0,
        )
    )


def get_keyvault_breaker() -> CircuitBreaker:
    """Circuit breaker for Key Vault calls."""
    return CircuitBreaker(
        "key-vault",
        CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout=30.0,
        )
    )