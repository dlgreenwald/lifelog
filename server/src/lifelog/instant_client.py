"""Server-side WebSocket client for instant transcription via transcription-worker.

Design: one persistent WebSocket per session. The session handle owns a single
reader task that drains the WebSocket and puts events onto a queue.
feed_audio() sends Opus bytes and returns immediately (does NOT wait for a
transcript result).  The caller is responsible for consuming events from the
queue separately.

The WebSocket is kept open for the lifetime of the session.  When the session
closes (gap timeout or explicit end), close_session() cancels the reader task
and tears down the socket.
"""

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
    # Fires once the WebSocket connection is fully open.
    # feed_audio() waits on this before sending.
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)


def uses_fallback(session_id: int) -> bool:
    """Return True if this session has fallen back to quick jobs."""
    return session_id in _session_uses_fallback


def mark_fallback(session_id: int) -> None:
    """Mark a session as having fallen back to quick jobs."""
    _session_uses_fallback.add(session_id)


async def open_session(session_id: int) -> _SessionHandle:
    """Open a WebSocket to the transcription-worker for this session.

    If a handle already exists for this session the existing handle is returned
    (the WebSocket is reused, not reopened).
    """
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

    async def reader(ws: Any, queue: asyncio.Queue, ready_event: asyncio.Event) -> None:
        # Signal that the WebSocket is open and we can start receiving.
        ready_event.set()
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    data = json.loads(msg)
                else:
                    data = msg  # already a dict if websockets auto-decodes JSON text frames
                logger.debug(
                    "instant_ws_received_event",
                    extra={"session_id": session_id, "event": data},
                )
                await queue.put(data)
        except websockets.ConnectionClosed:
            logger.info("instant_ws_closed", extra={"session_id": session_id})
        except asyncio.CancelledError:
            logger.info("instant_ws_cancelled", extra={"session_id": session_id})
            raise

    handle.task = asyncio.create_task(reader(ws, handle.queue, handle.ready_event))
    async with _lock:
        _sessions[session_id] = handle
    return handle


async def feed_audio(session_id: int, audio_opus: bytes) -> None:
    """Feed a compressed Opus audio chunk to the session's WebSocket.

    Waits for the WebSocket to be ready (open) before sending.  Does NOT wait
    for a transcript result — the caller consumes events from the session's
    queue independently.

    If the connection is dead (transcription-worker restarted or model crash),
    the old handle is removed and a fresh session is opened before retrying.
    """
    async with _lock:
        if session_id not in _sessions:
            raise KeyError(f"No active instant session for session_id={session_id}")
        handle = _sessions[session_id]

    # Wait for the reader to confirm the socket is open (avoids sending before
    # the connection has been accepted by the server).
    await handle.ready_event.wait()

    logger.info(
        "instant_ws_sending_audio",
        extra={"session_id": session_id, "size_bytes": len(audio_opus)},
    )
    try:
        await handle.ws.send(audio_opus)
        logger.info("instant_ws_audio_sent", extra={"session_id": session_id})
    except websockets.ConnectionClosedError:
        logger.warning(
            "instant_ws_connection_died",
            extra={"session_id": session_id},
        )
        # Remove the dead handle and reopen.
        old_handle = None
        async with _lock:
            old_handle = _sessions.pop(session_id, None)
        if old_handle is not None and old_handle.task:
            old_handle.task.cancel()
            try:
                await old_handle.task
            except asyncio.CancelledError:
                pass
        # Open a new session and wait for it to be ready.
        new_handle = await open_session(session_id)
        await new_handle.ready_event.wait()
        await new_handle.ws.send(audio_opus)
        logger.info(
            "instant_ws_reconnected_and_sent",
            extra={"session_id": session_id},
        )


async def wait_for_event(session_id: int, timeout: float = 2.0) -> dict | None:
    """Wait up to `timeout` for a single transcript event on the session's queue.

    Returns the event dict, or None if the queue was empty after `timeout`.
    This is a lightweight poll used by the session worker to drain events as they
    arrive while feeding audio continuously.
    """
    async with _lock:
        if session_id not in _sessions:
            return None
        handle = _sessions[session_id]

    try:
        return await asyncio.wait_for(handle.queue.get(), timeout=timeout)
    except TimeoutError:
        return None


async def close_session(session_id: int) -> None:
    """Close the WebSocket and cancel the reader task for this session."""
    async with _lock:
        if session_id not in _sessions:
            return
        handle = _sessions.pop(session_id)

    if handle.task:
        handle.task.cancel()
        try:
            await handle.task
        except asyncio.CancelledError:
            pass

    try:
        await handle.ws.close()
    except websockets.ConnectionClosed:
        pass  # already closed — benign

    logger.info("instant_session_closed", extra={"session_id": session_id})
