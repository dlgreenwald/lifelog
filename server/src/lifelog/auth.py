import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer

from lifelog.config import settings

security = HTTPBearer()

# JWKS client — fetches and caches the OIDC provider's signing keys
_jwk_client = None


def _get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        # Fetch the OpenID configuration to get the correct jwks_uri
        import urllib.request
        discovery_url = f"{settings.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
        with urllib.request.urlopen(discovery_url) as resp:
            discovery = __import__('json').load(resp)
        jwks_url = discovery["jwks_uri"]
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
