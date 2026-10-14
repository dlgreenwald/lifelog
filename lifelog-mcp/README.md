# LifeLog MCP Server

Exposes the LifeLog voice journal as [Model Context Protocol (MCP)](https://modelcontextprotocol.io) tools, enabling AI agents in LibreChat to answer questions about your recordings, transcripts, speakers, action items, and decisions.

## Prerequisites

- **Authentik 2026.8.0+** — On-Behalf-Of (OBO) token exchange requires this version or newer.
- **LibreChat `MCP_SERVERS.CONFIGURE_OBO` role** — Users need this role to configure OBO in the LibreChat Agent Builder.
- **Main LifeLog server running** — The MCP server calls the existing FastAPI orchestrator; it is not standalone.
- **Shared OIDC issuer** — The MCP server and LifeLog dashboard must use the same OIDC provider (Authentik). This can be the same Authentik instance, or a federated pair of instances (see [Authentik Setup](#authentik-setup) below).

---

## Quick Setup: Shared Authentik Instance

Use this path when LibreChat, the LifeLog dashboard, and the MCP server all share the **same Authentik instance**. This is the simplest configuration and covers most self-hosted deployments.

### Step 1 — Create an OAuth2 Provider for the MCP Server

1. In Authentik Admin, navigate to **Applications → Providers**.
2. Click **Create** → choose **OAuth2 Provider** (not OpenID Connect — OBO requires OAuth2 token exchange).
3. Name it `lifelog-mcp`.
4. Under **Grant Types**, select only:
   - `token-exchange` (required for OBO)
5. Under **Token Exchange Policy**, select **Always allow** (or restrict to a policy group as needed).
6. Save. Note the **Client ID** and **Client Secret**.

### Step 2 — Create the `lifelog:tools.read` Scope Mapping

Scopes in Authentik are defined as **scope mappings** (a type of property mapping), then attached to the provider.

1. In Authentik Admin, navigate to **Customization** → **Property Mappings**.
2. Click **New Property Mapping** → select **OAuth2/OIDC scope mapping** → click **Next**.
3. Set **Name** to `lifelog:tools.read`.
4. Set **Scope expression** to:

   ```python
   # Returns the scope name so the issued token contains lifelog:tools.read.
   # The expression returns a dict of claims; return {} for a namespaced scope.
   return {}
   ```

5. Click **Finish**.
6. Open the `lifelog-mcp` OAuth2 Provider → navigate to its **Scopes** section.
7. Add the `lifelog:tools.read` scope mapping and save.

> **Note:** The scope must be named `lifelog:tools.read` (not a generic name like `tools.read`) to avoid scope collisions with other OAuth2 clients on the same Authentik instance. The MCP server enforces this scope via the MCP SDK's `RequireAuthMiddleware` — requests without `lifelog:tools.read` in the token's `scope` claim are rejected with HTTP 403.

### Step 3 — Create the Application

1. Navigate to **Applications → Applications** → **Create**.
2. Name: `LifeLog MCP`, slug: `lifelog-mcp`.
3. Bind it to the `lifelog-mcp` provider.
4. Save.

### Step 4 — LibreChat Configuration

Add the following to your `librechat.yaml`:

```yaml
mcpServers:
  lifelog:
    type: streamable-http
    url: http://lifelog-mcp:9001/mcp
    obo:
      clientID: "<lifelog-mcp-client-id>"
      clientSecret: "<lifelog-mcp-client-secret>"
      scopes: 'lifelog:tools.read'
    serverInstructions: >
      The LifeLog MCP server provides access to your voice recordings,
      transcripts, action items, decisions, and speaker information.
      Ask me about what you discussed, decided, or planned.
```

> **Note:** `clientSecret` is the **MCP server's OAuth2 client secret** (from Step 1), not the user's credentials. LibreChat authenticates as the MCP server during token exchange, so it needs the MCP server's `client_id` and `clientSecret`. This is required in the shared-instance setup because LibreChat connects directly to the same Authentik that authenticated the user.

Restart LibreChat after updating `librechat.yaml`.

---

## Advanced Setup: Federated Authentik Instances

Use this path when LibreChat and the MCP server use **different Authentik instances** (e.g., LibreChat is managed by your organization on `auth.company.com` while the MCP server/LifeLog run on a separate instance at `auth.internal.com`). Token exchange across instances requires federation configuration.

### Step 1 — Configure Federation on the MCP Server's Authentik

1. In Authentik Admin (the MCP server's Authentik at `auth.internal.com`), navigate to **Applications → Providers**.
2. Open the existing `lifelog-mcp` OAuth2 Provider (created in the shared setup above, or create a new one).
3. Scroll to **Machine-to-Machine authentication settings**. Under **Federated OAuth2/OpenID Providers**, add the **LibreChat OAuth2/OIDC provider** from `auth.company.com`. This tells Authentik how to validate tokens issued by the other Authentik instance.
4. Save.

### Step 2 — LibreChat Configuration

Configure LibreChat to point to its own Authentik (`auth.company.com`) for authentication, and configure the OBO section with the MCP server's Authentik (`auth.internal.com`) as the token exchange endpoint:

```yaml
mcpServers:
  lifelog:
    type: streamable-http
    url: http://lifelog-mcp:9001/mcp
    obo:
      clientID: "<lifelog-mcp-client-id>"
      # No clientSecret needed when using federated OBO — LibreChat's Authentik
      # issues the delegated token directly after token exchange with the
      # MCP server's Authentik.
      scopes: 'lifelog:tools.read'
    serverInstructions: >
      The LifeLog MCP server provides access to your voice recordings,
      transcripts, action items, decisions, and speaker information.
      Ask me about what you discussed, decided, or planned.
```

> The token exchange endpoint follows Authentik's standard token endpoint format:
> `https://auth.internal.com/application/o/<mcp-slug>/token/`

---

## Testing

### 1. Verify Token Exchange

**Shared instance** — exchange directly with your Authentik:

```bash
curl -X POST https://<your-authentik-domain>/application/o/<mcp-slug>/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=<librechat-user-id-token>" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "client_id=<lifelog-mcp-client-id>" \
  -d "client_secret=<lifelog-mcp-client-secret>" \
  -d "scope=lifelog:tools.read"
```

**Federated instance** — exchange with the MCP server's Authentik using a token from LibreChat's Authentik:

```bash
curl -X POST https://<mcp-authentik-domain>/application/o/<mcp-slug>/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=<librechat-user-token-from-auth-company-com>" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "client_id=<lifelog-mcp-client-id>" \
  -d "scope=lifelog:tools.read"
```

Expected: JSON with `access_token` (the delegated token for the MCP server).

### 2. List MCP Tools

```bash
curl -X POST http://localhost:9001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <delegated-token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Expected: JSON-RPC response with `tools` array:
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
| `LIFELOG_OIDC_ISSUER` | *(none)* | OIDC provider issuer URL for JWKS token validation. Set to your Authentik base URL, e.g. `https://auth.example.com`. Must match the `OIDC_ISSUER_URL` used by the main LifeLog server and dashboard. |
| `LIFELOG_MCP_PORT` | `9001` | Port the MCP server listens on |
| `LIFELOG_MCP_HOST` | `0.0.0.0` | Host the MCP server binds to |
| `LIFELOG_MCP_URL` | `http://localhost:9002/mcp` | Public URL clients use to reach this MCP server. **Must match the URL LibreChat uses** — e.g. `http://localhost:9002/mcp` when LibreChat runs on the host, or `http://lifelog-mcp:9001/mcp` when LibreChat runs inside Docker. Used as the OAuth 2.0 resource URL (RFC 9728); must be the URL clients actually call, not the internal Docker hostname. |

In `docker-compose`, `LIFELOG_OIDC_ISSUER` is set from `${OIDC_ISSUER_URL}` and `LIFELOG_MCP_URL` defaults to `http://localhost:9002/mcp` (override with `${LIFELOG_MCP_URL}` if LibreChat is inside Docker).

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
