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
The transcript may be any kind of conversation: a work meeting, a casual
chat between friends or family, a phone call, a chance encounter. Treat
all of these equally.

CONTEXT: The system has already split the recording wherever there was a
5-minute silence. Your job is to find the remaining boundaries: cases where
one conversation ENDED and another BEGAN back-to-back, with little or no
gap — for example, someone wrapping up one conversation and starting
another within minutes, or a structured conversation beginning right after
a stretch of ambient noise, or back-to-back meetings changing rooms. When
audio quality changes at a boundary (new room, new microphone placement),
the transcription there may be poor. Occasionally a transcript contains
several such back-to-back conversations in sequence. That is legitimate
and you should detect every genuine boundary — but it is uncommon, so
each boundary you propose must stand on its own strong evidence.

Your default is: NO SPLIT. A single conversation naturally covers many
topics, includes tangents, welcomes late arrivals, and loses people along
the way. Topic changes, asides, and participant churn within an ongoing
conversation are NOT boundaries.

A split is justified ONLY where one conversation ENDS and another BEGINS
back-to-back: a CLOSURE immediately followed by an OPENING, close together.
Closure and opening can be signaled verbally or through the participants
themselves:

CLOSURE signals (any register — formal or casual):
- Goodbyes, farewells, sign-offs: "Bye.", "great meeting everyone",
  "alright, I'll let you go", "love you, bye", "thanks for taking the
  time", "Thanks, bye-bye"
- Wrap-up language: "so to summarize...", "that's all I had", "well, it
  was great catching up", "I'll take it bi-weekly. Thank you.",
  "Appreciate it."
- An explicit ending of the interaction itself, not just of one topic
- A LARGE FRACTION of participants leaving at once (e.g., a group of ten
  dwindles to a pair), which effectively ends the prior conversation even
  if no one says goodbye

PURPOSE COMPLETION: A conversation with a transactional goal (scheduling
an appointment, ordering, asking an office a question) ends when the goal
is achieved. Scheduling language followed by a sign-off ("that works",
"Thursday at 10:30 is a little safer", "see you then", "Thanks, bye-bye")
is a COMPLETED conversation — a closure — even though it may be brief.
Do not merge a completed transactional call into the conversation that
follows it.

ONE-SIDED PHONE CALLS: Some speech is one side of a phone call: one
speaker, scheduling or logistics language (making appointments, agreeing
on times, "Thursday at 10", "that works"), pleasantries ("How are you?"
/ "Good"), and a call sign-off ("Thanks, bye-bye", "Okay, thanks, bye").
This IS a structured conversation, and its sign-off is a valid CLOSURE.
When it ends and a different conversation (e.g., a meeting with multiple
participants and a work topic) begins — even immediately, and even
without greetings — that is a boundary.

OPENING signals (any register):
- Fresh greetings or introductions: "hi everyone, thanks for joining",
  "hey! how've you been?", "nice to meet you"
- Audio/connection checks at a start: "Good morning", "Can you not hear me?"
- A short silence gap between the closure and the opening
- A largely different set of participants
- A topic introduced from scratch that shares nothing with the previous
  conversation and is never tied back to it

COLD MEETING STARTS: Not every meeting opens with greetings. When someone
joins late, a meeting starts mid-stream — no hellos, just business. Treat
the following as valid OPENING signals even without any greeting:
- Multiple new speakers participating in a coherent discussion of shared
  work (references to colleagues by name, "let me give a summary",
  agenda-like structure)
