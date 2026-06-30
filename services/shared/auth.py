"""Azure AD / Entra ID Authentication for ChangeTrace APIs."""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from jwt import PyJWKClient, decode as jwt_decode

logger = logging.getLogger(__name__)

JWKS_CACHE: Dict[str, Any] = {}
JWKS_CACHE_EXPIRY: Optional[datetime] = None


def get_simple_auth_secret() -> str:
    """Return the SIMPLE_AUTH_SECRET, failing closed in production if unset."""
    secret = os.getenv("SIMPLE_AUTH_SECRET", "")
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if secret:
        return secret
    if environment in ("production", "prod"):
        raise RuntimeError("SIMPLE_AUTH_SECRET is required when ENVIRONMENT=production")
    return "changetrace-dev-secret"


class AzureADAuth:
    def __init__(self):
        self.tenant_id = os.getenv("AZURE_TENANT_ID", "")
        self.client_id = os.getenv("AZURE_CLIENT_ID", "")
        self.required_roles = os.getenv("APP_ROLES", "").split(",") if os.getenv("APP_ROLES") else []
        self._jwks_uri = (
            f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
            if self.tenant_id else ""
        )

    @property
    def disabled(self) -> bool:
        """Whether the DISABLE_AUTH bypass is active."""
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment in ("production", "prod"):
            return False
        return os.getenv("DISABLE_AUTH", "").lower() in ("true", "1", "yes")

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    async def get_jwks_client(self) -> PyJWKClient:
        if not self._jwks_uri:
            raise ValueError("AZURE_TENANT_ID not configured")
        return PyJWKClient(self._jwks_uri)

    def decode_token(self, token: str) -> Dict[str, Any]:
        jwks_client = PyJWKClient(self._jwks_uri)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt_decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.client_id,
            issuer=self.issuer,
            options={"verify_exp": True},
        )


auth_handler = AzureADAuth()
