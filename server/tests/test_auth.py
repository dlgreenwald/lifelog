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

    with pytest.raises(ValueError, match="HTTPS"):
        _get_jwk_client("http://evil.example.com/issuer")


@pytest.mark.asyncio
async def test_rejects_http_jwks_uri():
    """OIDC discovery rejects non-HTTPS JWKS URIs in discovery response."""
    from lifelog.auth import _get_jwk_client

    fake_discovery = {"jwks_uri": "http://evil.example.com/jwks"}

    with patch("lifelog.auth.httpx.Client") as MockClient:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_discovery
        mock_resp.raise_for_status = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(
            return_value=MockClient.return_value
        )
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        MockClient.return_value.get.return_value = mock_resp
        with pytest.raises(ValueError, match="HTTPS"):
            _get_jwk_client("https://auth.test.com")


# ── _token_payload ─────────────────────────────────────────────────────────────


class TestTokenPayload:
    """Test _token_payload — pure decode without signature verification."""

    def test_valid_jwt_returns_payload(self):
        import jwt as pyjwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        from lifelog.auth import _token_payload

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        payload = {"sub": "user-123", "iss": "https://auth.test.com"}
        token = pyjwt.encode(payload, private_pem, algorithm="RS256")

        result = _token_payload(token)
        assert result["sub"] == "user-123"
        assert result["iss"] == "https://auth.test.com"

    def test_malformed_token_returns_empty_dict(self):
        from lifelog.auth import _token_payload

        assert _token_payload("not.a.jwt") == {}
        assert _token_payload("") == {}

    def test_expired_token_returns_payload_not_error(self):
        """Even an expired JWT decodes successfully — _token_payload does not verify expiry."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        from lifelog.auth import _token_payload

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        # JWT with exp in the past — signature still verifies, expiry not checked here
        import time

        payload = {"sub": "user", "exp": int(time.time()) - 3600}
        token = pyjwt.encode(payload, private_pem, algorithm="RS256")
        result = _token_payload(token)
        assert result["sub"] == "user"


# ── validate_bearer_token — simulator path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_bearer_token_simulator_user_exists():
    """Simulator token with existing user returns that user."""
    from lifelog.auth import validate_bearer_token

    fake_user = {"id": 5, "oidc_sub": "simulator:fake-client", "name": "Sim"}

    with (
        patch("lifelog.auth.settings") as mock_settings,
        patch(
            "lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock
        ) as mock_get,
    ):
        mock_settings.oidc_simulator_client_id = "fake-client"
        mock_get.return_value = fake_user
        result = await validate_bearer_token("simulator:fake-client")
        assert result == fake_user
        mock_get.assert_awaited_once_with("simulator:fake-client")


@pytest.mark.asyncio
async def test_validate_bearer_token_simulator_creates_user():
    """Simulator token first use creates and returns new user."""
    from lifelog.auth import validate_bearer_token

    new_user = {
        "id": 99,
        "oidc_sub": "simulator:fake-client",
        "name": "Simulator (fake-client)",
    }

    with (
        patch(
            "lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock
        ) as mock_get,
        patch("lifelog.database.create_user", new_callable=AsyncMock) as mock_create,
        patch("lifelog.auth.settings") as mock_settings,
    ):
        mock_get.return_value = None
        mock_create.return_value = new_user
        mock_settings.oidc_simulator_client_id = "fake-client"

        result = await validate_bearer_token("simulator:fake-client")
        assert result == new_user
        mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_bearer_token_simulator_unknown_client_raises():
    """Simulator token with unknown client ID raises 401."""
    from lifelog.auth import validate_bearer_token

    with patch("lifelog.auth.settings") as mock_settings:
        mock_settings.oidc_simulator_client_id = "real-client"
        with pytest.raises(HTTPException) as exc_info:
            await validate_bearer_token("simulator:unknown-client")
        assert exc_info.value.status_code == 401


# ── validate_oidc_token — error handlers ──────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_oidc_token_expired_raises_401():
    """Expired token raises 401 with 'Token expired'."""
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
    import time

    token_payload = {
        "sub": "user-123",
        "aud": "test-client",
        "iss": "https://auth.test.com",
        "exp": int(time.time()) - 3600,  # expired
    }
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")
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
        mock_get.return_value = {"id": 1}

        with pytest.raises(HTTPException) as exc_info:
            await validate_oidc_token(token=mock_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token expired"


@pytest.mark.asyncio
async def test_validate_oidc_token_invalid_audience_raises_401():
    """Token with wrong audience raises 401."""
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
        "sub": "user-123",
        "aud": "wrong-client",
        "iss": "https://auth.test.com",
    }
    token = pyjwt.encode(token_payload, private_pem, algorithm="RS256")
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
        mock_get.return_value = {"id": 1}

        with pytest.raises(HTTPException) as exc_info:
            await validate_oidc_token(token=mock_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid audience"


@pytest.mark.asyncio
async def test_validate_oidc_token_invalid_issuer_raises_401():
    """Token with wrong issuer raises 401."""
    import jwt as pyjwt

    from lifelog.auth import validate_oidc_token

    mock_token = MagicMock()
    mock_token.credentials = "some.jwt.token"

    signing_key = MagicMock()
    signing_key.key = "mock-public-key"

    with (
        patch("lifelog.auth._get_jwk_client") as mock_get_jwk,
        patch("lifelog.auth.pyjwt.decode") as mock_decode,
        patch("lifelog.auth.settings") as mock_settings,
        patch(
            "lifelog.database.get_user_by_oidc_sub", new_callable=AsyncMock
        ) as mock_get,
    ):
        mock_get_jwk.return_value.get_signing_key_from_jwt.return_value = signing_key
        mock_decode.side_effect = pyjwt.InvalidIssuerError()
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_issuer_url = "https://auth.test.com"
        mock_get.return_value = {"id": 1}

        with pytest.raises(HTTPException) as exc_info:
            await validate_oidc_token(token=mock_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid issuer"
