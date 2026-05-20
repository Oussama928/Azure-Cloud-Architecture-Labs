"""
Terraform Source Collector for ChangeTrace

Collects change events from Terraform Cloud/Enterprise:
- Plan outputs (what will change)
- Apply results (what actually changed)
- Run events (started, completed, failed)

Parses Terraform plan JSON output to extract resource changes.
"""

import logging
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    ResourceReference,
    TerraformReference,
)

logger = logging.getLogger(__name__)


class TerraformConfig(BaseModel):
    """Configuration for Terraform source"""
    # Terraform Cloud/Enterprise
    hostname: str = "app.terraform.io"
    organization: str
    token: str  # API

    # Workspace filters
    workspaces: list[str] = Field(default_factory=list)  # Empty = all
    workspace_prefixes: list[str] = Field(default_factory=list)

    # Polling configuration
    poll_interval_seconds: int = 300  # 5 *60
    lookback_hours: int = 24

    # Event types
    collect_plans: bool = True
    collect_applies: bool = True
    collect_runs: bool = True


class TerraformRun(BaseModel):
    """Terraform run representation"""
    id: str
    workspace_id: str
    workspace_name: str
    status: str
    message: str | None = None
    created_at: datetime
    plan_id: str | None = None
    apply_id: str | None = None
    plan_json_api_url: str | None = None
    apply_json_api_url: str | None = None
    source: str  # "tfe-api", "cli", "vcs"
    trigger_reason: str
    actions: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)


class TerraformPlan(BaseModel):
    """Terraform plan representation"""
    id: str
    run_id: str
    status: str
    log_read_url: str | None = None
    json_output_url: str | None = None
    resource_changes: list[dict[str, Any]] = Field(default_factory=list)
    resource_drift: list[dict[str, Any]] = Field(default_factory=list)


