"""Dashboard API Service for ChangeTrace."""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sys
import uuid
import jwt as pyjwt
import dotenv
dotenv.load_dotenv()

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from services.dashboard_api.src.users import (
    build_user_from_vertex,
    hash_password,
    new_tenant_id,
    new_user_id,
    normalize_email,
    verify_password,
)

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.shared.auth import auth_handler, get_simple_auth_secret
from services.shared.secrets import get_secret, key_vault_url, set_secret, source_secret_refs

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Thread pool for synchronous Gremlin client calls
gremlin_executor = ThreadPoolExecutor(max_workers=4)




def _run_gremlin_query(query: str) -> list:
    """Run a Gremlin query using the shared global client (blocking)."""
    rs = gremlin_client.submit(query)
    return rs.all().result()


def _run_gremlin_query_threadsafe(query: str) -> list:
    """Run a Gremlin query in a subprocess with its own event loop (Safe for async contexts)."""
    import subprocess as _sp
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gremlin_write.py")
    result = _sp.run(
        [sys.executable, script, query],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CHANGETRACE_WRITE_GREMLIN": "1"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gremlin write failed: {result.stderr[:200]}")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return []


class DashboardConfig(BaseModel):
    """Dashboard API configuration"""
    # Cosmos DB
    cosmos_connection_string: str = ""
    cosmos_database: str = "changetrace-graph"
    dependency_graph_name: str = "dependency-graph"
    change_history_name: str = "change-history"
    incidents_name: str = "incidents"

    # Azure Monitor
    log_analytics_workspace_id: str | None = None

    # Service
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "info"


# Global state
config: DashboardConfig | None = None
gremlin_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global config, gremlin_client

    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        cosmos_connection_string: str = ""
        cosmos_database: str = "changetrace-graph"
        dependency_graph_name: str = "dependency-graph"
        change_history_name: str = "change-history"
        incidents_name: str = "incidents"
        log_analytics_workspace_id: str | None = None
        host: str = "0.0.0.0"
        port: int = 8002
        log_level: str = "info"

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"

    settings = Settings()
    config = DashboardConfig(**settings.model_dump())

    from services.shared.cosmos import get_cosmos_config_from_env, create_gremlin_client
    cosmos_cfg = get_cosmos_config_from_env()
    global gremlin_client
    gremlin_client = create_gremlin_client(
        endpoint=cosmos_cfg["endpoint"],
        key=cosmos_cfg["key"],
        database=cosmos_cfg["database"],
        graph=config.dependency_graph_name,
    )
    if not gremlin_client:
        logger.warning("Cosmos DB not configured - some endpoints will return mock data")

    yield

    # Cleanup
    if gremlin_client:
        gremlin_client.close()
        logger.info("Closed Gremlin client")


