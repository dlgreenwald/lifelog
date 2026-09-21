"""Unit tests for lifelog.search — Meilisearch client.

Covers: constants, _build_filters, upsert_*, search, get_facets (with mocked client).
Smoke/integration tests against the live Meilisearch instance live in test_search_smoke.py.
"""

from unittest.mock import MagicMock, patch

# ── Constants ──────────────────────────────────────────────────────────────────


class TestConstants:
    def test_index_name_is_conversations(self):
        from lifelog.search import INDEX_NAME

        assert INDEX_NAME == "conversations"

    def test_kind_constants(self):
        from lifelog.search import (
            KIND_DECISION,
            KIND_SUMMARY,
            KIND_TODO,
            KIND_TRANSCRIPT,
        )

        assert KIND_TRANSCRIPT == "transcript"
        assert KIND_SUMMARY == "summary"
        assert KIND_DECISION == "decision"
        assert KIND_TODO == "todo"

    def test_filterable_attributes(self):
        from lifelog.search import FILTERABLE

        assert "kind" in FILTERABLE
        assert "user_id" in FILTERABLE
        assert "conversation_id" in FILTERABLE
        assert "date" in FILTERABLE

    def test_sortable_attributes(self):
        from lifelog.search import SORTABLE

        assert "date" in SORTABLE
        assert "conversation_id" in SORTABLE


# ── _build_filters ─────────────────────────────────────────────────────────────


class TestBuildFilters:
    """Test the _build_filters pure function."""

    def test_empty_args_returns_none(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants=None,
            user_id=None,
        )
        assert result is None

    def test_kind_only(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind="transcript",
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants=None,
            user_id=None,
        )
        assert result == 'kind = "transcript"'

    def test_kind_and_status(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind="todo",
            status="open",
            speaker=None,
            date_from=None,
            date_to=None,
            participants=None,
            user_id=None,
        )
        assert 'kind = "todo"' in result
        assert 'status = "open"' in result
        assert " AND " in result

    def test_speaker_filter(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker="Alice",
            date_from=None,
            date_to=None,
            participants=None,
            user_id=None,
        )
        assert result == 'speaker = "Alice"'

    def test_date_range(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from="2026-09-01",
            date_to="2026-09-30",
            participants=None,
            user_id=None,
        )
        assert "date >= '2026-09-01'" in result
        assert "date <= '2026-09-30'" in result
        assert " AND " in result

    def test_date_from_only(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from="2026-09-01",
            date_to=None,
            participants=None,
            user_id=None,
        )
        assert result == "date >= '2026-09-01'"

    def test_date_to_only(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to="2026-09-30",
            participants=None,
            user_id=None,
        )
        assert result == "date <= '2026-09-30'"

    def test_participants_single(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants="Alice",
            user_id=None,
        )
        assert result == 'participants = "Alice"'

    def test_participants_multiple(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants="Alice, Bob",
            user_id=None,
        )
        assert 'participants = "Alice"' in result
        assert 'participants = "Bob"' in result
        assert " AND " in result

    def test_participants_trims_whitespace(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants=" Alice , Bob ",
            user_id=None,
        )
        assert 'participants = "Alice"' in result
        assert 'participants = "Bob"' in result

    def test_participants_ignores_empty_parts(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants="Alice,,Bob",
            user_id=None,
        )
        assert 'participants = "Alice"' in result
        assert 'participants = "Bob"' in result
        # empty string not added
        assert '""' not in result

    def test_user_id_filter(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants=None,
            user_id=42,
        )
        assert result == "user_id = 42"

    def test_user_id_zero(self):
        from lifelog.search import _build_filters

        # user_id=0 is a valid filter (not None)
        result = _build_filters(
            kind=None,
            status=None,
            speaker=None,
            date_from=None,
            date_to=None,
            participants=None,
            user_id=0,
        )
        assert result == "user_id = 0"

    def test_all_filters_combined(self):
        from lifelog.search import _build_filters

        result = _build_filters(
            kind="transcript",
            status=None,
            speaker="Alice",
            date_from="2026-09-01",
            date_to="2026-09-30",
            participants="Alice, Bob",
            user_id=1,
        )
        parts = result.split(" AND ")
        # kind + speaker + date_from + date_to + participants(Alice) + participants(Bob) + user_id = 7
        assert len(parts) == 7
        assert 'kind = "transcript"' in result
        assert 'speaker = "Alice"' in result
        assert "date >= '2026-09-01'" in result
        assert "date <= '2026-09-30'" in result
        assert "user_id = 1" in result


# ── upsert_recording ───────────────────────────────────────────────────────────


