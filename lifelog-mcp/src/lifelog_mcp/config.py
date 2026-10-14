from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Lifelog MCP server settings — all from environment variables."""

    lifelog_api_base_url: str = "http://server:8443"
    """Base URL of the main LifeLog FastAPI server."""

    lifelog_oidc_issuer: str = "https://auth.example.com"
    """OIDC provider issuer URL used for JWKS token validation."""

    lifelog_mcp_port: int = 9001
    """Port the MCP server listens on."""

    lifelog_mcp_host: str = "0.0.0.0"
    """Host the MCP server binds to."""

    model_config = {"env_file": ".env", "env_prefix": "LIFELOG_"}


settings = Settings()
