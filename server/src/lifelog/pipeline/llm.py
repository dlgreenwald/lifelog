import json

from openai import OpenAI

from lifelog.config import settings

client = OpenAI(
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
)

PROMPT = """You are a life journal assistant analyzing a conversation transcript with speaker identification.

Your task is to analyze the conversation and produce a structured JSON output with the following:

1. **summary**: A concise summary (3-5 sentences) of the entire conversation, identifying who spoke and what was discussed.

2. **conversation_changes**: Detect any changes or transitions in the conversation topic. For each change:
   - "from_topic": What was being discussed before
   - "to_topic": What the conversation shifted to
   - "speaker": Who initiated the change
   - "timestamp": Approximate time if available (or null)

3. **decisions**: List any decisions that were made during the conversation:
   - "decision": What was decided
   - "made_by": Who made or agreed to the decision
   - "context": Brief context around the decision

4. **todos**: List any action items or tasks that were discussed or assigned:
   - "task": The action item
   - "owner": Who is responsible (use speaker name if known, otherwise "Unassigned")
   - "due": Any mentioned deadline (or null if not specified)
   - "priority": "high", "medium", or "low" based on urgency cues

5. **calendar**: List any meetings, appointments, or time-bound events mentioned:
   - "event": Description of the event
   - "time": When it should happen (verbatim if mentioned, or parsed datetime)
   - "participants": Who is involved

6. **notes**: Key points, ideas, or important information worth remembering.

Format your response as valid JSON with these exact keys: summary, conversation_changes, decisions, todos, calendar, notes.

---

TRANSCRIPT:
{transcript}"""


def summarize(segments: list[dict]) -> dict:
    """Send named transcript to LLM for analysis."""
    formatted_lines = []
    for seg in segments:
        timestamp = f"[{seg.get('start', '?'):.1f}s]" if "start" in seg else ""
        formatted_lines.append(f"{timestamp} {seg['name']}: {seg['text']}")

    formatted = "\n".join(formatted_lines)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "You are a life journal assistant that analyzes conversations and extracts structured information.",
            },
            {"role": "user", "content": PROMPT.format(transcript=formatted)},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)
