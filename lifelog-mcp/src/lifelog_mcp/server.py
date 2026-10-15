"""LifeLog MCP server — exposes LifeLog FastAPI routes as MCP tools.

Uses the official mcp Python SDK with streamable-http transport and
built-in Bearer token verification (JWKS-based OIDC).
"""

from __future__ import annotations

import logging

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.types import TextContent
from pydantic import AnyHttpUrl

from lifelog_mcp import tools as lifelog_tools
from lifelog_mcp.config import settings

logger = logging.getLogger("lifelog_mcp")


# Monkey-patch BearerAuthBackend.authenticate to log all rejection paths.
# Without this, missing/invalid auth headers produce a bare 401 with no trace.
_orig_authenticate = BearerAuthBackend.authenticate

async def _authenticate_with_logging(self, conn):
    all_headers = {k: v for k, v in conn.headers.items()}
    auth_header = next(
        (conn.headers.get(key) for key in conn.headers if key.lower() == "authorization"),
        None,
    )
    if not auth_header:
        logger.debug("auth_missing_header headers=%s", all_headers)
        return None
    if not auth_header.lower().startswith("bearer "):
        logger.debug("auth_invalid_scheme header=%s", auth_header[:50])
        return None
    token = auth_header[7:]
    if not token:
        logger.debug("auth_empty_token")
        return None
    return await _orig_authenticate(self, conn)

BearerAuthBackend.authenticate = _authenticate_with_logging


# Monkey-patch RequireAuthMiddleware._send_auth_error to omit resource_metadata.
# Without this, the WWW-Authenticate header includes resource_metadata pointing to
# the MCP server's /.well-known/oauth-protected-resource/mcp endpoint. LibreChat
# then tries to use the MCP server as the OAuth authorization server instead of
# the explicit authorization_url configured in the LibreChat yaml. Removing
# resource_metadata forces LibreChat to use its explicit oauth config.
import mcp.server.auth.middleware.bearer_auth as bearer_auth_module

_orig_send_auth_error = bearer_auth_module.RequireAuthMiddleware._send_auth_error

async def _send_auth_error_no_resource_metadata(self, send, status_code, error, description):
    # Build WWW-Authenticate header WITHOUT resource_metadata
    www_authenticate = f'Bearer error="{error}", error_description="{description}"'
    body = {"error": error, "error_description": description}
    body_bytes = __import__("json").dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body_bytes)).encode()),
            (b"www-authenticate", www_authenticate.encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body_bytes})

bearer_auth_module.RequireAuthMiddleware._send_auth_error = _send_auth_error_no_resource_metadata


# ----------------------------------------------------------------------------
# Token Verifier — validates Bearer JWT against the OIDC JWKS endpoint
# ----------------------------------------------------------------------------


class JWKSTokenVerifier(TokenVerifier):
    """TokenVerifier that validates JWTs against an OIDC JWKS endpoint."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a raw Bearer JWT and return an AccessToken with its claims."""
        token_prefix = token[:20] + "..." if token and len(token) > 20 else "(empty)"
        logger.info("token_received prefix=%s", token_prefix)

        if not token:
            logger.debug("auth_no_token")
            return None

        try:
            payload = await _validate_token(token)
            scopes = payload.get("scope", "").split()
            logger.info(
                "token_validated sub=%s scopes=%s",
                payload.get("sub"),
                scopes,
            )
            return AccessToken(
                token=token,
                client_id=payload.get("client_id", "lifelog-mcp"),
                scopes=scopes,
                subject=payload.get("sub"),
                claims=payload,
            )
        except AuthError as exc:
            logger.warning("token_rejected reason=%s", exc.message)
            return None
        except Exception:
            logger.exception("token_error")
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
        # Authentik uses /jwks/ not /.well-known/jwks.json
        jwks_url = f"{issuer.rstrip('/')}/jwks/"
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
            options={"verify_aud": False},
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


