"""Tests for Collector Service - Change Event Models"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from services.collector.src.models.change_event import (
    AzureResourceChangeDetail,
    ChangeEvent,
    ChangeEventBatch,
    ChangeEventFilter,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    GitReference,
    KubernetesChangeDetail,
    ResourceReference,
    TerraformReference,
)


class TestChangeEventModels:
    """Test change event model validation and serialization"""

    def test_change_event_creation_minimal(self):
        """Test creating a minimal valid change event"""
        event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            service_name="payment-service",
        )

        assert event.change_type == ChangeType.CODE_DEPLOYMENT
        assert event.source == ChangeSource.GITHUB
        assert event.service_name == "payment-service"
        assert event.status == ChangeStatus.SUCCEEDED
        assert event.id is not None
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_change_event_service_name_validation(self):
        """Test service name validation"""
        # Valid service name
        event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            service_name="  payment-service  ",
        )
        assert event.service_name == "payment-service"

        # Invalid: empty service name
        with pytest.raises(ValidationError):
            ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.GITHUB,
                service_name="",
            )

    def test_change_event_environment_validation(self):
        """Test environment validation"""
        valid_envs = ["production", "prod", "staging", "stage", "development", "dev", "test"]

        for env in valid_envs:
            event = ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.GITHUB,
                service_name="test-service",
                environment=env,
            )
            assert event.environment == env.lower()

        # Invalid environment
        with pytest.raises(ValidationError):
            ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.GITHUB,
                service_name="test-service",
                environment="invalid-env",
            )

    def test_change_event_with_git_reference(self):
        """Test change event with Git reference"""
        git_ref = GitReference(
            repo_url="https://github.com/org/repo",
            repo_name="org/repo",
            commit_sha="abc123",
            commit_message="Fix bug",
            branch="main",
            author="John Doe",
            author_email="john@example.com",
        )

        event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            service_name="payment-service",
            git=git_ref,
        )

        assert event.git is not None
        assert event.git.commit_sha == "abc123"
        assert event.get_git_commit_sha() == "abc123"

    def test_change_event_with_terraform_reference(self):
        """Test change event with Terraform reference"""
        tf_ref = TerraformReference(
            workspace="production",
            plan_id="plan-123",
            apply_id="apply-456",
            run_id="run-789",
            organization="my-org",
            module_addresses=["module.network", "module.compute"],
        )

        event = ChangeEvent(
            change_type=ChangeType.INFRASTRUCTURE_CHANGE,
            source=ChangeSource.TERRAFORM,
            service_name="network",
            terraform=tf_ref,
        )

        assert event.terraform is not None
        assert event.terraform.workspace == "production"
        assert event.get_terraform_run_id() == "run-789"

    def test_change_event_with_kubernetes_changes(self):
        """Test change event with Kubernetes changes"""
        k8s_change = KubernetesChangeDetail(
            resource=ResourceReference(
                api_version="apps/v1",
                kind="Deployment",
                namespace="production",
                name="payment-service",
            ),
            operation="UPDATE",
            diff={"replicas": {"before": 3, "after": 5}},
        )

        event = ChangeEvent(
            change_type=ChangeType.CONFIG_CHANGE,
            source=ChangeSource.KUBERNETES,
            service_name="payment-service",
            kubernetes_changes=[k8s_change],
        )

        assert len(event.kubernetes_changes) == 1
        assert event.kubernetes_changes[0].resource.kind == "Deployment"
        assert "Deployment/payment-service" in event.get_kubernetes_resources()

    def test_change_event_with_azure_changes(self):
        """Test change event with Azure resource changes"""
        azure_change = AzureResourceChangeDetail(
            resource_id="/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_type="Microsoft.Compute/virtualMachines",
            resource_group="rg",
            location="eastus",
            operation="UPDATE",
            properties_delta={"vmSize": {"before": "Standard_D2s_v3", "after": "Standard_D4s_v3"}},
        )

        event = ChangeEvent(
            change_type=ChangeType.INFRASTRUCTURE_CHANGE,
            source=ChangeSource.AZURE_RESOURCE_GRAPH,
            service_name="compute",
            azure_resource_changes=[azure_change],
        )

        assert len(event.azure_resource_changes) == 1
        assert event.azure_resource_changes[0].resource_type == "Microsoft.Compute/virtualMachines"
        assert event.get_azure_resource_ids()[0] == azure_change.resource_id

    def test_change_event_to_gremlin_vertex(self):
        """Test conversion to Gremlin vertex properties"""
        event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            service_name="payment-service",
            environment="production",
            author="John Doe",
            description="Deploy v1.2.3",
            git=GitReference(
                repo_url="https://github.com/org/repo",
                repo_name="org/repo",
                commit_sha="abc123",
                branch="main",
            ),
        )

        vertex = event.to_gremlin_vertex()

        assert "id" not in vertex
        assert vertex["eventId"] == event.event_id
        assert vertex["eventId"] != event.id
        assert vertex["changeType"] == "code_deployment"
        assert vertex["source"] == "github"
        assert vertex["serviceName"] == "payment-service"
        assert vertex["environment"] == "production"
        assert vertex["author"] == "John Doe"
        assert vertex["git"] is not None

    def test_change_event_batch(self):
        """Test change event batch"""
        events = [
            ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.GITHUB,
                service_name=f"service-{i}",
            )
            for i in range(3)
        ]

        batch = ChangeEventBatch(
            events=events,
            source=ChangeSource.GITHUB,
        )

        assert len(batch) == 3
        assert batch.source == ChangeSource.GITHUB
        assert batch.batch_id is not None
        assert batch.received_at is not None

    def test_change_event_filter(self):
        """Test change event filter"""
        filter_obj = ChangeEventFilter(
            service_name="payment-service",
            environment="production",
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 12, 31),
            limit=50,
            offset=0,
        )

        assert filter_obj.service_name == "payment-service"
        assert filter_obj.limit == 50
        assert filter_obj.offset == 0


class TestResourceReference:
    """Test resource reference model"""

    def test_kubernetes_resource_reference(self):
        """Test Kubernetes resource reference"""
        ref = ResourceReference(
            api_version="apps/v1",
            kind="Deployment",
            namespace="production",
            name="payment-service",
            uid="abc-123",
            labels={"app": "payment-service", "version": "v1.2.3"},
            annotations={"deployment.kubernetes.io/revision": "5"},
        )

        assert ref.api_version == "apps/v1"
        assert ref.kind == "Deployment"
        assert ref.namespace == "production"
        assert ref.name == "payment-service"

    def test_azure_resource_reference(self):
        """Test Azure resource reference"""
        ref = ResourceReference(
            resource_id="/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Web/sites/app1",
            resource_type="Microsoft.Web/sites",
            resource_group="rg",
            name="app1",
        )

        assert ref.resource_id == "/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Web/sites/app1"
        assert ref.resource_type == "Microsoft.Web/sites"
        assert ref.resource_group == "rg"


class TestGitReference:
    """Test Git reference model"""

    def test_git_reference_commit(self):
        """Test Git reference for commit"""
        ref = GitReference(
            repo_url="https://github.com/org/repo",
            repo_name="org/repo",
            commit_sha="abc123def456",
            commit_message="Fix critical bug",
            branch="main",
            author="Jane Smith",
            author_email="jane@example.com",
            commit_url="https://github.com/org/repo/commit/abc123def456",
        )

        assert ref.commit_sha == "abc123def456"
        assert ref.branch == "main"
        assert ref.tag is None

    def test_git_reference_tag(self):
        """Test Git reference for tag/release"""
        ref = GitReference(
            repo_url="https://github.com/org/repo",
            repo_name="org/repo",
            tag="v1.2.3",
            commit_sha="abc123",
            author="Release Bot",
        )

        assert ref.tag == "v1.2.3"
        assert ref.commit_sha == "abc123"


class TestTerraformReference:
    """Test Terraform reference model"""

    def test_terraform_reference(self):
        """Test Terraform reference"""
        ref = TerraformReference(
            workspace="production",
            plan_id="plan-abc",
            apply_id="apply-def",
            run_id="run-ghi",
            organization="my-org",
            module_addresses=["module.network", "module.compute"],
            resource_changes=[
                {"address": "azurerm_resource_group.rg", "type": "azurerm_resource_group", "change": {"actions": ["create"]}},
            ],
        )

        assert ref.workspace == "production"
        assert ref.organization == "my-org"
        assert len(ref.module_addresses) == 2
        assert len(ref.resource_changes) == 1


class TestUpsertQuery:
    def test_upsert_query_dedupes_by_deployment_id(self):
        from services.collector.src.main import CollectorService, CollectorConfig

        svc = CollectorService(CollectorConfig())
        query = svc._build_upsert_query({
            "eventId": "evt-1",
            "serviceName": "checkout-service",
            "tenantId": "tenant-x",
            "deploymentId": "dep-050",
            "changeType": "code_deployment",
        })

        assert "fold().coalesce" in query
        assert "hasLabel('ChangeEvent')" in query
        assert "has('deploymentId', 'dep-050')" in query
        assert "addV('ChangeEvent')" in query
        # partition key must only appear on addV, never on the unfold update branch
        assert "unfold().property('serviceName'," not in query
        add_branch = query.split("addV('ChangeEvent')")[1]
        assert "property('serviceName', 'checkout-service')" in add_branch

    def test_upsert_query_falls_back_to_event_id(self):
        from services.collector.src.main import CollectorService, CollectorConfig

        svc = CollectorService(CollectorConfig())
        query = svc._build_upsert_query({
            "eventId": "evt-1",
            "serviceName": "checkout-service",
            "tenantId": "tenant-x",
            "changeType": "code_deployment",
        })

        assert "fold().coalesce" in query
        assert "has('tenantId', 'tenant-x')" in query
        assert "has('eventId', 'evt-1')" in query
        assert "addV('ChangeEvent')" in query

    def test_upsert_query_requires_tenant_id(self):
        from services.collector.src.main import CollectorService, CollectorConfig

        svc = CollectorService(CollectorConfig())
        with pytest.raises(ValueError, match="tenantId is required"):
            svc._build_upsert_query({"eventId": "evt-1", "serviceName": "checkout-service"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
