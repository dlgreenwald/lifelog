from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Lifelog MCP server settings — all from environment variables."""

    lifelog_api_base_url: str = "http://server:8443"
    """Base URL of the main LifeLog FastAPI server (internal Docker hostname)."""

    lifelog_oidc_issuer: str = "https://auth.example.com"
    """OIDC provider issuer URL used for JWKS token validation."""

    lifelog_mcp_port: int = 9001
    """Port the MCP server listens on."""

    lifelog_mcp_host: str = "0.0.0.0"
    """Host the MCP server binds to."""

    lifelog_mcp_url: str = "http://localhost:9002/mcp"
    """Public URL clients use to reach this MCP server.

    This is used as the ``resource_server_url`` in AuthSettings, which
    determines the OAuth 2.0 protected resource metadata endpoint
    (RFC 9728 ``/.well-known/oauth-protected-resource/<path>``) and the
    ``aud`` claim that issued tokens must contain. Must be the URL that
    *clients* (LibreChat) actually use — e.g. ``http://host:9002/mcp``
    when the client runs outside Docker, or ``http://lifelog-mcp:9001/mcp``
    when the client runs inside the same Docker network.
    """

    lifelog_mcp_log_level: str = "DEBUG"
    """Python log level for the lifelog_mcp and uvicorn loggers.

    DEBUG shows all HTTP requests, token exchange details, tool calls, and
    full auth events. INFO (default for production) shows only startup,
    tool calls, and auth results.
    """

    model_config = {"env_file": ".env", "env_prefix": "LIFELOG_"}


settings = Settings()