async def _get_recordings_by_date(date: str, category: str | None = None) -> str:
    token = _get_bearer_token()
    kwargs = {"tool_name": "get_recordings_by_date", "date": date}
    if category:
        kwargs["category"] = category
    result = await lifelog_tools.recordings.call(token=token, **kwargs)
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
        resource_server_url=AnyHttpUrl(settings.lifelog_mcp_url),
        required_scopes=["lifelog:tools.read"],
        validate_token_resource=False,  # We validate audience in our TokenVerifier
    )

    server = MCPServer(
        name="lifelog-mcp",
        version="1.0.0",
        description="Read-only access to your LifeLog voice journal",
        instructions="""You are connected to a voice journal MCP server. Read this carefully — it tells you how to use the tools correctly.

== THE MOST IMPORTANT RULE ==
The search tool does NOT understand abstract concepts like "work", "meetings", "my week", "what I did". It matches EXACT WORDS spoken in recordings.
- BAD query: "work activities" → returns nothing useful
- GOOD query: "project deadline" → finds recordings where you said "project" and "deadline"
- BAD query: "what did I do last week" → returns nothing
- GOOD approach: use get_recordings_by_date to pull recordings for that week, then read the transcripts

== CONTEXT-FIRST FOR BROAD QUESTIONS ==
When a user asks about a time period or broad topic ("what did I do last week", "summarize my meetings"):
1. Use get_recordings_by_date with the date range (e.g. start_date="2026-10-07", end_date="2026-10-13")
2. This returns ALL recordings for that range (ids, timestamps, speakers, duration)
3. Use get_recording_detail on interesting recordings to read the full transcript
4. Reason over the actual transcript content to answer the question
DO NOT try to search_recordings with an abstract query — it won't work.

== CATEGORY (work/personal) ==
The search index does NOT contain category information.
- To filter by category: use get_recordings_by_date with category="work" or category="personal"
- Then read specific recordings with get_recording_detail

== VALID SEARCH PARAMETERS ==
search_recordings parameters:
- query: the EXACT words you think were spoken (not concepts)
- start_date / end_date: YYYY-MM-DD format, e.g. "2026-10-07"
- kind: "transcript" | "summary" | "decision" | "todo" (never use "meeting")
- speaker: exact speaker name as enrolled
- limit: max results (default 20)

get_recordings_by_date parameters:
- date: YYYY-MM-DD, e.g. "2026-10-13"
- category: "work" | "personal" (optional)

get_recording_detail parameters:
- recording_id: the numeric ID from get_recordings_by_date results

== FOR ACTION ITEMS ==
Use get_todos — todos are indexed separately, not found by search_recordings kind="todo"

== FOR DECISIONS ==
Use get_decisions""",
        auth=auth_settings,
        token_verifier=JWKSTokenVerifier(),
        log_level=settings.lifelog_mcp_log_level.upper(),
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
    ) -> TextContent:
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
        logger.info("tool_completed tool=search_recordings result_length=%s", len(result.text))
        return result

    @server.tool(name="get_recordings_by_date")
    async def get_recordings_by_date(date: str, category: str | None = None) -> TextContent:
        """Get all voice recordings for a specific calendar date (YYYY-MM-DD).

        Use this to browse recordings from a known date. Optionally filter by category.
        """
        logger.info("tool_called tool=get_recordings_by_date date=%r category=%r", date, category)
        result = await _get_recordings_by_date(date=date, category=category)
        logger.info("tool_completed tool=get_recordings_by_date result_length=%s", len(result.text))
        return result

    @server.tool(name="get_recording_detail")
    async def get_recording_detail(recording_id: int) -> TextContent:
        """Get the full details of a specific recording including transcript segments,
        speaker labels, summary, action items, decisions, and metadata.
        """
        logger.info("tool_called tool=get_recording_detail recording_id=%s", recording_id)
        result = await _get_recording_detail(recording_id=recording_id)
        logger.info("tool_completed tool=get_recording_detail result_length=%s", len(result.text))
        return result

    @server.tool(name="get_todos")
    async def get_todos(
        date: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> TextContent:
        """Get action items (todos) from voice recordings, optionally filtered by date or status.

        Use this to answer questions like 'what action items did I capture yesterday'
        or 'show me all pending todos'.
        """
        logger.info("tool_called tool=get_todos date=%r status=%r limit=%s", date, status, limit)
        result = await _get_todos(date=date, status=status, limit=limit)
        logger.info("tool_completed tool=get_todos result_length=%s", len(result.text))
        return result

    @server.tool(name="get_decisions")
    async def get_decisions(date: str | None = None, limit: int = 50) -> TextContent:
        """Get decisions captured from voice recordings, optionally filtered by date.

        Use this to answer questions like 'what decisions did I make last week'.
        """
        logger.info("tool_called tool=get_decisions date=%r limit=%s", date, limit)
        result = await _get_decisions(date=date, limit=limit)
        logger.info("tool_completed tool=get_decisions result_length=%s", len(result.text))
        return result

    @server.tool(name="get_speakers")
    async def get_speakers(recording_id: int | None = None) -> TextContent:
        """Get all enrolled speakers with voiceprint counts and recording counts.

        Use this to see who has been identified in your recordings.
        """
        logger.info("tool_called tool=get_speakers recording_id=%s", recording_id)
        result = await _get_speakers(recording_id=recording_id)
        logger.info("tool_completed tool=get_speakers result_length=%s", len(result.text))
        return result

    return server


def run():
    """Run the MCP server with streamable-http transport."""
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    server = create_server()

    logger.info(
        "mcp_server_starting host=%s port=%s mcp_url=%s api_base=%s oidc_issuer=%s "
        "required_scopes=['lifelog:tools.read']",
        settings.lifelog_mcp_host,
        settings.lifelog_mcp_port,
        settings.lifelog_mcp_url,
        settings.lifelog_api_base_url,
        settings.lifelog_oidc_issuer,
    )

    server.run(
        transport="streamable-http",
        host=settings.lifelog_mcp_host,
        port=settings.lifelog_mcp_port,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run()