app = FastAPI(
    title="ChangeTrace Dashboard API",
    description="API for ChangeTrace dashboard - dependency graphs, incidents, SLOs, risk scores",
    version="1.0.0",
    lifespan=lifespan,
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["WWW-Authenticate"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if auth_handler.disabled:
        return await call_next(request)

    public_paths = ["/health", "/ready", "/docs", "/openapi.json", "/redoc", "/api/v1/auth/login", "/api/v1/auth/register"]
    if request.url.path in public_paths:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authorization header missing"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = auth_header[7:]
        # Try simple auth first if secret is configured
        if SIMPLE_AUTH_SECRET:
            try:
                payload = pyjwt.decode(token, SIMPLE_AUTH_SECRET, algorithms=["HS256"])
            except Exception:
                payload = None
            if payload is not None:
                request.state.user = payload
                return await call_next(request)
        # Fall back to Azure AD auth
        payload = auth_handler.decode_token(token)
        request.state.user = payload
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": f"Invalid token: {e}"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


def _tenant(request: Request) -> str:
    """Extract the tenant id from the authenticated request."""
    user = getattr(request.state, "user", None)
    tenant_id = (user or {}).get("tenant_id") or (user or {}).get("tenantId")
    if not tenant_id:
        if os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod"):
            raise HTTPException(status_code=403, detail="Authenticated tenant context is required")
        tenant_id = os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
    return tenant_id


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _tq(tenant_id: str, label: str) -> str:
    """Return a Gremlin step that scopes a vertex query to a tenant."""
    return f"g.V().hasLabel('{label}').has('tenantId', '{tenant_id}')"


# Response models
class ServiceNode(BaseModel):
    """Service node in dependency graph"""
    id: str
    name: str
    namespace: str | None = None
    criticality: str = "medium"
    slo_target: float | None = None
    current_slo: float | None = None
    error_budget_remaining: float | None = None
    incident_count_24h: int = 0
    deployment_count_24h: int = 0
    current_risk_score: float | None = None


class DependencyEdge(BaseModel):
    """Dependency edge between services"""
    source: str
    target: str
    type: str = "depends_on"
    latency_p99: float | None = None
    error_rate: float | None = None
    request_volume: int | None = None


class DependencyGraph(BaseModel):
    """Full dependency graph"""
    nodes: list[ServiceNode]
    edges: list[DependencyEdge]
    updated_at: datetime


class IncidentSummary(BaseModel):
    """Incident summary for timeline"""
    incident_id: str
    title: str
    severity: str
    status: str
    affected_service: str
    detected_at: datetime
    resolved_at: datetime | None = None
    root_cause_candidate: str | None = None
    confidence: float | None = None
    remediation_action: str | None = None


class SLOBurnData(BaseModel):
    """SLO burn rate data point"""
    timestamp: datetime
    service: str
    slo_name: str
    target: float
    actual: float
    burn_rate: float
    error_budget_remaining: float


class RiskScoreHistory(BaseModel):
    """Risk score history entry"""
    timestamp: datetime
    service: str
    deployment_id: str | None = None
    risk_score: float
    risk_level: str  # low, medium, high, critical
    factors: dict[str, float]


class CorrelationAccuracy(BaseModel):
    """Correlation accuracy metrics"""
    period_start: datetime
    period_end: datetime
    total_incidents: int
    precision_at_1: float
    precision_at_3: float
    recall: float
    mean_time_to_detection_seconds: float
    model_version: str


# Simple Auth
SIMPLE_AUTH_SECRET = get_simple_auth_secret()

# Source integration URLs (defaults; per-tenant overrides persisted in Cosmos)
SOURCE_URLS = {
    "github": os.getenv("SOURCE_URL_GITHUB", ""),
    "gitlab": os.getenv("SOURCE_URL_GITLAB", ""),
    "terraform": os.getenv("SOURCE_URL_TERRAFORM", ""),
    "kubernetes": os.getenv("SOURCE_URL_KUBERNETES", ""),
    "argocd": os.getenv("SOURCE_URL_ARGOCD", ""),
    "azure_resource_graph": os.getenv("SOURCE_URL_AZURE", ""),
    "jenkins": os.getenv("SOURCE_URL_JENKINS", ""),
}


def _issue_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "user_id": user["id"],
        "tenant_id": user["tenant_id"],
        "name": user["name"],
        "email": user["email"],
        "roles": user["roles"],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return pyjwt.encode(payload, SIMPLE_AUTH_SECRET, algorithm="HS256")


async def _find_user_by_email(email: str) -> dict | None:
    if not gremlin_client:
        return None
    query = f"g.V().hasLabel('User').has('email', '{normalize_email(email)}').valueMap(true)"
    result_list = _run_gremlin_query_threadsafe(query)
    if not result_list:
        return None
    props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}
    return build_user_from_vertex(props)


async def _persist_user(user: dict) -> None:
    if not gremlin_client:
        return
    email = user["email"]
    pw = user["password_hash"]
    tn = user["tenant_id"]
    uid = user["id"]
    n = user["name"]
    roles = user.get("roles", "admin")
    if isinstance(roles, (list, tuple)):
        roles = ",".join(roles)
    now = datetime.now(timezone.utc).isoformat()
    safe_email = email.replace("'", "\\'")
    query = (
        f"g.addV('User')"
        f".property('userId', '{uid}')"
        f".property('email', '{email}')"
        f".property('name', '{n}')"
        f".property('passwordHash', '{pw}')"
        f".property('tenantId', '{tn}')"
        f".property('serviceName', '{safe_email}')"
        f".property('roles', '{roles}')"
        f".property('createdAt', '{now}')"
    )
    _run_gremlin_query_threadsafe(query)


@app.post("/api/v1/auth/register")
async def register(request: Request):
    body = await request.json()
    email = normalize_email(body.get("email", ""))
    password = body.get("password", "")
    name = body.get("name") or email.split("@")[0]

    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    existing = await _find_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = {
        "id": new_user_id(),
        "email": email,
        "name": name,
        "password_hash": hash_password(password),
        "tenant_id": new_tenant_id(),
        "roles": ["admin"],
    }
    await _persist_user(user)
    tenant_api_key = await _ensure_tenant_api_key(user["tenant_id"])
    token = _issue_token(user)
    return {
        "token": token,
        "user": {"sub": user["id"], "user_id": user["id"], "tenant_id": user["tenant_id"],
                 "name": user["name"], "email": user["email"], "roles": user["roles"]},
        "api_key": tenant_api_key,
    }


@app.post("/api/v1/auth/login")
async def login(request: Request):
    body = await request.json()

    # New flow: email + password against stored users
    email = normalize_email(body.get("email", ""))
    password = body.get("password", "")
    if email and password:
        user = await _find_user_by_email(email)
        if user and verify_password(password, user.get("password_hash", "")):
            token = _issue_token(user)
            return {
                "token": token,
                "user": {"sub": user["id"], "user_id": user["id"], "tenant_id": user["tenant_id"],
                         "name": user["name"], "email": user["email"], "roles": user["roles"]},
            }
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Legacy flow: token_id (demo / dev) - gated off unless explicitly enabled
    token_id = body.get("token_id", "")
    username = body.get("username", token_id.split("@")[0] if "@" in token_id else token_id)
    if not token_id:
        raise HTTPException(status_code=400, detail="email and password are required")

    if os.getenv("ENABLE_DEMO_LOGIN", "").lower() not in ("true", "1", "yes"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    demo_user = {
        "id": "demo-user",
        "email": token_id,
        "name": username,
        "tenant_id": os.getenv("DEFAULT_TENANT_ID", "demo-tenant"),
        "roles": ["admin", "user"],
    }
    token = _issue_token(demo_user)
    return {
        "token": token,
        "user": {"sub": demo_user["id"], "user_id": demo_user["id"], "tenant_id": demo_user["tenant_id"],
                 "name": demo_user["name"], "email": demo_user["email"], "roles": demo_user["roles"]},
    }


@app.patch("/api/v1/auth/me")
async def update_me(request: Request):
    body = await request.json()
    user = getattr(request.state, "user", None) or {}
    email = (user.get("email") or (user.get("sub") or "")).lower()
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")

    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(new_name) > 64:
        raise HTTPException(status_code=400, detail="name must be 64 characters or fewer")

    stored = await _find_user_by_email(email)
    if stored is None:
        stored = {
            "id": user.get("user_id") or user.get("sub") or email,
            "email": email,
            "name": user.get("name") or email.split("@")[0],
            "password_hash": "",
            "tenant_id": user.get("tenant_id") or user.get("tenantId") or os.getenv("DEFAULT_TENANT_ID", "demo-tenant"),
            "roles": user.get("roles") or ["admin"],
        }
        await _persist_user(stored)

    safe_name = new_name.replace("'", "\\'")
    _run_gremlin_query_threadsafe(
        f"g.V().hasLabel('User').has('email', '{email}').property('name', '{safe_name}')"
    )

    stored["name"] = new_name
    token = _issue_token(stored)
    return {
        "token": token,
        "user": {"sub": stored["id"], "user_id": stored["id"], "tenant_id": stored["tenant_id"],
                 "name": stored["name"], "email": stored["email"], "roles": stored["roles"]},
    }


# Per-source credential capabilities. Keys are the dashboard source keys.
# "github" supports full credential auth (token/repo/org/secret); others can
# later grow the same. Holds the auth info a client supplies to connect a real
# external system.
SUPPORTED_SOURCE_CREDENTIALS = {"github"}


def _mask_source_config(cfg: dict) -> dict:
    """Return a config with secrets blanked out for the GET response."""
    c = dict(cfg or {})
    if c.get("token"):
        c["token"] = "••••••••" + c["token"][-4:] if len(c["token"]) > 4 else "••••••"
    if c.get("webhook_secret") or c.get("webhookSecret"):
        c["webhook_secret"] = "••••••••"
    return c


async def _get_tenant_source_configs(tenant_id: str) -> dict:
    if not gremlin_client:
        return {}
    query = f"g.V().hasLabel('Settings').has('tenantId', '{tenant_id}').valueMap(true)"
    result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    if not result_list:
        return {}
    props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}
    import json
    raw = props.get("sourceConfigs")
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


async def _persist_tenant_source_configs(tenant_id: str, configs: dict) -> None:
    if not gremlin_client:
        return
    import json
    cfg_json = json.dumps(configs).replace("'", "\\'")
    now = datetime.now(timezone.utc).isoformat()
    query = (
        f"g.V().hasLabel('Settings').has('tenantId', '{tenant_id}').fold()"
        f".coalesce("
        f"unfold()"
        f".property('sourceConfigs', '{cfg_json}')"
        f".property('updatedAt', '{now}'),"
        f"addV('Settings')"
        f".property('tenantId', '{tenant_id}')"
        f".property('serviceName', 'settings')"
        f".property('sourceConfigs', '{cfg_json}')"
        f".property('updatedAt', '{now}')"
        f")"
    )
    await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)


@app.get("/api/v1/settings/sources")
async def get_source_configs(request: Request):
    tenant_id = _tenant(request)
    configs = await _get_tenant_source_configs(tenant_id)
    settings = await _get_tenant_settings(tenant_id) or {}
    statuses = settings.get("integrationStatuses", {})
    merged = {}
    for key in set(configs) | set((settings.get("sourceUrls") or {})):
        config = configs.get(key, {})
        merged[key] = _configure_source_config({**config, **(statuses.get(key) or {})})
    return {"sources": merged}


