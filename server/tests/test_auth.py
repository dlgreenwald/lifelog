"""Unit tests for auth module (API key + OIDC JWKS validation)."""

from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_validate_api_key_valid():
    """Valid API key returns user dict."""
    from lifelog.auth import validate_api_key

    fake_user = {"id": 1, "api_key": "valid-key", "name": "Test"}

    with patch(
        "lifelog.database.get_user_by_api_key", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = fake_user
        result = await validate_api_key(x_api_key="valid-key")
        assert result == fake_user
        mock_get.assert_awaited_once_with("valid-key")


@pytest.mark.asyncio
async def test_validate_api_key_invalid():
    """Invalid API key raises 401."""
    from lifelog.auth import validate_api_key

    with patch(
        "lifelog.database.get_user_by_api_key", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key(x_api_key="bad-key")
        assert exc_info.value.status_code == 401


def _make_jwk_mock(private_key):
    """Create a mock PyJWKClient that returns a signing key from the given RSA key."""

    # Build a JWKS-like dict from the public key
    public_pem = private_key.public_key().public_bytes(
        encoding=__import__(
            "cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]
        ).Encoding.PEM,
        format=__import__(
            "cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]
        ).PublicFormat.SubjectPublicKeyInfo,
    )
    # PyJWK can construct from a jwk dict — use the PEM for the mock
    signing_key = MagicMock()
    signing_key.key = public_pem.decode()

    mock_jwk_client = MagicMock()
    mock_jwk_client.get_signing_key_from_jwt.return_value = signing_key
    return mock_jwk_client


@pytest.mark.asyncio
async def test_validate_oidc_token_valid():
    """Valid OIDC token verified via JWKS returns user dict."""
    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from lifelog.auth import validate_oidc_token

    # Generate RSA key pair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    token_payload = {
        "sub": "user-123",
        "aud": "test-client",
        "iss": "https://auth.test.com",
    }
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")

    fake_user = {"id": 1, "oidc_sub": "user-123", "name": "Test"}
    mock_token = MagicMock()
    mock_token.credentials = token

    mock_jwk_client = _make_jwk_mock(private_key)

    with (
        patch("lifelog.auth._get_jwk_client", return_value=mock_jwk_client),
        patch("lifelog.auth.settings") as mock_settings,
        patch(
            "lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock
        ) as mock_get,
    ):
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"
        mock_get.return_value = fake_user
        result = await validate_oidc_token(token=mock_token)
        assert result == fake_user


@pytest.mark.asyncio
async def test_validate_oidc_token_invalid():
    """Invalid token raises 401."""
    from lifelog.auth import validate_oidc_token

    mock_token = MagicMock()
    mock_token.credentials = "not-a-valid-jwt"

    mock_jwk_client = MagicMock()
    mock_jwk_client.get_signing_key_from_jwt.side_effect = pyjwt.InvalidTokenError()

    with patch("lifelog.auth._get_jwk_client", return_value=mock_jwk_client):
        with patch("lifelog.auth.settings") as mock_settings:
            mock_settings.oidc_client_id = "client"
            mock_settings.oidc_issuer_url = "https://auth.test.com"

            with pytest.raises(HTTPException) as exc_info:
                await validate_oidc_token(token=mock_token)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_oidc_token_user_not_found():
    """Valid token but user not in DB — auto-creates new user."""
    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from lifelog.auth import validate_oidc_token

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    token_payload = {
        "sub": "unknown-user",
        "aud": "test-client",
        "iss": "https://auth.test.com",
    }
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")

    mock_token = MagicMock()
    mock_token.credentials = token

    mock_jwk_client = _make_jwk_mock(private_key)
    new_user = {"id": 99, "oidc_sub": "unknown-user", "name": "User"}

    with (
        patch("lifelog.auth._get_jwk_client", return_value=mock_jwk_client),
        patch("lifelog.auth.settings") as mock_settings,
        patch(
            "lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock
        ) as mock_get,
        patch("lifelog.database.create_user", new_callable=AsyncMock) as mock_create,
    ):
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"
        mock_get.return_value = None
        mock_create.return_value = new_user
        result = await validate_oidc_token(token=mock_token)
        assert result == new_user
        mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejects_http_oidc_issuer():
    """OIDC discovery rejects non-HTTPS issuer URLs."""
    from lifelog.auth import _get_jwk_client

    with patch("lifelog.auth.settings") as mock_settings:
        mock_settings.oidc_issuer_url = "http://evil.example.com/issuer"
        with pytest.raises(ValueError, match="HTTPS"):
            _get_jwk_client()


@pytest.mark.asyncio
async def test_rejects_http_jwks_uri():
    """OIDC discovery rejects non-HTTPS JWKS URIs in discovery response."""
    from lifelog.auth import _get_jwk_client

    fake_discovery = {"jwks_uri": "http://evil.example.com/jwks"}

    with (
        patch("lifelog.auth.settings") as mock_settings,
        patch("lifelog.auth.httpx.Client") as MockClient,
    ):
        mock_settings.oidc_issuer_url = "https://auth.test.com"
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_discovery
        mock_resp.raise_for_status = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(
            return_value=MockClient.return_value
        )
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        MockClient.return_value.get.return_value = mock_resp
        with pytest.raises(ValueError, match="HTTPS"):
            _get_jwk_client()
