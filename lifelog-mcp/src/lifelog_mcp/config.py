from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Lifelog MCP server settings — all from environment variables."""

    lifelog_api_base_url: str = Field(
        default="http://server:8443",
        validation_alias="LIFELOG_API_BASE_URL",
    )
    """Base URL of the main LifeLog FastAPI server (internal Docker hostname)."""

    lifelog_oidc_issuer: str = Field(
        default="https://auth.example.com",
        validation_alias="LIFELOG_OIDC_ISSUER",
    )
    """OIDC provider issuer URL used for JWKS token validation."""

    lifelog_mcp_port: int = Field(
        default=9001,
        validation_alias="LIFELOG_MCP_PORT",
    )
    """Port the MCP server listens on."""

    lifelog_mcp_host: str = Field(
        default="0.0.0.0",
        validation_alias="LIFELOG_MCP_HOST",
    )
    """Host the MCP server binds to."""

    lifelog_mcp_url: str = Field(
        default="http://localhost:9002/mcp",
        validation_alias="LIFELOG_MCP_URL",
    )
    """Public URL clients use to reach this MCP server.

    This is used as the ``resource_server_url`` in AuthSettings, which
    determines the OAuth 2.0 protected resource metadata endpoint
    (RFC 9728 ``/.well-known/oauth-protected-resource/<path>``) and the
    ``aud`` claim that issued tokens must contain. Must be the URL that
    *clients* (LibreChat) actually use — e.g. ``http://host:9002/mcp``
    when the client runs outside Docker, or ``http://lifelog-mcp:9001/mcp``
    when the client runs inside the same Docker network.
    """

    lifelog_mcp_log_level: str = Field(
        default="DEBUG",
        validation_alias="LIFELOG_MCP_LOG_LEVEL",
    )
    """Python log level for the ``lifelog_mcp`` and ``uvicorn.access`` loggers.

    DEBUG shows every HTTP request, token exchange detail, and tool call.
    INFO (production default) shows only startup, tool calls, and auth results.
    """

    lifelog_client_secret: str = Field(
        default="",
        validation_alias="LIFELOG_CLIENT_SECRET",
    )
    """OAuth2 client secret for the lifelog-mcp provider in Authentik.

    Used for HS256 token validation — the provider uses symmetric signing
    (client_secret as the HMAC key) rather than asymmetric RS256.
    """


settings = Settings()