def _configure_source_config(cfg: dict) -> dict:
    c = dict(cfg or {})
    repo = c.get("repositories") or []
    if isinstance(repo, str):
        repo = c["repositories"]
    org = c.get("organizations") or c.get("org") or ""
    c.setdefault("configured", True)
    return {
        "token": _masked_token(c.get("token") or ""),
        "has_token": bool(c.get("token") or c.get("token_secret_name")),
        "repositories": repo if isinstance(repo, list) else ([repo] if repo else []),
        "organizations": _as_list(org),
        "webhook_secret": bool(c.get("webhook_secret") or c.get("webhookSecret")),
        "username": c.get("username") or "",
        "configured": True,
        "base_url": c.get("base_url") or "",
        "groups": c.get("groups") or [],
        "projects": c.get("projects") or [],
        "applications": c.get("applications") or [],
        "app_projects": c.get("app_projects") or [],
        "jobs": c.get("jobs") or [],
        "job_folders": c.get("job_folders") or [],
        "organization": c.get("organization") or "",
        "workspaces": c.get("workspaces") or [],
        "status": c.get("status") or c.get("state", "not_connected"),
        "last_successful_poll": c.get("lastSuccessfulPoll"),
        "last_event_received": c.get("lastEventReceived"),
        "events_last_24h": int(c.get("eventsLast24h", c.get("events_last_24h", 0)) or 0),
        "last_error": c.get("lastError"),
    }


def _masked_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 4:
        return "••••"
    return "••••" + token[-4:]


def _as_list(v):
    if isinstance(v, list):
        return v
    return [v] if v else []


