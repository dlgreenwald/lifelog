import base64
import os
import pickle
import sys
import tempfile
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from pipeline import (
    _extract_segment_wav,
    _patch_huggingface_hub_use_auth_token,
    _register_omegaconf_safe_globals,
    group_into_speaker_segments,
    quick_transcribe,
    transcribe_audio,
    unload_models,
)


def test_group_merges_consecutive_speakers():
    result = group_into_speaker_segments(
        [
            {"speaker": "A", "start": 0, "end": 1, "text": " hello "},
            {"speaker": "A", "start": 1, "end": 2, "text": "world"},
            {"speaker": "B", "start": 2, "end": 3, "text": "bye"},
        ]
    )
    assert result[0] == {
        "speaker": "A",
        "start": 0.0,
        "end": 2.0,
        "text": "hello world",
        "segment_indices": [0, 1],
    }
    assert result[1]["speaker"] == "B"


def test_missing_speaker_defaults_unknown():
    assert (
        group_into_speaker_segments([{"start": 0, "end": 1, "text": "x"}])[0]["speaker"]
        == "Unknown"
    )


def test_wav_extraction_is_bounded():
    encoded = _extract_segment_wav(
        np.arange(10, dtype=np.float32), 10, [{"start": -1, "end": 0.5}], [0]
    )
    assert base64.b64decode(encoded).startswith(b"RIFF")


def test_quick_transcribe_only_calls_asr():
    asr = MagicMock()
    asr.transcribe.return_value = {"segments": [{"text": "hi"}]}
    result = quick_transcribe({"asr": asr}, np.zeros(10, dtype=np.float32), 16000)
    assert result == {
        "segments": [{"text": "hi"}],
        "full_transcript": {"segments": [{"text": "hi"}]},
    }
    asr.transcribe.assert_called_once()


def test_full_result_shape_and_audio():
    asr = MagicMock()
    asr.transcribe.return_value = {
        "segments": [{"speaker": "SPEAKER_00", "start": 0, "end": 0.01, "text": "hi"}],
        "language": "en",
    }
    diarize = MagicMock(return_value=MagicMock())
    fake_whisperx = MagicMock()
    fake_whisperx.assign_word_speakers.return_value = {
        "segments": asr.transcribe.return_value["segments"]
    }
    with patch.dict(sys.modules, {"whisperx": fake_whisperx}):
        result = transcribe_audio(
            {"asr": asr, "diarize": diarize, "device": "cpu"},
            np.ones(160, dtype=np.float32),
            16000,
        )
    assert set(result) == {
        "segments",
        "full_transcript",
        "speaker_map",
        "speaker_segments",
    }
    assert result["speaker_segments"][0]["speaker"] == "SPEAKER_00"
    assert "audio" in result["speaker_segments"][0]
    assert "segment_indices" not in result["speaker_segments"][0]


# ----------------------------------------------------------------------
# _register_omegaconf_safe_globals tests
#
# Strategy: replace torch.load with a counting sentinel BEFORE calling the
# helper. The helper captures the sentinel as `original_load` and wraps it.
# Subsequent `torch.load(...)` calls flow through the wrapper, which calls
# sentinel. Asserting sentinel.calls reveals whether the wrapper did
# pass-through, retry, or refusal correctly.
# ----------------------------------------------------------------------


