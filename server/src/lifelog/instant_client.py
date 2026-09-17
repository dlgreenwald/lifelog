"""Server-side WebSocket client for instant transcription via transcription-worker."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import websockets

logger = logging.getLogger("instant_client")

# {session_id: _SessionHandle}
_sessions: dict[int, _SessionHandle] = {}
_lock = asyncio.Lock()

# Sessions that fell back to quick jobs (per-session, not per-utterance)
_session_uses_fallback: set[int] = set()


@dataclass
class _SessionHandle:
    session_id: int
    ws: Any  # websockets client protocol
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


def uses_fallback(session_id: int) -> bool:
    """Return True if this session has fallen back to quick jobs."""
    return session_id in _session_uses_fallback


def mark_fallback(session_id: int) -> None:
    """Mark a session as having fallen back to quick jobs."""
    _session_uses_fallback.add(session_id)


async def open_session(session_id: int) -> _SessionHandle:
    """Open a WebSocket to the transcription-worker for this session."""
    if session_id in _session_uses_fallback:
        raise ConnectionError(f"session {session_id} is in fallback mode")

    async with _lock:
        if session_id in _sessions:
            logger.debug(
                "instant_client_reusing_session", extra={"session_id": session_id}
            )
            return _sessions[session_id]

    url = f"ws://transcription-worker:9000/ws/instant/{session_id}"
    logger.info("instant_ws_connecting", extra={"session_id": session_id, "url": url})
    ws = await websockets.connect(url, open_timeout=10, close_timeout=5)
    logger.info("instant_ws_connected", extra={"session_id": session_id})
    handle = _SessionHandle(session_id=session_id, ws=ws)

    async def reader(ws, queue: asyncio.Queue) -> None:
        async for msg in ws:
            print(
                f"[DEBUG instant_client reader] session={session_id} received msg type={type(msg).__name__} repr={repr(msg)[:200]}",
                flush=True,
            )
            if isinstance(msg, str):
                data = json.loads(msg)
            else:
                data = msg  # already a dict if websockets auto-decodes JSON text frames
            print(
                f"[DEBUG instant_client reader] session={session_id} parsed data={repr(data)[:200]}",
                flush=True,
            )
            logger.debug(
                "instant_ws_received_event",
                extra={"session_id": session_id, "event": data},
            )
            await queue.put(data)

    handle.task = asyncio.create_task(reader(ws, handle.queue))
    async with _lock:
        _sessions[session_id] = handle
    return handle


async def feed_audio(session_id: int, audio_opus: bytes) -> None:
    """Feed a compressed Opus audio chunk to the session's transcription stream.

    If the connection is dead (transcription-worker restarted or model crashed),
    close the dead handle and reopen the session before retrying.
    """
    try:
        async with _lock:
            if session_id not in _sessions:
                raise KeyError(f"No active instant session for session_id={session_id}")
        handle = _sessions[session_id]
        logger.info(
            "instant_ws_sending_audio",
            extra={"session_id": session_id, "size_bytes": len(audio_opus)},
        )
        await handle.ws.send(audio_opus)
        logger.info("instant_ws_audio_sent", extra={"session_id": session_id})
    except websockets.ConnectionClosedError:
        # Connection died (transcription-worker restarted or model crashed).
        # Close the dead socket, remove the handle, and reopen.
        old_handle = None
        async with _lock:
            old_handle = _sessions.pop(session_id, None)
        if old_handle is not None:
            try:
                await old_handle.ws.close()
            except websockets.ConnectionClosed:
                pass  # already closed — benign
            if old_handle.task:
                old_handle.task.cancel()
        # Retry once with a fresh connection
        handle = await open_session(session_id)
        await handle.ws.send(audio_opus)


async def get_transcript_events(session_id: int, timeout: float = 15.0) -> list[dict]:
    """Wait for transcript events to arrive, up to `timeout` seconds total."""
    events = []
    async with _lock:
        if session_id not in _sessions:
            logger.warning(
                "instant_events_session_gone", extra={"session_id": session_id}
            )
            return events
    handle = _sessions[session_id]
    logger.info(
        "instant_events_waiting", extra={"session_id": session_id, "timeout": timeout}
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            logger.info(
                "instant_events_timeout",
                extra={"session_id": session_id, "event_count": len(events)},
            )
            break
        try:
            event = await asyncio.wait_for(
                handle.queue.get(), timeout=min(remaining, 2.0)
            )
            events.append(event)
            logger.info(
                "instant_events_received",
                extra={"session_id": session_id, "event_count": len(events)},
            )
        except TimeoutError:
            logger.info(
                "instant_events_drain_done",
                extra={"session_id": session_id, "event_count": len(events)},
            )
            break
    return events


async def close_session(session_id: int) -> None:
    """Close the WebSocket and clean up the session."""
    async with _lock:
        if session_id not in _sessions:
            return
        handle = _sessions.pop(session_id)
    if handle.task:
        handle.task.cancel()
    try:
        await handle.ws.close()
    except websockets.ConnectionClosed:
        pass  # already closed — benign