@app.put("/api/v1/settings/sources/github")
async def update_github_source(request: Request):
    body = await request.json()
    tenant_id = _tenant(request)

    token = (body.get("token") or "").strip()
    repositories = _as_list(body.get("repositories") or [])
    organizations = _as_list(body.get("organizations") or body.get("org") or [])
    webhook_secret = (body.get("webhook_secret") or body.get("webhookSecret") or "").strip()
    branches = _as_list(body.get("branches") or []) or ["main", "master", "production"]

    if not token:
        raise HTTPException(status_code=400, detail="A GitHub token is required to connect.")

    configs = await _get_tenant_source_configs(tenant_id)
    existing = configs.get("github", {})
    refs = source_secret_refs(tenant_id, "github", ("token", "webhook-secret"))
    if key_vault_url():
        try:
            set_secret(refs["token"], token)
            if webhook_secret:
                set_secret(refs["webhook-secret"], webhook_secret)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not store GitHub credentials securely: {exc}")
    elif os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod"):
        raise HTTPException(status_code=503, detail="KEY_VAULT_URL is required in production")
    configs["github"] = {
        # Development can use the legacy value; production stores only refs.
        "token": token if not key_vault_url() else "",
        "token_secret_name": refs["token"] if key_vault_url() else "",
        "repositories": repositories,
        "organizations": organizations,
        "webhook_secret": webhook_secret if not key_vault_url() else "",
        "webhook_secret_name": refs["webhook-secret"] if key_vault_url() else "",
        "branches": branches,
        "username": (body.get("username") or existing.get("username") or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _persist_tenant_source_configs(tenant_id, configs)
    return {"sources": {k: _configure_source_config(v) for k, v in configs.items()}}


@app.post("/api/v1/settings/sources/github/test")
async def test_github_source(request: Request):
    body = await request.json()
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="A token is required to test.")

    import httpx
    url = "https://api.github.com/user"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code == 200:
                me = resp.json()
                username = me.get("login", "")
                # Verify repo visibility if provided
                repo_check = None
                repo = (body.get("repo") or "").strip()
                if repo:
                    repo_resp = await client.get(
                        f"https://api.github.com/repos/{repo}",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    )
                    repo_check = "ok" if repo_resp.status_code == 200 else f"repo not accessible ({repo_resp.status_code})"
                return {"ok": True, "username": username, "repo_check": repo_check}
            return {"ok": False, "error": f"GitHub rejected the token ({resp.status_code})"}
    except Exception as e:
        return {"ok": False, "error": f"Could not reach GitHub: {e}"}


# Native connector config (GitLab, Jenkins, ArgoCD, Terraform Cloud)
# Per-tenant credentials are stored in Key Vault; the Settings vertex holds refs.
_CONNECTOR_SECRET_KINDS = {
    "gitlab": ("token", "webhook-secret"),
    "jenkins": ("token",),
    "argocd": ("token",),
    "terraform": ("token",),
}

# Fields allowed per connector kind (whitelist to avoid persisting stray keys).
_CONNECTOR_FIELDS = {
    "gitlab": ["base_url", "token", "webhook_secret", "username", "groups", "projects", "branches", "poll_interval_seconds"],
    "jenkins": ["base_url", "token", "username", "jobs", "job_folders", "poll_interval_seconds"],
    "argocd": ["base_url", "token", "username", "password", "applications", "app_projects", "poll_interval_seconds"],
    "terraform": ["base_url", "token", "organization", "workspaces", "poll_interval_seconds"],
}


@app.put("/api/v1/settings/sources/{kind}")
async def update_native_source(kind: str, request: Request):
    if kind not in _CONNECTOR_SECRET_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported connector kind: {kind}")

    body = await request.json()
    tenant_id = _tenant(request)

    base_url = (body.get("base_url") or body.get("baseUrl") or "").strip()
    token = (body.get("token") or "").strip()
    if not base_url or not token:
        raise HTTPException(status_code=400, detail=f"A base_url and token are required to connect {kind}.")

    configs = await _get_tenant_source_configs(tenant_id)
    existing = configs.get(kind, {})
    kinds = _CONNECTOR_SECRET_KINDS[kind]
    refs = source_secret_refs(tenant_id, kind, kinds)
    if key_vault_url():
        try:
            set_secret(refs["token"], token)
            if "webhook-secret" in refs and (body.get("webhook_secret") or "").strip():
                set_secret(refs["webhook-secret"], (body.get("webhook_secret") or "").strip())
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not store {kind} credentials securely: {exc}")
    elif os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod"):
        raise HTTPException(status_code=503, detail="KEY_VAULT_URL is required in production")

    allowed = set(_CONNECTOR_FIELDS[kind])
    new_cfg: dict[str, Any] = {"base_url": base_url}
    if not key_vault_url():
        new_cfg["token"] = token
    else:
        new_cfg["token"] = ""
        new_cfg["token_secret_name"] = refs["token"]
    if "webhook-secret" in kinds and not key_vault_url() and (body.get("webhook_secret") or "").strip():
        new_cfg["webhook_secret"] = (body.get("webhook_secret") or "").strip()
    elif "webhook-secret" in kinds and key_vault_url() and (body.get("webhook_secret") or "").strip():
        new_cfg["webhook_secret_name"] = refs["webhook-secret"]

    for field in allowed:
        if field in {"base_url", "token", "webhook_secret"}:
            continue
        if field in body:
            new_cfg[field] = body[field]

    new_cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    configs[kind] = new_cfg
    await _persist_tenant_source_configs(tenant_id, configs)
    return {"sources": {k: _configure_source_config(v) for k, v in configs.items()}}


@app.post("/api/v1/settings/sources/{kind}/test")
async def test_native_source(kind: str, request: Request):
    """Verify a connector is reachable and authenticated before saving it."""
    if kind not in _CONNECTOR_SECRET_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported connector kind: {kind}")

    body = await request.json()
    base_url = (body.get("base_url") or body.get("baseUrl") or "").strip().rstrip("/")
    token = (body.get("token") or "").strip()
    if not base_url or not token:
        return {"ok": False, "error": "A base URL and token are required to test.", "kind": kind}

    import httpx

    label = kind.capitalize()
    if kind == "terraform":
        label = "Terraform Cloud"

    def _err(e: Exception) -> dict:
        return {"ok": False, "error": f"Could not reach {label}: {e}", "kind": kind}

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        try:
            if kind == "gitlab":
                api = base_url.rstrip("/") + "/api/v4"
                resp = await client.get(
                    f"{api}/user",
                    headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "username": resp.json().get("username", ""), "kind": kind}
                return {"ok": False, "error": f"GitLab rejected the token ({resp.status_code})", "kind": kind}

            if kind == "jenkins":
                label = "Jenkins"
                username = (body.get("username") or "").strip()
                import base64
                creds = base64.b64encode(f"{username}:{token}".encode()).decode() if username else token
                resp = await client.get(
                    f"{base_url}/api/json",
                    headers={"Authorization": f"Basic {creds}", "Accept": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"ok": True, "username": data.get("user", {}).get("fullName", "") or username, "kind": kind}
                return {"ok": False, "error": f"Jenkins rejected the credentials ({resp.status_code})", "kind": kind}

            if kind == "argocd":
                label = "ArgoCD"
                username = (body.get("username") or "").strip()
                password = (body.get("password") or body.get("token") or "").strip()
                if not username:
                    return {"ok": False, "error": "ArgoCD requires a username to test.", "kind": kind}
                # Exchange credentials for a session token, then probe applications.
                sess = await client.post(
                    f"{base_url}/api/v1/session",
                    json={"username": username, "password": password},
                )
                if sess.status_code != 200:
                    return {"ok": False, "error": f"ArgoCD login failed ({sess.status_code})", "kind": kind}
                token = sess.json().get("token")
                if not token:
                    return {"ok": False, "error": "ArgoCD login did not return a token.", "kind": kind}
                apps = await client.get(
                    f"{base_url}/api/v1/applications",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                ok = apps.status_code == 200
                return {
                    "ok": ok,
                    "error": None if ok else f"ArgoCD returned {apps.status_code} listing applications",
                    "applications": len(apps.json().get("items", [])) if ok else 0,
                    "kind": kind,
                }

            if kind == "terraform":
                label = "Terraform Cloud"
                org = (body.get("organization") or "").strip()
                # Determine host: default Terraform Cloud, or self-hosted TFE via base_url.
                if base_url and "app.terraform.io" not in base_url and "terraform.io" not in base_url:
                    host = base_url
                else:
                    host = "https://app.terraform.io"
                resp = await client.get(
                    f"{host}/api/v2/organizations/{org}",
                    headers={"Authorization": f"Bearer {token}", "TFC-X-Api-Version": "2022-11-07"},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {"ok": True, "organization": data.get("attributes", {}).get("name", org), "kind": kind}
                return {"ok": False, "error": f"Terraform rejected the token ({resp.status_code})", "kind": kind}
        except httpx.HTTPError as e:
            return _err(e)
        except Exception as e:
            return _err(e)

    return {"ok": False, "error": "Unsupported connector kind.", "kind": kind}


@app.delete("/api/v1/settings/sources/{kind}")
async def delete_native_source(kind: str, request: Request):
    if kind not in _CONNECTOR_SECRET_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported connector kind: {kind}")
    tenant_id = _tenant(request)
    configs = await _get_tenant_source_configs(tenant_id)
    if kind in configs:
        del configs[kind]
        await _persist_tenant_source_configs(tenant_id, configs)
    return {"sources": {k: _configure_source_config(v) for k, v in configs.items()}}


@app.get("/api/v1/settings/sources/health")
async def get_source_health_history(request: Request):
    """Return rolling integration health history for the tenant."""
    tenant_id = _tenant(request)
    if not gremlin_client:
        return {"history": []}
    query = f"g.V().hasLabel('Settings').has('tenantId', '{tenant_id}').valueMap(true)"
    result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    if not result_list:
        return {"history": []}
    props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}
    import json
    history_raw = props.get("integrationHistory")
    if not history_raw:
        return {"history": []}
    history = []
    if isinstance(history_raw, str):
        try:
            history = json.loads(history_raw)
        except Exception:
            history = []
    if not isinstance(history, list):
        history = [history] if isinstance(history, dict) else []
    statuses = props.get("integrationStatuses")
    statuses_obj = {}
    if isinstance(statuses, str):
        try:
            statuses_obj = json.loads(statuses)
        except Exception:
            statuses_obj = {}
    return {"history": history[-200:], "statuses": statuses_obj}


@app.get("/api/v1/settings/source-urls")
async def get_source_urls(request: Request):
    tenant_id = _tenant(request)
    stored = await _get_tenant_settings(tenant_id)
    merged = dict(SOURCE_URLS)
    if stored:
        merged.update(stored.get("sourceUrls", {}))
    return {"sources": merged}


@app.put("/api/v1/settings/source-urls")
async def update_source_urls(request: Request):
    body = await request.json()
    updates = body.get("sources", {})
    tenant_id = _tenant(request)
    stored = await _get_tenant_settings(tenant_id) or {}
    current = dict(stored.get("sourceUrls", {}))
    for key, value in updates.items():
        if key in SOURCE_URLS:
            current[key] = str(value)
    stored["tenantId"] = tenant_id
    stored["sourceUrls"] = current
    await _persist_tenant_settings(tenant_id, stored)
    merged = dict(SOURCE_URLS)
    merged.update(current)
    return {"sources": merged}


async def _get_tenant_settings(tenant_id: str) -> dict | None:
    if not gremlin_client:
        return None
    query = f"g.V().hasLabel('Settings').has('tenantId', '{tenant_id}').valueMap(true)"
    result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    if not result_list:
        return None
    props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}
    import json
    src = props.get("sourceUrls")
    statuses = props.get("integrationStatuses")
    if isinstance(statuses, str):
        try:
            statuses = json.loads(statuses)
        except Exception:
            statuses = {}
    return {
        "tenantId": props.get("tenantId", tenant_id),
        "sourceUrls": json.loads(src) if isinstance(src, str) else (src or {}),
        "integrationStatuses": statuses or {},
    }


async def _persist_tenant_settings(tenant_id: str, settings: dict) -> None:
    if not gremlin_client:
        return
    import json
    src_json = json.dumps(settings.get("sourceUrls", {})).replace("'", "\\'")
    statuses_json = json.dumps(settings.get("integrationStatuses", {})).replace("'", "\\'")
    now = datetime.now(timezone.utc).isoformat()
    query = (
        f"g.V().hasLabel('Settings').has('tenantId', '{tenant_id}').fold()"
        f".coalesce("
        f"unfold()"
        f".property('sourceUrls', '{src_json}')"
        f".property('integrationStatuses', '{statuses_json}')"
        f".property('updatedAt', '{now}'),"
        f"addV('Settings')"
        f".property('tenantId', '{tenant_id}')"
        f".property('serviceName', 'settings')"
        f".property('sourceUrls', '{src_json}')"
        f".property('integrationStatuses', '{statuses_json}')"
        f".property('updatedAt', '{now}')"
        f")"
    )
    await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)


def _generate_api_key() -> str:
    """Generate a per-tenant API key for programmatic /ingest access."""
    return "ct_" + secrets.token_urlsafe(32)


async def _ensure_tenant_api_key(tenant_id: str) -> str:
    """Create (or fetch) the tenant's API key and client id."""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    query = f"g.V().hasLabel('TenantKey').has('tenantId', '{tenant_id}').valueMap(true)"
    result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    if result_list:
        props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}
        # Existing plaintext keys are returned only for development migration.
        if props.get("apiKey") and os.getenv("ENVIRONMENT", "development").lower() not in ("production", "prod"):
            return props["apiKey"]
        secret_ref = props.get("apiKeySecretName")
        if secret_ref:
            stored = get_secret(secret_ref)
            if stored:
                return stored
        raise HTTPException(status_code=409, detail="API key is already provisioned; rotate it to reveal a new key")

    api_key = _generate_api_key()
    client_id = f"client-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    secret_ref = source_secret_refs(tenant_id, "tenant", ("api-key",))["api-key"]
    if key_vault_url():
        set_secret(secret_ref, api_key)
    query = (
        f"g.addV('TenantKey')"
        f".property('tenantId', '{tenant_id}')"
        f".property('serviceName', 'tenantkey')"
        f".property('clientId', '{client_id}')"
        f".property('apiKeyHash', '{_hash_api_key(api_key)}')"
        f".property('apiKeySecretName', '{secret_ref if key_vault_url() else ''}')"
        f".property('apiKey', '')"
        f".property('createdAt', '{now}')"
    )
    await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    return api_key


