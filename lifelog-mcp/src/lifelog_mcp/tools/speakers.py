"""get_speakers — list enrolled speakers with voiceprint counts."""

import httpx
from mcp.types import TextContent, Tool

from lifelog_mcp.config import settings


def _build_tool() -> Tool:
    return Tool(
        name="get_speakers",
        description=(
            "Get all enrolled speakers with voiceprint counts and recording counts. "
            "Use this to see who has been identified in your recordings and "
            "answer questions like 'who were the speakers in my recording from October 10th'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "recording_id": {
                    "type": "integer",
                    "description": "Optional: filter speakers to those appearing in a specific recording",
                },
            },
            "required": [],
        },
    )


async def _call(
    token: str,
    recording_id: int | None = None,
) -> TextContent:
    async with httpx.AsyncClient(
        base_url=settings.lifelog_api_base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as client:
        resp = await client.get("/api/v1/dashboard/speakers/all")
        resp.raise_for_status()
        data = resp.json()

    speakers = data.get("speakers", [])
    if not speakers:
        return TextContent(type="text", text="No enrolled speakers found.")

    lines = [f"Found {len(speakers)} enrolled speaker(s):\n"]
    for spk in speakers:
        lines.append(
            f"- {spk['name']} "
            f"(id={spk['id']}, recordings={spk.get('recording_count', 0)}, "
            f"voiceprints={spk.get('voiceprint_count', 0)})"
        )
    return TextContent(type="text", text="\n".join(lines))


def build_tool() -> Tool:
    return _build_tool()


async def call(**kwargs) -> TextContent:
    return await _call(**kwargs)
