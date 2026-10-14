"""search_recordings — full-text search across transcripts, summaries, todos, and decisions."""

import httpx
from mcp.types import TextContent, Tool

from lifelog_mcp.config import settings


def _build_tool() -> Tool:
    return Tool(
        name="search_recordings",
        description=(
            "Search across all voice recording transcripts, summaries, action items, "
            "and decisions using natural language. Returns recordings that match the query "
            "with highlighted snippets. Use this as the primary tool for answering questions "
            "like 'what did I discuss with Alex last week' or 'show me all meetings about budget'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (required, 1-500 chars)",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter results to recordings on or after this date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter results to recordings on or before this date (YYYY-MM-DD)",
                },
                "speaker": {
                    "type": "string",
                    "description": "Filter results to recordings mentioning a specific speaker name",
                },
                "kind": {
                    "type": "string",
                    "description": "Filter by content type: 'transcript', 'summary', 'decision', or 'todo'",
                    "enum": ["transcript", "summary", "decision", "todo"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-100, default 20)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    )


async def _call(
    token: str,
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    speaker: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> TextContent:
    params: dict = {"q": query, "limit": limit}
    if start_date:
        params["date_from"] = start_date
    if end_date:
        params["date_to"] = end_date
    if speaker:
        params["speaker"] = speaker
    if kind:
        params["kind"] = kind

    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    ) as client:
        resp = await client.get("/api/v1/search", params=params)
        resp.raise_for_status()
        data = resp.json()

    hits = data.get("hits", [])
    results = []
    for hit in hits:
        results.append(
            {
                "id": hit.get("id"),
                "kind": hit.get("kind"),
                "title": hit.get("title"),
                "date": hit.get("date"),
                "speakers": hit.get("speakers", []),
                "snippet": hit.get("_formatted", {}).get("transcript")
                or hit.get("_formatted", {}).get("summary")
                or hit.get("snippet", ""),
                "highlights": hit.get("_formatted", {}),
            }
        )

    return TextContent(
        type="text",
        text=f"Found {len(results)} result(s) for '{query}':\n\n"
        + "\n\n".join(
            f"## [{r['date']}] {r['title'] or r['kind']} (id={r['id']})\n"
            f"Speakers: {', '.join(r['speakers']) if r['speakers'] else 'unknown'}\n"
            f"Snippet: {r['snippet']}"
            for r in results
        ),
    )


def build_tool() -> Tool:
    return _build_tool()


async def call(**kwargs) -> TextContent:
    return await _call(**kwargs)
