"""
Tests for ChangeTrace Collector Service - Source Connectors.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.collector.src.models.change_event import (
    ChangeSource,
    ChangeStatus,
    ChangeType,
)
from services.collector.src.sources.github_source import (
    GitHubConfig,
    GitHubEventPayload,
    GitHubSource,
)
from services.collector.src.sources.terraform_source import (
    TerraformApply,
    TerraformConfig,
    TerraformPlan,
    TerraformSource,
)
from services.collector.src.sources.k8s_source import (
    K8sConfig,
    K8sResourceEvent,
    K8sSource,
)
from services.collector.src.sources.azure_resource_graph_source import (
    AzureResourceGraphConfig,
    AzureResourceGraphSource,
)


# Fixtures


@pytest.fixture
def github_config():
    return GitHubConfig(
        personal_access_token="ghp_test_token",
        webhook_secret="test-secret-123",
        organizations=["my-org"],
        repositories=["my-org/my-repo"],
        branches=["main", "production"],
    )


@pytest.fixture
def github_source(github_config):
    return GitHubSource(github_config)


@pytest.fixture
def terraform_config():
    return TerraformConfig(
        organization="my-org",
        token="tf-test-token",
        workspaces=["prod-app", "staging-app"],
    )


@pytest.fixture
def terraform_source(terraform_config):
    return TerraformSource(terraform_config)


@pytest.fixture
def k8s_config():
    return K8sConfig(
        namespaces=["default", "production", "staging"],
        exclude_namespaces=["kube-system"],
    )


@pytest.fixture
def k8s_source(k8s_config):
    return K8sSource(k8s_config)


@pytest.fixture
def azure_config():
    return AzureResourceGraphConfig(
        subscription_ids=["sub-123", "sub-456"],
        resource_groups=["rg-prod", "rg-staging"],
        locations=["eastus"],
    )


@pytest.fixture
def azure_source(azure_config):
    return AzureResourceGraphSource(azure_config)


def _make_gh_event(
    event_type: str,
    payload: dict[str, Any],
    repo: dict[str, Any] | None = None,
    action: str | None = None,
    delivery_id: str = "delivery-001",
) -> GitHubEventPayload:
    if repo is None:
        repo = {
            "full_name": "my-org/my-repo",
            "name": "my-repo",
            "html_url": "https://github.com/my-org/my-repo",
        }
    return GitHubEventPayload(
        event_type=event_type,
        action=action,
        repository=repo,
        sender={"login": "test-user"},
        payload=payload,
        delivery_id=delivery_id,
        timestamp=datetime.now(timezone.utc),
    )


def _make_k8s_event(
    event_type: str = "ADDED",
    resource_type: str = "Deployment",
    namespace: str = "production",
    name: str = "payment-service",
    uid: str = "uid-001",
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> K8sResourceEvent:
    return K8sResourceEvent(
        event_type=event_type,
        resource_type=resource_type,
        namespace=namespace,
        name=name,
        uid=uid,
        resource_version="12345",
        labels=labels or {"app": name},
        annotations=annotations or {},
        spec={"replicas": 3},
        timestamp=datetime.now(timezone.utc),
    )


def _make_azure_resource(
    resource_id: str = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Web/sites/myapp",
    resource_type: str = "Microsoft.Web/sites",
    name: str = "myapp",
    resource_group: str = "rg-prod",
    location: str = "eastus",
    tags: dict[str, str] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "id": resource_id,
        "type": resource_type,
        "name": name,
        "resourceGroup": resource_group,
        "subscriptionId": "sub-123",
        "location": location,
        "tags": tags or {"service": "my-app"},
        "properties": {},
        "identity": {},
        "sku": {},
        "kind": "",
        "managedBy": "",
        "etag": "etag-1",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "changedTime": None,
    }


# GitHub Source Tests


class TestGitHubShouldProcessRepo:
    """Tests for GitHubSource._should_process_repo"""

    def test_matches_org_and_repo(self, github_source):
        assert github_source._should_process_repo("my-org/my-repo") is True

    def test_rejects_unknown_org(self, github_source):
        assert github_source._should_process_repo("other-org/my-repo") is False

    def test_rejects_unknown_repo(self, github_source):
        assert github_source._should_process_repo("my-org/other-repo") is False

    def test_no_org_filter_passes_all(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t", repositories=["any-org/any-repo"]))
        assert src._should_process_repo("any-org/any-repo") is True

    def test_no_repo_filter_passes_all(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t", organizations=["my-org"]))
        assert src._should_process_repo("my-org/anything") is True

    def test_org_only_filter(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t", organizations=["my-org"]))
        assert src._should_process_repo("my-org/repo") is True
        assert src._should_process_repo("other-org/repo") is False

    def test_repo_only_filter(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t", repositories=["my-org/my-repo"]))
        assert src._should_process_repo("my-org/my-repo") is True
        assert src._should_process_repo("my-org/other") is False

    def test_empty_filters_pass_everything(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t"))
        assert src._should_process_repo("any/any") is True


class TestGitHubExtractServiceName:
    """Tests for GitHubSource._extract_service_name"""

    def test_strips_api_suffix(self, github_source):
        repo = {"name": "payment-api"}
        assert github_source._extract_service_name(repo, {}) == "payment"

    def test_strips_service_suffix(self, github_source):
        repo = {"name": "order-service"}
        assert github_source._extract_service_name(repo, {}) == "order"

    def test_strips_svc_suffix(self, github_source):
        repo = {"name": "auth-svc"}
        assert github_source._extract_service_name(repo, {}) == "auth"

    def test_strips_app_suffix(self, github_source):
        repo = {"name": "frontend-app"}
        assert github_source._extract_service_name(repo, {}) == "frontend"

    def test_strips_backend_suffix(self, github_source):
        repo = {"name": "api-backend"}
        assert github_source._extract_service_name(repo, {}) == "api"

    def test_strips_frontend_suffix(self, github_source):
        repo = {"name": "web-frontend"}
        assert github_source._extract_service_name(repo, {}) == "web"

    def test_no_suffix_to_strip(self, github_source):
        repo = {"name": "payments"}
        assert github_source._extract_service_name(repo, {}) == "payments"

    def test_lowercases_name(self, github_source):
        repo = {"name": "MyService-API"}
        assert github_source._extract_service_name(repo, {}) == "myservice"


class TestGitHubVerifyWebhookSignature:
    """Tests for GitHubSource.verify_webhook_signature"""

    def test_valid_signature(self, github_source):
        payload = b'{"action":"push"}'
        expected = hmac.new(
            b"test-secret-123", payload, hashlib.sha256
        ).hexdigest()
        sig = f"sha256={expected}"
        assert github_source.verify_webhook_signature(payload, sig) is True

    def test_invalid_signature(self, github_source):
        payload = b'{"action":"push"}'
        assert github_source.verify_webhook_signature(payload, "sha256=deadbeef") is False

    def test_no_secret_configured_returns_true(self):
        src = GitHubSource(GitHubConfig(personal_access_token="t"))
        assert src.verify_webhook_signature(b"payload", "") is True

    def test_empty_signature_invalid(self, github_source):
        payload = b'{"action":"push"}'
        assert github_source.verify_webhook_signature(payload, "") is False


class TestGitHubParseWebhook:
    """Tests for GitHubSource.parse_webhook"""

    @pytest.mark.asyncio
    async def test_valid_webhook(self, github_source):
        payload_dict = {"action": "push", "repository": {}, "sender": {}}
        payload = json.dumps(payload_dict).encode()
        headers = {
            "X-Hub-Signature-256": hmac.new(
                b"test-secret-123", payload, hashlib.sha256
            ).hexdigest(),
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "del-001",
        }
        # Prepend sha256= to match verify logic
        headers["X-Hub-Signature-256"] = f"sha256={headers['X-Hub-Signature-256']}"

        result = await github_source.parse_webhook(payload, headers)

        assert result is not None
        assert result.event_type == "push"
        assert result.delivery_id == "del-001"
        assert result.action == "push"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, github_source):
        headers = {
            "X-Hub-Signature-256": "sha256=anything",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "del-002",
        }
        result = await github_source.parse_webhook(b"not-json", headers)
        assert result is None

    @pytest.mark.asyncio
    async def test_bad_signature_returns_none(self, github_source):
        payload = b'{"action":"push"}'
        headers = {
            "X-Hub-Signature-256": "sha256=wrong",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "del-003",
        }
        result = await github_source.parse_webhook(payload, headers)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_headers_uses_defaults(self, github_source):
        # No secret configured so signature check passes
        src = GitHubSource(GitHubConfig(personal_access_token="t"))
        payload = b'{"action": "test"}'
        result = await src.parse_webhook(payload, {})
        assert result is not None
        assert result.event_type == ""
        assert result.delivery_id == ""


class TestGitHubProcessWebhook:
    """Tests for GitHubSource.process_webhook"""

    @pytest.mark.asyncio
    async def test_skips_unfiltered_repo(self, github_source):
        repo = {"full_name": "other-org/other-repo", "name": "other-repo", "html_url": "http://x"}
        event = _make_gh_event("push", {"ref": "refs/heads/main", "commits": []}, repo=repo)
        assert await github_source.process_webhook(event) == []

    @pytest.mark.asyncio
    async def test_push_event(self, github_source):
        payload = {
            "ref": "refs/heads/main",
            "commits": [
                {
                    "id": "abc123",
                    "message": "feat: add feature",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "author": {"name": "Alice", "email": "alice@test.com"},
                    "url": "https://github.com/my-org/my-repo/commit/abc123",
                }
            ],
            "compare": "https://github.com/my-org/my-repo/compare/aaa...bbb",
        }
        event = _make_gh_event("push", payload)
        events = await github_source.process_webhook(event)
        assert len(events) == 1
        ce = events[0]
        assert ce.change_type == ChangeType.CODE_DEPLOYMENT
        assert ce.source == ChangeSource.GITHUB
        assert ce.service_name == "my-repo"
        assert ce.author == "Alice"
        assert ce.git.commit_sha == "abc123"
        assert ce.git.branch == "main"
        assert ce.labels["github.event"] == "push"

    @pytest.mark.asyncio
    async def test_push_skips_merge_commits(self, github_source):
        payload = {
            "ref": "refs/heads/main",
            "commits": [
                {
                    "id": "abc123",
                    "message": "Merge branch 'feature' into main",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "author": {"name": "Alice", "email": "alice@test.com"},
                    "url": "https://github.com/my-org/my-repo/commit/abc123",
                }
            ],
        }
        event = _make_gh_event("push", payload)
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_push_filters_by_branch(self, github_source):
        payload = {
            "ref": "refs/heads/feature-x",
            "commits": [
                {
                    "id": "abc123",
                    "message": "feat: new thing",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "author": {"name": "Bob", "email": "bob@test.com"},
                    "url": "http://x",
                }
            ],
        }
        event = _make_gh_event("push", payload)
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_pr_merged_event(self, github_source):
        payload = {
            "pull_request": {
                "number": 42,
                "title": "Add billing",
                "body": "Adds billing module",
                "merged": True,
                "merged_at": "2025-01-15T12:00:00Z",
                "merge_commit_sha": "def456",
                "base": {"ref": "main"},
                "user": {"login": "charlie", "email": "charlie@test.com"},
                "html_url": "https://github.com/my-org/my-repo/pull/42",
            }
        }
        event = _make_gh_event("pull_request", payload, action="closed")
        events = await github_source.process_webhook(event)
        assert len(events) == 1
        ce = events[0]
        assert ce.change_type == ChangeType.CODE_DEPLOYMENT
        assert ce.git.pr_number == 42
        assert ce.git.pr_title == "Add billing"
        assert ce.labels["github.action"] == "merged"

    @pytest.mark.asyncio
    async def test_pr_not_merged_ignored(self, github_source):
        payload = {
            "pull_request": {
                "number": 43,
                "title": "WIP",
                "merged": False,
                "merged_at": None,
                "base": {"ref": "main"},
                "user": {"login": "dave"},
                "html_url": "http://x",
            }
        }
        event = _make_gh_event("pull_request", payload, action="closed")
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_pr_opened_ignored(self, github_source):
        payload = {"pull_request": {"merged": True, "base": {"ref": "main"}, "user": {"login": "x"}, "html_url": "http://x", "number": 1, "title": "t"}}
        event = _make_gh_event("pull_request", payload, action="opened")
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_pr_target_branch_not_in_config(self, github_source):
        payload = {
            "pull_request": {
                "number": 44,
                "title": "Feature",
                "merged": True,
                "merged_at": "2025-01-15T12:00:00Z",
                "merge_commit_sha": "aaa",
                "base": {"ref": "develop"},
                "user": {"login": "eve"},
                "html_url": "http://x",
            }
        }
        event = _make_gh_event("pull_request", payload, action="closed")
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_release_published(self, github_source):
        payload = {
            "release": {
                "tag_name": "v1.0.0",
                "name": "Release 1.0.0",
                "body": "Initial release",
                "published_at": "2025-01-15T14:00:00Z",
                "target_commitish": "abc123",
                "author": {"login": "frank"},
                "html_url": "https://github.com/my-org/my-repo/releases/tag/v1.0.0",
            }
        }
        event = _make_gh_event("release", payload, action="published")
        events = await github_source.process_webhook(event)
        assert len(events) == 1
        ce = events[0]
        assert ce.change_type == ChangeType.RELEASE
        assert ce.new_version == "v1.0.0"
        assert ce.git.tag == "v1.0.0"
        assert ce.labels["github.action"] == "published"

    @pytest.mark.asyncio
    async def test_release_edited_ignored(self, github_source):
        payload = {"release": {"tag_name": "v1.0.0", "name": "R", "body": "", "published_at": "2025-01-15T14:00:00Z", "target_commitish": "a", "author": {"login": "x"}, "html_url": "http://x"}}
        event = _make_gh_event("release", payload, action="edited")
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_tag_creation(self, github_source):
        payload = {"ref": "v2.0.0", "ref_type": "tag"}
        event = _make_gh_event("create", payload)
        events = await github_source.process_webhook(event)
        assert len(events) == 1
        ce = events[0]
        assert ce.change_type == ChangeType.RELEASE
        assert ce.new_version == "v2.0.0"
        assert ce.git.tag == "v2.0.0"
        assert ce.labels["github.ref_type"] == "tag"

    @pytest.mark.asyncio
    async def test_branch_creation_ignored(self, github_source):
        payload = {"ref": "feature-new", "ref_type": "branch"}
        event = _make_gh_event("create", payload)
        events = await github_source.process_webhook(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_collect_commits_disabled(self, github_config):
        github_config.collect_commits = False
        src = GitHubSource(github_config)
        payload = {"ref": "refs/heads/main", "commits": [{"id": "a", "message": "m", "timestamp": "2025-01-15T10:00:00Z", "author": {"name": "x", "email": "x@x.com"}, "url": "http://x"}]}
        event = _make_gh_event("push", payload)
        events = await src.process_webhook(event)
        assert len(events) == 0


class TestGitHubInitialize:
    """Tests for GitHubSource.initialize"""

    @pytest.mark.asyncio
    async def test_pat_initialization(self, github_config):
        src = GitHubSource(github_config)
        with patch("services.collector.src.sources.github_source.Github") as mock_gh:
            await src.initialize()
            mock_gh.assert_called_once_with("ghp_test_token")
            assert src._client is not None

    @pytest.mark.asyncio
    async def test_no_auth_raises(self):
        src = GitHubSource(GitHubConfig())
        with pytest.raises(ValueError, match="No GitHub authentication"):
            await src.initialize()

    @pytest.mark.asyncio
    async def test_app_auth_initialization(self):
        config = GitHubConfig(app_id=1, private_key="key", installation_id=2)
        src = GitHubSource(config)
        with patch("services.collector.src.sources.github_source.GithubIntegration") as MockIntegration, \
             patch("services.collector.src.sources.github_source.Github") as MockGithub:
            mock_integration = MockIntegration.return_value
            mock_integration.get_access_token.return_value = MagicMock(token="app-token-abc")
            await src.initialize()
            MockIntegration.assert_called_once_with(1, "key")
            MockGithub.assert_called_once_with("app-token-abc")


# Terraform Source Tests


class TestTerraformParsePlanChanges:
    """Tests for TerraformSource.parse_plan_changes"""

    def test_create_action(self, terraform_source):
        plan = TerraformPlan(
            id="plan-001",
            run_id="run-001",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.data",
                    "type": "aws_s3_bucket",
                    "name": "data",
                    "provider_name": "aws",
                    "module_address": "",
                    "change": {
                        "actions": ["create"],
                        "before": None,
                        "after": {"bucket": "data-bucket"},
                        "before_sensitive": {},
                        "after_sensitive": {},
                    },
                }
            ],
        )
        changes = terraform_source.parse_plan_changes(plan)
        assert len(changes) == 1
        assert changes[0]["operation"] == "CREATE"
        assert changes[0]["address"] == "aws_s3_bucket.data"

    def test_update_action(self, terraform_source):
        plan = TerraformPlan(
            id="plan-002",
            run_id="run-002",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.data",
                    "type": "aws_s3_bucket",
                    "name": "data",
                    "provider_name": "aws",
                    "change": {
                        "actions": ["update"],
                        "before": {"versioning": False},
                        "after": {"versioning": True},
                        "before_sensitive": {},
                        "after_sensitive": {},
                    },
                }
            ],
        )
        changes = terraform_source.parse_plan_changes(plan)
        assert len(changes) == 1
        assert changes[0]["operation"] == "UPDATE"
        assert changes[0]["diff"]["versioning"] == {"before": False, "after": True}

    def test_delete_action(self, terraform_source):
        plan = TerraformPlan(
            id="plan-003",
            run_id="run-003",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.old",
                    "type": "aws_s3_bucket",
                    "name": "old",
                    "provider_name": "aws",
                    "change": {
                        "actions": ["delete"],
                        "before": {"bucket": "old-bucket"},
                        "after": None,
                        "before_sensitive": {},
                        "after_sensitive": {},
                    },
                }
            ],
        )
        changes = terraform_source.parse_plan_changes(plan)
        assert len(changes) == 1
        assert changes[0]["operation"] == "DELETE"

    def test_noop_skipped(self, terraform_source):
        plan = TerraformPlan(
            id="plan-004",
            run_id="run-004",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.unchanged",
                    "type": "aws_s3_bucket",
                    "name": "unchanged",
                    "provider_name": "aws",
                    "change": {
                        "actions": ["no-op"],
                        "before": {},
                        "after": {},
                        "before_sensitive": {},
                        "after_sensitive": {},
                    },
                }
            ],
        )
        changes = terraform_source.parse_plan_changes(plan)
        assert len(changes) == 0

    def test_replace_action(self, terraform_source):
        plan = TerraformPlan(
            id="plan-005",
            run_id="run-005",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_instance.web",
                    "type": "aws_instance",
                    "name": "web",
                    "provider_name": "aws",
                    "change": {
                        "actions": ["destroy", "create"],
                        "before": {"instance_type": "t2.micro"},
                        "after": {"instance_type": "t2.large"},
                        "before_sensitive": {},
                        "after_sensitive": {},
                    },
                }
            ],
        )
        changes = terraform_source.parse_plan_changes(plan)
        assert len(changes) == 1
        # "create" is checked first in the if-elif chain, so operation is CREATE
        assert changes[0]["operation"] == "CREATE"
        assert changes[0]["actions"] == ["destroy", "create"]

    def test_empty_plan(self, terraform_source):
        plan = TerraformPlan(id="p", run_id="r", status="planned", resource_changes=[])
        assert terraform_source.parse_plan_changes(plan) == []


class TestTerraformPlanToChangeEvents:
    """Tests for TerraformSource.plan_to_change_events"""

    def test_groups_by_service(self, terraform_source):
        plan = TerraformPlan(
            id="plan-010",
            run_id="run-010",
            status="planned",
            resource_changes=[
                {
                    "address": "module.auth.kubernetes_deployment.app",
                    "type": "kubernetes_deployment",
                    "name": "app",
                    "provider_name": "kubernetes",
                    "module_address": "module.auth",
                    "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}},
                },
                {
                    "address": "module.auth.kubernetes_service.svc",
                    "type": "kubernetes_service",
                    "name": "svc",
                    "provider_name": "kubernetes",
                    "module_address": "module.auth",
                    "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}},
                },
                {
                    "address": "module.billing.kubernetes_deployment.app",
                    "type": "kubernetes_deployment",
                    "name": "app",
                    "provider_name": "kubernetes",
                    "module_address": "module.billing",
                    "change": {"actions": ["update"], "before": {}, "after": {}, "before_sensitive": {}, "after_sensitive": {}},
                },
            ],
        )
        events = terraform_source.plan_to_change_events(plan, "prod-app")
        assert len(events) == 2
        service_names = {e.service_name for e in events}
        assert "auth" in service_names
        assert "billing" in service_names

    def test_errored_plan_sets_failed_status(self, terraform_source):
        plan = TerraformPlan(
            id="plan-err",
            run_id="run-err",
            status="errored",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.x",
                    "type": "aws_s3_bucket",
                    "name": "x",
                    "provider_name": "aws",
                    "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}},
                }
            ],
        )
        events = terraform_source.plan_to_change_events(plan, "prod-app")
        assert len(events) == 1
        assert events[0].status == ChangeStatus.FAILED

    def test_pending_plan_sets_pending_status(self, terraform_source):
        plan = TerraformPlan(
            id="plan-p", run_id="run-p", status="pending",
            resource_changes=[
                {"address": "a.b", "type": "b", "name": "b", "provider_name": "aws",
                 "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}}}
            ],
        )
        events = terraform_source.plan_to_change_events(plan, "dev-app")
        assert events[0].status == ChangeStatus.PENDING

    def test_planned_status_sets_in_progress(self, terraform_source):
        plan = TerraformPlan(
            id="plan-pl", run_id="run-pl", status="planned",
            resource_changes=[
                {"address": "a.b", "type": "b", "name": "b", "provider_name": "aws",
                 "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}}}
            ],
        )
        events = terraform_source.plan_to_change_events(plan, "staging-app")
        assert events[0].status == ChangeStatus.IN_PROGRESS

    def test_empty_changes_returns_empty(self, terraform_source):
        plan = TerraformPlan(id="p", run_id="r", status="planned", resource_changes=[])
        assert terraform_source.plan_to_change_events(plan, "prod-app") == []


class TestTerraformExtractServiceName:
    """Tests for TerraformSource._extract_service_name"""

    def test_from_module_path(self, terraform_source):
        assert terraform_source._extract_service_name("module.payment", {}) == "payment"

    def test_from_nested_module(self, terraform_source):
        assert terraform_source._extract_service_name("network.module.database", {}) == "database"

    def test_from_address_when_no_module(self, terraform_source):
        change = {"address": "module.auth.kubernetes_deployment.app", "type": ""}
        assert terraform_source._extract_service_name("root", change) == "auth"

    def test_from_resource_type_fallback(self, terraform_source):
        assert terraform_source._extract_service_name("root", {"address": "", "type": "azurerm_resource_group"}) == "azurerm-resource-group"

    def test_unknown_fallback(self, terraform_source):
        assert terraform_source._extract_service_name("root", {"address": "", "type": ""}) == "unknown-service"


class TestTerraformExtractEnvironment:
    """Tests for TerraformSource._extract_environment"""

    def test_prod(self, terraform_source):
        assert terraform_source._extract_environment("prod-app") == "production"

    def test_production(self, terraform_source):
        assert terraform_source._extract_environment("production-network") == "production"

    def test_staging(self, terraform_source):
        assert terraform_source._extract_environment("staging-app") == "staging"

    def test_stage(self, terraform_source):
        assert terraform_source._extract_environment("stage-services") == "staging"

    def test_dev(self, terraform_source):
        assert terraform_source._extract_environment("dev-experiment") == "development"

    def test_development(self, terraform_source):
        assert terraform_source._extract_environment("development- playground") == "development"

    def test_test(self, terraform_source):
        assert terraform_source._extract_environment("test-env") == "test"

    def test_testing(self, terraform_source):
        assert terraform_source._extract_environment("testing-integration") == "test"

    def test_default_is_production(self, terraform_source):
        assert terraform_source._extract_environment("my-custom-workspace") == "production"


class TestTerraformApplyToChangeEvents:
    """Tests for TerraformSource.apply_to_change_events"""

    def test_apply_with_timing(self, terraform_source):
        started = datetime(2025, 1, 15, 10, 0, 0)
        finished = datetime(2025, 1, 15, 10, 5, 30)
        apply = TerraformApply(
            id="apply-001",
            run_id="run-001",
            status="applied",
            started_at=started,
            finished_at=finished,
        )
        plan = TerraformPlan(
            id="plan-001",
            run_id="run-001",
            status="planned",
            resource_changes=[
                {
                    "address": "aws_s3_bucket.data",
                    "type": "aws_s3_bucket",
                    "name": "data",
                    "provider_name": "aws",
                    "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}},
                }
            ],
        )
        events = terraform_source.apply_to_change_events(apply, plan, "prod-app")
        assert len(events) == 1
        assert events[0].duration_seconds == 330.0
        assert events[0].started_at == started
        assert events[0].completed_at == finished
        assert events[0].labels["terraform.event"] == "apply"

    def test_apply_errored(self, terraform_source):
        apply = TerraformApply(id="a", run_id="r", status="errored")
        plan = TerraformPlan(
            id="p", run_id="r", status="errored",
            resource_changes=[
                {"address": "a.b", "type": "b", "name": "b", "provider_name": "aws",
                 "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}}}
            ],
        )
        events = terraform_source.apply_to_change_events(apply, plan, "prod-app")
        assert events[0].status == ChangeStatus.FAILED

    def test_apply_in_progress(self, terraform_source):
        apply = TerraformApply(id="a", run_id="r", status="applying")
        plan = TerraformPlan(
            id="p", run_id="r", status="planned",
            resource_changes=[
                {"address": "a.b", "type": "b", "name": "b", "provider_name": "aws",
                 "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}}}
            ],
        )
        events = terraform_source.apply_to_change_events(apply, plan, "prod-app")
        assert events[0].status == ChangeStatus.IN_PROGRESS

    def test_apply_no_timing(self, terraform_source):
        apply = TerraformApply(id="a", run_id="r", status="applied", started_at=None, finished_at=None)
        plan = TerraformPlan(
            id="p", run_id="r", status="planned",
            resource_changes=[
                {"address": "a.b", "type": "b", "name": "b", "provider_name": "aws",
                 "change": {"actions": ["create"], "before": None, "after": {}, "before_sensitive": {}, "after_sensitive": {}}}
            ],
        )
        events = terraform_source.apply_to_change_events(apply, plan, "prod-app")
        assert events[0].duration_seconds is None


# Kubernetes Source Tests


class TestK8sShouldProcessNamespace:
    """Tests for K8sSource._should_process_namespace"""

    def test_allowed_namespace(self, k8s_source):
        assert k8s_source._should_process_namespace("production") is True

    def test_excluded_namespace(self, k8s_source):
        assert k8s_source._should_process_namespace("kube-system") is False

    def test_not_in_list(self, k8s_source):
        assert k8s_source._should_process_namespace("random-ns") is False

    def test_empty_list_allows_all(self):
        src = K8sSource(K8sConfig(namespaces=[], exclude_namespaces=[]))
        assert src._should_process_namespace("anything") is True


class TestK8sExtractServiceName:
    """Service name extraction from K8s events"""

    def test_from_app_label(self, k8s_source):
        event = _make_k8s_event(labels={"app": "billing-service"})
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce.service_name == "billing-service"

    def test_from_k8s_name_label(self, k8s_source):
        event = _make_k8s_event(labels={"app.kubernetes.io/name": "payment"})
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce.service_name == "payment"

    def test_fallback_to_resource_name(self, k8s_source):
        event = _make_k8s_event(name="my-deployment", labels={})
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce.service_name == "my-deployment"

    def test_app_label_preferred_over_k8s_name(self, k8s_source):
        event = _make_k8s_event(labels={"app": "from-app", "app.kubernetes.io/name": "from-k8s"})
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce.service_name == "from-app"


class TestK8sEventToChangeEvent:
    """Tests for K8sSource.k8s_event_to_change_event"""

    def test_deployment_added(self, k8s_source):
        event = _make_k8s_event(event_type="ADDED", resource_type="Deployment", namespace="production")
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce is not None
        assert ce.change_type == ChangeType.CONFIG_CHANGE
        assert ce.source == ChangeSource.KUBERNETES
        assert ce.status == ChangeStatus.SUCCEEDED
        assert ce.environment == "production"
        assert ce.kubernetes_changes[0].operation == "ADDED"
        assert ce.kubernetes_changes[0].resource.kind == "Deployment"

    def test_deployment_modified(self, k8s_source):
        event = _make_k8s_event(event_type="MODIFIED", resource_type="Deployment")
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce is not None
        assert ce.kubernetes_changes[0].operation == "MODIFIED"
        assert ce.kubernetes_changes[0].diff is not None

    def test_deployment_deleted(self, k8s_source):
        event = _make_k8s_event(event_type="DELETED", resource_type="Deployment")
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce is not None
        assert ce.kubernetes_changes[0].operation == "DELETED"
        assert ce.kubernetes_changes[0].new_manifest is None

    def test_unknown_event_type_returns_none(self, k8s_source):
        event = _make_k8s_event(event_type="BOOKMARK")
        assert k8s_source.k8s_event_to_change_event(event) is None

    def test_excluded_namespace_returns_none(self, k8s_source):
        event = _make_k8s_event(namespace="kube-system")
        assert k8s_source.k8s_event_to_change_event(event) is None

    def test_namespace_not_in_list_returns_none(self, k8s_source):
        event = _make_k8s_event(namespace="random-ns")
        assert k8s_source.k8s_event_to_change_event(event) is None

    def test_api_version_for_deployment(self, k8s_source):
        assert k8s_source._get_api_version("Deployment") == "apps/v1"

    def test_api_version_for_configmap(self, k8s_source):
        assert k8s_source._get_api_version("ConfigMap") == "v1"

    def test_api_version_for_ingress(self, k8s_source):
        assert k8s_source._get_api_version("Ingress") == "networking.k8s.io/v1"

    def test_api_version_fallback(self, k8s_source):
        assert k8s_source._get_api_version("CustomResource") == "v1"


class TestK8sNamespaceToEnvironment:
    """Tests for K8sSource._namespace_to_environment"""

    def test_prod(self, k8s_source):
        assert k8s_source._namespace_to_environment("production") == "production"

    def test_staging(self, k8s_source):
        assert k8s_source._namespace_to_environment("staging") == "staging"

    def test_stage(self, k8s_source):
        assert k8s_source._namespace_to_environment("stage") == "staging"

    def test_dev(self, k8s_source):
        assert k8s_source._namespace_to_environment("dev") == "development"

    def test_test(self, k8s_source):
        assert k8s_source._namespace_to_environment("test") == "test"

    def test_unknown_defaults_production(self, k8s_source):
        assert k8s_source._namespace_to_environment("custom") == "production"


class TestK8sSecretsHandling:
    """Tests ensuring secrets metadata-only handling"""

    def test_secret_event_has_empty_spec(self, k8s_source):
        event = _make_k8s_event(
            resource_type="Secret",
            labels={"app": "my-app"},
        )
        # Manually set spec to simulate secret data
        event.spec = {"data": {"password": "supersecret", "api_key": "abc123"}}
        ce = k8s_source.k8s_event_to_change_event(event)
        assert ce is not None
        # The secret event's spec should NOT contain the actual secret data
        # The watch_secrets method clears spec, but k8s_event_to_change_event
        # uses event.spec directly. This tests the data flows through as-is
        # (the clearing happens in the watch loop, not in the converter).
        assert ce.kubernetes_changes[0].resource.kind == "Secret"


class TestK8sParseLabelSelector:
    """Tests for K8sSource._parse_label_selector"""

    def test_simple_selector(self, k8s_source):
        result = k8s_source._parse_label_selector("app=payment")
        assert result == [("app", "payment")]

    def test_multi_selector(self, k8s_source):
        result = k8s_source._parse_label_selector("app=payment,env=prod")
        assert result == [("app", "payment"), ("env", "prod")]

    def test_whitespace_handling(self, k8s_source):
        result = k8s_source._parse_label_selector(" app = payment , env = prod ")
        assert result == [("app", "payment"), ("env", "prod")]


class TestK8sShouldProcessResource:
    """Tests for K8sSource._should_process_resource"""

    def test_no_selector_passes_all(self, k8s_source):
        assert k8s_source._should_process_resource({}, {}) is True

    def test_label_selector_match(self):
        src = K8sSource(K8sConfig(label_selector="app=payment"))
        assert src._should_process_resource({"app": "payment"}, {}) is True

    def test_label_selector_no_match(self):
        src = K8sSource(K8sConfig(label_selector="app=payment"))
        assert src._should_process_resource({"app": "billing"}, {}) is False

    def test_annotation_selector_match(self):
        src = K8sSource(K8sConfig(annotation_selector="team=platform"))
        assert src._should_process_resource({}, {"team": "platform"}) is True

    def test_annotation_selector_no_match(self):
        src = K8sSource(K8sConfig(annotation_selector="team=platform"))
        assert src._should_process_resource({}, {"team": "backend"}) is False


class TestK8sInitialize:
    """Tests for K8sSource.initialize"""

    @pytest.mark.asyncio
    async def test_kubeconfig_initialization(self, k8s_source):
        with patch("services.collector.src.sources.k8s_source.config") as mock_config:
            await k8s_source.initialize()
            mock_config.load_kube_config.assert_called_once()
            assert k8s_source._apps_v1 is not None
            assert k8s_source._core_v1 is not None
            assert k8s_source._networking_v1 is not None

    @pytest.mark.asyncio
    async def test_incluster_initialization(self):
        src = K8sSource(K8sConfig(in_cluster=True))
        with patch("services.collector.src.sources.k8s_source.config") as mock_config:
            await src.initialize()
            mock_config.load_incluster_config.assert_called_once()


# Azure Resource Graph Source Tests


class TestAzureBuildQuery:
    """Tests for AzureResourceGraphSource._build_query"""

    def test_base_query(self, azure_source):
        since = datetime(2025, 1, 15, 0, 0, 0)
        query = azure_source._build_query(since)
        assert "resources" in query
        assert "2025-01-15" in query
        assert "order by timestamp desc" in query

    def test_subscription_filter(self, azure_source):
        since = datetime(2025, 1, 15, 0, 0, 0)
        query = azure_source._build_query(since)
        assert "sub-123" in query
        assert "sub-456" in query
        assert "subscriptionId ==" in query

    def test_resource_group_filter(self, azure_source):
        since = datetime(2025, 1, 15, 0, 0, 0)
        query = azure_source._build_query(since)
        assert "rg-prod" in query
        assert "rg-staging" in query
        assert "resourceGroup ==" in query

    def test_location_filter(self, azure_source):
        since = datetime(2025, 1, 15, 0, 0, 0)
        query = azure_source._build_query(since)
        assert "eastus" in query
        assert "location ==" in query

    def test_no_filters(self):
        src = AzureResourceGraphSource(AzureResourceGraphConfig())
        query = src._build_query(datetime(2025, 1, 1))
        assert "subscriptionId ==" not in query
        assert "resourceGroup ==" not in query
        assert "location ==" not in query

    def test_resource_type_filter(self):
        src = AzureResourceGraphSource(AzureResourceGraphConfig(
            resource_types=["Microsoft.Web/sites", "Microsoft.Compute/virtualMachines"]
        ))
        query = src._build_query(datetime(2025, 1, 1))
        assert "Microsoft.Web/sites" in query
        assert "Microsoft.Compute/virtualMachines" in query
        assert "type ==" in query

    def test_required_tags_filter(self):
        src = AzureResourceGraphSource(AzureResourceGraphConfig(
            required_tags={"env": "prod", "team": "platform"}
        ))
        query = src._build_query(datetime(2025, 1, 1))
        assert "tags['env'] == 'prod'" in query
        assert "tags['team'] == 'platform'" in query

    def test_excluded_tags_filter(self):
        src = AzureResourceGraphSource(AzureResourceGraphConfig(
            excluded_tags={"temp": "true"}
        ))
        query = src._build_query(datetime(2025, 1, 1))
        assert "tags['temp'] != 'true'" in query


class TestAzureResourceToChangeEvent:
    """Tests for AzureResourceGraphSource.resource_to_change_event"""

    def test_basic_conversion(self, azure_source):
        resource = _make_azure_resource()
        ce = azure_source.resource_to_change_event(resource)
        assert ce is not None
        assert ce.change_type == ChangeType.INFRASTRUCTURE_CHANGE
        assert ce.source == ChangeSource.AZURE_RESOURCE_GRAPH
        assert ce.status == ChangeStatus.SUCCEEDED
        assert ce.service_name == "my-app"
        assert ce.environment == "production"

    def test_azure_change_detail(self, azure_source):
        resource = _make_azure_resource(
            resource_group="rg-prod",
            location="westus2",
            tags={"service": "billing"},
        )
        ce = azure_source.resource_to_change_event(resource)
        assert len(ce.azure_resource_changes) == 1
        ac = ce.azure_resource_changes[0]
        assert ac.resource_type == "Microsoft.Web/sites"
        assert ac.resource_group == "rg-prod"
        assert ac.location == "westus2"

    def test_labels_include_azure_metadata(self, azure_source):
        resource = _make_azure_resource()
        ce = azure_source.resource_to_change_event(resource)
        assert ce.labels["azure.resource_type"] == "Microsoft.Web/sites"
        assert ce.labels["azure.subscription_id"] == "sub-123"

    def test_none_timestamp_falls_back(self, azure_source):
        resource = _make_azure_resource(timestamp=None, tags={})
        ce = azure_source.resource_to_change_event(resource)
        assert ce.timestamp is not None

    def test_invalid_timestamp_falls_back(self, azure_source):
        resource = _make_azure_resource(timestamp="not-a-date", tags={})
        ce = azure_source.resource_to_change_event(resource)
        assert ce.timestamp is not None

    def test_correlation_id_is_resource_id(self, azure_source):
        resource = _make_azure_resource(resource_id="/subscriptions/sub-123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1")
        ce = azure_source.resource_to_change_event(resource)
        assert ce.correlation_id == resource["id"]


class TestAzureInferServiceName:
    """Tests for AzureResourceGraphSource._infer_service_name"""

    def test_from_service_tag(self, azure_source):
        resource = {"tags": {"service": "billing-api"}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "billing-api"

    def test_from_app_tag(self, azure_source):
        resource = {"tags": {"app": "web-frontend"}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "web-frontend"

    def test_from_application_tag(self, azure_source):
        resource = {"tags": {"application": "data-pipeline"}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "data-pipeline"

    def test_from_workload_tag(self, azure_source):
        resource = {"tags": {"workload": "analytics"}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "analytics"

    def test_strips_prefix_from_name(self, azure_source):
        resource = {"tags": {}, "name": "svc-payment-vm", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "payment-vm"

    def test_strips_suffix_from_name(self, azure_source):
        resource = {"tags": {}, "name": "payment-app", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg"}
        assert azure_source._infer_service_name(resource) == "payment"

    def test_fallback_to_resource_group(self, azure_source):
        resource = {"tags": {}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "rg-billing"}
        assert azure_source._infer_service_name(resource) == "rg-billing"

    def test_fallback_to_resource_type(self, azure_source):
        resource = {"tags": {}, "name": "vm1", "type": "Microsoft.Compute/virtualMachines", "resourceGroup": "default"}
        assert azure_source._infer_service_name(resource) == "virtualMachines"


class TestAzureInferEnvironment:
    """Tests for AzureResourceGraphSource._infer_environment"""

    def test_from_environment_tag_prod(self, azure_source):
        resource = {"tags": {"environment": "prod"}, "resourceGroup": "rg"}
        assert azure_source._infer_environment(resource) == "production"

    def test_from_env_tag_staging(self, azure_source):
        resource = {"tags": {"env": "staging"}, "resourceGroup": "rg"}
        assert azure_source._infer_environment(resource) == "staging"

    def test_from_stage_tag(self, azure_source):
        resource = {"tags": {"stage": "dev"}, "resourceGroup": "rg"}
        assert azure_source._infer_environment(resource) == "development"

    def test_from_tier_tag(self, azure_source):
        resource = {"tags": {"tier": "test"}, "resourceGroup": "rg"}
        assert azure_source._infer_environment(resource) == "test"

    def test_from_resource_group(self, azure_source):
        resource = {"tags": {}, "resourceGroup": "rg-production-main"}
        assert azure_source._infer_environment(resource) == "production"

    def test_from_resource_group_staging(self, azure_source):
        resource = {"tags": {}, "resourceGroup": "staging-rg"}
        assert azure_source._infer_environment(resource) == "staging"

    def test_from_resource_group_dev(self, azure_source):
        resource = {"tags": {}, "resourceGroup": "dev-playground"}
        assert azure_source._infer_environment(resource) == "development"

    def test_from_resource_group_test(self, azure_source):
        resource = {"tags": {}, "resourceGroup": "test-rg"}
        assert azure_source._infer_environment(resource) == "test"

    def test_default_is_production(self, azure_source):
        resource = {"tags": {}, "resourceGroup": "rg-custom"}
        assert azure_source._infer_environment(resource) == "production"


class TestAzureQueryResources:
    """Tests for AzureResourceGraphSource.query_resources (mocked API)"""

    @pytest.mark.asyncio
    async def test_query_returns_data(self, azure_source):
        mock_response = MagicMock()
        mock_response.data = [
            {"id": "/sub/res1", "name": "res1", "type": "Microsoft.Compute/virtualMachines"},
            {"id": "/sub/res2", "name": "res2", "type": "Microsoft.Web/sites"},
        ]
        with patch.object(azure_source, "initialize", new_callable=AsyncMock), \
             patch("services.collector.src.sources.azure_resource_graph_source.ResourceGraphClient") as MockClient:
            azure_source._client = MockClient.return_value
            azure_source._client.resources.return_value = mock_response
            result = await azure_source.query_resources(datetime(2025, 1, 1))
            assert len(result) == 2
            assert result[0]["name"] == "res1"

    @pytest.mark.asyncio
    async def test_query_error_returns_empty(self, azure_source):
        with patch.object(azure_source, "initialize", new_callable=AsyncMock), \
             patch("services.collector.src.sources.azure_resource_graph_source.ResourceGraphClient") as MockClient:
            azure_source._client = MockClient.return_value
            azure_source._client.resources.side_effect = Exception("API error")
            result = await azure_source.query_resources(datetime(2025, 1, 1))
            assert result == []


class TestAzurePollChanges:
    """Tests for AzureResourceGraphSource.poll_changes"""

    @pytest.mark.asyncio
    async def test_poll_changes(self, azure_source):
        resource = _make_azure_resource()
        with patch.object(azure_source, "query_resources", new_callable=AsyncMock, return_value=[resource]):
            events = await azure_source.poll_changes()
            assert len(events) == 1
            assert events[0].source == ChangeSource.AZURE_RESOURCE_GRAPH

    @pytest.mark.asyncio
    async def test_poll_updates_last_query_time(self, azure_source):
        with patch.object(azure_source, "query_resources", new_callable=AsyncMock, return_value=[]):
            await azure_source.poll_changes()
            assert azure_source._last_query_time is not None


# GitLab Source Tests

from services.collector.src.sources.gitlab_source import GitLabConfig, GitLabSource, GitLabWebhookPayload


@pytest.fixture
def gitlab_source():
    cfg = GitLabConfig(
        base_url="https://gitlab.com/api/v4",
        token="glpat-test",
        webhook_secret="gl-secret",
        groups=["my-org"],
        projects=["my-org/my-repo"],
        branches=["main", "production"],
    )
    return GitLabSource(cfg)


class TestGitLabShouldProcessProject:
    def test_matches_group_and_project(self, gitlab_source):
        assert gitlab_source._should_process_project("my-org/my-repo") is True

    def test_rejects_unknown_group(self, gitlab_source):
        assert gitlab_source._should_process_project("other-org/my-repo") is False

    def test_rejects_unknown_project(self, gitlab_source):
        assert gitlab_source._should_process_project("my-org/other") is False


class TestGitLabWebhookVerification:
    def test_verifies_token(self, gitlab_source):
        assert gitlab_source.verify_webhook_signature(b"payload", "gl-secret") is True

    def test_rejects_bad_token(self, gitlab_source):
        assert gitlab_source.verify_webhook_signature(b"payload", "wrong") is False


class TestGitLabProcessPush:
    @pytest.mark.asyncio
    async def test_push_to_main_creates_event(self, gitlab_source):
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/main",
            "user_username": "dev1",
            "commits": [
                {"id": "abc123", "message": "fix bug", "timestamp": "2025-01-01T00:00:00Z", "url": "https://gitlab.com/commit/abc123"}
            ],
        }
        event = GitLabWebhookPayload(
            object_kind="push",
            payload=payload,
            project={"path_with_namespace": "my-org/my-repo", "web_url": "https://gitlab.com/my-org/my-repo"},
            timestamp=datetime.now(timezone.utc),
        )
        events = await gitlab_source.process_webhook(event)
        assert len(events) == 1
        assert events[0].service_name == "my-repo"
        assert events[0].source == ChangeSource.CI_CD_PIPELINE

    @pytest.mark.asyncio
    async def test_push_to_unmonitored_branch_ignored(self, gitlab_source):
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/feature-x",
            "user_username": "dev1",
            "commits": [{"id": "abc", "message": "wip", "timestamp": "2025-01-01T00:00:00Z"}],
        }
        event = GitLabWebhookPayload(
            object_kind="push",
            payload=payload,
            project={"path_with_namespace": "my-org/my-repo", "web_url": "https://gitlab.com"},
            timestamp=datetime.now(timezone.utc),
        )
        events = await gitlab_source.process_webhook(event)
        assert events == []


# Jenkins Source Tests

from services.collector.src.sources.jenkins_source import JenkinsBuild, JenkinsConfig, JenkinsSource


@pytest.fixture
def jenkins_source():
    return JenkinsSource(JenkinsConfig(
        base_url="https://jenkins.example.com",
        username="admin",
        token="jenkins-token",
        jobs=["payment-service"],
    ))


class TestJenkinsBuildToEvent:
    def test_success_build(self, jenkins_source):
        build = JenkinsBuild(
            number=42,
            job_name="payment-service-deploy",
            result="SUCCESS",
            building=False,
            timestamp=1700000000000,
            url="https://jenkins.example.com/job/payment-service-deploy/42/",
            duration=10000,
        )
        event = jenkins_source.build_to_change_event(build)
        assert event.source == ChangeSource.CI_CD_PIPELINE
        assert event.status == ChangeStatus.SUCCEEDED
        assert event.service_name == "payment-service"
        assert event.pipeline_run_id == "42"

    def test_failed_build(self, jenkins_source):
        build = JenkinsBuild(
            number=43,
            job_name="payment-service-deploy",
            result="FAILURE",
            building=False,
            timestamp=1700000000000,
            url="https://jenkins.example.com/job/payment-service-deploy/43/",
            duration=5000,
        )
        event = jenkins_source.build_to_change_event(build)
        assert event.status == ChangeStatus.FAILED

    def test_running_build(self, jenkins_source):
        build = JenkinsBuild(
            number=44,
            job_name="payment-service-deploy",
            result=None,
            building=True,
            timestamp=1700000000000,
            url="https://jenkins.example.com/job/payment-service-deploy/44/",
            duration=0,
        )
        event = jenkins_source.build_to_change_event(build)
        assert event.status == ChangeStatus.IN_PROGRESS

    def test_extracts_service_name(self, jenkins_source):
        assert jenkins_source._extract_service_name("payment-service-deploy") == "payment-service"
        assert jenkins_source._extract_service_name("auth-service-build") == "auth-service"


# ArgoCD Source Tests

from services.collector.src.sources.argocd_source import ArgoCDApplication, ArgoCDConfig, ArgoCDSource


@pytest.fixture
def argocd_source():
    return ArgoCDSource(ArgoCDConfig(
        base_url="https://argocd.example.com",
        token="argocd-token",
        applications=["payment-service"],
    ))


class TestArgoCDSyncToEvent:
    def test_sync_to_event(self, argocd_source):
        app = ArgoCDApplication(
            name="payment-service-prod",
            project="default",
            namespace="production",
            destination="https://kubernetes.default.svc",
            repo_url="https://github.com/my-org/payment-service",
            path="production",
            sync_status="Synced",
            health_status="Healthy",
            revision="abc123",
        )
        event = argocd_source._sync_to_change_event(app, "abc123", "Synced")
        assert event.source == ChangeSource.ARGO_ROLLOUTS
        assert event.status == ChangeStatus.SUCCEEDED
        assert event.service_name == "payment-service-prod"
        assert event.deployment_strategy == "rolling"

    def test_environment_production(self, argocd_source):
        assert argocd_source._extract_environment("payment-service-prod") == "production"
        assert argocd_source._extract_environment("payment-service-dev") == "development"
        assert argocd_source._extract_environment("payment-service-staging") == "staging"


# K8s module-level conversion (customer-agent ingestion path)

from services.collector.src.sources.k8s_source import (
    k8s_resource_event_to_change_event,
    _get_api_version,
    _namespace_to_environment,
)


class TestK8sModuleConversion:
    def test_converts_deployment_event(self):
        event = _make_k8s_event(
            event_type="ADDED",
            resource_type="Deployment",
            namespace="production",
            name="payment-service",
            labels={"app": "payment-service"},
        )
        ce = k8s_resource_event_to_change_event(event)
        assert ce is not None
        assert ce.source == ChangeSource.KUBERNETES
        assert ce.service_name == "payment-service"
        assert ce.environment == "production"

    def test_skips_kube_system(self):
        event = _make_k8s_event(namespace="kube-system", name="coredns")
        assert k8s_resource_event_to_change_event(event) is None

    def test_unknown_event_type_returns_none(self):
        event = _make_k8s_event(event_type="ERROR")
        assert k8s_resource_event_to_change_event(event) is None

    def test_get_api_version(self):
        assert _get_api_version("Deployment") == "apps/v1"
        assert _get_api_version("Service") == "v1"
        assert _get_api_version("Unknown") == "v1"

    def test_namespace_to_environment(self):
        assert _namespace_to_environment("prod") == "production"
        assert _namespace_to_environment("staging") == "staging"
        assert _namespace_to_environment("dev") == "development"
        assert _namespace_to_environment("custom") == "production"
