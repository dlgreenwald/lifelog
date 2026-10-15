"""Tests for lifelog_mcp auth module."""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest

from lifelog_mcp.auth import AuthError, validate_bearer_token


class TestValidateBearerToken:
    """Tests for validate_bearer_token()."""

    @pytest.fixture
    def mock_settings(self):
        with patch("lifelog_mcp.auth.settings") as mock:
            mock.lifelog_oidc_issuer = "https://auth.example.com"
            yield mock

    async def test_empty_token_raises(self, mock_settings):
        with pytest.raises(AuthError) as exc_info:
            await validate_bearer_token("")
        assert "Empty token" in exc_info.value.message

    async def test_no_issuer_configured_raises(self):
        with patch("lifelog_mcp.auth.settings") as mock:
            mock.lifelog_oidc_issuer = ""
            with pytest.raises(AuthError) as exc_info:
                await validate_bearer_token("sometoken")
        assert "not configured" in exc_info.value.message

    async def test_expired_token_raises(self, mock_settings):
        """Expired tokens should be rejected."""
        with patch("lifelog_mcp.auth._get_jwk_client") as mock_get_client:
            mock_jwk_client = MagicMock()
            mock_jwk_client.get_signing_key_from_jwt.return_value = MagicMock(key="secret")
            mock_get_client.return_value = mock_jwk_client

            with patch("lifelog_mcp.auth.pyjwt.decode") as mock_decode:
                mock_decode.side_effect = pyjwt.ExpiredSignatureError("Signature has expired")
                with pytest.raises(AuthError) as exc_info:
                    await validate_bearer_token("some_expired_token")
        assert "expired" in exc_info.value.message.lower()

    async def test_invalid_issuer_raises(self, mock_settings):
        """Token for wrong issuer should be rejected."""
        with patch("lifelog_mcp.auth._get_jwk_client") as mock_get_client:
            mock_jwk_client = MagicMock()
            mock_jwk_client.get_signing_key_from_jwt.return_value = MagicMock(key="secret")
            mock_get_client.return_value = mock_jwk_client

            with patch("lifelog_mcp.auth.pyjwt.decode") as mock_decode:
                mock_decode.side_effect = pyjwt.InvalidIssuerError("Invalid issuer")
                with pytest.raises(AuthError) as exc_info:
                    await validate_bearer_token("token_with_wrong_issuer")
        assert "issuer" in exc_info.value.message.lower()

    async def test_validation_error_raises_generic_auth_error(self, mock_settings):
        """Unexpected exceptions during validation should raise AuthError with message."""
        with patch("lifelog_mcp.auth._get_jwk_client") as mock_get_client:
            mock_jwk_client = MagicMock()
            mock_jwk_client.get_signing_key_from_jwt.side_effect = ValueError("Unexpected error")
            mock_get_client.return_value = mock_jwk_client
            with pytest.raises(AuthError) as exc_info:
                await validate_bearer_token("sometoken")
        assert "validation failed" in exc_info.value.message.lower()
