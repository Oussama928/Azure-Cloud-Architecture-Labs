"""User account + tenant management for ChangeTrace (multi-tenant SaaS)."""

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timezone

_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False


def new_tenant_id() -> str:
    return f"tenant-{uuid.uuid4().hex[:12]}"


def new_user_id() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def build_user_from_vertex(props: dict) -> dict:
    return {
        "id": props.get("userId") or props.get("id", ""),
        "email": props.get("email", ""),
        "name": props.get("name", ""),
        "password_hash": props.get("passwordHash", ""),
        "tenant_id": props.get("tenantId", ""),
        "roles": (props.get("roles") or "admin").split(","),
        "created_at": props.get("createdAt", ""),
    }