- Meta-conversation about the meeting itself (jokes about who's in the
  meeting, complaints about the schedule, "is this just a standard, like,
  there are too many Davids in a meeting?")
- A sudden, full change in conversational register and participant set
  (e.g., a one-sided phone call ending and a multi-party work discussion
  starting seconds later)

A CLOSURE (call sign-off, goodbyes) followed by a COLD START — different
participants, different register, wholly unrelated topic — is a boundary,
even with no gap and no greetings.

GARBLED OR LOW-QUALITY OPENINGS: The first moments of a new conversation
are often badly transcribed — room or microphone changes, cross-talk,
distance from the mic. Text may appear as disconnected fragments, nonsense
phrases, or fragments with no coherent topic ("appears that the answer is
clear.", "A lot is happening.", "Fair point.").

Treat unreadable text as NEUTRAL evidence — neither an opening signal nor
a reason to withhold a split. Do NOT classify a garbled stretch as ambient
noise when it immediately follows a clear closure and a gap. Instead, look
PAST the garbled stretch to where the transcript stabilizes: if coherent
speech resumes with a different topic and largely different participants
than the conversation that closed, that is a boundary — split at the start
of the garbled stretch (or the first segment after the gap), even though
no readable opening signal exists.

When the text immediately after a gap is garbled, evaluate the topic of
the conversation as it appears over the following few minutes, not the
first few sentences.

PARTICIPANT CHANGE — evaluate it proportionally and in combination with
the topic:
- What matters is the fraction of speakers replaced, not the raw number.
  One person joining a two-person conversation is a major change; one
  person joining a ten-person conversation is not.
- Participant change is evidence of a boundary ONLY when the topic also
  changes with it. A new person joining and the existing topic continuing
  = someone joined the conversation; no split. Major participant turnover
  accompanied by a wholly unrelated topic = a new conversation; split.
- A mass departure with a few people remaining can be a closure: if the
  remaining people then start a fresh topic, that is a boundary.
- When the text at a boundary is garbled, compare the participant sets
  on either side of the garbled stretch, not within it.

A closure WITHOUT an opening (people say goodbye, then keep talking) is
not a split. An opening WITHOUT a closure (a new person joins an ongoing
discussion, or someone greets a latecomer) is not a split — EXCEPT where
an opening sequence follows ambient noise (see DENSITY MARKERS), or a
cold start follows a completed one-sided call or a clear closure. You
need the sequence: ending → new beginning.

Conversational flow within one conversation is NOT a boundary: people
drift between topics, greet each other again after distractions ("hey,
you're back!"), say goodbye to one person while continuing with others,
or move to the next agenda item ("There's something I'm working on right
now...", "So the big thing here is...", "Then let's change gears",
"Contract auto copy is moving along..."). A new proposal, a pivot to a
different workstream, or several subjects within one sitting are all
still one conversation — even when the new topic occupies the rest of
the conversation.

DENSITY MARKERS: The transcript contains computed speech-density markers
at each significant pause, e.g.:
[gap: 18 min 29 sec | speech before: sparse — isolated fragments | speech
after: dense — sustained conversation | elapsed: young conversation]

These describe the computed share of time containing speech in the 5
minutes on each side of the gap (the gap itself excluded). Use them:

- Sparse on both sides of a gap = ambient noise: overheard fragments, not
  a conversation. Do not split inside noise, and do not treat noise
  ending as a conversation boundary.
- Sparse before, dense after a gap = a structured conversation is
  BEGINNING (e.g., a meeting starting). This IS a boundary candidate:
  split at the opening, and confirm the opening signals in the text
  (greetings, introductions, audio checks like "Can you not hear me?").
  Do NOT require closure signals before it — ambient noise has no
  goodbye to give.
- Dense before and after a gap = the same conversation with a pause. Do
  not split without strong closure AND opening evidence (farewells
  followed by greetings AND a wholly unrelated topic).
- Dense before, gap, dense after, but the text at the seam is garbled or
  fragmentary = likely a physical change of conversation (new room or
  mic placement). This favors a split; verify with the post-garble topic
  and participants.
- Dense before, none after = the conversation ended there (likely already
  handled by the upstream silence splitter).
- "insufficient data" or "no prior speech": do not draw conclusions from
  that side; rely on the other side and the text.

Density is supporting evidence only — it lowers or raises the bar for
verbal evidence; it never alone determines a boundary.

TIME CALIBRATION (from markers):
- A gap of ~30+ minutes: strong evidence of a boundary (likely already
  handled upstream); confirm closure/opening if text is present.
- A gap of 5–30 minutes: the boundary rests on clear closure AND opening
  signals (farewells, greetings, participant turnover, unrelated topic).
- A gap under 5 minutes: requires OVERWHELMING evidence — explicit mutual
  farewells immediately followed by greetings or a wholly new participant
  set AND a completely unrelated topic — unless density markers show a
  sparse→dense transition (a conversation beginning), or a completed
  one-sided call is followed by a cold start.
- ELAPSED TIME (from markers): a small gap in a young conversation
  (< 30 min in) is almost never a boundary — treat it as a lull or
  agenda transition. A small or moderate gap in a mature (30–60 min) or
  long-running (60+ min) conversation is a plausible boundary — but
  still require clear closure followed by opening.
- In a long-running conversation (60+ min), a closure (farewells, thanks,
  wrap-up) followed by a gap of any length may be sufficient EVEN IF the
  opening signals are unreadable or garbled — weigh instead what the
  conversation becomes after the gap: a wholly different topic and a
  largely different participant set confirm the split.
- Two proposed boundaries within ~30 minutes of each other is a red flag:
  re-verify each independently; it usually means you are detecting topic
  changes, not conversation changes.

CALIBRATION: Most transcripts contain zero or one boundaries. If you
find yourself proposing several, slow down and re-verify each one
individually: does EACH boundary have its own clear closure and opening
(or a sparse→dense transition, or a closure followed by a cold start)
at that exact point? Drop any boundary whose evidence would not have
convinced you on its own.

If the transcript contains no such boundary sequence, it is one
continuous conversation. Returning no boundaries is a valid and common
outcome.

When in doubt, do not split.

Do NOT split for: topic shifts, brief asides, one person joining or
leaving mid-conversation, an interrupted question where the topic then
resumes, several subjects within one meeting, agenda transitions,
small talk or re-greetings inside an ongoing conversation, garbled or
low-quality stretches where the topic and participants continue on both
sides, or someone excusing themselves briefly and returning.

Return a JSON object with this exact key:
- "topic_splits": list of {{ "at_seconds": float, "reason": str }} objects,
  sorted ascending by at_seconds.

The "reason" must cite the closure and opening evidence — quoted phrases,
before/after participant sets and topics, or the density transition —
never a topic change alone.

Markers (e.g. "[gap: ...]") are part of the input transcript, not speech:
never quote a marker as closure/opening evidence, and set "at_seconds" to
the timestamp of the first opening segment (e.g., the "Good morning." or
"From year one." line), never to the marker's position.

If there are no genuine conversation boundaries, return:
{{ "topic_splits": [] }}


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
few minutes), the long_summary may be identical to the summary.  Write the long \
summary as a markdown string. 

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
    result.setdefault("calendar", [])
    result.setdefault("notes", [])
    result.setdefault("conversation_changes", [])
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