class TerraformApply(BaseModel):
    """Terraform apply representation"""
    id: str
    run_id: str
    status: str
    log_read_url: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TerraformSource:
    """
    Terraform change event collector.

    Collects from Terraform Cloud/Enterprise API.
    Parses plan JSON to extract detailed resource changes.
    """

    def __init__(self, config: TerraformConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=f"https://{config.hostname}/api/v2",
            headers={
                "Authorization": f"Bearer {config.token}",
                "Content-Type": "application/vnd.api+json",
            },
            timeout=60.0,
        )
        self._last_poll_time: datetime | None = None

    async def close(self) -> None:
        """Close HTTP client"""
        await self._client.aclose()

    async def get_workspaces(self) -> list[dict[str, Any]]:
        """Get list of workspaces"""
        params = {"organization[name]": self.config.organization}
        if self.config.workspaces:
            params["filter[name]"] = ",".join(self.config.workspaces)

        response = await self._client.get("/workspaces", params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    async def get_runs(self, workspace_id: str, since: datetime | None = None) -> list[TerraformRun]:
        """Get runs for a workspace"""
        params = {
            "filter[workspace][id]": workspace_id,
            "page[size]": 100,
        }

        if since:
            params["filter[created-at]"] = since.isoformat() + "Z"

        response = await self._client.get("/runs", params=params)
        response.raise_for_status()
        data = response.json()

        runs = []
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            runs.append(TerraformRun(
                id=item["id"],
                workspace_id=attrs.get("workspace-id", ""),
                workspace_name=attrs.get("workspace-name", ""),
                status=attrs.get("status", ""),
                message=attrs.get("message"),
                created_at=datetime.fromisoformat(attrs.get("created-at", "").replace("Z", "+00:00")),
                plan_id=attrs.get("plan-id"),
                apply_id=attrs.get("apply-id"),
                plan_json_api_url=attrs.get("plan-json-api-url"),
                apply_json_api_url=attrs.get("apply-json-api-url"),
                source=attrs.get("source", ""),
                trigger_reason=attrs.get("trigger-reason", ""),
                actions=attrs.get("actions", {}),
                permissions=attrs.get("permissions", {}),
            ))

        return runs

    async def get_plan(self, plan_id: str) -> TerraformPlan | None:
        """Get plan details including JSON output"""
        # Get plan metadata
        response = await self._client.get(f"/plans/{plan_id}")
        response.raise_for_status()
        data = response.json()
        attrs = data.get("data", {}).get("attributes", {})

        plan = TerraformPlan(
            id=plan_id,
            run_id=attrs.get("run-id", ""),
            status=attrs.get("status", ""),
            log_read_url=attrs.get("log-read-url"),
            json_output_url=attrs.get("json-output-url"),
        )

        # Fetch JSON output if available
        if plan.json_output_url:
            try:
                plan_response = await self._client.get(plan.json_output_url)
                plan_response.raise_for_status()
                plan_json = plan_response.json()
                plan.resource_changes = plan_json.get("resource_changes", [])
                plan.resource_drift = plan_json.get("resource_drift", [])
            except Exception as e:
                logger.warning(f"Failed to fetch plan JSON for {plan_id}: {e}")

        return plan

    async def get_apply(self, apply_id: str) -> TerraformApply | None:
        """Get apply details"""
        response = await self._client.get(f"/applies/{apply_id}")
        response.raise_for_status()
        data = response.json()
        attrs = data.get("data", {}).get("attributes", {})

        return TerraformApply(
            id=apply_id,
            run_id=attrs.get("run-id", ""),
            status=attrs.get("status", ""),
            log_read_url=attrs.get("log-read-url"),
            started_at=datetime.fromisoformat(attrs.get("started-at", "").replace("Z", "+00:00")) if attrs.get("started-at") else None,
            finished_at=datetime.fromisoformat(attrs.get("finished-at", "").replace("Z", "+00:00")) if attrs.get("finished-at") else None,
        )

    def parse_plan_changes(self, plan: TerraformPlan) -> list[dict[str, Any]]:
        """Parse Terraform plan resource changes into structured format"""
        changes = []

        for rc in plan.resource_changes:
            change = rc.get("change", {})
            actions = change.get("actions", [])

            # Skip no-op changes
            if actions == ["no-op"]:
                continue

            # Determine operation
            if "create" in actions:
                operation = "CREATE"
            elif "delete" in actions:
                operation = "DELETE"
            elif "update" in actions:
                operation = "UPDATE"
            elif "read" in actions:
                operation = "READ"
            else:
                operation = actions[0].upper() if actions else "UNKNOWN"

            # Extract before/after
            before = change.get("before", {})
            after = change.get("after", {})
            before_sensitive = change.get("before_sensitive", {})
            after_sensitive = change.get("after_sensitive", {})

            # Build diff
            diff = {}
            all_keys = set(before.keys()) | set(after.keys())
            for key in all_keys:
                if before.get(key) != after.get(key):
                    diff[key] = {
                        "before": before.get(key),
                        "after": after.get(key),
                    }

            changes.append({
                "address": rc.get("address", ""),
                "type": rc.get("type", ""),
                "name": rc.get("name", ""),
                "provider": rc.get("provider_name", ""),
                "module": rc.get("module_address", ""),
                "operation": operation,
                "actions": actions,
                "before": before,
                "after": after,
                "diff": diff,
                "before_sensitive": before_sensitive,
                "after_sensitive": after_sensitive,
            })

        return changes

    def plan_to_change_events(self, plan: TerraformPlan, workspace_name: str) -> list[ChangeEvent]:
        """Convert Terraform plan to ChangeEvents"""
        events = []
        changes = self.parse_plan_changes(plan)

        if not changes:
            return events

        # Group changes by module/service
        service_changes: dict[str, list[dict]] = {}
        for change in changes:
            module = change.get("module", "root")
            service_name = self._extract_service_name(module, change)
            if service_name not in service_changes:
                service_changes[service_name] = []
            service_changes[service_name].append(change)

        # Create one event per service
        for service_name, svc_changes in service_changes.items():
            # Determine overall status
            status = ChangeStatus.SUCCEEDED
            if plan.status in ["errored", "canceled"]:
                status = ChangeStatus.FAILED
            elif plan.status == "pending":
                status = ChangeStatus.PENDING
            elif plan.status == "planned":
                status = ChangeStatus.IN_PROGRESS

            # Build resource references
            k8s_changes = []
            azure_changes = []

            for change in svc_changes:
                if change["provider"] and "kubernetes" in change["provider"]:
                    k8s_changes.append(self._build_k8s_change(change))
                elif change["provider"] and "azurerm" in change["provider"]:
                    azure_changes.append(self._build_azure_change(change))

            event = ChangeEvent(
                change_type=ChangeType.INFRASTRUCTURE_CHANGE,
                source=ChangeSource.TERRAFORM,
                status=status,
                timestamp=datetime.utcnow(),  # Plan creation time
                service_name=service_name,
                environment=self._extract_environment(workspace_name),
                description=f"Terraform plan with {len(svc_changes)} resource changes",
                summary=f"Terraform plan: {len(svc_changes)} changes for {service_name}",
                terraform=TerraformReference(
                    workspace=workspace_name,
                    plan_id=plan.id,
                    run_id=plan.run_id,
                    organization=self.config.organization,
                    module_addresses=list(set(c.get("module", "") for c in svc_changes)),
                    resource_changes=svc_changes,
                ),
                pipeline_name=f"terraform/{self.config.organization}/{workspace_name}",
                pipeline_run_id=plan.run_id,
                pipeline_url=f"https://{self.config.hostname}/app/{self.config.organization}/workspaces/{workspace_name}/runs/{plan.run_id}",
                labels={
                    "terraform.event": "plan",
                    "terraform.workspace": workspace_name,
                    "terraform.plan_id": plan.id,
                    "terraform.run_id": plan.run_id,
                    "terraform.status": plan.status,
                },
                correlation_id=plan.run_id,
            )
            events.append(event)

        return events

    def apply_to_change_events(self, apply: TerraformApply, plan: TerraformPlan, workspace_name: str) -> list[ChangeEvent]:
        """Convert Terraform apply to ChangeEvents"""
        events = []
        changes = self.parse_plan_changes(plan)

        if not changes:
            return events

        # Group changes by module/service
        service_changes: dict[str, list[dict]] = {}
        for change in changes:
            module = change.get("module", "root")
            service_name = self._extract_service_name(module, change)
            if service_name not in service_changes:
                service_changes[service_name] = []
            service_changes[service_name].append(change)

        # Determine status
        status = ChangeStatus.SUCCEEDED
        if apply.status in ["errored", "canceled"]:
            status = ChangeStatus.FAILED
        elif apply.status in ["applying", "pending"]:
            status = ChangeStatus.IN_PROGRESS

        # Create one event per service
        for service_name, svc_changes in service_changes.items():
            k8s_changes = []
            azure_changes = []

            for change in svc_changes:
                if change["provider"] and "kubernetes" in change["provider"]:
                    k8s_changes.append(self._build_k8s_change(change))
                elif change["provider"] and "azurerm" in change["provider"]:
                    azure_changes.append(self._build_azure_change(change))

            duration = None
            if apply.started_at and apply.finished_at:
                duration = (apply.finished_at - apply.started_at).total_seconds()

            event = ChangeEvent(
                change_type=ChangeType.INFRASTRUCTURE_CHANGE,
                source=ChangeSource.TERRAFORM,
                status=status,
                timestamp=apply.finished_at or apply.started_at or datetime.utcnow(),
                started_at=apply.started_at,
                completed_at=apply.finished_at,
                duration_seconds=duration,
                service_name=service_name,
                environment=self._extract_environment(workspace_name),
                description=f"Terraform apply with {len(svc_changes)} resource changes",
                summary=f"Terraform apply: {len(svc_changes)} changes for {service_name}",
                terraform=TerraformReference(
                    workspace=workspace_name,
                    plan_id=plan.id,
                    apply_id=apply.id,
                    run_id=apply.run_id,
                    organization=self.config.organization,
                    module_addresses=list(set(c.get("module", "") for c in svc_changes)),
                    resource_changes=svc_changes,
                ),
                pipeline_name=f"terraform/{self.config.organization}/{workspace_name}",
                pipeline_run_id=apply.run_id,
                pipeline_url=f"https://{self.config.hostname}/app/{self.config.organization}/workspaces/{workspace_name}/runs/{apply.run_id}",
                labels={
                    "terraform.event": "apply",
                    "terraform.workspace": workspace_name,
                    "terraform.apply_id": apply.id,
                    "terraform.run_id": apply.run_id,
                    "terraform.status": apply.status,
                },
                correlation_id=apply.run_id,
            )
            events.append(event)

        return events

    def _extract_service_name(self, module: str, change: dict[str, Any]) -> str:
        """Extract service name from module and change"""
        # Try to get from module path
        if module and module != "root":
            # Module path like "module.service-name" or "module.network.module.service-name"
            parts = module.split(".")
            for part in parts:
                if part.startswith("module."):
                    return part[7:]  # Remove "module."

        # Try to infer from resource address
        address = change.get("address", "")
        if address:
            # Address like "module.service-name.kubernetes_deployment.app"
            parts = address.split(".")
            for part in parts:
                if part.startswith("module."):
                    return part[7:]

        # Fallback to resource type
        resource_type = change.get("type", "")
        if resource_type:
            return resource_type.replace("_", "-")

        return "unknown-service"

    def _extract_environment(self, workspace_name: str) -> str:
        """Extract environment from workspace name"""
        workspace_lower = workspace_name.lower()

        if any(env in workspace_lower for env in ["prod", "production"]):
            return "production"
        elif any(env in workspace_lower for env in ["staging", "stage"]):
            return "staging"
        elif any(env in workspace_lower for env in ["dev", "development"]):
            return "development"
        elif any(env in workspace_lower for env in ["test", "testing"]):
            return "test"

        return "production"  # Default

    def _build_k8s_change(self, change: dict[str, Any]):
        """Build Kubernetes change detail from Terraform change"""
        from ..models.change_event import KubernetesChangeDetail

        address = change.get("address", "")
        parts = address.split(".")
        kind = parts[-1] if parts else "Unknown"
        name = change.get("name", "")

        return KubernetesChangeDetail(
            resource=ResourceReference(
                api_version="v1",
                kind=kind,
                name=name,
            ),
            operation=change.get("operation", "UNKNOWN"),
            diff=change.get("diff"),
            previous_manifest=change.get("before"),
            new_manifest=change.get("after"),
        )

    def _build_azure_change(self, change: dict[str, Any]):
        """Build Azure resource change detail from Terraform change"""
        from ..models.change_event import AzureResourceChangeDetail

        change.get("address", "")
        resource_type = change.get("type", "")

        # Extract resource ID from after state
        after = change.get("after", {})
        resource_id = after.get("id", "")

        return AzureResourceChangeDetail(
            resource_id=resource_id,
            resource_type=resource_type,
            resource_group=after.get("resource_group_name", ""),
            location=after.get("location", ""),
            operation=change.get("operation", "UNKNOWN"),
            properties_delta=change.get("diff"),
            tags_delta={k: v for k, v in change.get("diff", {}).items() if k.startswith("tags")},
        )

    async def poll_workspace(self, workspace_id: str, workspace_name: str) -> list[ChangeEvent]:
        """Poll a workspace for new runs"""
        since = self._last_poll_time
        if not since:
            from datetime import timedelta
            since = datetime.utcnow() - timedelta(hours=self.config.lookback_hours)

        events = []

        try:
            runs = await self.get_runs(workspace_id, since)

            for run in runs:
                # Get plan if available
                if run.plan_id and self.config.collect_plans:
                    plan = await self.get_plan(run.plan_id)
                    if plan:
                        events.extend(self.plan_to_change_events(plan, workspace_name))

                # Get apply if available
                if run.apply_id and self.config.collect_applies:
                    apply = await self.get_apply(run.apply_id)
                    if apply and run.plan_id:
                        plan = await self.get_plan(run.plan_id)
                        if plan:
                            events.extend(self.apply_to_change_events(apply, plan, workspace_name))

            self._last_poll_time = datetime.utcnow()

        except Exception as e:
            logger.error(f"Failed to poll workspace {workspace_name}: {e}")

        return events

    async def poll_all_workspaces(self) -> list[ChangeEvent]:
        """Poll all configured workspaces"""
        all_events = []

        workspaces = await self.get_workspaces()

        for ws in workspaces:
            ws_id = ws["id"]
            ws_name = ws["attributes"]["name"]

            # Check prefix filter
            if self.config.workspace_prefixes:
                if not any(ws_name.startswith(p) for p in self.config.workspace_prefixes):
                    continue

            events = await self.poll_workspace(ws_id, ws_name)
            all_events.extend(events)

        return all_events


async def create_terraform_source(config: TerraformConfig) -> TerraformSource:
    """Factory function to create Terraform source"""
    return TerraformSource(config)
