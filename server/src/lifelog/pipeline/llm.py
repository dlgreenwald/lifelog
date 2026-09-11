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

# ---------------------------------------------------------------------------
# Pass 1 – topic-split detection
# ---------------------------------------------------------------------------

SPLIT_PROMPT = """\
You are a life journal assistant analyzing a conversation transcript.

Your task is to detect genuine topic shifts — conversational boundaries where \
the discussion moves to a substantially different subject, not mere tangents \
that return to the original thread.

When evaluating whether to split at a point, consider:
- A greeting or introduction followed by a topic change → genuine split
- A question answered and then the original topic continues → no split
- A clear, sustained topic change that occupies the rest of the conversation \
  → genuine split
- A brief aside that returns to the prior topic → no split

Return a JSON object with this exact key:
- "topic_splits": list of {{ "at_seconds": float, "reason": str }} objects, \
  sorted ascending by at_seconds

If there are no genuine topic shifts, return: {{ "topic_splits": [] }}

---
USER CONTEXT:
{llm_context}

---
TRANSCRIPT:
{transcript}"""


# ---------------------------------------------------------------------------
# Pass 2 – per-partition analysis
# ---------------------------------------------------------------------------

PARTITION_PROMPT = """\
You are a life journal assistant analyzing a conversation transcript that has \
been isolated to a single coherent topic partition. Your task is to produce a \
structured analysis of this partition.

Output format — return a JSON object with ALL of these keys (use empty \
defaults when a field has nothing to report):

{{
  "category": "personal" | "work" | "not_meaningful",
  "title": "5-7 word title",
  "summary": "1-2 sentence prose summary",
  "long_summary": "prose or outline+prose if long",
  "decisions": [
    {{
      "decision": "What was decided",
      "made_by": "Display name (or null)",
      "context": "Brief context (or null)",
      "reason": "Brief explanation of why (or null)"
    }}
  ],
  "todos": [
    {{
      "task": "The action item",
      "owner": "Display name (or null)",
      "due": "YYYY-MM-DD or null",
      "priority": "high" | "medium" | "low"
    }}
  ]
}}

=== CATEGORY ===

Classify this conversation partition as one of:
- "personal" — family, friends, errands, plans, health, hobbies, life admin
- "work" — meetings, projects, technical discussions, colleague interactions, \
  work tasks
- "not_meaningful" — silence, noise, garbled speech, no substantive content, \
  or audio from an audiobook, podcast, movie, TV show, or other entertainment \
  source

Heuristics:
- Time-of-day matters: standard work hours (roughly 09:00–17:00 on weekdays) \
  tilt toward "work"; late-night / early-morning hours tilt toward \
  "not_meaningful".
- Longer recordings and multi-speaker conversations tend to be more important \
  and are more likely "personal" or "work".
- A single speaker with brief or fragmented utterances is rarely important.

=== SUMMARY STYLE ===

Write like a journalist composing a brief: focus on *what happened* and *what \
was decided*, not on who said what. Never write "Speaker_0 said X" or similar \
attribution-heavy sentences. Capture the substance, outcomes, and context in \
concise prose.

=== LONG SUMMARY ===

The long_summary should be roughly one page (≈400 words) of prose per hour of \
transcribed audio. If the content exceeds a single page, prepend a brief \
bullet-point outline before the prose. When the partition is short (under a \
few minutes), the long_summary may be identical to the summary.

=== TODO EXTRACTION ===

Extract only clear, explicit action items — things like:
- "Bob, you take care of X"
- "I'll handle that by Friday"
- "Someone should follow up on Y"

Do NOT extract casual language, offhand suggestions, or vague intentions. If \
there are no concrete action items, return an empty list.

=== DECISION EXTRACTION ===

Extract only explicit decisions — language such as:
- "Let's go with option A"
- "Agreed, we'll do X"
- "We should use framework Y"
- "I decided to switch to Z"

Do NOT extract tentative preferences or unconfirmed plans. If no decisions \
were made, return an empty list.

=== NOTE ON TRANSCRIPT QUALITY ===

These transcripts come from automatic speech recognition (ASR). They may \
contain minor errors caused by background noise, overlapping speech, or \
accented speech. Do your best to interpret meaning despite imperfections.

---
USER CONTEXT:
{llm_context}

---
TRANSCRIPT:
{transcript}"""


