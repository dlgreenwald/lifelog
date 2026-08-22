import httpx
import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer

from lifelog.config import settings

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


async def validate_oidc_token(
    token: str = Depends(security),
) -> dict:
    """Validate OIDC JWT token using JWKS public key."""
    from lifelog.database import get_user_by_oidc_sub

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
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
