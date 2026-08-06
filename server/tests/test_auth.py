"""Unit tests for auth module (API key + OIDC validation)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_validate_api_key_valid():
    """Valid API key returns user dict."""
    from lifelog.auth import validate_api_key

    fake_user = {"id": 1, "api_key": "valid-key", "name": "Test"}

    with patch("lifelog.database.get_user_by_api_key", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fake_user
        result = await validate_api_key(x_api_key="valid-key")
        assert result == fake_user
        mock_get.assert_awaited_once_with("valid-key")


@pytest.mark.asyncio
async def test_validate_api_key_invalid():
    """Invalid API key raises 401."""
    from lifelog.auth import validate_api_key

    with patch("lifelog.database.get_user_by_api_key", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key(x_api_key="bad-key")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_oidc_token_valid():
    """Valid OIDC token returns user dict.

    We sign with RS256 to match the decode algorithm, using a generated
    RSA key pair so the test is self-contained.
    """
    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from lifelog.auth import validate_oidc_token

    # Generate a real RSA key pair for the test
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    secret = public_pem.decode()  # jwt.decode uses the public key for RS256
    token_payload = {"sub": "user-123", "aud": "test-client", "iss": "https://auth.test.com"}
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")

    fake_user = {"id": 1, "oidc_sub": "user-123", "name": "Test"}

    mock_token = MagicMock()
    mock_token.credentials = token

    with patch("lifelog.auth.settings") as mock_settings:
        mock_settings.oidc_client_secret = secret
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"

        with patch("lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = fake_user
            result = await validate_oidc_token(token=mock_token)
            assert result == fake_user


@pytest.mark.asyncio
async def test_validate_oidc_token_invalid():
    """Invalid token raises 401."""
    from lifelog.auth import validate_oidc_token

    mock_token = MagicMock()
    mock_token.credentials = "not-a-valid-jwt"

    with patch("lifelog.auth.settings") as mock_settings:
        mock_settings.oidc_client_secret = "secret"
        mock_settings.oidc_client_id = "client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"

        with pytest.raises(HTTPException) as exc_info:
            await validate_oidc_token(token=mock_token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_oidc_token_user_not_found():
    """Valid token but user not in DB raises 401."""
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
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    token_payload = {"sub": "unknown-user", "aud": "test-client", "iss": "https://auth.test.com"}
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")

    mock_token = MagicMock()
    mock_token.credentials = token

    with patch("lifelog.auth.settings") as mock_settings:
        mock_settings.oidc_client_secret = public_pem.decode()
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"

        with patch("lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await validate_oidc_token(token=mock_token)
    assert exc_info.value.status_code == 401
