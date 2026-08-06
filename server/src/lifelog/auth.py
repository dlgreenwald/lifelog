from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer

from lifelog.config import settings

security = HTTPBearer()


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
    """Validate OIDC JWT token and return user info."""
    import jwt

    from lifelog.database import get_user_by_oidc_sub

    try:
        payload = jwt.decode(
            token.credentials,
            settings.oidc_client_secret,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer_url,
        )
        user = await get_user_by_oidc_sub(payload["sub"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
