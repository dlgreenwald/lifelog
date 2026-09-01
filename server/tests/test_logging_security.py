"""Behavioral tests that user-controlled values containing format specifiers
are never substituted into log format strings.

structlog's ``key=value`` positional-agnostic rendering means user data is
always treated as a value, never as a format placeholder.  These tests
document and regression-test that security property.
"""

from __future__ import annotations

import io
import json

import pytest


class TestLogSecurityProperty:
    """Verify structlog prevents log-injection via format-specifier injection."""

    @pytest.fixture
    def log_buffer(self) -> io.StringIO:
        """Return a StringIO that captures structlog JSONRenderer output."""
        output = io.StringIO()
        return output

    @pytest.fixture
    def structured_logger(self, log_buffer: io.StringIO):
        """Return a structlog logger configured to write JSON to log_buffer."""
        import structlog

        # Configure structlog to output JSON to our buffer
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=log_buffer),
            cache_logger_on_first_use=False,
        )
        return structlog.get_logger()

    def _parse_last_event(self, buffer: io.StringIO) -> dict:
        """Parse the last JSON line from the buffer."""
        buffer.seek(0)
        lines = [l for l in buffer.read().strip().split("\n") if l]
        return json.loads(lines[-1]) if lines else {}

    def test_percent_s_injected_value_not_interpreted_as_format(
        self, structured_logger, log_buffer
    ):
        """Values containing '%s' must appear verbatim in log output."""
        user_input = "hello %s world %s again"
        structured_logger.info("test_event", user_value=user_input)

        event = self._parse_last_event(log_buffer)
        # The value must appear verbatim — not expanded as a format placeholder.
        assert user_input in json.dumps(event)

    def test_percent_d_injected_value_not_interpreted_as_format(
        self, structured_logger, log_buffer
    ):
        """Values containing '%d' must appear verbatim in log output."""
        user_input = "count %d items %d left"
        structured_logger.info("test_event", user_value=user_input)

        event = self._parse_last_event(log_buffer)
        assert user_input in json.dumps(event)

    def test_newline_injected_value_not_split_event(
        self, structured_logger, log_buffer
    ):
        """Values containing newlines must not create spurious log events."""
        user_input = "line1\nline2\nevent: steal"
        structured_logger.info("real_event", user_value=user_input)

        log_buffer.seek(0)
        lines = [l for l in log_buffer.read().strip().split("\n") if l]
        # Exactly one log event should be emitted, not two.
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        # The injected content must appear verbatim in the single event.
        assert parsed.get("event") == "real_event"
        assert "line1" in json.dumps(parsed)

    def test_format_string_injection_attempt_is_harmless(
        self, structured_logger, log_buffer
    ):
        """Malicious format-string injection ('%s%s%s%n') must not crash or corrupt."""
        malicious = "%s%s%s%n"
        structured_logger.info("test_event", user_value=malicious)

        event = self._parse_last_event(log_buffer)
        # The event must be recorded with its name intact.
        assert event.get("event") == "test_event"
        # The malicious string must appear verbatim as a value.
        assert malicious in json.dumps(event)

    def test_mixture_of_format_chars_and_real_values(
        self, structured_logger, log_buffer
    ):
        """Mixed format chars and real data are all preserved verbatim."""
        values = {
            "username": "alice",
            "message": "hello %s %d end",
            "path": "/var/log/%s/../secrets",
            "template": "UPDATE %s SET %d WHERE id=%s",
        }
        structured_logger.info("test_event", **values)

        event = self._parse_last_event(log_buffer)
        for key, val in values.items():
            assert val in json.dumps(event), f"value for {key!r} was corrupted"

    def test_empty_value_does_not_break_event(self, structured_logger, log_buffer):
        """Empty string values are logged correctly."""
        structured_logger.info("test_event", user_value="")

        event = self._parse_last_event(log_buffer)
        assert event.get("event") == "test_event"

    def test_unicode_format_chars_preserved(self, structured_logger, log_buffer):
        """Unicode format-like chars (fullwidth, etc.) are preserved verbatim."""
        user_input = "\uff25\uff25\uff25"  # Fullwidth E's
        structured_logger.info("test_event", user_value=user_input)

        event = self._parse_last_event(log_buffer)
        # JSON serializes \uff25 as the escaped string; compare dict values.
        assert event.get("user_value") == user_input

    def test_user_controlled_keys_with_format_chars(
        self, structured_logger, log_buffer
    ):
        """Keys that look like format strings don't cause KeyError or crashes."""
        structured_logger.info(
            "test_event",
            **{
                "user_%s_input": "value1",
                "session_%d_id": "value2",
            },
        )
        event = self._parse_last_event(log_buffer)
        assert event.get("event") == "test_event"
