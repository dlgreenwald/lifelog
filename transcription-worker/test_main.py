import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_poll_reports_per_job_failure_and_continues():
    from main import poll_once

    claim = MagicMock(status_code=200)
    claim.json.return_value = {"job_id": 7, "job_type": "quick"}
    client = AsyncMock()
    client.post.side_effect = [claim, MagicMock(status_code=200)]
    with patch(
        "main._process_job",
        new_callable=AsyncMock,
        side_effect=RuntimeError("decode failed"),
    ):
        assert asyncio.run(poll_once(client))
    assert client.post.call_count == 2
    assert client.post.call_args_list[1].kwargs["json"] == {"error": "decode failed"}


# ---------- Idle-unload ModelManager tests ----------


@pytest.fixture
def fresh_model_manager(monkeypatch):
    """Reset model_manager singleton and patch pipeline.load_models /
    pipeline.unload_models for each test, mirroring how ModelManager
    reaches them via lazy imports inside its methods.
    """
    import main as main_mod
    import pipeline as pipeline_mod

    load_marker = MagicMock(
        name="load_models", return_value={"asr": "stub", "device": "cpu"}
    )
    unload_marker = MagicMock(name="unload_models")
    monkeypatch.setattr(pipeline_mod, "load_models", load_marker)
    monkeypatch.setattr(pipeline_mod, "unload_models", unload_marker)

    main_mod.model_manager._stop_event = main_mod.threading.Event()
    main_mod.model_manager._models = {}
    main_mod.model_manager._active_jobs = 0
    main_mod.model_manager._last_activity = time.time()
    return main_mod, load_marker, unload_marker


def test_model_manager_load_calls_pipeline_once(fresh_model_manager):
    main_mod, load_marker, _ = fresh_model_manager

    first = main_mod.model_manager.load()
    second = main_mod.model_manager.load()
    assert first == {"asr": "stub", "device": "cpu"}
    assert second == first
    assert load_marker.call_count == 1


def test_model_manager_record_activity_updates_last_activity(fresh_model_manager):
    main_mod, _, _ = fresh_model_manager

    main_mod.model_manager._last_activity = 0.0
    main_mod.model_manager.record_activity()
    assert main_mod.model_manager._last_activity > 0
    assert main_mod.model_manager._last_activity <= time.time()


def test_check_idle_does_not_unload_with_active_jobs(fresh_model_manager):
    main_mod, _, unload_marker = fresh_model_manager

    main_mod.model_manager.load()
    main_mod.model_manager._last_activity = time.time() - 10000  # ancient
    main_mod.model_manager._active_jobs = 1
    main_mod.model_manager._check_idle()
    assert unload_marker.call_count == 0
    assert main_mod.model_manager._models != {}


def test_check_idle_unloads_after_timeout_plus_warmup(fresh_model_manager, monkeypatch):
    main_mod, _, unload_marker = fresh_model_manager

    main_mod.model_manager.load()
    main_mod.model_manager._active_jobs = 0
    main_mod.model_manager._last_activity = time.time() - 10000
    monkeypatch.setattr(main_mod.settings, "idle_unload_seconds", 5)
    monkeypatch.setattr(main_mod.settings, "warm_keepalive_seconds", 1)
    main_mod.model_manager._check_idle()
    assert unload_marker.call_count == 1


def test_health_response_shape(fresh_model_manager):
    main_mod, _, _ = fresh_model_manager

    main_mod.model_manager.load()
    response = asyncio.run(main_mod.health())
    assert response["status"] == "ok"
    assert response["models_loaded"] is True
    assert "last_activity" in response
    assert isinstance(response["last_activity"], float)


def test_check_idle_unloads_without_process_restart_when_restart_disabled(
    fresh_model_manager, monkeypatch
):
    """When ``idle_process_restart_seconds`` is 0 (default), the
    watchdog must NOT call ``os._exit``. Long idleness is fine
    because the unload path already reclaimed what Python can
    free."""
    main_mod, _, _ = fresh_model_manager
    main_mod.model_manager.load()
    main_mod.model_manager._active_jobs = 0
    main_mod.model_manager._last_activity = time.time() - 10000
    monkeypatch.setattr(main_mod.settings, "idle_unload_seconds", 5)
    monkeypatch.setattr(main_mod.settings, "warm_keepalive_seconds", 1)
    monkeypatch.setattr(main_mod.settings, "idle_process_restart_seconds", 0)
    with patch("os._exit") as exit_marker:
        main_mod.model_manager._check_idle()
    exit_marker.assert_not_called()


def test_check_idle_exits_when_idle_exceeds_process_restart_threshold(
    fresh_model_manager, monkeypatch
):
    """When ``idle_process_restart_seconds`` is set AND idleness
    exceeds that threshold (so models have been unloaded first),
    the watchdog calls ``os._exit(0)`` so docker-compose's
    ``restart: unless-stopped`` policy resurrects the container
    and reclaims GPU memory that the in-process unload cannot
    (CTranslate2 / pyannote pinned device buffers)."""
    main_mod, _, _ = fresh_model_manager
    main_mod.model_manager.load()
    main_mod.model_manager._active_jobs = 0
    main_mod.model_manager._last_activity = time.time() - 2000
    monkeypatch.setattr(main_mod.settings, "idle_unload_seconds", 5)
    monkeypatch.setattr(main_mod.settings, "warm_keepalive_seconds", 1)
    monkeypatch.setattr(main_mod.settings, "idle_process_restart_seconds", 10)
    with patch("os._exit") as exit_marker:
        main_mod.model_manager._check_idle()
    exit_marker.assert_called_once_with(0)


def test_check_idle_does_not_exit_before_unload_threshold(
    fresh_model_manager, monkeypatch
):
    """When idleness has crossed ``idle_process_restart_seconds``
    but NOT yet been observed by a watchdog tick (because the
    watchdog polls every 30 s and idle started recently), the
    restart MUST NOT fire prematurely: the unload-stage threshold
    is the gate, not the value of ``idle_process_restart_seconds``
    by itself. ``idle_process_restart_seconds`` must always be
    greater than ``idle_unload_seconds + warm_keepalive_seconds``
    so the in-process unload runs first."""
    main_mod, _, _ = fresh_model_manager
    main_mod.model_manager.load()
    main_mod.model_manager._active_jobs = 0
    # Idle for 10s only: restart_threshold=20s, so threshold 5+1=6
    # already passed (unload fires), but restart_threshold not yet
    # crossed.
    main_mod.model_manager._last_activity = time.time() - 10
    monkeypatch.setattr(main_mod.settings, "idle_unload_seconds", 5)
    monkeypatch.setattr(main_mod.settings, "warm_keepalive_seconds", 1)
    monkeypatch.setattr(main_mod.settings, "idle_process_restart_seconds", 20)
    with patch("os._exit") as exit_marker:
        main_mod.model_manager._check_idle()
    exit_marker.assert_not_called()
