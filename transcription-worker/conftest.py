"""Session-wide test guards for the transcription worker.

``main.ModelManager._check_idle`` can call ``os._exit`` (the idle process
restart path). If a test reaches that call unmocked, pytest dies with
exit code 0 — no summary, no failure, green CI with a truncated run
(this actually happened: the suite silently ran only a third of its
tests). The autouse fixture below turns any real ``os._exit`` into a
loud AssertionError instead. Tests that explicitly exercise the exit
path patch ``os._exit`` themselves and are unaffected.

The ``_fake_ffmpeg`` fixture mocks ``subprocess.run`` so that tests can
call ``_extract_segment_opus`` (and by extension ``transcribe_audio``)
without needing ``ffmpeg`` in the venv.
"""

import os
import tempfile
from contextlib import contextmanager

import pytest


@pytest.fixture(autouse=True)
def _forbid_os_exit(monkeypatch):
    def _explode(code):
        raise AssertionError(
            f"os._exit({code}) reached test code — an unmocked idle-restart "
            "path killed the suite silently before; failing loudly instead"
        )

    monkeypatch.setattr(os, "_exit", _explode)


@pytest.fixture(autouse=True)
def _fake_ffmpeg(monkeypatch):
    """Mock ffmpeg subprocess calls so tests work without ffmpeg in the venv."""
    import subprocess

    fake_opus = b"OggS" + b"\x00" * 16

    @contextmanager
    def fake_tempdir(*, prefix):
        yield tempfile.gettempdir()

    def fake_run(cmd, *, capture_output, timeout, check):
        _ = next((a for a in cmd if a.endswith(".wav")), None)
        opus_path = next((a for a in cmd if a.endswith(".opus")), None)
        if opus_path:
            with open(opus_path, "wb") as f:
                f.write(fake_opus)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", fake_tempdir)
