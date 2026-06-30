"""
Jenkins Source Collector for ChangeTrace.

Collects change events from Jenkins CI/CD and authenticates via a user API token.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    GitReference,
)

logger = logging.getLogger(__name__)


class JenkinsConfig(BaseModel):
    """Configuration for Jenkins source"""
    base_url: str  # e.g. https://jenkins.example.com
    username: str | None = None
    token: str  # Jenkins API token

    # Job filters
    jobs: list[str] = Field(default_factory=list)  # Empty = all
    job_folders: list[str] = Field(default_factory=list)  # Folder paths to search

    # Polling configuration
    poll_interval_seconds: int = 300
    lookback_hours: int = 24


class JenkinsBuild(BaseModel):
    """Jenkins build representation"""
    number: int
    job_name: str
    result: str | None
    building: bool
    timestamp: int  # ms epoch
    url: str
    duration: int  # ms
    parameters: dict[str, Any] = Field(default_factory=dict)
    scm: dict[str, Any] = Field(default_factory=dict)


class JenkinsSource:
    """Jenkins change event collector."""

    def __init__(self, config: JenkinsConfig):
        self.config = config
        auth = None
        if config.username and config.token:
            import base64
            creds = f"{config.username}:{config.token}"
            auth = "Basic " + base64.b64encode(creds.encode()).decode()
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = auth
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=60.0,
        )
        self._last_poll_time: dict[str, datetime] = {}

    async def initialize(self) -> None:
        logger.info("Initialized Jenkins source")

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params) -> Any:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_jobs(self, folder: str | None = None) -> list[dict[str, Any]]:
        """List jobs, optionally within a folder."""
        tree = "jobs[name,url,color,class]"
        params = {"tree": tree}
        if folder:
            url = f"/job/{folder}/api/json"
        else:
            url = "/api/json"
        try:
            data = await self._get(url, **params)
        except Exception as e:
            logger.warning(f"Failed to list Jenkins jobs in {folder or 'root'}: {e}")
            return []
        return data.get("jobs", [])

    async def discover_jobs(self) -> list[dict[str, Any]]:
        """Recursively discover jobs across configured folders."""
        found: list[dict[str, Any]] = []
        folders = self.config.job_folders or [None]
        for folder in folders:
            jobs = await self.get_jobs(folder)
            for job in jobs:
                if job.get("class", "").startswith("org.jenkinsci.plugins.workflow"):
                    found.append({"name": job["name"], "url": job["url"], "folder": folder})
                elif job.get("class") == "com.cloudbees.hudson.plugins.folder.Folder":
                    subfolder = f"{folder + '/' if folder else ''}{job['name']}"
                    found.extend(await self.discover_jobs_in_folder(subfolder))
        return found

    async def discover_jobs_in_folder(self, folder: str) -> list[dict[str, Any]]:
        jobs = await self.get_jobs(folder)
        found: list[dict[str, Any]] = []
        for job in jobs:
            if job.get("class", "").startswith("org.jenkinsci.plugins.workflow") or "FreeStyleProject" in job.get("class", ""):
                found.append({"name": job["name"], "url": job["url"], "folder": folder})
            elif job.get("class") == "com.cloudbees.hudson.plugins.folder.Folder":
                subfolder = f"{folder}/{job['name']}"
                found.extend(await self.discover_jobs_in_folder(subfolder))
        return found

    async def get_build(self, job_name: str, url: str, number: int) -> JenkinsBuild | None:
        try:
            data = await self._get(f"/job/{job_name}/{number}/api/json")
        except Exception as e:
            logger.warning(f"Failed to fetch build {job_name}#{number}: {e}")
            return None

        return JenkinsBuild(
            number=data.get("number", number),
            job_name=job_name,
            result=data.get("result"),
            building=data.get("building", False),
            timestamp=data.get("timestamp", 0),
            url=data.get("url", ""),
            duration=data.get("duration", 0),
            parameters={a.get("name"): a.get("value") for a in data.get("actions", []) if a.get("_class") == "hudson.model.ParametersAction"},
            scm=data.get("scm", {}),
        )

    async def poll_job(self, job: dict[str, Any]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        job_name = f"{job['folder'] + '/' if job.get('folder') else ''}{job['name']}"
        job_url = job["url"]
        since = self._last_poll_time.get(job_name) or (datetime.utcnow() - timedelta(hours=self.config.lookback_hours))
        since_ms = int(since.timestamp() * 1000)

        try:
            resp = await self._client.get(f"/job/{job_name}/api/json", params={"tree": "builds[number,timestamp,result,building,url,duration]"})
            resp.raise_for_status()
            builds = resp.json().get("builds", [])
        except Exception as e:
            logger.warning(f"Failed to list builds for {job_name}: {e}")
            return events

        recent = [b for b in builds if b.get("timestamp", 0) >= since_ms]
        for b in recent[:20]:
            detail = await self.get_build(job_name, job_url, b["number"])
            if detail:
                events.append(self.build_to_change_event(detail))

        self._last_poll_time[job_name] = datetime.utcnow()
        return events

    def build_to_change_event(self, build: JenkinsBuild) -> ChangeEvent:
        status_map = {
            "SUCCESS": ChangeStatus.SUCCEEDED,
            "FAILURE": ChangeStatus.FAILED,
            "ABORTED": ChangeStatus.CANCELLED,
            "UNSTABLE": ChangeStatus.IN_PROGRESS,
        }
        status = status_map.get(build.result or "", ChangeStatus.IN_PROGRESS)
        if build.building:
            status = ChangeStatus.IN_PROGRESS

        service_name = self._extract_service_name(build.job_name)
        started_at = datetime.fromtimestamp(build.timestamp / 1000, tz=datetime.now().astimezone().tzinfo)

        return ChangeEvent(
            change_type=ChangeType.CODE_DEPLOYMENT,
            source=ChangeSource.CI_CD_PIPELINE,
            status=status,
            timestamp=started_at,
            started_at=started_at,
            duration_seconds=build.duration / 1000 if build.duration else None,
            service_name=service_name,
            environment="production",
            description=f"Jenkins build #{build.number} of {build.job_name}",
            summary=f"Build {build.job_name}#{build.number}: {build.result or 'running'}",
            pipeline_name=f"jenkins/{build.job_name}",
            pipeline_run_id=str(build.number),
            pipeline_stage=build.result or "running",
            pipeline_url=build.url,
            labels={
                "jenkins.job": build.job_name,
                "jenkins.build": str(build.number),
                "jenkins.result": build.result or "running",
            },
            correlation_id=str(build.number),
        )

    def _extract_service_name(self, job_name: str) -> str:
        name = job_name.split("/")[-1].lower()
        # Strip a single terminal CI/CD suffix, but never eat a "-service" suffix
        # that is itself the service's meaningful name.
        for suffix in ["-deploy-job", "-build-job", "-pipeline", "-deploy", "-build", "-job", "-cd"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name or "unknown-service"

    async def poll_all_jobs(self) -> list[ChangeEvent]:
        all_events: list[ChangeEvent] = []
        jobs = await self.discover_jobs()
        for job in jobs:
            events = await self.poll_job(job)
            all_events.extend(events)
        return all_events

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/json", params={"tree": "jobs[name]"})
            return resp.status_code == 200
        except Exception:
            return False
