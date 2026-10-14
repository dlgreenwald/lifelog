"""OIDC JWT validation — Bearer token validation against OIDC JWKS.

The MCP server receives Bearer tokens forwarded by LibreChat (via OBO token exchange).
This module validates those tokens and extracts the user_id for per-user query scoping.
"""

from __future__ import annotations

import logging

import jwt as pyjwt

from lifelog_mcp.config import settings

logger = logging.getLogger("lifelog_mcp")

# JWKS clients keyed by issuer URL — one per OIDC provider
_jwk_clients: dict[str, pyjwt.PyJWKClient] = {}


def _get_jwk_client(issuer: str) -> pyjwt.PyJWKClient:
    """Return a JWKS client for the given issuer, cached per-issuer."""
    if issuer not in _jwk_clients:
        jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
        logger.debug("jwks_client_create issuer=%s jwks_url=%s", issuer, jwks_url)
        _jwk_clients[issuer] = pyjwt.PyJWKClient(jwks_url)
    else:
        logger.debug("jwks_client_cache_hit issuer=%s", issuer)
    return _jwk_clients[issuer]


class AuthError(Exception):
    """Raised when token validation fails."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def validate_bearer_token(token: str) -> dict:
    """Validate a raw Bearer token string and return the decoded payload.

    Raises:
        AuthError: if the token is invalid, expired, or the issuer is unreachable.
    """
    if not token:
        raise AuthError("Empty token")

    if not settings.lifelog_oidc_issuer:
        raise AuthError("LIFELOG_OIDC_ISSUER not configured")

    try:
        client = _get_jwk_client(settings.lifelog_oidc_issuer)
        logger.debug("jwks_fetch_signing_key")
        signing_key = client.get_signing_key_from_jwt(token)
        logger.debug("jwks_signing_key_fetched key_id=%s", signing_key.key_id)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=None,  # Audience validation done by the main server
            issuer=settings.lifelog_oidc_issuer,
        )
        return dict(payload)
    except pyjwt.ExpiredSignatureError:
        raise AuthError("Token has expired")
    except pyjwt.InvalidAudienceError:
        raise AuthError("Invalid token audience")
    except pyjwt.InvalidIssuerError:
        raise AuthError("Invalid token issuer")
    except Exception as exc:  # noqa: BLE001  # Broad: PyJWKClient raises varied network/decode errors
        logger.warning("token_validation_error error=%s issuer=%s", exc, settings.lifelog_oidc_issuer)
        raise AuthError(f"Token validation failed: {exc}")


def extract_user_id(payload: dict) -> int | None:
    """Extract numeric user_id from JWT payload.

    The 'sub' claim holds the OIDC subject identifier. The main server maintains
    a user table mapping oidc_sub to integer id — we delegate user_id resolution
    to the main server by calling the /api/v1/me endpoint.
    Returns None if user_id cannot be determined.
    """
    # The main server's /api/v1/me endpoint resolves oidc_sub -> user_id.
    # We call it lazily inside each tool rather than here so tools get fresh resolution.
    return None  # Caller must use _resolve_user_id() instead


async def _resolve_user_id(token: str, payload: dict) -> int:
    """Resolve the numeric user_id from a validated token by calling the main server."""
    import httpx

    sub = payload.get("sub")
    if not sub:
        raise AuthError("Token missing 'sub' claim")

    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    ) as client:
        resp = await client.get("/api/v1/me")
        if resp.status_code == 401:
            raise AuthError("Token rejected by main server")
        resp.raise_for_status()
        data = resp.json()
        user_id = data.get("id")
        if not user_id:
            raise AuthError("Main server returned user without id")
        return int(user_id)
