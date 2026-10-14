# LifeLog MCP Server

Exposes the LifeLog voice journal as [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tools, enabling AI agents in LibreChat to answer questions about your recordings, transcripts, speakers, action items, and decisions.

## Prerequisites

> **Hard requirements.** The MCP server cannot be deployed without these.

- **Authentik 2026.8.0+** — On-Behalf-Of (OBO) token exchange is not available in older versions.
- **LibreChat `MCP_SERVERS.CONFIGURE_OBO` role** — Users need this role to configure OBO in the LibreChat Agent Builder. Without it, OBO cannot be set up.
- **Main LifeLog server running** — The MCP server calls the existing FastAPI orchestrator; it is not standalone.

## Authentik Setup

LibreChat's OBO section automatically exchanges the authenticated user's OpenID token for a delegated token and forwards it as a `Authorization: Bearer <token>` header on every MCP request. The MCP server validates the delegated token against Authentik's JWKS endpoint.

### Step 1 — Create an OAuth2 Provider for the MCP Server

1. In Authentik Admin, navigate to **Applications → Providers**.
2. Click **Create**.
3. Choose **OAuth2 Provider** (not OpenID Connect Provider — OBO requires OAuth2 token exchange).
4. Name it `lifelog-mcp`.
5. Under **Grant Types**, select only:
   - `token-exchange` (required for OBO)
6. Under **Token Exchange Policy**, select **Always allow** (or scope to a policy group as needed).
7. Scroll to **Machine-to-Machine authentication settings**. Under **Federated OAuth2/OpenID Providers**, add the LibreChat OAuth2/OIDC provider. This allows Authentik to verify LibreChat's user tokens as subject tokens in the exchange.
8. Save the provider. Note its **Client ID** and **Client Secret**.

### Step 2 — Add the `tools.read` Scope

1. Open the `lifelog-mcp` provider.
2. Navigate to **Scopes**.
3. Click **Create**.
4. Name: `tools.read`, Scope description: `Read-only access to LifeLog MCP tools`.
5. Save.

### Step 3 — Create the Application

1. Navigate to **Applications → Applications**.
2. Click **Create**.
3. Name: `LifeLog MCP`.
4. Bind it to the `lifelog-mcp` provider.
5. Under **Launch URL**, optionally set `http://localhost:5173` (not required for MCP).
6. Save.

### Step 4 — Note the Token Exchange Endpoint

The token exchange endpoint is:
```
https://<your-authentik-domain>/application/o/token-exchange/
```

LibreChat's `librechat.yaml` `obo` section will point here automatically. The `client_id` from Step 1 and the `tools.read` scope name from Step 2 are used in the LibreChat config below.

---

## LibreChat Configuration

Add the following to your `librechat.yaml`:

```yaml
mcpServers:
  lifelog:
    type: streamable-http
    url: http://lifelog-mcp:9001/mcp
    obo:
      clientID: "<lifelog-mcp-provider-client-id>"
      scopes: 'tools.read'
    serverInstructions: >
      The LifeLog MCP server provides access to your voice recordings,
      transcripts, action items, decisions, and speaker information.
      Ask me about what you discussed, decided, or planned.
```

Restart LibreChat after updating `librechat.yaml`.

---

## Testing

### 1. Verify OBO Token Exchange with Authentik

```bash
# Exchange a LibreChat user token for an MCP delegated token
curl -X POST https://<auth-prefix>.your-authentik-domain/application/o/token-exchange/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=<librechat-user-id-token>" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "client_id=<lifelog-mcp-client-id>" \
  -d "client_secret=<lifelog-mcp-client-secret>" \
  -d "scope=tools.read"
```

Expected: JSON with `access_token` (the delegated token for the MCP server).

### 2. List MCP Tools

```bash
curl -X POST http://localhost:9001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <delegated-token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Expected: JSON-RPC response with `tools` array containing all 6 tools:
`search_recordings`, `get_recordings_by_date`, `get_recording_detail`,
`get_todos`, `get_decisions`, `get_speakers`.

### 3. Call a Tool

```bash
curl -X POST http://localhost:9001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <delegated-token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "search_recordings",
      "arguments": {"query": "alex"}
    }
  }'
```

### 4. Verify Auth Rejection

```bash
# No Authorization header — should return HTTP 401
curl -X POST http://localhost:9001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LIFELOG_API_BASE_URL` | `http://server:8443` | Base URL of the main LifeLog FastAPI server |
| `LIFELOG_OIDC_ISSUER` | *(empty)* | OIDC provider issuer URL (e.g. `https://auth.example.com`) |
| `LIFELOG_MCP_PORT` | `9001` | Port the MCP server listens on |
| `LIFELOG_MCP_HOST` | `0.0.0.0` | Host the MCP server binds to |

---

## Tools

| Tool | Description |
|---|---|
| `search_recordings` | Full-text search across transcripts, summaries, todos, decisions |
| `get_recordings_by_date` | List all recordings for a given date (YYYY-MM-DD) |
| `get_recording_detail` | Full details of a specific recording (transcript, speakers, todos, decisions) |
| `get_todos` | Action items from recordings, optionally filtered by date or status |
| `get_decisions` | Decisions captured from recordings, optionally filtered by date |
| `get_speakers` | All enrolled speakers with voiceprint and recording counts |

## Docker

```yaml
lifelog-mcp:
  build: ./lifelog-mcp
  ports:
    - "9001:9001"
  environment:
    LIFELOG_API_BASE_URL: http://server:8443
    LIFELOG_OIDC_ISSUER: ${OIDC_ISSUER}
  depends_on:
    - server
```
