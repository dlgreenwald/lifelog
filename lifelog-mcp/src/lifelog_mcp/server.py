"""LifeLog MCP server — exposes LifeLog FastAPI routes as MCP tools.

Uses the official mcp Python SDK with streamable-http transport and
built-in Bearer token verification (JWKS-based OIDC).
"""

from __future__ import annotations

import logging
import sys

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.middleware.base import BaseHTTPMiddleware

from lifelog_mcp import tools as lifelog_tools
from lifelog_mcp.auth import LoggingTokenVerifierWrapper
from lifelog_mcp.config import settings


class AuthLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request's Authorization header for operator diagnostics.

    This runs BEFORE the MCP SDK's AuthenticationMiddleware so we can see
    whether LibreChat is actually sending a Bearer token on each request.
    """

    async def dispatch(self, request, call_next):
        auth_header = request.headers.get("authorization")
        if auth_header:
            prefix = auth_header[:20] + "..." if len(auth_header) > 20 else auth_header
            logger.info("http_request auth_present=True prefix=%s", prefix)
        else:
            logger.warning("http_request auth_present=False")

        return await call_next(request)

logger = logging.getLogger("lifelog_mcp")


# ----------------------------------------------------------------------------
# Token Verifier — validates Bearer JWT against the OIDC JWKS endpoint
# ----------------------------------------------------------------------------


class JWKSTokenVerifier(TokenVerifier):
    """TokenVerifier that validates JWTs against an OIDC JWKS endpoint."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a raw Bearer JWT and return an AccessToken with its claims.

        All auth events (token received, accepted, rejected) are logged by
        LoggingTokenVerifierWrapper — do not log here to avoid duplication.
        """
        try:
            payload = await _validate_token(token)
            scopes = payload.get("scope", "").split()
            return AccessToken(
                token=token,
                client_id=payload.get("client_id", "lifelog-mcp"),
                scopes=scopes,
                subject=payload.get("sub"),
                claims=payload,
            )
        except AuthError:
            # AuthError is logged by LoggingTokenVerifierWrapper
            return None
        except Exception:  # noqa: BLE001
            # Unexpected errors also logged by wrapper
            return None


# ----------------------------------------------------------------------------
# Auth (mirrors server/src/lifelog/auth.py pattern)
# ----------------------------------------------------------------------------


class AuthError(Exception):
    """Raised when token validation fails."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


_jwk_clients: dict[str, object] = {}  # keyed by issuer


def _get_jwk_client(issuer: str):
    """Return a cached JWKS client for the given issuer."""
    import jwt as pyjwt

    if issuer not in _jwk_clients:
        jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
        _jwk_clients[issuer] = pyjwt.PyJWKClient(jwks_url)
    return _jwk_clients[issuer]


async def _validate_token(token: str) -> dict:
    """Validate a raw Bearer token string and return the decoded payload."""
    import jwt as pyjwt

    if not token:
        raise AuthError("Empty token")
    if not settings.lifelog_oidc_issuer:
        logger.error("LIFELOG_OIDC_ISSUER not configured")
        raise AuthError("LIFELOG_OIDC_ISSUER not configured")

    logger.debug("validating_token issuer=%s", settings.lifelog_oidc_issuer)

    try:
        client = _get_jwk_client(settings.lifelog_oidc_issuer)
        signing_key = client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=None,
            issuer=settings.lifelog_oidc_issuer,
        )
        return dict(payload)
    except pyjwt.ExpiredSignatureError:
        raise AuthError("Token has expired")
    except pyjwt.InvalidAudienceError:
        raise AuthError("Invalid token audience")
    except pyjwt.InvalidIssuerError:
        raise AuthError("Invalid token issuer")
    except Exception as exc:  # noqa: BLE001  # PyJWKClient raises varied network/decode errors
        logger.warning("jwt_decode_error error=%s issuer=%s", exc, settings.lifelog_oidc_issuer)
        raise AuthError(f"Token validation failed: {exc}")


