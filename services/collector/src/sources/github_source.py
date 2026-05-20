"""
GitHub Source Collector for ChangeTrace

Collects change events from GitHub:
- Commits pushed to protected branches
- Pull requests merged
- Releases published
- Tags created

Uses GitHub App authentication for production, PAT for development.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from github import Github, GithubIntegration
from github.GithubException import GithubException
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    GitReference,
)

logger = logging.getLogger(__name__)


class GitHubConfig(BaseModel):
    """Configuration for GitHub source"""
    # GitHub App authentication (preferred for production)
    app_id: int | None = None
    private_key: str | None = None
    installation_id: int | None = None

    # Personal Access Token (for development)
    personal_access_token: str | None = None

    # Webhook secret for validating webhooks
    webhook_secret: str | None = None

    # Repository filters
    organizations: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)  # Format: "owner/repo"
    branches: list[str] = Field(default_factory=lambda: ["main", "master", "production"])

    # Polling configuration (fallback if webhooks not available)
    poll_interval_seconds: int = 300  # 5 minutes
    lookback_hours: int = 24

    # Event types to collect
    collect_commits: bool = True
    collect_pull_requests: bool = True
    collect_releases: bool = True
    collect_tags: bool = True


class GitHubEventPayload(BaseModel):
    """Parsed GitHub webhook payload"""
    event_type: str
    action: str | None = None
    repository: dict[str, Any]
    sender: dict[str, Any]
    payload: dict[str, Any]
    delivery_id: str
    timestamp: datetime


class GitHubSource:
    """
    GitHub change event collector.

    Supports both webhook-based (real-time) and polling-based (fallback) collection.
    """

    def __init__(self, config: GitHubConfig):
        self.config = config
        self._client: Github | None = None
        self._installation_client: Github | None = None
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._last_poll_time: dict[str, datetime] = {}

    async def initialize(self) -> None:
        """Initialize GitHub client with authentication"""
        if self.config.app_id and self.config.private_key and self.config.installation_id:
            # GitHub App authentication
            integration = GithubIntegration(
                self.config.app_id,
                self.config.private_key
            )
            token = integration.get_access_token(self.config.installation_id)
            self._client = Github(token.token)
            logger.info("Initialized GitHub client with App authentication")
        elif self.config.personal_access_token:
            # PAT authentication
            self._client = Github(self.config.personal_access_token)
            logger.info("Initialized GitHub client with PAT authentication")
        else:
            raise ValueError("No GitHub authentication configured. Provide either GitHub App credentials or PAT.")

    async def close(self) -> None:
        """Close HTTP client"""
        await self._http_client.aclose()
        if self._client:
            self._client.close()

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature"""
        if not self.config.webhook_secret:
            logger.warning("No webhook secret configured, skipping signature verification")
            return True

        expected = hmac.new(
            self.config.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected}", signature)

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> GitHubEventPayload | None:
        """Parse and validate GitHub webhook payload"""
        # Verify signature
        signature = headers.get("X-Hub-Signature-256", "")
        if not self.verify_webhook_signature(payload, signature):
            logger.warning("Invalid webhook signature")
            return None

        event_type = headers.get("X-GitHub-Event", "")
        delivery_id = headers.get("X-GitHub-Delivery", "")

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse webhook JSON: {e}")
            return None

        return GitHubEventPayload(
            event_type=event_type,
            action=data.get("action"),
            repository=data.get("repository", {}),
            sender=data.get("sender", {}),
            payload=data,
            delivery_id=delivery_id,
            timestamp=datetime.utcnow()
        )

    async def process_webhook(self, event: GitHubEventPayload) -> list[ChangeEvent]:
        """Process a webhook event and extract change events"""
        events = []

        repo_full_name = event.repository.get("full_name", "")
        if not self._should_process_repo(repo_full_name):
            return events

        if event.event_type == "push" and self.config.collect_commits:
            events.extend(await self._process_push_event(event))
        elif event.event_type == "pull_request" and self.config.collect_pull_requests:
            events.extend(await self._process_pr_event(event))
        elif event.event_type == "release" and self.config.collect_releases:
            events.extend(await self._process_release_event(event))
        elif event.event_type == "create" and self.config.collect_tags:
            events.extend(await self._process_create_event(event))

        return events

    def _should_process_repo(self, repo_full_name: str) -> bool:
        """Check if repository should be processed based on filters"""
        if self.config.organizations:
            org = repo_full_name.split("/")[0]
            if org not in self.config.organizations:
                return False

        if self.config.repositories:
            if repo_full_name not in self.config.repositories:
                return False

        return True

    async def _process_push_event(self, event: GitHubEventPayload) -> list[ChangeEvent]:
        """Process push event (commits)"""
        events = []
        payload = event.payload

        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "")

        if branch not in self.config.branches:
            return events

        commits = payload.get("commits", [])
        repo = event.repository

        for commit in commits:
            # Skip merge commits
            if commit.get("message", "").startswith("Merge "):
                continue

            change_event = ChangeEvent(
                change_type=ChangeType.CODE_DEPLOYMENT,
                source=ChangeSource.GITHUB,
                status=ChangeStatus.SUCCEEDED,
                timestamp=datetime.fromisoformat(commit["timestamp"].replace("Z", "+00:00")),
                service_name=self._extract_service_name(repo, commit),
                environment="production",  # Could be inferred from branch
                author=commit["author"]["name"],
                author_email=commit["author"]["email"],
                description=commit["message"],
                summary=commit["message"].split("\n")[0][:200],
                git=GitReference(
                    repo_url=repo["html_url"],
                    repo_name=repo["full_name"],
                    commit_sha=commit["id"],
                    commit_message=commit["message"],
                    branch=branch,
                    author=commit["author"]["name"],
                    author_email=commit["author"]["email"],
                    commit_url=commit["url"],
                    compare_url=payload.get("compare"),
                ),
                pipeline_name=f"github/{repo['full_name']}",
                pipeline_run_id=event.delivery_id,
                pipeline_url=repo["html_url"],
                labels={
                    "github.event": "push",
                    "github.branch": branch,
                    "github.repo": repo["full_name"],
                },
                correlation_id=event.delivery_id,
            )
            events.append(change_event)

        return events

    async def _process_pr_event(self, event: GitHubEventPayload) -> list[ChangeEvent]:
        """Process pull request event"""
        events = []
        payload = event.payload
        action = event.action

        if action != "closed" or not payload.get("pull_request", {}).get("merged"):
            return events

        pr = payload["pull_request"]
        repo = event.repository
        base_branch = pr["base"]["ref"]

        if base_branch not in self.config.branches:
            return events

        change_event = ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")),
            service_name=self._extract_service_name(repo, pr),
            environment="production",
            author=pr["user"]["login"],
            author_email=pr["user"].get("email"),
            description=pr["body"] or pr["title"],
            summary=f"PR #{pr['number']}: {pr['title']}",
            git=GitReference(
                repo_url=repo["html_url"],
                repo_name=repo["full_name"],
                commit_sha=pr["merge_commit_sha"],
                branch=base_branch,
                pr_number=pr["number"],
                pr_title=pr["title"],
                author=pr["user"]["login"],
                author_email=pr["user"].get("email"),
                commit_url=pr["html_url"],
            ),
            pipeline_name=f"github/{repo['full_name']}",
            pipeline_run_id=str(pr["number"]),
            pipeline_url=pr["html_url"],
            labels={
                "github.event": "pull_request",
                "github.action": "merged",
                "github.base_branch": base_branch,
                "github.repo": repo["full_name"],
                "github.pr_number": str(pr["number"]),
            },
            correlation_id=event.delivery_id,
        )
        events.append(change_event)

        return events

    async def _process_release_event(self, event: GitHubEventPayload) -> list[ChangeEvent]:
        """Process release event"""
        events = []
        payload = event.payload
        action = event.action

        if action != "published":
            return events

        release = payload["release"]
        repo = event.repository

        change_event = ChangeEvent(
            change_type=ChangeType.RELEASE,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=datetime.fromisoformat(release["published_at"].replace("Z", "+00:00")),
            service_name=self._extract_service_name(repo, release),
            environment="production",
            author=release["author"]["login"],
            description=release["body"] or release["name"],
            summary=f"Release {release['tag_name']}: {release['name']}",
            git=GitReference(
                repo_url=repo["html_url"],
                repo_name=repo["full_name"],
                tag=release["tag_name"],
                commit_sha=release["target_commitish"],
                author=release["author"]["login"],
                commit_url=release["html_url"],
            ),
            pipeline_name=f"github/{repo['full_name']}",
            pipeline_run_id=release["tag_name"],
            pipeline_url=release["html_url"],
            new_version=release["tag_name"],
            labels={
                "github.event": "release",
                "github.action": "published",
                "github.repo": repo["full_name"],
                "github.tag": release["tag_name"],
            },
            correlation_id=event.delivery_id,
        )
        events.append(change_event)

        return events

    async def _process_create_event(self, event: GitHubEventPayload) -> list[ChangeEvent]:
        """Process tag creation event"""
        events = []
        payload = event.payload

        if payload.get("ref_type") != "tag":
            return events

        repo = event.repository
        tag_name = payload["ref"]

        change_event = ChangeEvent(
            change_type=ChangeType.RELEASE,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=datetime.utcnow(),
            service_name=self._extract_service_name(repo, payload),
            environment="production",
            author=event.sender["login"],
            description=f"Tag {tag_name} created",
            summary=f"Tag {tag_name} created",
            git=GitReference(
                repo_url=repo["html_url"],
                repo_name=repo["full_name"],
                tag=tag_name,
                author=event.sender["login"],
            ),
            pipeline_name=f"github/{repo['full_name']}",
            pipeline_run_id=tag_name,
            pipeline_url=repo["html_url"],
            new_version=tag_name,
            labels={
                "github.event": "create",
                "github.ref_type": "tag",
                "github.repo": repo["full_name"],
                "github.tag": tag_name,
            },
            correlation_id=event.delivery_id,
        )
        events.append(change_event)

        return events

    def _extract_service_name(self, repo: dict[str, Any], data: dict[str, Any]) -> str:
        """Extract service name from repository and commit data"""
        # Try to infer from repo name
        repo_name = repo["name"].lower()

        # Common patterns: service-name, service-name-api, service-name-service, etc.
        # Remove common suffixes
        for suffix in ["-api", "-service", "-svc", "-app", "-backend", "-frontend"]:
            if repo_name.endswith(suffix):
                repo_name = repo_name[: -len(suffix)]

        return repo_name

    # Polling methods (fallback when webhooks not available)

    async def poll_repository(self, repo_full_name: str) -> list[ChangeEvent]:
        """Poll a repository for new changes since last poll"""
        if not self._client:
            await self.initialize()

        events = []
        last_poll = self._last_poll_time.get(repo_full_name)
        since = last_poll or (datetime.utcnow() - timedelta(hours=self.config.lookback_hours))

        try:
            repo = self._client.get_repo(repo_full_name)

            # Get commits since last poll
            if self.config.collect_commits:
                for branch in self.config.branches:
                    try:
                        commits = repo.get_commits(sha=branch, since=since)
                        for commit in commits:
                            event = self._commit_to_change_event(commit, repo, branch)
                            if event:
                                events.append(event)
                    except GithubException as e:
                        logger.warning(f"Failed to get commits for {repo_full_name}/{branch}: {e}")

            # Get merged PRs since last poll
            if self.config.collect_pull_requests:
                pulls = repo.get_pulls(state="closed", sort="updated", base=branch)
                for pr in pulls:
                    if pr.merged_at and pr.merged_at > since:
                        event = self._pr_to_change_event(pr, repo)
                        if event:
                            events.append(event)

            # Get releases since last poll
            if self.config.collect_releases:
                releases = repo.get_releases()
                for release in releases:
                    if release.published_at and release.published_at > since:
                        event = self._release_to_change_event(release, repo)
                        if event:
                            events.append(event)

            self._last_poll_time[repo_full_name] = datetime.utcnow()

        except GithubException as e:
            logger.error(f"Failed to poll repository {repo_full_name}: {e}")

        return events

    def _commit_to_change_event(self, commit, repo, branch: str) -> ChangeEvent | None:
        """Convert GitHub commit to ChangeEvent"""
        if commit.commit.message.startswith("Merge "):
            return None

        return ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=commit.commit.author.date,
            service_name=self._extract_service_name(repo.raw_data, commit.raw_data),
            environment="production",
            author=commit.commit.author.name,
            author_email=commit.commit.author.email,
            description=commit.commit.message,
            summary=commit.commit.message.split("\n")[0][:200],
            git=GitReference(
                repo_url=repo.html_url,
                repo_name=repo.full_name,
                commit_sha=commit.sha,
                commit_message=commit.commit.message,
                branch=branch,
                author=commit.commit.author.name,
                author_email=commit.commit.author.email,
                commit_url=commit.html_url,
            ),
            pipeline_name=f"github/{repo.full_name}",
            pipeline_run_id=commit.sha[:8],
            pipeline_url=repo.html_url,
            labels={
                "github.event": "push",
                "github.branch": branch,
                "github.repo": repo.full_name,
            },
        )

    def _pr_to_change_event(self, pr, repo) -> ChangeEvent | None:
        """Convert GitHub PR to ChangeEvent"""
        if not pr.merged:
            return None

        return ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=pr.merged_at,
            service_name=self._extract_service_name(repo.raw_data, pr.raw_data),
            environment="production",
            author=pr.user.login,
            author_email=pr.user.email,
            description=pr.body or pr.title,
            summary=f"PR #{pr.number}: {pr.title}",
            git=GitReference(
                repo_url=repo.html_url,
                repo_name=repo.full_name,
                commit_sha=pr.merge_commit_sha,
                branch=pr.base.ref,
                pr_number=pr.number,
                pr_title=pr.title,
                author=pr.user.login,
                author_email=pr.user.email,
                commit_url=pr.html_url,
            ),
            pipeline_name=f"github/{repo.full_name}",
            pipeline_run_id=str(pr.number),
            pipeline_url=pr.html_url,
            labels={
                "github.event": "pull_request",
                "github.action": "merged",
                "github.base_branch": pr.base.ref,
                "github.repo": repo.full_name,
                "github.pr_number": str(pr.number),
            },
        )

    def _release_to_change_event(self, release, repo) -> ChangeEvent | None:
        """Convert GitHub release to ChangeEvent"""
        return ChangeEvent(
            change_type=ChangeType.RELEASE,
            source=ChangeSource.GITHUB,
            status=ChangeStatus.SUCCEEDED,
            timestamp=release.published_at,
            service_name=self._extract_service_name(repo.raw_data, release.raw_data),
            environment="production",
            author=release.author.login,
            description=release.body or release.name,
            summary=f"Release {release.tag_name}: {release.name}",
            git=GitReference(
                repo_url=repo.html_url,
                repo_name=repo.full_name,
                tag=release.tag_name,
                commit_sha=release.target_commitish,
                author=release.author.login,
                commit_url=release.html_url,
            ),
            pipeline_name=f"github/{repo.full_name}",
            pipeline_run_id=release.tag_name,
            pipeline_url=release.html_url,
            new_version=release.tag_name,
            labels={
                "github.event": "release",
                "github.action": "published",
                "github.repo": repo.full_name,
                "github.tag": release.tag_name,
            },
        )

    async def poll_all_repositories(self) -> list[ChangeEvent]:
        """Poll all configured repositories"""
        all_events = []

        for repo_name in self.config.repositories:
            events = await self.poll_repository(repo_name)
            all_events.extend(events)

        return all_events


async def create_github_source(config: GitHubConfig) -> GitHubSource:
    """Factory function to create and initialize GitHub source"""
    source = GitHubSource(config)
    await source.initialize()
    return source