class TestUpsertRecording:
    """Test upsert_recording builds and sends the correct document."""

    def test_empty_text_skips_indexing(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=42,
                full_text="   ",
                title="Test",
            )

        mock_index.add_documents.assert_not_called()

    def test_whitespace_only_text_skips_indexing(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=42,
                full_text=" \n\t ",
            )

        mock_index.add_documents.assert_not_called()

    def test_doc_structure(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=42,
                full_text="Hello world",
                title="My Recording",
                date="2026-09-20T10:00:00",
                participants=["Alice", "Bob"],
            )

        mock_index.add_documents.assert_called_once()
        docs = mock_index.add_documents.call_args[0][0]
        assert len(docs) == 1
        doc = docs[0]
        assert doc["id"] == "u1_c42_transcript"
        assert doc["user_id"] == 1
        assert doc["conversation_id"] == 42
        assert doc["text"] == "Hello world"
        assert doc["title"] == "My Recording"
        assert doc["speaker"] == ""
        assert doc["kind"] == "transcript"
        assert doc["date"] == "2026-09-20"
        assert doc["participants"] == ["Alice", "Bob"]
        assert doc["status"] == ""
        assert doc["topics"] == ""

    def test_date_strips_timezone(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=1,
                full_text="Test",
                date="2026-09-20T10:00:00+05:00",
            )

        docs = mock_index.add_documents.call_args[0][0]
        assert docs[0]["date"] == "2026-09-20"

    def test_empty_date_field(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=1,
                full_text="Test",
                date="",
            )

        docs = mock_index.add_documents.call_args[0][0]
        assert docs[0]["date"] == ""

    def test_empty_participants_defaults_to_empty_list(self):
        from lifelog.search import upsert_recording

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_recording(
                user_id=1,
                conversation_id=1,
                full_text="Test",
            )

        docs = mock_index.add_documents.call_args[0][0]
        assert docs[0]["participants"] == []


# ── upsert_summary ─────────────────────────────────────────────────────────────


class TestUpsertSummary:
    def test_doc_structure(self):
        from lifelog.search import upsert_summary

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_summary(
                user_id=1,
                conversation_id=42,
                text="This is a summary",
                participants=["Alice"],
                date="2026-09-20",
                title="Session Title",
                topics="gaming, strategy",
            )

        mock_index.add_documents.assert_called_once()
        docs = mock_index.add_documents.call_args[0][0]
        assert len(docs) == 1
        doc = docs[0]
        assert doc["id"] == "u1_c42_summary"
        assert doc["kind"] == "summary"
        assert doc["summary"] == "This is a summary"
        assert doc["topics"] == "gaming, strategy"
        assert doc["participants"] == ["Alice"]
        assert doc["date"] == "2026-09-20"


# ── upsert_decision ───────────────────────────────────────────────────────────


class TestUpsertDecision:
    def test_doc_structure(self):
        from lifelog.search import upsert_decision

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_decision(
                user_id=1,
                conversation_id=42,
                idx=3,
                text="We decided to go with Option A",
                title="Decision Title",
            )

        mock_index.add_documents.assert_called_once()
        docs = mock_index.add_documents.call_args[0][0]
        doc = docs[0]
        assert doc["id"] == "u1_c42_decision_3"
        assert doc["kind"] == "decision"
        assert doc["decision"] == "We decided to go with Option A"
        assert doc["date"] == ""
        assert doc["status"] == ""


# ── upsert_todo ───────────────────────────────────────────────────────────────


class TestUpsertTodo:
    def test_doc_structure_open(self):
        from lifelog.search import upsert_todo

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_todo(
                user_id=1,
                conversation_id=42,
                idx=2,
                text="Send the report",
                status="open",
                title="Todo Title",
            )

        docs = mock_index.add_documents.call_args[0][0]
        doc = docs[0]
        assert doc["id"] == "u1_c42_todo_2"
        assert doc["kind"] == "todo"
        assert doc["todo"] == "Send the report"
        assert doc["status"] == "open"

    def test_doc_structure_done(self):
        from lifelog.search import upsert_todo

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            upsert_todo(
                user_id=1,
                conversation_id=42,
                idx=0,
                text="Task completed",
                status="done",
            )

        docs = mock_index.add_documents.call_args[0][0]
        assert docs[0]["status"] == "done"


# ── delete_conversation ───────────────────────────────────────────────────────


class TestDeleteConversation:
    def test_deletes_with_filter(self):
        from lifelog.search import delete_conversation

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            delete_conversation(user_id=1, conversation_id=99)

        mock_index.delete_documents_by_filter.assert_called_once_with(
            "conversation_id = 99"
        )


