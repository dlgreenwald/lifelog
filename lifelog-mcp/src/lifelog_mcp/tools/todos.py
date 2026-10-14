"""get_todos — list action items from recordings."""

import httpx
from mcp.types import TextContent, Tool

from lifelog_mcp.config import settings


def _build_tool() -> Tool:
    return Tool(
        name="get_todos",
        description=(
            "Get action items (todos) from voice recordings, optionally filtered by date or status. "
            "Use this to answer questions like 'what action items did I capture yesterday' "
            "or 'show me all pending todos'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Filter to todos from recordings on a specific date (YYYY-MM-DD)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by completion status",
                    "enum": ["pending", "completed", "all"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of todos to return (1-200, default 50)",
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
    status: str | None = None,
    limit: int = 50,
) -> TextContent:
    params: dict = {"limit": limit}
    if date:
        params["date"] = date
    if status:
        params["status"] = status

    path = "/api/v1/dashboard/todos"
    if date:
        path = f"/api/v1/dashboard/todos/{date}"

    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        data = resp.json()

    todos = data.get("todos", [])
    if not todos:
        return TextContent(type="text", text="No todos found matching the criteria.")

    lines = [f"Found {len(todos)} todo(s):\n"]
    for t in todos:
        completed = t.get("completed_at")
        status_str = f"completed {completed}" if completed else "pending"
        lines.append(
            f"- [{status_str}] {t['task']} "
            f"(id={t['id']}, created={t.get('created_at', 'n/a')})"
        )
    return TextContent(type="text", text="\n".join(lines))


def build_tool() -> Tool:
    return _build_tool()


async def call(**kwargs) -> TextContent:
    return await _call(**kwargs)
