"""Input validation and prompt injection defense for user-supplied LLM context."""

import re
import unicodedata

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    # Role hijack
    re.compile(r"ignore\s+(all\s+)?(previous|your)", re.IGNORECASE),
    re.compile(r"ignore\s+previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|your)", re.IGNORECASE),
    re.compile(r"forget\s+everything", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    # Delimiter escape — 3+ special token sequences
    re.compile(r"(#{2,}|[-=]{3,}|\*{3,})"),
    # Instruction override
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\balways\s+follow\b", re.IGNORECASE),
    re.compile(r"\boverride\b", re.IGNORECASE),
    re.compile(r"\bnew\s+rule\b", re.IGNORECASE),
    # XML/HTML injection
    re.compile(r"<(system|instruction|prompt)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL),
]

_MAX_LENGTH = 2000

# Control characters to strip (U+0000–U+001F except newline/tab, U+007F–U+009F)
_STRIP_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)


def validate_llm_context(text: str) -> str:
    """Sanitize and validate user-provided LLM context.

    Raises ValueError on detection of prompt injection patterns.
    Returns the cleaned text on success.
    """
    if not text:
        return ""

    # Normalize unicode to NFC to prevent homoglyph attacks
    text = unicodedata.normalize("NFC", text)

    # Strip control characters
    text = _STRIP_RE.sub("", text)

    # Enforce max length
    if len(text) > _MAX_LENGTH:
        raise ValueError(f"LLM context exceeds maximum length of {_MAX_LENGTH} characters")

    # Scan for injection patterns
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise ValueError(
                f"LLM context contains disallowed pattern: {pattern.pattern!r}"
            )

    return text
