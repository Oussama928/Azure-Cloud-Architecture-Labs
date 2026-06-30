"""
Azure Resource Graph Source Collector for ChangeTrace.

Collects change events from Azure Resource Graph and converts them to ChangeEvents.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from pydantic import BaseModel, Field

from ..models.change_event import (
    AzureResourceChangeDetail,
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
)

logger = logging.getLogger(__name__)


class AzureResourceGraphConfig(BaseModel):
    """Configuration for Azure Resource Graph source"""
    # Authentication
    subscription_ids: list[str] = Field(default_factory=list)  # Empty = all accessible
    tenant_id: str | None = None

    # Query configuration
    lookback_hours: int = 24
    poll_interval_seconds: int = 300  # 5 minutes

    # Resource filters
    resource_types: list[str] = Field(default_factory=list)  # Empty = all
    resource_groups: list[str] = Field(default_factory=list)  # Empty = all
    locations: list[str] = Field(default_factory=list)  # Empty = all

    # Change types to track
    track_creates: bool = True
    track_updates: bool = True
    track_deletes: bool = True
    track_policy_changes: bool = True
    track_tag_changes: bool = True

    # Tag filters
    required_tags: dict[str, str] = Field(default_factory=dict)
    excluded_tags: dict[str, str] = Field(default_factory=dict)


class AzureResourceGraphSource:
    """Azure Resource Graph change event collector."""

    def __init__(self, config: AzureResourceGraphConfig):
        self.config = config
        self._client: ResourceGraphClient | None = None
        self._monitor_client: MonitorManagementClient | None = None
        self._credential = DefaultAzureCredential()
        self._last_query_time: datetime | None = None

    async def initialize(self) -> None:
        """Initialize Resource Graph client"""
        self._client = ResourceGraphClient(
            credential=self._credential,
        )
        # Monitor client needed for Activity Log queries
        try:
            from azure.common import AzureException
            self._monitor_client = MonitorManagementClient(
                credential=self._credential,
                subscription_id=self.config.subscription_ids[0] if self.config.subscription_ids else "",
            )
        except Exception as e:
            logger.warning(f"Could not initialize Monitor client (Activity Log unavailable): {e}")
            self._monitor_client = None
        logger.info("Initialized Azure Resource Graph client")

    async def close(self) -> None:
        """Close client"""
        if self._client:
            await self._client.close()

    def _build_query(self, since: datetime) -> str:
        """Build KQL query for resource changes"""
        query_parts = [
            "resources",
            f"| where timestamp >= datetime({since.isoformat()}Z)",
        ]

        # Filter by subscription
        if self.config.subscription_ids:
            sub_filter = " or ".join([f"subscriptionId == '{sid}'" for sid in self.config.subscription_ids])
            query_parts.append(f"| where {sub_filter}")

        # Filter by resource group
        if self.config.resource_groups:
            rg_filter = " or ".join([f"resourceGroup == '{rg}'" for rg in self.config.resource_groups])
            query_parts.append(f"| where {rg_filter}")

        # Filter by resource type
        if self.config.resource_types:
            type_filter = " or ".join([f"type == '{rt}'" for rt in self.config.resource_types])
            query_parts.append(f"| where {type_filter}")

        # Filter by location
        if self.config.locations:
            loc_filter = " or ".join([f"location == '{loc}'" for loc in self.config.locations])
            query_parts.append(f"| where {loc_filter}")

        # Filter by tags
        if self.config.required_tags:
            for key, value in self.config.required_tags.items():
                query_parts.append(f"| where tags['{key}'] == '{value}'")

        if self.config.excluded_tags:
            for key, value in self.config.excluded_tags.items():
                query_parts.append(f"| where tags['{key}'] != '{value}'")

        # Select relevant fields
        query_parts.append("""
        | project
            id,
            name,
            type,
            resourceGroup,
            subscriptionId,
            location,
            tags,
            properties,
            identity,
            sku,
            kind,
            managedBy,
            etag,
            timestamp,
            changedTime
        """)

        query_parts.append("| order by timestamp desc")

        return " ".join(query_parts)

    def _build_activity_log_query(self, since: datetime) -> str:
        """Build query for Azure Activity Log (for detailed change tracking)"""
        # This would query the Activity Log for detailed change events
        # Requires Log Analytics workspace with Activity Log analytics enabled
        return f"""
        AzureActivity
        | where TimeGenerated >= datetime({since.isoformat()}Z)
        | where OperationName has_any ("Write", "Delete", "Action")
        | where ActivityStatus == "Succeeded"
        | project
            TimeGenerated,
            OperationName,
            ResourceId,
            ResourceGroup,
            SubscriptionId,
            Caller,
            Category,
            Level,
            Properties,
            _ResourceId
        | order by TimeGenerated desc
        """

    async def query_resources(self, since: datetime) -> list[dict[str, Any]]:
        """Query Resource Graph for resources changed since timestamp"""
        if not self._client:
            await self.initialize()

        query = self._build_query(since)

        request = QueryRequest(
            query=query,
            subscriptions=self.config.subscription_ids if self.config.subscription_ids else None,
            options=QueryRequestOptions(
                result_format="objectArray",
                allow_partial_scopes=True,
            ),
        )

        try:
            response = self._client.resources(request)
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Resource Graph query failed: {e}")
            return []

    async def query_activity_log(self, since: datetime) -> list[dict[str, Any]]:
        """Query Activity Log for detailed change events"""
        if not self._monitor_client:
            logger.debug("Activity Log unavailable: no Monitor client")
            return []
        try:
            filter_str = f"eventTimestamp ge {since.isoformat()}Z"
            events = []
            # Activity Logs are retained for 90 days
            async for event in self._monitor_client.activity_logs.list(filter=filter_str):
                events.append(event.as_dict())
            logger.info(f"Activity Log: found {len(events)} events since {since}")
            return events
        except Exception as e:
            logger.error(f"Activity Log query failed: {e}")
            return []

    def resource_to_change_event(self, resource: dict[str, Any]) -> ChangeEvent | None:
        """Convert Resource Graph resource to ChangeEvent"""
        # Determine change type from properties
        # Resource Graph doesn't directly tell us the change type
        # We infer from the presence of certain fields or compare with previous state

        resource_id = resource.get("id", "")
        resource_type = resource.get("type", "")
        resource_name = resource.get("name", "")
        resource_group = resource.get("resourceGroup", "")
        subscription_id = resource.get("subscriptionId", "")
        location = resource.get("location", "")
        tags = resource.get("tags", {})
        properties = resource.get("properties", {})
        identity = resource.get("identity", {})
        etag = resource.get("etag", "")
        timestamp_str = resource.get("timestamp") or resource.get("changedTime")

        if not timestamp_str:
            timestamp = datetime.utcnow()
        else:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except:
                timestamp = datetime.utcnow()

        service_name = self._infer_service_name(resource)

        environment = self._infer_environment(resource)

        azure_change = AzureResourceChangeDetail(
            resource_id=resource_id,
            resource_type=resource_type,
            resource_group=resource_group,
            location=location,
            operation="UPDATE",  # Default, would need Activity Log for exact operation
            properties_delta=properties,
            tags_delta=tags,
            identity_delta=identity,
        )

        change_type = ChangeType.INFRASTRUCTURE_CHANGE

        return ChangeEvent(
            change_type=change_type,
            source=ChangeSource.AZURE_RESOURCE_GRAPH,
            status=ChangeStatus.SUCCEEDED,
            timestamp=timestamp,
            service_name=service_name,
            environment=environment,
            description=f"Azure resource change: {resource_type}/{resource_name}",
            summary=f"{resource_type} {resource_name} in {resource_group}",
            azure_resource_changes=[azure_change],
            labels={
                "azure.resource_id": resource_id,
                "azure.resource_type": resource_type,
                "azure.resource_group": resource_group,
                "azure.subscription_id": subscription_id,
                "azure.location": location,
                "azure.etag": etag,
            },
            correlation_id=resource_id,
        )

    def _infer_service_name(self, resource: dict[str, Any]) -> str:
        """Infer service name from resource"""
        # Try tags first
        tags = resource.get("tags", {})
        if "service" in tags:
            return tags["service"]
        if "app" in tags:
            return tags["app"]
        if "application" in tags:
            return tags["application"]
        if "workload" in tags:
            return tags["workload"]

        # Try resource name patterns
        name = resource.get("name", "")
        resource_type = resource.get("type", "")

        # Common patterns: service-name-xxx, xxx-service-name, etc.
        # Remove common suffixes/prefixes
        original_name = name
        for prefix in ["app-", "svc-", "service-", "workload-"]:
            if name.startswith(prefix):
                name = name[len(prefix):]

        for suffix in ["-app", "-svc", "-service", "-workload", "-prod", "-staging", "-dev"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]

        if name and name != original_name:
            return name

        # Use resource group as fallback
        rg = resource.get("resourceGroup", "")
        if rg and rg not in ["default", "production", "staging", "development"]:
            return rg

        # Last resort: resource type
        return resource_type.split("/")[-1].replace(".", "-")

    def _infer_environment(self, resource: dict[str, Any]) -> str:
        """Infer environment from resource tags or resource group"""
        tags = resource.get("tags", {})

        # Check common environment tags
        for tag_key in ["environment", "env", "stage", "tier"]:
            if tag_key in tags:
                value = tags[tag_key].lower()
                if value in ["prod", "production"]:
                    return "production"
                elif value in ["staging", "stage"]:
                    return "staging"
                elif value in ["dev", "development"]:
                    return "development"
                elif value in ["test", "testing"]:
                    return "test"

        # Check resource group name
        rg = resource.get("resourceGroup", "").lower()
        if "prod" in rg:
            return "production"
        elif "staging" in rg or "stage" in rg:
            return "staging"
        elif "dev" in rg:
            return "development"
        elif "test" in rg:
            return "test"

        return "production"

    async def poll_changes(self) -> list[ChangeEvent]:
        """Poll for resource changes since last query"""
        since = self._last_query_time
        if not since:
            since = datetime.utcnow() - timedelta(hours=self.config.lookback_hours)

        resources = await self.query_resources(since)

        events = []
        for resource in resources:
            event = self.resource_to_change_event(resource)
            if event:
                events.append(event)

        self._last_query_time = datetime.utcnow()

        logger.info(f"Polled Azure Resource Graph: found {len(events)} changes since {since}")
        return events

    async def start_polling(self) -> AsyncGenerator[ChangeEvent, None]:
        """Start continuous polling for changes"""
        while True:
            try:
                events = await self.poll_changes()
                for event in events:
                    yield event
            except Exception as e:
                logger.error(f"Error polling Azure Resource Graph: {e}")

            await asyncio.sleep(self.config.poll_interval_seconds)


async def create_azure_resource_graph_source(config: AzureResourceGraphConfig) -> AzureResourceGraphSource:
    """Factory function to create Azure Resource Graph source"""
    source = AzureResourceGraphSource(config)
    await source.initialize()
    return source
