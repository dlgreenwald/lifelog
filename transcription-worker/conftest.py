"""Session-wide test guards for the transcription worker.

``main.ModelManager._check_idle`` can call ``os._exit`` (the idle process
restart path). If a test reaches that call unmocked, pytest dies with
exit code 0 — no summary, no failure, green CI with a truncated run
(this actually happened: the suite silently ran only a third of its
tests). The autouse fixture below turns any real ``os._exit`` into a
loud AssertionError instead. Tests that explicitly exercise the exit
path patch ``os._exit`` themselves and are unaffected.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _forbid_os_exit(monkeypatch):
    def _explode(code):
        raise AssertionError(
            f"os._exit({code}) reached test code — an unmocked idle-restart "
            "path killed the suite silently before; failing loudly instead"
        )

    monkeypatch.setattr(os, "_exit", _explode)