@app.get("/api/v1/settings/api-key")
async def get_tenant_api_key(request: Request):
    """Return the tenant's API key (only the plaintext on first view; store hashed thereafter)."""
    tenant_id = _tenant(request)
    api_key = await _ensure_tenant_api_key(tenant_id)
    return {
        "tenant_id": tenant_id,
        "client_id": None,
        "api_key": api_key,
        "usage": "Send Authorization: Bearer <api_key> when POSTing to the collector /ingest endpoint",
    }


@app.post("/api/v1/settings/api-key/rotate")
async def rotate_tenant_api_key(request: Request):
    """Rotate the tenant ingestion key; plaintext is returned only in this response."""
    tenant_id = _tenant(request)
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    api_key = _generate_api_key()
    client_id = f"client-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    secret_ref = source_secret_refs(tenant_id, "tenant", ("api-key",))["api-key"]
    if key_vault_url():
        set_secret(secret_ref, api_key)
    query = (
        f"g.V().hasLabel('TenantKey').has('tenantId', '{tenant_id}').fold()"
        f".coalesce(unfold()"
        f".property('clientId', '{client_id}')"
        f".property('apiKeyHash', '{_hash_api_key(api_key)}')"
        f".property('apiKeySecretName', '{secret_ref if key_vault_url() else ''}')"
        f".property('apiKey', '' )"
        f".property('updatedAt', '{now}'),"
        f"addV('TenantKey').property('tenantId', '{tenant_id}')"
        f".property('serviceName', 'tenantkey').property('clientId', '{client_id}')"
        f".property('apiKeyHash', '{_hash_api_key(api_key)}')"
        f".property('apiKeySecretName', '{secret_ref if key_vault_url() else ''}')"
        f".property('apiKey', '')"
        f".property('createdAt', '{now}'))"
    )
    await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
    return {"tenant_id": tenant_id, "client_id": client_id, "api_key": api_key,
            "usage": "Send Authorization: Bearer <api_key> when POSTing to the collector /ingest endpoint"}


# Health endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "dashboard-api",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")
    return {"status": "ready"}


