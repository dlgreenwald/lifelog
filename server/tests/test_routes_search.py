"""Unit tests for lifelog.routes.search — pure functions and route helpers."""

from lifelog.routes.search import (
    _consolidate_by_conversation,
    _count_matches,
    _merge_matches,
)

# ── _count_matches ──────────────────────────────────────────────────────────────


class TestCountMatches:
    def test_none_returns_zero(self):
        assert _count_matches(None) == 0

    def test_empty_dict_returns_zero(self):
        assert _count_matches({}) == 0

    def test_single_field(self):
        result = _count_matches({"text": [{"start": 0, "length": 5}]})
        assert result == 1

    def test_multiple_fields_sums_lengths(self):
        result = _count_matches(
            {
                "text": [{"start": 0, "length": 5}, {"start": 10, "length": 3}],
                "summary": [{"start": 0, "length": 2}],
            }
        )
        assert result == 3  # 2 + 1

    def test_empty_positions_list(self):
        result = _count_matches({"text": []})
        assert result == 0


# ── _merge_matches ──────────────────────────────────────────────────────────────


class TestMergeMatches:
    def test_empty_list_returns_empty(self):
        assert _merge_matches([]) == {}

    def test_single_item(self):
        item = {"text": [{"start": 0, "length": 5}]}
        result = _merge_matches([item])
        assert result == {"text": [{"start": 0, "length": 5}]}

    def test_multiple_items_same_field_deduplicated(self):
        # Two hits with same field, some overlapping positions
        items = [
            {"text": [{"start": 0, "length": 5}, {"start": 10, "length": 3}]},
            {"text": [{"start": 0, "length": 5}, {"start": 20, "length": 2}]},
        ]
        result = _merge_matches(items)
        # (0, 5) appears twice — kept once; (10, 3) and (20, 2) are unique
        text_positions = result["text"]
        starts = [(p["start"], p["length"]) for p in text_positions]
        assert (0, 5) in starts
        assert (10, 3) in starts
        assert (20, 2) in starts
        assert len(text_positions) == 3

    def test_different_fields_all_preserved(self):
        items = [
            {"text": [{"start": 0, "length": 5}]},
            {"summary": [{"start": 0, "length": 3}]},
        ]
        result = _merge_matches(items)
        assert "text" in result
        assert "summary" in result
        assert len(result) == 2


# ── _consolidate_by_conversation ───────────────────────────────────────────────


class TestConsolidateByConversation:
    def test_empty_list_returns_empty(self):
        assert _consolidate_by_conversation([]) == []

    def test_hit_without_conversation_id_filtered(self):
        hits = [{"id": 1, "text": "hello"}]  # no conversation_id
        result = _consolidate_by_conversation(hits)
        assert result == []

    def test_single_hit_gets_total_matches(self):
        hits = [
            {
                "id": "u1_c1_transcript",
                "conversation_id": 1,
                "text": "hello world",
                "_matchesPosition": {"text": [{"start": 0, "length": 5}]},
                "_formatted": {"text": "hello world"},
            }
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 1
        assert result[0]["_totalMatches"] == 1
        assert result[0]["conversation_id"] == 1

    def test_multiple_hits_same_conversation_merged(self):
        hits = [
            {
                "id": "u1_c1_transcript",
                "conversation_id": 1,
                "text": "hello world",
                "kind": "transcript",
                "_matchesPosition": {"text": [{"start": 0, "length": 5}]},
                "_formatted": {"text": "hello world"},
            },
            {
                "id": "u1_c1_summary",
                "conversation_id": 1,
                "text": "summary text",
                "kind": "summary",
                "_matchesPosition": {"summary": [{"start": 0, "length": 3}]},
                "_formatted": {"summary": "summary text"},
            },
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 1
        # Primary = most matches (transcript with 1 match vs summary with 1 match — tie, max returns first)
        assert result[0]["_totalMatches"] == 2  # 1 + 1
        assert result[0]["_matchesPosition"]["text"] == [{"start": 0, "length": 5}]
        assert result[0]["_matchesPosition"]["summary"] == [{"start": 0, "length": 3}]

    def test_primary_hit_is_one_with_most_matches(self):
        hits = [
            {
                "id": "u1_c1_summary",
                "conversation_id": 1,
                "kind": "summary",
                "_matchesPosition": {"summary": [{"start": 0, "length": 1}]},
                "_formatted": {"summary": "sum"},
            },
            {
                "id": "u1_c1_transcript",
                "conversation_id": 1,
                "kind": "transcript",
                "_matchesPosition": {
                    "text": [{"start": 0, "length": 5}, {"start": 10, "length": 3}]
                },
                "_formatted": {"text": "transcript text"},
            },
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 1
        # Primary = transcript (2 matches > 1 match)
        assert result[0]["kind"] == "transcript"
        # _totalMatches = sum of ALL merged positions (transcript 2 + summary 1 = 3)
        assert result[0]["_totalMatches"] == 3

    def test_formatted_text_fallback_to_transcript_hit(self):
        # Primary hit has no _formatted.text but another hit does
        hits = [
            {
                "id": "u1_c1_summary",
                "conversation_id": 1,
                "kind": "summary",
                "_matchesPosition": {"summary": [{"start": 0, "length": 1}]},
                "_formatted": {"summary": "sum"},  # no text field
            },
            {
                "id": "u1_c1_transcript",
                "conversation_id": 1,
                "kind": "transcript",
                "_matchesPosition": {"text": [{"start": 0, "length": 5}]},
                "_formatted": {"text": "transcript text"},
            },
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 1
        # _formatted should include text from the transcript hit
        assert result[0]["_formatted"]["text"] == "transcript text"
        assert result[0]["_totalMatches"] == 2  # 1 + 1 from both hits

    def test_multiple_conversations_sorted_by_match_count(self):
        hits = [
            {
                "id": "u1_c1_transcript",
                "conversation_id": 1,
                "kind": "transcript",
                "_matchesPosition": {"text": [{"start": 0, "length": 1}]},  # 1 match
                "_formatted": {"text": "x"},
            },
            {
                "id": "u1_c2_transcript",
                "conversation_id": 2,
                "kind": "transcript",
                "_matchesPosition": {
                    "text": [{"start": 0, "length": 5}, {"start": 10, "length": 3}]
                },  # 2 matches
                "_formatted": {"text": "x"},
            },
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 2
        # Descending by _totalMatches: c2 (2 matches) first, c1 (1 match) second
        assert result[0]["conversation_id"] == 2
        assert result[1]["conversation_id"] == 1

    def test_null_conversation_id_in_hit_skipped(self):
        hits = [
            {"id": 1, "conversation_id": None},
            {"id": 2, "conversation_id": 1},
        ]
        result = _consolidate_by_conversation(hits)
        assert len(result) == 1
        assert result[0]["conversation_id"] == 1
