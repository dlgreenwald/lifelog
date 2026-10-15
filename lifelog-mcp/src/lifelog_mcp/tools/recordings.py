"""get_recordings_by_date and get_recording_detail tools."""

import httpx
from mcp.types import TextContent, Tool

from lifelog_mcp.config import settings


def _build_get_recordings_by_date_tool() -> Tool:
    return Tool(
        name="get_recordings_by_date",
        description=(
            "Get all voice recordings for a specific calendar date (YYYY-MM-DD). "
            "Valid categories: 'work', 'personal'. "
            "Use this to browse recordings from a known date, optionally filtered by category."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, e.g. '2026-10-13'",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category: 'work' or 'personal'",
                    "enum": ["work", "personal"],
                },
            },
            "required": ["date"],
        },
    )


def _build_get_recording_detail_tool() -> Tool:
    return Tool(
        name="get_recording_detail",
        description=(
            "Get the full details of a specific recording including transcript segments, "
            "speaker labels, summary, action items, decisions, and metadata. "
            "Use this to deep-dive into a specific recording."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "recording_id": {
                    "type": "integer",
                    "description": "The numeric ID of the recording",
                },
            },
            "required": ["recording_id"],
        },
    )


async def _get_recordings_by_date(token: str, date: str, category: str | None = None) -> TextContent:
    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as client:
        params = {}
        if category:
            params["category"] = category
        resp = await client.get(f"/api/v1/dashboard/recordings/{date}", params=params)
        resp.raise_for_status()
        data = resp.json()

    recordings = data.get("recordings", [])
    if not recordings:
        return TextContent(type="text", text=f"No recordings found for {date}.")

    lines = [f"Recordings on {date}:\n"]
    for rec in recordings:
        lines.append(
            f"- id={rec['id']} | timestamp={rec.get('timestamp', 'n/a')} "
            f"| duration={rec.get('duration_s', 0):.0f}s | "
            f"category={rec.get('category', 'n/a')} | "
            f"speakers={', '.join(rec.get('speakers', []) or ['unknown'])}"
        )
    return TextContent(type="text", text="\n".join(lines))


async def _get_recording_detail(token: str, recording_id: int) -> TextContent:
    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as client:
        resp = await client.get(f"/api/v1/dashboard/recording/{recording_id}")
        if resp.status_code == 404:
            return TextContent(type="text", text=f"Recording {recording_id} not found.")
        resp.raise_for_status()
        rec = resp.json()

    segments = rec.get("transcript", {}).get("segments", [])
    segment_lines = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if text:
            segment_lines.append(
                f"  [{seg.get('speaker', 'unknown')}] {text}"
            )

    todos = rec.get("todos", [])
    todo_lines = [f"  - {t['task']} (id={t['id']}, status={t.get('completed_at', 'pending')})"
                  for t in todos]

    decisions = rec.get("decisions", [])
    decision_lines = [f"  - {d['decision']} (id={d['id']})" for d in decisions]

    summary = rec.get("summary") or "No summary available."

    lines = [
        f"## Recording {recording_id}",
        f"Date: {rec.get('timestamp', 'n/a')}",
        f"Duration: {rec.get('duration_s', 0):.0f}s",
        f"Category: {rec.get('category', 'n/a')}",
        f"Speakers: {', '.join(rec.get('speakers', []) or ['unknown'])}",
        "\n### Summary",
        summary,
        f"\n### Transcript ({len(segment_lines)} segments)",
        *(segment_lines or ["  (no transcript available)"]),
        f"\n### Action Items ({len(todo_lines)})",
        *(todo_lines or ["  (none)"]),
        f"\n### Decisions ({len(decision_lines)})",
        *(decision_lines or ["  (none)"]),
    ]
    return TextContent(type="text", text="\n".join(lines))


def build_tools() -> list[Tool]:
    return [
        _build_get_recordings_by_date_tool(),
        _build_get_recording_detail_tool(),
    ]


async def call(tool_name: str, **kwargs) -> TextContent:
    if tool_name == "get_recordings_by_date":
        return await _get_recordings_by_date(**kwargs)
    if tool_name == "get_recording_detail":
        return await _get_recording_detail(**kwargs)
    raise ValueError(f"Unknown tool: {tool_name}")
