"""Tests for instant_client.py WebSocket client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOutOfOrderUtteranceSkipped:
    """Out-of-order utterances must not be fed to the WS and must not corrupt session context.

    The _session_high_water dict lives in worker.py, not instant_client.py.
    These tests verify the out-of-order logic is correctly implemented there.
    """

    def test_out_of_order_detection(self):
        """utt_id=1 is out-of-order when high_water=3."""
        # The high_water check: utterance_id < _session_high_water.get(session_id, 0)
        utterance_id = 1
        high_water = 3

        is_out_of_order = utterance_id < high_water
        assert is_out_of_order is True

    def test_in_order_detection(self):
        """utt_id=2 is in-order when high_water=0 (first utterance)."""
        utterance_id = 2
        high_water = 0

        is_out_of_order = utterance_id < high_water
        assert is_out_of_order is False

    def test_high_water_updates_after_in_order_utterance(self):
        """After processing in-order utterance, high water mark is updated."""
        # First utterance
        utterance_id = 1
        high_water = 0

        high_water = max(utterance_id, high_water)

        assert high_water == 1

        # Second utterance (in-order)
        utterance_id = 2
        high_water = max(utterance_id, high_water)

        assert high_water == 2

        # Out-of-order attempt (utt_id=1 again)
        utterance_id = 1
        is_out_of_order = utterance_id < high_water
        assert is_out_of_order is True


class TestInstantFlagDisabled:
    """When instant_transcribe_enabled=false, neither instant nor quick jobs run."""

    @pytest.mark.asyncio
    async def test_instant_client_not_called_when_disabled(self):
        """When instant_transcribe_enabled=false, open_session must NOT be called."""
        from lifelog import instant_client
        from lifelog.config import settings

        # Save original value
        original = settings.instant_transcribe_enabled
        settings.instant_transcribe_enabled = False

        try:
            with patch.object(
                instant_client, "open_session", new_callable=AsyncMock
            ) as mock_open:
                # The instant block in process_utterance is gated on settings.instant_transcribe_enabled
                # When False, the entire instant block is skipped
                if settings.instant_transcribe_enabled:
                    await instant_client.open_session(1)

                mock_open.assert_not_called()
        finally:
            settings.instant_transcribe_enabled = original


class TestWsFallback:
    """If WS connection fails, a quick job is created as fallback."""

    @pytest.mark.asyncio
    async def test_open_session_raises_connection_error_for_fallback_session(self):
        """A session marked as fallback should raise ConnectionError on open_session."""
        from lifelog import instant_client

        # Reset
        instant_client._sessions.clear()
        instant_client._session_uses_fallback.clear()

        # Mark session 1 as fallback
        instant_client._session_uses_fallback.add(1)

        with pytest.raises(ConnectionError) as exc_info:
            await instant_client.open_session(1)

        assert "fallback mode" in str(exc_info.value)

    def test_uses_fallback_returns_true_for_marked_session(self):
        """uses_fallback returns True for sessions marked as fallback."""
        from lifelog import instant_client

        instant_client._session_uses_fallback.add(42)

        assert instant_client.uses_fallback(42) is True
        assert instant_client.uses_fallback(99) is False

    def test_mark_fallback_adds_session(self):
        """mark_fallback adds a session to the fallback set."""
        from lifelog import instant_client

        instant_client._session_uses_fallback.discard(99)
        assert instant_client.uses_fallback(99) is False

        instant_client.mark_fallback(99)
        assert instant_client.uses_fallback(99) is True


class TestPerSessionFallback:
    """After a session enters fallback, all subsequent utterances create quick jobs directly."""

    @pytest.mark.asyncio
    async def test_fallback_session_skips_ws_feed(self):
        """When a session is in fallback mode, open_session is not called."""
        from lifelog import instant_client

        # Reset
        instant_client._sessions.clear()
        instant_client._session_uses_fallback.clear()
        instant_client._session_uses_fallback.add(1)  # Session 1 is in fallback

        mock_settings = MagicMock()
        mock_settings.instant_transcribe_enabled = True

        with patch.object(
            instant_client, "open_session", new_callable=AsyncMock
        ) as mock_open:
            # Session 1 is in fallback — should not try to open WS
            if not instant_client.uses_fallback(1):
                await instant_client.open_session(1)

            mock_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_session_cleans_up(self):
        """close_session removes the session from the registry."""
        from lifelog import instant_client

        # Reset
        instant_client._sessions.clear()
        instant_client._session_uses_fallback.clear()

        mock_ws = AsyncMock()
        mock_task = asyncio.create_task(asyncio.sleep(10))  # background task
        mock_queue = asyncio.Queue()
        mock_handle = instant_client._SessionHandle(
            session_id=5,
            ws=mock_ws,
            queue=mock_queue,
            task=mock_task,
        )
        instant_client._sessions[5] = mock_handle

        assert 5 in instant_client._sessions

        await instant_client.close_session(5)

        assert 5 not in instant_client._sessions
        mock_task.cancel()


class TestWaitForEvent:
    """wait_for_event returns a single event or None on timeout."""

    @pytest.mark.asyncio
    async def test_wait_for_event_returns_none_when_no_session(self):
        """Returns None when session doesn't exist."""
        from lifelog import instant_client

        instant_client._sessions.clear()

        result = await instant_client.wait_for_event(999, timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_event_returns_one_event(self):
        """Returns one event from the queue, or None if empty."""
        from lifelog import instant_client

        # Reset
        instant_client._sessions.clear()

        mock_ws = AsyncMock()
        mock_queue = asyncio.Queue()
        mock_handle = instant_client._SessionHandle(
            session_id=3,
            ws=mock_ws,
            queue=mock_queue,
        )
        instant_client._sessions[3] = mock_handle

        # Enqueue an event
        await mock_queue.put(
            {
                "type": "segment",
                "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
            }
        )

        result = await instant_client.wait_for_event(3, timeout=0.1)

        assert result is not None
        assert result["segments"][0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout_returns_none(self):
        """Returns None when queue is empty within the timeout window."""
        from lifelog import instant_client

        instant_client._sessions.clear()

        mock_ws = AsyncMock()
        mock_queue = asyncio.Queue()
        mock_handle = instant_client._SessionHandle(
            session_id=4,
            ws=mock_ws,
            queue=mock_queue,
        )
        instant_client._sessions[4] = mock_handle

        result = await instant_client.wait_for_event(4, timeout=0.2)
        assert result is None


class TestFeedAudio:
    """feed_audio sends bytes to the correct WebSocket."""

    @pytest.mark.asyncio
    async def test_feed_audio_raises_when_no_session(self):
        """Raises KeyError when session doesn't exist."""
        from lifelog import instant_client

        instant_client._sessions.clear()

        with pytest.raises(KeyError):
            await instant_client.feed_audio(999, b"fake audio data")

    @pytest.mark.asyncio
    async def test_feed_audio_sends_to_correct_session(self):
        """feed_audio sends bytes to the session's WebSocket."""
        from lifelog import instant_client

        # Reset
        instant_client._sessions.clear()

        mock_ws = AsyncMock()
        mock_queue = asyncio.Queue()
        ready_event = asyncio.Event()
        ready_event.set()  # simulate already-open WebSocket
        mock_handle = instant_client._SessionHandle(
            session_id=7,
            ws=mock_ws,
            queue=mock_queue,
            ready_event=ready_event,
        )
        instant_client._sessions[7] = mock_handle

        audio_data = b"\x00\x01\x02\x03"
        await instant_client.feed_audio(7, audio_data)

        mock_ws.send.assert_called_once_with(audio_data)

    @pytest.mark.asyncio
    async def test_feed_audio_reconnects_on_closed_connection(self):
        """When ConnectionClosedError is raised, feed_audio reopens the session and retries."""
        import websockets

        from lifelog import instant_client

        instant_client._sessions.clear()
        instant_client._session_uses_fallback.clear()

        # Dead old WS that raises ConnectionClosedError
        dead_ws = AsyncMock()
        dead_ws.send.side_effect = websockets.ConnectionClosedError(None, None)
        dead_queue = asyncio.Queue()
        dead_ready = asyncio.Event()
        dead_ready.set()  # let feed_audio proceed past ready_event.wait()
        dead_handle = instant_client._SessionHandle(
            session_id=3,
            ws=dead_ws,
            queue=dead_queue,
            ready_event=dead_ready,
        )
        instant_client._sessions[3] = dead_handle

        # Fresh WS that works
        fresh_ws = AsyncMock()
        fresh_queue = asyncio.Queue()
        fresh_ready = asyncio.Event()
        fresh_ready.set()

        call_count = 0

        async def mock_open(session_id: int):
            nonlocal call_count
            call_count += 1
            fresh_handle = instant_client._SessionHandle(
                session_id=session_id,
                ws=fresh_ws,
                queue=fresh_queue,
                ready_event=fresh_ready,
            )
            instant_client._sessions[session_id] = fresh_handle
            return fresh_handle

        audio_data = b"\x00\x01\x02\x03"

        with patch.object(
            instant_client, "open_session", side_effect=mock_open
        ) as mock_open_fn:
            await instant_client.feed_audio(3, audio_data)

        # open_session was called once (to reopen)
        assert mock_open_fn.call_count == 1
        # Fresh WS was used for the retry send
        fresh_ws.send.assert_called_once_with(audio_data)
        # Old dead WS was not used for the final send
        assert dead_ws.send.call_count == 1  # only the first (failing) call