# ----------------------------------------------------------------------------
# Tool handlers
# ----------------------------------------------------------------------------


def _get_bearer_token() -> str:
    """Extract the raw Bearer token from the current auth context."""
    access_token = get_access_token()
    if not access_token:
        raise AuthError("No authenticated user in context")
    return access_token.token


async def _search_recordings(
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    speaker: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> str:
    token = _get_bearer_token()
    return await lifelog_tools.search.call(
        token=token,
        query=query,
        start_date=start_date,
        end_date=end_date,
        speaker=speaker,
        kind=kind,
        limit=limit,
    )


async def _get_recordings_by_date(date: str) -> str:
    token = _get_bearer_token()
    result = await lifelog_tools.recordings.call(
        token=token, tool_name="get_recordings_by_date", date=date
    )
    return result.text


async def _get_recording_detail(recording_id: int) -> str:
    token = _get_bearer_token()
    result = await lifelog_tools.recordings.call(
        token=token, tool_name="get_recording_detail", recording_id=recording_id
    )
    return result.text


async def _get_todos(date: str | None = None, status: str | None = None, limit: int = 50) -> str:
    token = _get_bearer_token()
    result = await lifelog_tools.todos.call(token=token, date=date, status=status, limit=limit)
    return result.text


async def _get_decisions(date: str | None = None, limit: int = 50) -> str:
    token = _get_bearer_token()
    result = await lifelog_tools.decisions.call(token=token, date=date, limit=limit)
    return result.text


async def _get_speakers(recording_id: int | None = None) -> str:
    token = _get_bearer_token()
    result = await lifelog_tools.speakers.call(token=token, recording_id=recording_id)
    return result.text


# ----------------------------------------------------------------------------
# Server bootstrap
# ----------------------------------------------------------------------------


def create_server() -> MCPServer:
    """Build and configure the LifeLog MCP server."""
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(settings.lifelog_oidc_issuer),
        resource_server_url=AnyHttpUrl(settings.lifelog_api_base_url),
        required_scopes=["lifelog:tools.read"],
        validate_token_resource=False,  # We validate audience in our TokenVerifier
    )

    server = MCPServer(
        name="lifelog-mcp",
        version="1.0.0",
        description="Read-only access to your LifeLog voice journal",
        instructions="Use these tools to search recordings, browse calendar days, view recording details, get action items, decisions, and speaker information.",
        auth=auth_settings,
        token_verifier=LoggingTokenVerifierWrapper(JWKSTokenVerifier()),
    )

    # Register tools with the server
    @server.tool(name="search_recordings")
    async def search_recordings(
        query: str,
        start_date: str | None = None,
        end_date: str | None = None,
        speaker: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> str:
        """Search across all voice recording transcripts, summaries, action items, and decisions.

        Use this as the primary tool for answering questions like 'what did I discuss with Alex last week'
        or 'show me all meetings about budget'. Returns matching recordings with highlighted snippets.
        """
        logger.info("tool_called tool=search_recordings query=%r limit=%s", query, limit)
        result = await _search_recordings(
            query=query,
            start_date=start_date,
            end_date=end_date,
            speaker=speaker,
            kind=kind,
            limit=limit,
        )
        logger.info("tool_completed tool=search_recordings result_length=%s", len(result))
        return result

    @server.tool(name="get_recordings_by_date")
    async def get_recordings_by_date(date: str) -> str:
        """Get all voice recordings for a specific calendar date (YYYY-MM-DD).

        Use this to browse recordings from a known date.
        """
        logger.info("tool_called tool=get_recordings_by_date date=%r", date)
        result = await _get_recordings_by_date(date=date)
        logger.info("tool_completed tool=get_recordings_by_date result_length=%s", len(result))
        return result

    @server.tool(name="get_recording_detail")
    async def get_recording_detail(recording_id: int) -> str:
        """Get the full details of a specific recording including transcript segments,
        speaker labels, summary, action items, decisions, and metadata.
        """
        logger.info("tool_called tool=get_recording_detail recording_id=%s", recording_id)
        result = await _get_recording_detail(recording_id=recording_id)
        logger.info("tool_completed tool=get_recording_detail result_length=%s", len(result))
        return result

    @server.tool(name="get_todos")
    async def get_todos(
        date: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        """Get action items (todos) from voice recordings, optionally filtered by date or status.

        Use this to answer questions like 'what action items did I capture yesterday'
        or 'show me all pending todos'.
        """
        logger.info("tool_called tool=get_todos date=%r status=%r limit=%s", date, status, limit)
        result = await _get_todos(date=date, status=status, limit=limit)
        logger.info("tool_completed tool=get_todos result_length=%s", len(result))
        return result

    @server.tool(name="get_decisions")
    async def get_decisions(date: str | None = None, limit: int = 50) -> str:
        """Get decisions captured from voice recordings, optionally filtered by date.

        Use this to answer questions like 'what decisions did I make last week'.
        """
        logger.info("tool_called tool=get_decisions date=%r limit=%s", date, limit)
        result = await _get_decisions(date=date, limit=limit)
        logger.info("tool_completed tool=get_decisions result_length=%s", len(result))
        return result

    @server.tool(name="get_speakers")
    async def get_speakers(recording_id: int | None = None) -> str:
        """Get all enrolled speakers with voiceprint counts and recording counts.

        Use this to see who has been identified in your recordings.
        """
        logger.info("tool_called tool=get_speakers recording_id=%s", recording_id)
        result = await _get_speakers(recording_id=recording_id)
        logger.info("tool_completed tool=get_speakers result_length=%s", len(result))
        return result

    return server


def run():
    """Run the MCP server with streamable-http transport."""
    import uvicorn

    server = create_server()

    # Configure our logger AFTER create_server() so the MCP SDK's
    # configure_logging() (called inside MCPServer.__init__) runs first.
    # This way we know the root logger already has a handler and we
    # set propagate=False on our logger to prevent double-output.
    _configure_logging()

    logger.info(
        "mcp_server_starting host=%s port=%s api_base=%s oidc_issuer=%s "
        "required_scopes=['lifelog:tools.read']",
        settings.lifelog_mcp_host,
        settings.lifelog_mcp_port,
        settings.lifelog_api_base_url,
        settings.lifelog_oidc_issuer,
    )

    # Build the raw Starlette app via the MCP SDK, then wrap it with our
    # auth-logging middleware. We MUST do this here (not via MCPServer constructor
    # middleware=) because the SDK's streamable_http_app() creates its own
    # middleware list and does not include user-supplied middleware.
    # _lowlevel_server is the mcp.server.lowlevel.Server instance created in
    # MCPServer.__init__; it has streamable_http_app() which MCPServer.run() calls.
    raw_app = server._lowlevel_server.streamable_http_app(
        streamable_http_path="/mcp",
        host=settings.lifelog_mcp_host,
    )
    wrapped_app = AuthLoggingMiddleware(raw_app)

    # Run uvicorn directly so our wrapped app is used instead of the SDK
    # re-creating its own app internally (which would bypass our middleware).
    config = uvicorn.Config(
        wrapped_app,
        host=settings.lifelog_mcp_host,
        port=settings.lifelog_mcp_port,
        log_level="info",
    )
    uvicorn.Server(config).run()


def _configure_logging() -> None:
    """Configure Python logging so lifelog_mcp module logs reach stdout.

    We only touch the 'lifelog_mcp' logger — add a stdout handler to it.
    We do NOT call basicConfig() or configure the root logger, because:
    1. MCPServer.__init__() already called configure_logging() which may
       have set up the root logger; we don't want to override it.
    2. The uvicorn child loggers (uvicorn.error, uvicorn.access) have
       propagate=False and manage their own handlers — leave them alone.
    """
    import logging.config

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    our_logger = logging.getLogger("lifelog_mcp")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    our_logger.addHandler(handler)
    our_logger.setLevel(logging.INFO)
    our_logger.propagate = False


if __name__ == "__main__":
    run()
