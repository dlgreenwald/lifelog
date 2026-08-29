import json
import logging
import time

from openai import OpenAI

from lifelog.config import settings

logger = logging.getLogger("lifelog.llm")

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
   - "reason": Brief explanation of why this decision was made or what factors influenced it

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

7. **category**: Classify this conversation as one of:
   - "personal" — family, friends, errands, plans, health, hobbies, life admin
   - "work" — meetings, projects, technical discussions, colleague interactions, work tasks
   - "not_meaningful" — silence, noise, garbled speech, no substantive content, or audio from an audiobook, podcast, movie, TV show, or other entertainment source

Format your response as valid JSON with these exact keys: category, summary, conversation_changes, decisions, todos, calendar, notes.

---

USER CONTEXT:
{llm_context}

---

TRANSCRIPT:
{transcript}"""


DAILY_PROMPT = """You are a life journal assistant. Below are all conversation transcripts from a single day.

Produce a JSON object with a single key "daily_summary" containing a structured summary of the day divided into two sections:

1. **Work**: Summarize all work-related conversations — meetings, projects, decisions, tasks, technical discussions, colleague interactions. Be specific about what was discussed and any outcomes.

2. **Personal**: Summarize all personal conversations — family, friends, errands, plans, health, hobbies, life admin. Be specific about what was discussed and any outcomes.

If one section has no content, state "No {{section}} conversations recorded today."

Format your response as valid JSON with this exact key: daily_summary

---

USER CONTEXT:
{llm_context}

---

TRANSCRIPTS:
{transcripts}"""


def summarize_day(transcripts: str, llm_context: str = "") -> dict:
    """Send combined daily transcripts to LLM for Work/Personal summary."""
    start = time.monotonic()
    logger.info(
        "Generating daily summary (%d chars) with model %s",
        len(transcripts),
        settings.openai_model,
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "You are a life journal assistant that summarizes a day's conversations into Work and Personal categories.",
            },
            {"role": "user", "content": DAILY_PROMPT.format(transcripts=transcripts, llm_context=llm_context)},
        ],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    duration = time.monotonic() - start

    summary = result.get("daily_summary", "")
    logger.info("Daily summary complete in %.2fs: %d chars", duration, len(summary))

    return {"daily_summary": summary}


def summarize(segments: list[dict], llm_context: str = "") -> dict:
    """Send named transcript to LLM for analysis."""
    if not segments:
        return {
            "category": "not_meaningful",
            "summary": "",
            "conversation_changes": [],
            "decisions": [],
            "todos": [],
            "calendar": [],
            "notes": [],
        }

    start = time.monotonic()

    formatted_lines = []
    for seg in segments:
        timestamp = f"[{seg.get('start', '?'):.1f}s]" if "start" in seg else ""
        formatted_lines.append(f"{timestamp} {seg['name']}: {seg['text']}")

    formatted = "\n".join(formatted_lines)
    logger.info(
        "Summarizing %d segments (%d chars) with model %s",
        len(segments),
        len(formatted),
        settings.openai_model,
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "You are a life journal assistant that analyzes conversations and extracts structured information.",
            },
            {"role": "user", "content": PROMPT.format(transcript=formatted, llm_context=llm_context)},
        ],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    duration = time.monotonic() - start

    # Normalize: ensure all expected keys exist (models may omit empty ones)
    result.setdefault("category", "not_meaningful")
    result.setdefault("summary", "")
    result.setdefault("conversation_changes", [])
    result.setdefault("decisions", [])
    result.setdefault("todos", [])
    result.setdefault("calendar", [])
    result.setdefault("notes", [])

    todos = result.get("todos", [])
    decisions = result.get("decisions", [])
    logger.info(
        "LLM summary complete in %.2fs: %d todos, %d decisions, %d notes",
        duration,
        len(todos),
        len(decisions),
        len(result.get("notes", [])),
    )

    return result
