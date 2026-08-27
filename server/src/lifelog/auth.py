import logging

import httpx
import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer

from lifelog.config import settings

logger = logging.getLogger("lifelog.auth")

security = HTTPBearer()

# JWKS client — fetches and caches the OIDC provider's signing keys
_jwk_client = None


def _get_jwk_client():
    global _jwk_client
    if _jwk_client is not None:
        return _jwk_client

    issuer = settings.oidc_issuer_url.rstrip("/")
    if not issuer.startswith("https://"):
        raise ValueError("OIDC issuer URL must use HTTPS")

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        resp = client.get(discovery_url)
        resp.raise_for_status()
        discovery = resp.json()

    jwks_url = discovery["jwks_uri"]
    if not jwks_url.startswith("https://"):
        raise ValueError("JWKS URI must use HTTPS")

    _jwk_client = pyjwt.PyJWKClient(jwks_url)
    return _jwk_client


async def validate_api_key(x_api_key: str = Header(...)) -> dict:
    """Validate API key and return user info."""
    from lifelog.database import get_user_by_api_key

    user = await get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


async def validate_bearer_token(token: str) -> dict:
    """Validate a raw Bearer token string (not a FastAPI dependency).

    Used by endpoints that accept both API key and Bearer token auth.
    """
    from lifelog.database import get_user_by_oidc_sub

    # Decode payload without verification for logging in error handlers
    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.InvalidTokenError:
        payload = {}

    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer_url,
        )
        user = await get_user_by_oidc_sub(payload["sub"])
        if not user:
            from lifelog.database import create_user
            user = await create_user(
                oidc_sub=payload["sub"],
                name=payload.get("preferred_username", payload.get("sub", "User")),
            )
        return user
    except pyjwt.ExpiredSignatureError:
        logger.warning("Token expired: sub=%s exp=%s", payload.get("sub", "?"), payload.get("exp", "?"))
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidAudienceError:
        logger.warning("Invalid audience: token_aud=%s expected=%s", payload.get("aud", "?"), settings.oidc_client_id)
        raise HTTPException(status_code=401, detail="Invalid audience")
    except pyjwt.InvalidIssuerError:
        logger.warning("Invalid issuer: token_iss=%s expected=%s", payload.get("iss", "?"), settings.oidc_issuer_url)
        raise HTTPException(status_code=401, detail="Invalid issuer")
    except pyjwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")


async def validate_oidc_token(
    token: str = Depends(security),
) -> dict:
    """Validate OIDC JWT token using JWKS public key."""
    from lifelog.database import get_user_by_oidc_sub

    # Decode payload without verification for logging in error handlers
    try:
        payload = pyjwt.decode(token.credentials, options={"verify_signature": False})
    except pyjwt.InvalidTokenError:
        payload = {}

    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token.credentials)
        payload = pyjwt.decode(
            token.credentials,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer_url,
        )
        user = await get_user_by_oidc_sub(payload["sub"])
        if not user:
            # First OIDC login — auto-create user
            from lifelog.database import create_user
            user = await create_user(
                oidc_sub=payload["sub"],
                name=payload.get("preferred_username", payload.get("sub", "User")),
            )
        return user
    except pyjwt.ExpiredSignatureError:
        logger.warning("Token expired: sub=%s exp=%s", payload.get("sub", "?"), payload.get("exp", "?"))
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidAudienceError:
        logger.warning("Invalid audience: token_aud=%s expected=%s", payload.get("aud", "?"), settings.oidc_client_id)
        raise HTTPException(status_code=401, detail="Invalid audience")
    except pyjwt.InvalidIssuerError:
        logger.warning("Invalid issuer: token_iss=%s expected=%s", payload.get("iss", "?"), settings.oidc_issuer_url)
        raise HTTPException(status_code=401, detail="Invalid issuer")
    except pyjwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