# ---------------------------------------------------------------------------
# Daily roll-up (unchanged)
# ---------------------------------------------------------------------------

DAILY_PROMPT = """\
You are a life journal assistant. Below are all conversation transcripts from a single day.

Produce a JSON object with a single key "daily_summary" containing a structured \
summary of the day divided into two sections:

1. **Work**: Summarize all work-related conversations — meetings, projects, \
   decisions, tasks, technical discussions, colleague interactions. Be specific \
   about what was discussed and any outcomes.

2. **Personal**: Summarize all personal conversations — family, friends, errands, \
   plans, health, hobbies, life admin. Be specific about what was discussed and \
   any outcomes.

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
            {
                "role": "user",
                "content": DAILY_PROMPT.format(
                    transcripts=transcripts, llm_context=llm_context
                ),
            },
        ],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    duration = time.monotonic() - start

    summary = result.get("daily_summary", "")
    logger.info("Daily summary complete in %.2fs: %d chars", duration, len(summary))

    return {"daily_summary": summary}


# ---------------------------------------------------------------------------
# Pass 1 – detect topic splits
# ---------------------------------------------------------------------------


def _format_transcript(segments: list[dict]) -> str:
    """Format segments into a readable transcript string."""
    lines: list[str] = []
    for seg in segments:
        timestamp = f"[{seg.get('start', '?'):.1f}s]" if "start" in seg else ""
        lines.append(f"{timestamp} {seg['name']}: {seg['text']}")
    return "\n".join(lines)


def detect_splits(segments: list[dict], llm_context: str = "") -> dict:
    """Pass 1: detect topic splits in the full conversation.

    Returns ``{"topic_splits": [{"at_seconds": float, "reason": str}]}``.
    On error or when no splits are found, returns an empty list.
    """
    if not segments:
        return {"topic_splits": []}

    start = time.monotonic()
    formatted = _format_transcript(segments)
    logger.info(
        "Detecting topic splits in %d segments (%d chars) with model %s",
        len(segments),
        len(formatted),
        settings.openai_model,
    )

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a life journal assistant that detects topic boundaries in conversation transcripts.",
                },
                {
                    "role": "user",
                    "content": SPLIT_PROMPT.format(
                        transcript=formatted, llm_context=llm_context
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        duration = time.monotonic() - start

        splits = result.get("topic_splits", [])
        logger.info(
            "Split detection complete in %.2fs: %d splits found",
            duration,
            len(splits),
        )
        return {"topic_splits": splits}

    except Exception:
        logger.exception("Split detection failed; assuming no splits")
        return {"topic_splits": []}


# ---------------------------------------------------------------------------
# Pass 2 – per-partition summarization
# ---------------------------------------------------------------------------


def summarize_partition(segments: list[dict], llm_context: str = "") -> dict:
    """Pass 2: analyze a single topic partition.

    Returns a dict with keys: category, title, summary, long_summary,
    decisions, todos. On error or when segments are empty, returns safe
    defaults.
    """
    if not segments:
        return {
            "category": "not_meaningful",
            "title": "",
            "summary": "",
            "long_summary": "",
            "decisions": [],
            "todos": [],
        }

    start = time.monotonic()
    formatted = _format_transcript(segments)
    logger.info(
        "Summarizing partition (%d segments, %d chars) with model %s",
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
            {
                "role": "user",
                "content": PARTITION_PROMPT.format(
                    transcript=formatted, llm_context=llm_context
                ),
            },
        ],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    duration = time.monotonic() - start

    # Normalize: ensure all expected keys exist (models may omit empty ones)
    result.setdefault("category", "not_meaningful")
    result.setdefault("title", "")
    result.setdefault("summary", "")
    result.setdefault("long_summary", "")
    result.setdefault("decisions", [])
    result.setdefault("todos", [])

    todos = result.get("todos", [])
    decisions = result.get("decisions", [])
    logger.info(
        "Partition summary complete in %.2fs: %d todos, %d decisions",
        duration,
        len(todos),
        len(decisions),
    )

    return result


# ---------------------------------------------------------------------------
# Backwards-compatible alias
# ---------------------------------------------------------------------------

summarize = summarize_partition
