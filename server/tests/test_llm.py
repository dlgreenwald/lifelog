"""Unit tests for lifelog.pipeline.llm — LLM summarisation and split detection.

Tests _format_transcript (pure) and early-return guards.
API call paths are covered by the existing integration-style mock tests in test_pipeline.py.
"""


class TestFormatTranscript:
    """Test the _format_transcript pure formatting function."""

    def test_empty_list(self):
        from lifelog.pipeline.llm import _format_transcript

        assert _format_transcript([]) == ""

    def test_single_segment_with_timestamp(self):
        from lifelog.pipeline.llm import _format_transcript

        segments = [{"name": "Alice", "text": "Hello world", "start": 1.5}]
        result = _format_transcript(segments)
        assert "[1.5s] Alice: Hello world" in result

    def test_single_segment_without_start_key(self):
        from lifelog.pipeline.llm import _format_transcript

        segments = [{"name": "Alice", "text": "Hello world"}]
        result = _format_transcript(segments)
        assert "Alice: Hello world" in result

    def test_multiple_segments(self):
        from lifelog.pipeline.llm import _format_transcript

        segments = [
            {"name": "Alice", "text": "Hello", "start": 0.0},
            {"name": "Bob", "text": "Hi there", "start": 2.5},
        ]
        result = _format_transcript(segments)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "[0.0s] Alice: Hello" in result
        assert "[2.5s] Bob: Hi there" in result


class TestDetectSplitsEmpty:
    """Test detect_splits early-return guard (empty segments)."""

    def test_empty_segments_returns_empty_list(self):
        from lifelog.pipeline.llm import detect_splits

        result = detect_splits([])
        assert result == {"topic_splits": []}

    def test_none_segments_returns_empty_list(self):
        from lifelog.pipeline.llm import detect_splits

        result = detect_splits(None)  # type: ignore
        assert result == {"topic_splits": []}


class TestSummarizePartitionEmpty:
    """Test summarize_partition early-return guard (empty segments)."""

    def test_empty_segments_returns_safe_defaults(self):
        from lifelog.pipeline.llm import summarize_partition

        result = summarize_partition([])
        assert result["category"] == "not_meaningful"
        assert result["title"] == ""
        assert result["summary"] == ""
        assert result["long_summary"] == ""
        assert result["decisions"] == []
        assert result["todos"] == []

    def test_none_segments_returns_safe_defaults(self):
        from lifelog.pipeline.llm import summarize_partition

        result = summarize_partition(None)  # type: ignore
        assert result["category"] == "not_meaningful"
        assert result["decisions"] == []
        assert result["todos"] == []

    def test_empty_segments_does_not_call_llm(self):
        """Empty input should return defaults without any API call."""
        from unittest.mock import patch

        from lifelog.pipeline import llm

        with patch.object(llm, "client") as mock_client:
            result = llm.summarize_partition([])
            mock_client.chat.completions.create.assert_not_called()

        assert result["category"] == "not_meaningful"