class _CountingLoad:
    """Sentinel replacement for torch.load — records every call and lets
    tests script the response (raise / return)."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.return_value = "ok"
        self._scripted: list = []  # [(kind, payload), ...] in order

    def script(self, failures: int) -> "tuple[int, int]":
        """Configure the next N calls to fail with pickle.UnpicklingError."""
        plan = [("raise", None)] * failures + [("return", "ok")]
        self._scripted = plan
        return failures, len(plan)

    def __call__(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        if not self._scripted:
            return self.return_value
        kind, payload = self._scripted.pop(0)
        if kind == "raise":
            raise pickle.UnpicklingError("simulated unsafe global")
        return payload


def _reset_for_safe_load_test():
    """Reset wrapper state, populate sentinel + MODEL_CACHE_DIR for tests."""
    import torch

    base = tempfile.mkdtemp(prefix="lifelog_safe_load_")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    ckpt = os.path.join(cache, "fake.bin")
    open(ckpt, "wb").close()
    sentinel = _CountingLoad()
    torch.load = sentinel  # type: ignore[assignment]
    os.environ["MODEL_CACHE_DIR"] = cache
    return ckpt, sentinel


def test_register_omegaconf_safe_globals_wraps_torch_load():
    """Helper installs a torch.load wrapper that retries with
    weights_only=False when the file lives under MODEL_CACHE_DIR and the
    initial call raises pickle.UnpicklingError."""
    ckpt, sentinel = _reset_for_safe_load_test()
    sentinel.script(failures=1)

    _register_omegaconf_safe_globals()

    # Caller does NOT pass weights_only explicitly — torch 2.6+ defaults
    # it to True internally, but the wrapper sees no kwarg so the retry
    # path is allowed.
    result = torch.load(ckpt)

    assert result == "ok"
    assert len(sentinel.calls) == 2, (
        f"expected retry once, observed {len(sentinel.calls)} calls: {sentinel.calls}"
    )
    assert sentinel.calls[0][1].get("weights_only") is None
    assert sentinel.calls[1][1].get("weights_only") is False


def test_register_omegaconf_safe_globals_refuses_to_retry_outside_cache():
    """If pickle.UnpicklingError fires for a file outside MODEL_CACHE_DIR,
    the wrapper MUST propagate — retrying would silently downgrade
    weights_only for an untrusted source."""
    _reset_for_safe_load_test()
    # CodeQL py/insecure-temporary-file: use NamedTemporaryFile rather than
    # the deprecated `tempfile.mktemp` (predictable filename, race condition).
    _tf = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    _tf.close()
    outside = _tf.name
    sentinel = torch.load  # type: ignore[assignment]
    sentinel.script(failures=99)

    _register_omegaconf_safe_globals()
    with pytest.raises(pickle.UnpicklingError):
        torch.load(outside)

    # Only one call attempted — no retry.
    assert len(sentinel.calls) == 1
    assert sentinel.calls[0][0][0] == outside


def test_register_omegaconf_safe_globals_handles_file_like_candidate():
    """When lightning_fabric / fsspec opens a checkpoint as a file object
    (``torch.load(f, ...)``), the candidate is not a path string. The wrapper
    must still recover a path from ``.path`` / ``.name`` and apply the trust
    check so the retry kicks in for cache-local checkpoints."""
    ckpt, sentinel = _reset_for_safe_load_test()

    class FakeFileHandle:
        def __init__(self, path):
            self._path = path

        @property
        def name(self):
            return self._path

        def fileno(self):
            raise OSError("not a real fd for this test")

    sentinel.script(failures=1)
    _register_omegaconf_safe_globals()
    fh = FakeFileHandle(ckpt)
    result = torch.load(fh, map_location="cpu")

    assert result == "ok"
    assert len(sentinel.calls) == 2, (
        "expected wrap to retry when file-like exposes path under "
        f"MODEL_CACHE_DIR; got {len(sentinel.calls)} calls"
    )
    assert sentinel.calls[1][1].get("weights_only") is False


def test_register_omegaconf_safe_globals_is_idempotent():
    """Calling the helper twice must not stack wrappers — repeated calls
    must short-circuit on the wrap marker attribute."""
    _reset_for_safe_load_test()
    _register_omegaconf_safe_globals()
    first = torch.load
    _register_omegaconf_safe_globals()
    assert torch.load is first, "wrapper identity changed on re-entry"


def test_register_omegaconf_safe_globals_passes_through_uncached_exception():
    """Non-UnpicklingError exceptions (e.g. FileNotFoundError) must NOT
    trigger a retry — only pickle.UnpicklingError is the safe-no-op contract."""
    _reset_for_safe_load_test()

    class _RaisingSentinel(_CountingLoad):
        def __call__(self, *args, **kwargs):
            self.calls.append((args, dict(kwargs)))
            raise FileNotFoundError("not a cache-related failure")

    torch.load = _RaisingSentinel()  # type: ignore[assignment]
    _register_omegaconf_safe_globals()


def test_patch_huggingface_hub_use_auth_token_translates_token_kwarg():
    """pyannote.audio 3.x calls hf_hub_download with the legacy
    use_auth_token kwarg; huggingface_hub 1.0+ rejects that kwarg.
    Worker wraps hf_hub_download to translate use_auth_token -> token
    before delegating to the upstream implementation."""

    captured = {}

    class FakeOriginal:
        _lifelog_use_auth_token_bridge_wrapped = False

        def __call__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
            return "ok"

    fake_module = types.SimpleNamespace(hf_hub_download=FakeOriginal())
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        _patch_huggingface_hub_use_auth_token()
        # After install, hf_hub_download is the bridge.
        result = fake_module.hf_hub_download(
            "owner/repo",
            filename="model.bin",
            use_auth_token="abc",
        )

    assert result == "ok"
    # Legacy kwarg should be popped and translated to ``token``.
    assert "use_auth_token" not in captured["kwargs"]
    assert captured["kwargs"].get("token") == "abc"
    assert captured["kwargs"].get("filename") == "model.bin"


def test_patch_huggingface_hub_use_auth_token_is_idempotent():
    """Calling the bridge twice must not stack wrappers on top of each
    other — repeat calls short-circuit on the wrap marker attribute."""

    class FakeStable:
        _lifelog_use_auth_token_bridge_wrapped = False

        def __call__(self, *a, **kw):
            return "ok"

    sentinel = FakeStable()
    fake_module = types.SimpleNamespace(hf_hub_download=sentinel)
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        _patch_huggingface_hub_use_auth_token()
        first = fake_module.hf_hub_download
        _patch_huggingface_hub_use_auth_token()
        assert fake_module.hf_hub_download is first


class _FakeTensor:
    """Stand-in for a torch.Tensor whose ``.to(device)`` keeps memory pinned
    metaphorically. The unload path doesn't actually touch ``.to``; it just
    needs to drop references — but we still want a sentinel for asserting
    the dict no longer holds the object post-unload."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"_FakeTensor({self.name})"