# Dependency Graph endpoints
def _exec_gremlin(query: str) -> Any:
    """Run a Gremlin query in the shared executor thread pool."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(gremlin_executor, _run_gremlin_query, query)


async def _aggregate_latest_slo(tenant_id: str, services: list[str]) -> dict:
    """Latest SLOMetric per (service, sloName), keyed by service name -> sloName -> props."""
    out: dict[str, dict[str, dict]] = {}
    names = ",".join(f"'{s}'" for s in services if s)
    if not names:
        return out
    # One query per known SLO name — the group().by() pattern is the proven shape.
    for slo in ("availability", "latency_p99"):
        query = (
            f"g.V().hasLabel('SLOMetric').has('tenantId','{tenant_id}')"
            f".has('serviceName', within({names})).has('sloName','{slo}')"
            ".group().by('serviceName')"
            ".by(order().by('timestamp', decr).limit(1).project('actual','target','error_budget_remaining')"
            ".by('actual').by('target').by('errorBudgetRemaining'))"
        )
        try:
            rows = await _exec_gremlin(query)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                rows = rows[0]
            if isinstance(rows, dict):
                for svc, props in rows.items():
                    if isinstance(props, dict):
                        out.setdefault(svc, {})[slo] = props
        except Exception:
            pass
    return out


async def _aggregate_incidents(tenant_id: str, services: list[str], start_iso: str, end_iso: str) -> dict:
    """Incident counts per service in the last 24h."""
    out = {s: 0 for s in services if s}
    names = ",".join(f"'{s}'" for s in services if s)
    if not names:
        return out
    query = (
        f"g.V().hasLabel('Incident').has('tenantId','{tenant_id}')"
        f".has('affectedService', within({names}))"
        f".has('detectedAt', between('{start_iso}','{end_iso}'))"
        ".groupCount().by('affectedService')"
    )
    try:
        rows = await _exec_gremlin(query)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            rows = rows[0]
        if isinstance(rows, dict):
            for svc, count in rows.items():
                out[svc] = out.get(svc, 0) + int(count)
    except Exception:
        pass
    return out


async def _aggregate_deployments(tenant_id: str, services: list[str], start_iso: str, end_iso: str) -> dict:
    """ChangeEvent deployment counts per service in the last 24h."""
    out = {s: 0 for s in services if s}
    names = ",".join(f"'{s}'" for s in services if s)
    if not names:
        return out
    query = (
        f"g.V().hasLabel('ChangeEvent').has('tenantId','{tenant_id}')"
        f".has('serviceName', within({names}))"
        f".has('timestamp', between('{start_iso}','{end_iso}'))"
        ".groupCount().by('serviceName')"
    )
    try:
        rows = await _exec_gremlin(query)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            rows = rows[0]
        if isinstance(rows, dict):
            for svc, count in rows.items():
                out[svc] = out.get(svc, 0) + int(count)
    except Exception:
        pass
    return out


async def _aggregate_latest_risk(tenant_id: str, services: list[str]) -> dict:
    """Latest RiskScore per service, keyed by service name."""
    out: dict[str, float] = {}
    names = ",".join(f"'{s}'" for s in services if s)
    if not names:
        return out
    query = (
        f"g.V().hasLabel('RiskScore').has('tenantId','{tenant_id}')"
        f".has('serviceName', within({names}))"
        ".group().by('serviceName')"
        ".by(order().by('timestamp', decr).limit(1).values('riskScore'))"
    )
    try:
        rows = await _exec_gremlin(query)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            rows = rows[0]
        if isinstance(rows, dict):
            for svc, score in rows.items():
                try:
                    out[svc] = float(score[0] if isinstance(score, list) else score)
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return out


@app.get("/api/v1/graph/dependency", response_model=DependencyGraph)
async def get_dependency_graph(
    request: Request,
    namespace: str | None = Query(None, description="Filter by namespace"),
    include_metrics: bool = Query(True, description="Include SLO metrics"),
):
    """Get the full service dependency graph"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = _tq(tenant_id, "Service")
        if namespace:
            query += f".has('namespace', '{namespace}')"
        query += ".valueMap(true)"

        vertices = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)

        edge_query = (
            f"g.E().hasLabel('depends_on').has('tenantId', '{tenant_id}')"
            ".project('outV', 'inV', 'props').by(outV().id()).by(inV().id()).by(valueMap(true))"
        )
        edges = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, edge_query)

        # Enrich nodes with live per-service metrics from Cosmos instead of
        # hardcoded defaults, so the graph reflects real SLO/incident data.
        svc_names = []
        for v in vertices:
            props = {k: v[0] if isinstance(v, list) else v for k, v in v.items()}
            svc_names.append(props.get('serviceName', props.get('name', '')))

        now_iso = datetime.utcnow().isoformat()
        day_ago = (datetime.utcnow() - timedelta(hours=24)).isoformat()

        latest_slo = await _aggregate_latest_slo(tenant_id, svc_names)
        incident_counts = await _aggregate_incidents(tenant_id, svc_names, day_ago, now_iso)
        deploy_counts = await _aggregate_deployments(tenant_id, svc_names, day_ago, now_iso)
        risk_scores = await _aggregate_latest_risk(tenant_id, svc_names)

        nodes = []
        for v in vertices:
            props = {k: v[0] if isinstance(v, list) else v for k, v in v.items()}
            name = props.get('serviceName', props.get('name', ''))
            # The graph node SLO fields are rendered as percentages, so they
            # surface the availability SLO (per-service latest SLOMetric).
            avail = latest_slo.get(name, {}).get("availability") or {}
            # Only populate SLO fields when the service has REAL SLOMetric data.
            # Otherwise leave them null so the UI shows "no data" instead of a
            # fabricated default.
            has_real_slo = 'actual' in avail and 'target' in avail
            nodes.append(ServiceNode(
                id=props.get('id', ''),
                name=name,
                namespace=props.get('namespace'),
                criticality=props.get('criticality', 'medium'),
                slo_target=float(avail['target']) if has_real_slo else None,
                current_slo=float(avail['actual']) if has_real_slo else None,
                error_budget_remaining=float(avail.get('error_budget_remaining', 100.0)) if has_real_slo else None,
                incident_count_24h=incident_counts.get(name, 0),
                deployment_count_24h=deploy_counts.get(name, 0),
                current_risk_score=float(risk_scores.get(name, 0.0)),
            ))

        edge_list = []
        for e in edges:
            props = {k: v[0] if isinstance(v, list) else v for k, v in e.items()}
            edge_list.append(DependencyEdge(
                source=props.get('outV', ''),
                target=props.get('inV', ''),
                type=props.get('props', {}).get('type', 'depends_on'),
                latency_p99=props.get('props', {}).get('latencyP99'),
                error_rate=props.get('props', {}).get('errorRate'),
                request_volume=props.get('props', {}).get('requestVolume'),
            ))

        return DependencyGraph(
            nodes=nodes,
            edges=edge_list,
            updated_at=datetime.utcnow(),
        )
    except Exception as e:
        logger.error("Failed to fetch dependency graph", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch graph: {str(e)}")


@app.get("/api/v1/graph/blast-radius/{service_name}")
async def get_blast_radius(
    service_name: str,
    request: Request,
    namespace: str | None = Query(None),
    max_hops: int = Query(3, ge=1, le=5),
):
    """Get blast radius for a service"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().has('serviceName', '{service_name}').has('tenantId', '{tenant_id}')"
        if namespace:
            query += f".has('namespace', '{namespace}')"
        query += f".repeat(__.in('depends_on').simplePath()).times({max_hops}).emit().dedup().values('serviceName')"

        services = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)

        services = [s for s in services if s != service_name]

        return {
            "source_service": service_name,
            "affected_services": services,
            "hop_count": max_hops,
            "total_affected": len(services),
        }
    except Exception as e:
        logger.error("Failed to compute blast radius", service=service_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to compute blast radius: {str(e)}")


# Incident endpoints
@app.get("/api/v1/incidents", response_model=list[IncidentSummary])
async def get_incidents(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    service: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
    """Get incident timeline"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().hasLabel('Incident').has('tenantId', '{tenant_id}')"

        filters = []
        if severity:
            filters.append(f"has('severity', '{severity}')")
        if status:
            filters.append(f"has('status', '{status}')")
        if service:
            filters.append(f"has('affectedService', '{service}')")
        if start_time:
            filters.append(f"has('detectedAt', gte('{start_time.isoformat()}'))")
        if end_time:
            filters.append(f"has('detectedAt', lte('{end_time.isoformat()}'))")

        if filters:
            query += f".{''.join(filters)}"

        query += f".order().by('detectedAt', decr).range({offset}, {offset + limit})"

        query += ".valueMap(true)"

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        incidents = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            incidents.append(IncidentSummary(
                incident_id=props.get('incidentId', ''),
                title=props.get('title', ''),
                severity=props.get('severity', 'sev3'),
                status=props.get('status', 'open'),
                affected_service=props.get('affectedService', ''),
                detected_at=datetime.fromisoformat(props.get('detectedAt', datetime.utcnow().isoformat())),
                resolved_at=datetime.fromisoformat(props['resolvedAt']) if props.get('resolvedAt') else None,
                root_cause_candidate=props.get('rootCauseCandidate'),
                confidence=props.get('topCandidateConfidence'),
                remediation_action=props.get('remediationAction'),
            ))

        return incidents
    except Exception as e:
        logger.error("Failed to fetch incidents", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch incidents: {str(e)}")


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident_detail(incident_id: str, request: Request):
    """Get detailed incident information"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().has('incidentId', '{incident_id}').has('tenantId', '{tenant_id}').valueMap(true)"
        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)

        if not result_list:
            raise HTTPException(status_code=404, detail="Incident not found")

        props = {k: v[0] if isinstance(v, list) else v for k, v in result_list[0].items()}

        candidates_query = f"g.V().has('incidentId', '{incident_id}').has('tenantId', '{tenant_id}').out('has_candidate').has('tenantId', '{tenant_id}').valueMap(true)"
        candidates_raw = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, candidates_query)
        candidates = []
        for c in candidates_raw:
            cp = {k: v[0] if isinstance(v, list) else v for k, v in c.items()}
            candidates.append({
                "change_event_id": cp.get("changeEventId", ""),
                "service_name": cp.get("serviceName", ""),
                "change_type": cp.get("changeType", ""),
                "source": cp.get("source", ""),
                "timestamp": cp.get("timestamp", ""),
                "confidence_score": float(cp.get("confidenceScore", 0)),
                "evidence": cp.get("evidence", "{}"),
            })

        return {
            "incident_id": props.get("incidentId", ""),
            "title": props.get("title", ""),
            "severity": props.get("severity", ""),
            "status": props.get("status", ""),
            "affected_service": props.get("affectedService", ""),
            "affected_namespace": props.get("affectedNamespace", ""),
            "slo_name": props.get("sloName", ""),
            "error_budget_burn_rate": float(props.get("errorBudgetBurnRate", 0)),
            "detected_at": props.get("detectedAt", ""),
            "started_at": props.get("startedAt", ""),
            "resolved_at": props.get("resolvedAt", ""),
            "remediated_at": props.get("remediatedAt", ""),
            "candidates": candidates,
            "root_cause_candidate": props.get("rootCauseCandidate", ""),
            "confidence": float(props.get("topCandidateConfidence", 0)),
            "remediation_action": props.get("remediationAction", ""),
            "remediation_status": props.get("remediationStatus", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch incident detail", incident_id=incident_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch incident: {str(e)}")


class IncidentStatusUpdate(BaseModel):
    """Request to update an incident's lifecycle status."""
    status: str = Field(..., description="New status")


@app.patch("/api/v1/incidents/{incident_id}/status")
async def update_incident_status(incident_id: str, req: IncidentStatusUpdate, request: Request):
    """Advance an incident's lifecycle status."""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    allowed = {"open", "investigating", "root_cause_identified", "remediating",
               "verifying", "resolved", "closed"}
    if req.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")

    tenant_id = _tenant(request)
    now_iso = datetime.now(timezone.utc).isoformat()

    resolved_clause = ""
    if req.status in ("resolved", "closed"):
        resolved_clause = (
            f".property('resolvedAt','{now_iso}')"
            f".property('remediationStatus','completed')"
            f".property('remediatedAt','{now_iso}')"
        )
    elif req.status == "remediating":
        resolved_clause = f".property('remediationStatus','in_progress')"
    elif req.status == "verifying":
        resolved_clause = f".property('remediationStatus','verifying')"

    query = (
        f"g.V().has('incidentId', '{incident_id}').has('tenantId', '{tenant_id}')"
        f".property('status','{req.status}')"
        f"{resolved_clause}"
    )
    try:
        _run_gremlin_query_threadsafe(query)
    except Exception as e:
        logger.error("Failed to update incident status", incident_id=incident_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to update incident status: {str(e)}")

    return {"status": "ok", "incident_id": incident_id, "new_status": req.status}


# SLO/Burn Rate endpoints
@app.get("/api/v1/slo/burn-rate", response_model=list[SLOBurnData])
async def get_slo_burn_rate(
    request: Request,
    service: str | None = Query(None),
    slo_name: str | None = Query(None),
    hours: float = Query(24, ge=0.25, le=168),
    interval_minutes: int = Query(5, ge=1, le=60),
):
    """Get SLO burn rate data for charts from Gremlin DB / telemetry"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        query = f"g.V().hasLabel('SLOMetric').has('tenantId', '{tenant_id}').has('timestamp', gte('{cutoff}'))"
        if service:
            query += f".has('service', '{service}')"
        if slo_name:
            query += f".has('sloName', '{slo_name}')"
        query += ".order().by('timestamp', decr).limit(10000).valueMap(true)"

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)

        # Bucket raw points into interval_minutes buckets per service+slo so the
        # returned series matches the requested resolution and spans the whole
        # window instead of only the most recent points.
        interval_s = max(interval_minutes, 1) * 60
        buckets: dict[tuple[str, str, int], list[tuple[datetime, dict]]] = {}
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            ts_raw = props.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bucket = int(ts.timestamp() // interval_s)
            svc = props.get("service", service or "unknown")
            slo = props.get("sloName", slo_name or "availability")
            buckets.setdefault((svc, slo, bucket), []).append((ts, props))

        data = []
        for (svc, slo, bucket), points in buckets.items():
            bucket_ts = datetime.fromtimestamp(bucket * interval_s, tz=timezone.utc)
            actuals = [float(p.get("actual", 0)) for _, p in points]
            burns = [float(p.get("burnRate", 0)) for _, p in points]
            budgets = [float(p.get("errorBudgetRemaining", 0)) for _, p in points]
            data.append(SLOBurnData(
                timestamp=bucket_ts,
                service=svc,
                slo_name=slo,
                target=float(points[0][1].get("target", 99.9)),
                actual=sum(actuals) / len(actuals),
                burn_rate=sum(burns) / len(burns),
                error_budget_remaining=sum(budgets) / len(budgets),
            ))

        data.sort(key=lambda d: (d.service, d.slo_name, d.timestamp))

        return data
    except Exception as e:
        logger.error("Failed to query SLO burn rate", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to query SLO burn rate: {str(e)}")


@app.get("/api/v1/slo/status")
async def get_slo_status(
    request: Request,
    service: str | None = Query(None),
):
    """Get current SLO status for all services from Gremlin DB"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().hasLabel('Service').has('tenantId', '{tenant_id}')"
        if service:
            query += f".has('serviceName', '{service}')"
        query += ".valueMap(true)"

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        svc_names = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            svc_names.append(props.get("serviceName", props.get("name", "")))
        latest_slo = await _aggregate_latest_slo(tenant_id, svc_names)
        services = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            srv_name = props.get("serviceName", "service")
            live = latest_slo.get(srv_name, {})
            # Only report SLOs that have REAL data. If no SLOMetric exists for a
            # service, do NOT fabricate availability/latency values — otherwise the
            # dashboard shows fake numbers for an otherwise-empty tenant.
            slos = []
            avail = live.get("availability") or {}
            if "actual" in avail:
                slos.append({
                    "name": "availability",
                    "target": float(avail.get("target", props.get("slo_availability_target", 99.9))),
                    "current": float(avail.get("actual")),
                    "error_budget_remaining": float(avail.get("error_budget_remaining", 85.2)),
                    "burn_rate": float(props.get("burn_rate", 1.0)),
                    "status": props.get("slo_status", "healthy"),
                })
            lat = live.get("latency_p99") or {}
            if "actual" in lat:
                slos.append({
                    "name": "latency_p99",
                    "target": float(lat.get("target", 500.0)),
                    "current": float(lat.get("actual")),
                    "error_budget_remaining": float(lat.get("error_budget_remaining", 92.1)),
                    "burn_rate": float(props.get("latency_burn_rate", 0.8)),
                    "status": "healthy",
                })
            # Fallback: latency only if the Service vertex actually carries real
            # latency props (never the hardcoded fallbacks).
            elif props.get("slo_latency_target") is not None and props.get("slo_latency_current") is not None:
                slos.append({
                    "name": "latency_p99",
                    "target": float(props.get("slo_latency_target")),
                    "current": float(props.get("slo_latency_current")),
                    "error_budget_remaining": float(props.get("latency_budget_remaining", 92.1)),
                    "burn_rate": float(props.get("latency_burn_rate", 0.8)),
                    "status": "healthy",
                })
            services.append({
                "name": srv_name,
                "namespace": props.get("namespace", "default"),
                "slos": slos,
            })

        if not services:
            services = []

        return {
            "services": services,
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to query SLO status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to query SLO status: {str(e)}")


# Risk Score endpoints
@app.get("/api/v1/risk/history", response_model=list[RiskScoreHistory])
async def get_risk_history(
    request: Request,
    service: str | None = Query(None),
    hours: int = Query(168, ge=1, le=720),  # Up to 30 days
    limit: int = Query(100, ge=1, le=500),
):
    """Get risk score history from Gremlin DB"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().hasLabel('RiskScore').has('tenantId', '{tenant_id}')"
        if service:
            query += f".has('service', '{service}')"
        query += f".order().by('timestamp', decr).limit({limit}).valueMap(true)"

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        data = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            ts_raw = props.get("timestamp")
            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()
            score = float(props.get("riskScore", 0.3))
            level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
            data.append(RiskScoreHistory(
                timestamp=ts,
                service=props.get("service", service or "unknown"),
                deployment_id=props.get("deploymentId", "deploy-0"),
                risk_score=score,
                risk_level=level,
                factors={
                    "change_size": float(props.get("changeSize", 0.4)),
                    "service_criticality": float(props.get("serviceCriticality", 0.8)),
                    "recent_incidents": float(props.get("recentIncidents", 0.2)),
                    "dependency_risk": float(props.get("dependencyRisk", 0.3)),
                },
            ))

        if not data:
            data = []

        return data
    except Exception as e:
        logger.error("Failed to query risk history", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to query risk history: {str(e)}")


@app.get("/api/v1/risk/current")
async def get_current_risk_scores(
    request: Request,
    service: str | None = Query(None),
):
    """Get current risk scores for all services from Gremlin DB"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().hasLabel('Service').has('tenantId', '{tenant_id}')"
        if service:
            query += f".has('serviceName', '{service}')"
        query += ".valueMap(true)"

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        scores = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            srv = props.get("serviceName", "service")
            score = float(props.get("currentRiskScore", 0.35))
            level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
            scores.append({
                "service": srv,
                "risk_score": score,
                "risk_level": level,
                "last_deployment": props.get("lastDeploymentId", "deploy-latest"),
                "last_deployment_time": props.get("lastDeploymentTime", datetime.utcnow().isoformat()),
                "deployment_count_24h": props.get("deploymentCount24h", 0),
                "incident_count_24h": props.get("incidentCount24h", 0),
                "namespace": props.get("namespace", ""),
                "factors": {
                    "change_size": float(props.get("changeSize", 0.3)),
                    "service_criticality": float(props.get("serviceCriticality", 0.7)),
                    "recent_incidents": float(props.get("recentIncidents", 0.1)),
                    "dependency_risk": float(props.get("dependencyRisk", 0.3)),
                },
            })

        if not scores:
            scores = []

        return {
            "scores": scores,
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to query current risk scores", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to query current risk scores: {str(e)}")


# Correlation Accuracy endpoints
@app.get("/api/v1/correlation/accuracy", response_model=CorrelationAccuracy)
async def get_correlation_accuracy(
    request: Request,
    days: int = Query(30, ge=1, le=90),
):
    """Get correlation accuracy metrics derived from graph evaluation records"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        query = f"g.V().hasLabel('Incident').has('status', 'resolved').has('tenantId', '{tenant_id}').valueMap(true)"
        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        
        incidents = []
        top1_hits = 0
        top3_hits = 0
        detection_times = []  # seconds between start and detection
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            incidents.append(props)
            rank = props.get("trueCauseRank")
            if rank == 1:
                top1_hits += 1
                top3_hits += 1
            elif rank in (2, 3):
                top3_hits += 1

            # MTTD = mean(detectedAt - startedAt) over resolved incidents.
            try:
                det = props.get("detectedAt")
                start = props.get("startedAt")
                if det and start:
                    d = datetime.fromisoformat(str(det).replace("Z", "+00:00"))
                    s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                    # both are timezone-aware (or naive); coerce to avoid tz errors
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    if s.tzinfo is None:
                        s = s.replace(tzinfo=timezone.utc)
                    delta = (d - s).total_seconds()
                    if delta >= 0:
                        detection_times.append(delta)
            except Exception:
                pass

        total = len(incidents)
        if total >= 5:
            p1 = round(top1_hits / total, 2)
            p3 = round(top3_hits / total, 2)
        else:
            p1 = 0.0
            p3 = 0.0
        rec = 0.0
        tot_incidents = total
        mttd = round(sum(detection_times) / len(detection_times), 1) if detection_times else 0.0

        return CorrelationAccuracy(
            period_start=start_time,
            period_end=end_time,
            total_incidents=tot_incidents,
            precision_at_1=p1,
            precision_at_3=p3,
            recall=rec,
            mean_time_to_detection_seconds=mttd,
            model_version="1.0-live",
        )
    except Exception as e:
        logger.error("Failed to calculate correlation accuracy", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to calculate correlation accuracy: {str(e)}")


@app.get("/api/v1/correlation/accuracy/history")
async def get_correlation_accuracy_history(
    request: Request,
    days: int = Query(90, ge=1, le=365),
):
    """Get correlation accuracy over time from evaluation records"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        query = f"g.V().hasLabel('Incident').has('status', 'resolved').has('tenantId', '{tenant_id}').valueMap(true)"
        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)

        by_day: dict[str, list[dict]] = {}
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            ts = props.get("resolvedAt") or props.get("detectedAt") or ""
            try:
                day = datetime.fromisoformat(ts).date().isoformat()
            except (ValueError, TypeError):
                continue
            if start_time.date().isoformat() <= day <= end_time.date().isoformat():
                by_day.setdefault(day, []).append(props)

        data = []
        for day in sorted(by_day):
            incidents = by_day[day]
            total = len(incidents)
            top1 = sum(1 for i in incidents if i.get("trueCauseRank") == 1)
            top3 = sum(1 for i in incidents if i.get("trueCauseRank") in (1, 2, 3))
            data.append({
                "date": day,
                "total_incidents": total,
                "precision_at_1": round(top1 / total, 2) if total else 0.0,
                "precision_at_3": round(top3 / total, 2) if total else 0.0,
                "recall": 0.0,
                "model_version": "1.0-live",
            })

        return {"history": data}
    except Exception as e:
        logger.error("Failed to query accuracy history", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to query accuracy history: {str(e)}")


# Change History endpoints
@app.get("/api/v1/changes")
async def get_changes(
    request: Request,
    service: str | None = Query(None),
    source: str | None = Query(None),
    change_type: str | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
):
    """Get recent changes"""
    if not gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not initialized")

    tenant_id = _tenant(request)

    try:
        query = f"g.V().hasLabel('ChangeEvent').has('tenantId', '{tenant_id}')"
        if service:
            query += f".has('serviceName', '{service}')"
        if source:
            query += f".has('source', '{source}')"
        if change_type:
            query += f".has('changeType', '{change_type}')"
        query += f".has('timestamp', gte('{(datetime.utcnow() - timedelta(hours=hours)).isoformat()}')).order().by('timestamp', decr).limit({limit}).valueMap(true)"

        def _run_gremlin_query(q: str):
            rs = gremlin_client.submit(q)
            return rs.all().result()

        result_list = await asyncio.get_running_loop().run_in_executor(gremlin_executor, _run_gremlin_query, query)
        changes = []
        for result in result_list:
            props = {k: v[0] if isinstance(v, list) else v for k, v in result.items()}
            changes.append(props)

        return {"changes": changes, "count": len(changes)}
    except Exception as e:
        logger.error("Failed to fetch changes", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch changes: {str(e)}")


# Metrics endpoint for Prometheus
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def main():
    """Main entry point"""
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        host: str = "0.0.0.0"
        port: int = 8002
        log_level: str = "info"

        class Config:
            env_file = ".env"

    settings = Settings()

    uvicorn_config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        lifespan="on",
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
