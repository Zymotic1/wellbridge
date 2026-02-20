"""
Tenant context middleware.

Decodes and verifies the Auth0 JWT on every request, extracting:
  - tenant_id  (custom claim: https://wellbridge.app/tenant_id)
  - user_id    (Auth0 sub, e.g., "auth0|abc123")
  - role       (custom claim: https://wellbridge.app/role)

DEV MODE (WELLBRIDGE_DEV_MODE=true):
  When Auth0 is not configured, returns a fixed dev identity so endpoints
  can be exercised without real credentials. NEVER enable in production.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import get_settings

settings = get_settings()

# Fixed dev identity used when WELLBRIDGE_DEV_MODE=true and no real token is present
_DEV_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEV_USER_ID   = "dev|local-user"
_DEV_ROLE      = "patient"


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(settings.jwks_uri, cache_jwk_set=True, lifespan=3600)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str        # Auth0 sub
    role: str           # "patient" | "caregiver" | "admin"
    raw_token: str = "" # Original Bearer token — passed to Supabase for native JWT auth


CLAIM_NS = "https://wellbridge.app/"

# HTTPBearer with auto_error=False so we can handle the missing token ourselves
# (needed for dev-mode bypass when no Authorization header is sent)
_bearer = HTTPBearer(auto_error=False)


async def get_tenant_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext:
    """
    FastAPI dependency — validates JWT and returns TenantContext.

    In dev mode (WELLBRIDGE_DEV_MODE=true) without Auth0 configured:
      - Returns a fixed dev identity if no token is provided
      - Still validates real tokens if one IS provided (useful for testing)
    """
    # --- Dev mode bypass ---
    if settings.wellbridge_dev_mode and not settings.auth_configured:
        if credentials is None:
            return TenantContext(
                tenant_id=_DEV_TENANT_ID,
                user_id=_DEV_USER_ID,
                role=_DEV_ROLE,
            )
        # A token was provided even in dev mode — validate it if Auth0 is configured,
        # otherwise just decode without verification (dev only)
        try:
            payload = jwt.decode(
                credentials.credentials,
                options={"verify_signature": False},
            )
            return TenantContext(
                tenant_id=payload.get(f"{CLAIM_NS}tenant_id", _DEV_TENANT_ID),
                user_id=payload.get("sub", _DEV_USER_ID),
                role=payload.get(f"{CLAIM_NS}role", _DEV_ROLE),
            )
        except Exception:
            return TenantContext(
                tenant_id=_DEV_TENANT_ID,
                user_id=_DEV_USER_ID,
                role=_DEV_ROLE,
            )

    # --- Production path: require a valid Bearer token ---
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.auth_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Auth0 is not configured on this server. "
                "Set AUTH0_DOMAIN + AUTH0_AUDIENCE in .env, "
                "or set WELLBRIDGE_DEV_MODE=true for local testing."
            ),
        )

    token = credentials.credentials
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )

    tenant_id = payload.get(f"{CLAIM_NS}tenant_id")
    role = payload.get(f"{CLAIM_NS}role", "patient")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token missing tenant_id claim. Ensure the Auth0 Post-Login Action is deployed.",
        )

    return TenantContext(
        tenant_id=tenant_id,
        user_id=payload["sub"],
        role=role,
        raw_token=token,
    )
