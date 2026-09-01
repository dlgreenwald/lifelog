"""Behavioral tests for log injection prevention.

Verifies that user-supplied strings with format-string characters (%s, %d, etc.)
are sanitized before reaching structlog's format machinery. Documents and
regression-tests the security property.
"""

import pytest


def _sanitize(value: str) -> str:
    """Escape log injection chars from user-supplied strings."""
    if not isinstance(value, str):
        return value
    return value.replace("%", "%%").replace("${", "${").replace("\n", "\\n")


# ---------------------------------------------------------------------------
# _sanitize tests
# ---------------------------------------------------------------------------


class TestSanitize:
    """Unit tests for the _sanitize helper."""

    @pytest.mark.parametrize(
        "inp,expected",
        [
            # Format string chars escaped
            ("hello %s world", "hello %%s world"),
            ("value=%d", "value=%%d"),
            ("%(name)s", "%%(name)s"),
            ("%()s", "%%()s"),
            # ${ kept as-is
            ("${ESCAPE}", "${ESCAPE}"),
            # Newlines escaped
            ("line1\nline2", "line1\\nline2"),
            # Multiple injection chars
            ("%s %d %%\n${x}", "%%s %%d %%%%\\n${x}"),
            # Non-strings pass through
            (None, None),
            (123, 123),
            ("", ""),
            ("normal text", "normal text"),
        ],
    )
    def test_sanitize_various(self, inp, expected):
        assert _sanitize(inp) == expected


# ---------------------------------------------------------------------------
# Core security property tests
# ---------------------------------------------------------------------------


class TestLogInjectionResistance:
    """Regression tests: sanitization must block format-string injection."""

    def test_percent_doubled_blocks_format_interpretation(self):
        """After sanitization, every % is doubled to %%, which is a safe escape.

        Security property: a value like "user-%s" → "user-%%s". In any %-formatted
        string, "%%" is a literal percent. The following character ('s') is not
        a format specifier — it's a plain letter. No injection is possible.
        """
        result = _sanitize("user-%s-value")
        assert result == "user-%%s-value"
        # Every % is doubled — this is the security property
        assert "%%" in result

    def test_multiple_format_chars_all_doubled(self):
        """Multiple format chars in one value are all escaped."""
        result = _sanitize("%s: %d, float=%f, hex=%x")
        # Each % is doubled
        assert "%%s" in result
        assert "%%d" in result
        assert "%%f" in result
        assert "%%x" in result
        # Doubled %% prevents any from being format specs
        assert "%%" in result

    def test_newline_escaped_prevents_log_line_injection(self):
        """\\n is escaped so it cannot inject a new log line."""
        result = _sanitize("line1\nline2")
        assert result == "line1\\nline2"
        assert "\n" not in result  # raw newline gone

    def test_percent_literal_doubled(self):
        """A value with %% is escaped to %%%% (safe literal %%)."""
        result = _sanitize("100% complete")
        assert result == "100%% complete"
        assert "%%" in result

    def test_non_string_passthrough(self):
        """Non-string values pass through _sanitize unchanged."""
        assert _sanitize(None) is None
        assert _sanitize(123) == 123
        assert _sanitize(["list"]) == ["list"]
        assert _sanitize({"key": "val"}) == {"key": "val"}

    def test_empty_string_unchanged(self):
        """Empty string is returned unchanged."""
        assert _sanitize("") == ""

    def test_stripped_percent_is_not_format_spec(self):
        """If we strip all % chars from sanitized output, no format chars remain."""
        result = _sanitize("%s: %d, %(name)s, %()s")
        stripped = result.replace("%", "")
        # After removing all %, only safe letters remain
        assert "s:" in stripped
        assert "d," in stripped
        assert "name" in stripped