def test_unload_models_drops_all_gpu_memory_holders():
    """``unload_models`` must release EVERY slab of GPU memory that
    ``load_models`` typically owns, including the ``_align_cache``
    populated in the worker when a job requests a language other than
    the default. Anything left behind keeps a CUDA tensor resident.
    """
    asr = _FakeTensor("asr")
    align_model = _FakeTensor("align_model")
    diarize = _FakeTensor("diarize")
    extra_align = _FakeTensor("extra-align-es")
    extra_meta = {"labels": []}
    models = {
        "asr": asr,
        "align_model": align_model,
        "metadata": extra_meta,
        "align_language": "en",
        "diarize": diarize,
        "device": "cuda",
        "compute_type": "float16",
        # ``align_cache`` (no underscore) is the key ``load_models``
        # returns — a plain dict used by callers; it does not itself
        # hold GPU memory but unload_models still drops it for
        # consistency with ``load_models`` returning an empty dict.
        "align_cache": {},
        # ``_align_cache`` is populated by ``_get_align_model`` when a
        # job comes in for a non-default language; this dict carries
        # extra wav2vec2 alignment models pinned to GPU memory.
        "_align_cache": {"es": (extra_align, extra_meta)},
    }

    unload_models(models)

    # The bulk-memory holders and the per-language cache must be gone;
    # ``metadata`` is dropped too so the dict is internally consistent.
    for key in (
        "asr",
        "align_model",
        "diarize",
        "_align_cache",
        "metadata",
        "align_cache",
    ):
        assert key not in models, (
            f"unload_models left {key!r} behind — would keep GPU memory "
            "resident across idle windows"
        )


def test_unload_models_is_safe_against_empty_dict():
    """Calling ``unload_models`` on a dict that never got keys populated
    (e.g. after a startup-empty path) must not raise."""
    unload_models({})  # must NOT raise


def test_unload_models_is_idempotent():
    """Calling ``unload_models`` twice on the same dict has the same
    effect as calling it once: each pop is a no-op the second time
    and ``empty_cache`` is safe to repeat."""
    models = {
        "asr": _FakeTensor("asr"),
        "align_model": _FakeTensor("align_model"),
        "diarize": _FakeTensor("diarize"),
    }
    unload_models(models)
    unload_models(models)
    assert models == {}


def test_unload_models_calls_gc_collect_and_empty_cache(monkeypatch):
    """``unload_models`` MUST run ``gc.collect()`` plus
    ``torch.cuda.empty_cache()`` (and friends) so that the
    WhisperX/pyannote pipeline objects release their intermediate
    CTranslate2 / encoder scratch tensors before the cached
    allocator returns blocks to the driver. Without these calls,
    empty_cache returns most blocks but leaves several GiB
    ``reserved`` in the pytorch cache-aligned allocator even
    though no live tensors are present. ``synchronize`` ensures
    in-flight kernels have completed so the allocator bookkeeping
    is accurate; ``ipc_collect`` reaps any IPC handles that
    would otherwise keep tensors pinned across the process
    boundary."""
    fake_gc = MagicMock()
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = True
    monkeypatch.setitem(sys.modules, "gc", fake_gc)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    models = {"asr": object()}
    unload_models(models)

    fake_gc.collect.assert_called_once_with()
    fake_torch.cuda.synchronize.assert_called_once_with()
    fake_torch.cuda.empty_cache.assert_called_once_with()
    fake_torch.cuda.ipc_collect.assert_called_once_with()
    assert models == {}
