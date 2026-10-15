"""Tests for lifelog_mcp tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from lifelog_mcp.tools.decisions import build_tool as build_decisions_tool
from lifelog_mcp.tools.decisions import call as decisions_call
from lifelog_mcp.tools.recordings import build_tools
from lifelog_mcp.tools.recordings import call as recordings_call
from lifelog_mcp.tools.search import build_tool
from lifelog_mcp.tools.search import call as search_call
from lifelog_mcp.tools.speakers import build_tool as build_speakers_tool
from lifelog_mcp.tools.speakers import call as speakers_call
from lifelog_mcp.tools.todos import build_tool as build_todos_tool
from lifelog_mcp.tools.todos import call as todos_call


class TestSearchTool:
    """Tests for search_recordings tool."""

    def test_tool_schema_has_required_fields(self):
        tool = build_tool()
        assert tool.name == "search_recordings"
        assert "query" in tool.input_schema["required"]
        assert tool.input_schema["properties"]["query"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_search_returns_text_content(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "hits": [
                {
                    "id": 1,
                    "kind": "transcript",
                    "title": "Meeting with Alex",
                    "date": "2024-01-15",
                    "speakers": ["Alex"],
                    "_formatted": {"transcript": "We discussed <em>project</em> timeline"},
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.search.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await search_call(
                token="validtoken",
                query="alex",
                start_date=None,
                end_date=None,
                speaker=None,
                kind=None,
                limit=20,
            )

        assert isinstance(result, TextContent)
        assert "alex" in result.text.lower()
        assert "Meeting with Alex" in result.text


class TestRecordingsTools:
    """Tests for get_recordings_by_date and get_recording_detail tools."""

    def test_tools_defined(self):
        tools = build_tools()
        names = [t.name for t in tools]
        assert "get_recordings_by_date" in names
        assert "get_recording_detail" in names

    @pytest.mark.asyncio
    async def test_get_recordings_by_date_returns_recordings(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "recordings": [
                {
                    "id": 1,
                    "timestamp": "2024-01-15T10:00:00Z",
                    "duration_s": 120.0,
                    "category": "meeting",
                    "speakers": ["Alex", "Sam"],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.recordings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await recordings_call(
                tool_name="get_recordings_by_date",
                token="validtoken",
                date="2024-01-15",
            )

        assert isinstance(result, TextContent)
        assert "2024-01-15" in result.text
        assert "Alex" in result.text

    @pytest.mark.asyncio
    async def test_get_recording_detail_returns_full_detail(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "id": 1,
            "timestamp": "2024-01-15T10:00:00Z",
            "duration_s": 120.0,
            "category": "meeting",
            "speakers": ["Alex"],
            "summary": "Discussed project timeline",
            "transcript": {
                "segments": [
                    {"speaker": "Alex", "text": "Let's start with the timeline."}
                ]
            },
            "todos": [{"id": 1, "task": "Review document", "completed_at": None}],
            "decisions": [{"id": 1, "decision": "Ship by March 1", "made_by": "Alex"}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.recordings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await recordings_call(
                tool_name="get_recording_detail",
                token="validtoken",
                recording_id=1,
            )

        assert isinstance(result, TextContent)
        assert "Discussed project timeline" in result.text
        assert "timeline" in result.text
        assert "Review document" in result.text


class TestTodosTool:
    """Tests for get_todos tool."""

    def test_tool_schema(self):
        tool = build_todos_tool()
        assert tool.name == "get_todos"
        assert "properties" in tool.input_schema

    @pytest.mark.asyncio
    async def test_get_todos_returns_todos(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "todos": [
                {"id": 1, "task": "Review PR", "completed_at": None, "created_at": "2024-01-15"},
                {"id": 2, "task": "Send email", "completed_at": "2024-01-16", "created_at": "2024-01-15"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.todos.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await todos_call(token="validtoken", date=None, status=None, limit=50)

        assert isinstance(result, TextContent)
        assert "Review PR" in result.text
        assert "pending" in result.text
        assert "completed" in result.text


class TestDecisionsTool:
    """Tests for get_decisions tool."""

    def test_tool_schema(self):
        tool = build_decisions_tool()
        assert tool.name == "get_decisions"

    @pytest.mark.asyncio
    async def test_get_decisions_returns_decisions(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "decisions": [
                {
                    "id": 1,
                    "decision": "Ship by March 1",
                    "made_by": "Alex",
                    "created_at": "2024-01-15T10:00:00Z",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.decisions.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await decisions_call(token="validtoken", date=None, limit=50)

        assert isinstance(result, TextContent)
        assert "Ship by March 1" in result.text


class TestSpeakersTool:
    """Tests for get_speakers tool."""

    def test_tool_schema(self):
        tool = build_speakers_tool()
        assert tool.name == "get_speakers"

    @pytest.mark.asyncio
    async def test_get_speakers_returns_speakers(self):
        mock_response = MagicMock()
        mock_response.json = lambda: {
            "speakers": [
                {"id": 1, "name": "Alex", "recording_count": 10, "voiceprint_count": 5},
                {"id": 2, "name": "Sam", "recording_count": 3, "voiceprint_count": 2},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lifelog_mcp.tools.speakers.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await speakers_call(token="validtoken", recording_id=None)

        assert isinstance(result, TextContent)
        assert "Alex" in result.text
        assert "Sam" in result.text
        assert "recordings=10" in result.text