# ── delete_document ───────────────────────────────────────────────────────────


class TestDeleteDocument:
    def test_deletes_by_id(self):
        from lifelog.search import delete_document

        mock_index = MagicMock()
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            delete_document("u1_c42_transcript")

        mock_index.delete_document.assert_called_once_with("u1_c42_transcript")


# ── search ────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_passes_filters_to_index_search(self):
        from lifelog.search import search

        mock_index = MagicMock()
        mock_index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with (
            patch("lifelog.search.get_client", return_value=mock_client),
            patch("lifelog.search._build_filters", return_value='kind = "transcript"'),
        ):
            search(
                q="hello",
                user_id=1,
                kind="transcript",
                status=None,
                speaker=None,
                date_from=None,
                date_to=None,
                participants=None,
                limit=10,
                offset=5,
            )

        mock_index.search.assert_called_once()
        # index.search(q, options_dict) → call_args[0] = (q, options_dict)
        call_kwargs = mock_index.search.call_args[0][1]
        assert call_kwargs["filter"] == 'kind = "transcript"'
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 5

    def test_passes_no_filter_when_none(self):
        from lifelog.search import search

        mock_index = MagicMock()
        mock_index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with (
            patch("lifelog.search.get_client", return_value=mock_client),
            patch("lifelog.search._build_filters", return_value=None),
        ):
            search(q="hello", user_id=None)

        call_kwargs = mock_index.search.call_args[0][1]
        assert call_kwargs["filter"] is None

    def test_returns_index_search_result(self):
        from lifelog.search import search

        mock_result = {
            "hits": [{"id": "u1_c42_transcript", "text": "Hello world"}],
            "estimatedTotalHits": 1,
            "processingTimeMs": 5,
        }
        mock_index = MagicMock()
        mock_index.search.return_value = mock_result
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            result = search(q="hello", user_id=1)

        assert result == mock_result

    def test_requests_highlight_attributes(self):
        from lifelog.search import search

        mock_index = MagicMock()
        mock_index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            search(q="hello", user_id=1)

        call_kwargs = mock_index.search.call_args[0][1]
        assert "text" in call_kwargs["attributesToHighlight"]
        assert "summary" in call_kwargs["attributesToHighlight"]
        assert call_kwargs["highlightPreTag"] == "[[hilite]]"
        assert call_kwargs["highlightPostTag"] == "[[/hilite]]"


# ── get_facets ────────────────────────────────────────────────────────────────


class TestGetFacets:
    def test_builds_facet_request(self):
        from lifelog.search import get_facets

        mock_result = {
            "facetDistribution": {
                "kind": {"transcript": 10, "summary": 5},
                "speaker": {"Alice": 8, "Bob": 7},
                "status": {"open": 3, "done": 2},
                "participants": {"Alice": 8, "Carol": 4},
            }
        }
        mock_index = MagicMock()
        mock_index.search.return_value = mock_result
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            get_facets(user_id=1)

        call_kwargs = mock_index.search.call_args[0][1]
        assert call_kwargs["facets"] == ["kind", "speaker", "status", "participants"]
        assert call_kwargs["limit"] == 0
        assert call_kwargs["filter"] == "user_id = 1"

    def test_flatten_nested_facet_dict(self):
        from lifelog.search import get_facets

        mock_result = {
            "facetDistribution": {
                "kind": {"transcript": 10, "summary": 5},
                "speaker": {"Alice": 8},
                "status": {},
                "participants": {},
            }
        }
        mock_index = MagicMock()
        mock_index.search.return_value = mock_result
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            result = get_facets(user_id=1)

        assert "transcript" in result["kinds"]
        assert "summary" in result["kinds"]
        assert "Alice" in result["speakers"]
        assert result["statuses"] == []
        assert result["participants"] == []

    def test_returns_empty_lists_when_no_facets(self):
        from lifelog.search import get_facets

        mock_result = {"facetDistribution": {}}
        mock_index = MagicMock()
        mock_index.search.return_value = mock_result
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            result = get_facets(user_id=1)

        assert result["kinds"] == []
        assert result["speakers"] == []
        assert result["statuses"] == []
        assert result["participants"] == []

    def test_no_user_id_filter(self):
        from lifelog.search import get_facets

        mock_result = {"facetDistribution": {}}
        mock_index = MagicMock()
        mock_index.search.return_value = mock_result
        mock_client = MagicMock()
        mock_client.index.return_value = mock_index

        with patch("lifelog.search.get_client", return_value=mock_client):
            get_facets(user_id=None)

        call_kwargs = mock_index.search.call_args[0][1]
        assert call_kwargs["filter"] is None
