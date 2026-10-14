"""get_decisions — list decisions captured from recordings."""

import httpx
from mcp.types import TextContent, Tool

from lifelog_mcp.config import settings


def _build_tool() -> Tool:
    return Tool(
        name="get_decisions",
        description=(
            "Get decisions captured from voice recordings, optionally filtered by date. "
            "Use this to answer questions like 'what decisions did I make last week'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Filter to decisions from recordings on a specific date (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of decisions to return (1-200, default 50)",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            "required": [],
        },
    )


async def _call(
    token: str,
    date: str | None = None,
    limit: int = 50,
) -> TextContent:
    params: dict = {"limit": limit}
    if date:
        params["date"] = date

    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as client:
        resp = await client.get("/api/v1/dashboard/decisions", params=params)
        resp.raise_for_status()
        data = resp.json()

    decisions = data.get("decisions", [])
    if not decisions:
        return TextContent(type="text", text="No decisions found matching the criteria.")

    lines = [f"Found {len(decisions)} decision(s):\n"]
    for d in decisions:
        made_by = d.get("made_by", "unknown")
        lines.append(
            f"- [{d.get('created_at', 'n/a')}] "
            f"(speaker: {made_by}) {d['decision']} (id={d['id']})"
        )
    return TextContent(type="text", text="\n".join(lines))


def build_tool() -> Tool:
    return _build_tool()


async def call(**kwargs) -> TextContent:
    return await _call(**kwargs)
