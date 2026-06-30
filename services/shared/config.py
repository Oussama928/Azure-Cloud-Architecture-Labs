"""
Configuration Management for ChangeTrace Services.

Centralized configuration with environment variable support, validation, and secrets integration.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CosmosDBSettings(BaseModel):
    """Cosmos DB configuration."""
    connection_string: str = Field(default="", description="Cosmos DB connection string")
    endpoint: str = Field(default="", description="Cosmos DB endpoint URL")
    key: str = Field(default="", description="Cosmos DB primary key")
    database: str = Field(default="changetrace-graph", description="Database name")
    graph: str = Field(default="dependency-graph", description="Graph name")
    change_graph: str = Field(default="change-history", description="Change history graph name")
    
    @field_validator("connection_string", mode="before")
    @classmethod
    def build_connection_string(cls, v: str, info) -> str:
        if v:
            return v
        # Build from endpoint and key if provided
        endpoint = info.data.get("endpoint", "")
        key = info.data.get("key", "")
        if endpoint and key:
            return f"AccountEndpoint={endpoint};AccountKey={key}"
        return v


class EventGridSettings(BaseModel):
    """Event Grid configuration."""
    topic_endpoint: str = Field(default="", description="Event Grid topic endpoint")
    topic_key: str = Field(default="", description="Event Grid topic key")
    system_topic_name: str = Field(default="", description="System topic name for Azure resources")


class KeyVaultSettings(BaseModel):
    """Key Vault configuration."""
    vault_url: str = Field(default="", description="Key Vault URL")
    tenant_id: str = Field(default="", description="Azure tenant ID")


class ApplicationInsightsSettings(BaseModel):
    """Application Insights configuration."""
    connection_string: str = Field(default="", description="Application Insights connection string")
    instrumentation_key: str = Field(default="", description="Instrumentation key (legacy)")
    sampling_percentage: float = Field(default=10.0, description="Sampling percentage")
    daily_cap_gb: float = Field(default=0.1, description="Daily data cap in GB")


class MLSettings(BaseModel):
    """Azure ML configuration."""
    workspace_name: str = Field(default="", description="ML workspace name")
    resource_group: str = Field(default="", description="Resource group")
    subscription_id: str = Field(default="", description="Subscription ID")
    model_registry_name: str = Field(default="changetrace-models", description="Model registry name")
    scoring_endpoint: str = Field(default="", description="Scoring endpoint URL")
    scoring_key: str = Field(default="", description="Scoring endpoint key")


class GitHubSettings(BaseModel):
    """GitHub integration configuration."""
    app_id: str = Field(default="", description="GitHub App ID")
    private_key: str = Field(default="", description="GitHub App private key")
    webhook_secret: str = Field(default="", description="Webhook secret")
    organization: str = Field(default="", description="GitHub organization")


class TerraformSettings(BaseModel):
    """Terraform configuration."""
    backend_storage_account: str = Field(default="", description="Terraform backend storage account")
    backend_container: str = Field(default="tfstate", description="Terraform backend container")
    backend_key: str = Field(default="changetrace.tfstate", description="Terraform state key")


class ServiceSettings(BaseSettings):
    """Main service configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Service identification
    service_name: str = Field(default="changetrace-service", description="Service name")
    environment: str = Field(default="development", description="Environment name")
    version: str = Field(default="1.0.0", description="Service version")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # Azure configuration
    subscription_id: str = Field(default="", description="Azure subscription ID")
    resource_group: str = Field(default="", description="Resource group name")
    location: str = Field(default="eastus", description="Azure region")
    tenant_id: str = Field(default="", description="Azure tenant ID")
    
    # Component configurations
    cosmos_db: CosmosDBSettings = Field(default_factory=CosmosDBSettings)
    event_grid: EventGridSettings = Field(default_factory=EventGridSettings)
    key_vault: KeyVaultSettings = Field(default_factory=KeyVaultSettings)
    app_insights: ApplicationInsightsSettings = Field(default_factory=ApplicationInsightsSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    terraform: TerraformSettings = Field(default_factory=TerraformSettings)
    
    # Feature flags
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    enable_tracing: bool = Field(default=True, description="Enable distributed tracing")
    enable_health_checks: bool = Field(default=True, description="Enable health check endpoints")
    
    # Timeouts and retries
    http_timeout: float = Field(default=30.0, description="HTTP client timeout in seconds")
    db_timeout: float = Field(default=10.0, description="Database timeout in seconds")
    retry_attempts: int = Field(default=3, description="Number of retry attempts")
    retry_backoff: float = Field(default=1.0, description="Retry backoff base in seconds")
    
    # Rate limiting
    rate_limit_requests: int = Field(default=100, description="Requests per minute")
    rate_limit_window: int = Field(default=60, description="Rate limit window in seconds")
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()
    
    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        valid_envs = {"development", "staging", "production", "test"}
        if v.lower() not in valid_envs:
            raise ValueError(f"environment must be one of {valid_envs}")
        return v.lower()


@lru_cache
def get_settings() -> ServiceSettings:
    """Get cached settings instance."""
    return ServiceSettings()


def load_settings_from_keyvault(settings: ServiceSettings) -> ServiceSettings:
    """
    Load secrets from Azure Key Vault and update settings.
    
    This should be called during application startup after initializing
    the Key Vault client.
    """
    return settings


# Configuration for specific services
@dataclass
class CollectorConfig:
    """Collector service specific configuration."""
    batch_size: int = 100
    flush_interval_seconds: int = 30
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    lookback_hours: int = 24
    sources: List[str] = field(default_factory=lambda: ["github", "terraform", "kubernetes", "azure_resource_graph"])


@dataclass
class CorrelationEngineConfig:
    """Correlation engine specific configuration."""
    lookback_hours: int = 2
    max_candidates: int = 10
    min_confidence_threshold: float = 0.2
    model_version: str = "heuristic-1.0"
    confidence_threshold: float = 0.75
    blast_radius_max_hops: int = 3


@dataclass
class RiskEngineConfig:
    """Risk engine specific configuration."""
    risk_threshold: float = 0.70
    canary_stages: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"traffic_percentage": 10, "duration_minutes": 5, "slo_threshold": 0.99},
        {"traffic_percentage": 50, "duration_minutes": 5, "slo_threshold": 0.99},
        {"traffic_percentage": 100, "duration_minutes": 5, "slo_threshold": 0.99},
    ])
    slo_checks: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "error_rate": {"threshold": 0.02, "window_minutes": 5},
        "latency_p95": {"threshold": 400, "window_minutes": 5},
        "availability": {"threshold": 0.999, "window_minutes": 5},
    })


@dataclass
class GraphBuilderConfig:
    """Graph builder specific configuration."""
    lookback_hours: int = 1
    min_spans: int = 10
    update_interval_minutes: int = 15


@dataclass
class DashboardAPIConfig:
    """Dashboard API specific configuration."""
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000"])
    api_prefix: str = "/api/v1"
    cache_ttl_seconds: int = 60


# Default configurations
DEFAULT_COLLECTOR_CONFIG = CollectorConfig()
DEFAULT_CORRELATION_CONFIG = CorrelationEngineConfig()
DEFAULT_RISK_CONFIG = RiskEngineConfig()
DEFAULT_GRAPH_BUILDER_CONFIG = GraphBuilderConfig()
DEFAULT_DASHBOARD_CONFIG = DashboardAPIConfig()