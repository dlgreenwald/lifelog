from __future__ import annotations


import base64
import io
import os
import wave
from typing import Any

import numpy as np


def unload_models(models: dict) -> None:
    """Free GPU memory held by WhisperX models.

    WhisperX's ``load_models`` returns five GPU-memory candidates that
    this unload path needs to drop:
      * ``asr`` — WhisperX ASR (the bulk of GPU memory)
      * ``align_model`` — the per-language wav2vec2 alignment model
        (loaded lazily for the default language at startup, populated
        with extras on demand)
      * ``diarize`` — pyannote.audio segmentation+embedding pipeline
      * ``_align_cache`` — a ``{language_code: (align_model, metadata)}``
        cache; populated by ``_get_align_model`` whenever a transcript
        comes in for a non-default language, holding the additional
        per-language alignment model in GPU memory until dropped
      * ``metadata`` — small labels/durations dict; not on GPU but we
        drop it to keep the dict consistent with the loaded models

    After all GPU holders are gone, ``torch.cuda.empty_cache()``
    actually returns the freed memory to the driver.

    Sequence matters because the WhisperX ``FasterWhisperPipeline``,
    the pyannote ``DiarizationPipeline`` and the
    ``CTranslate2 WhisperModel`` allocate intermediate GPU state
    (output buffers, encoder scratch) on every transcription call;
    these tensors are dropped when their Python refs are released
    but Python's cyclic GC does not always run promptly. We
    therefore:

    1. Drop every key that mutually references a GPU holder, so the
       model objects themselves go unreachable.
    2. ``gc.collect()`` so cyclic reference chains inside the
       whisperx + pyannote pipelines run their ``__del__``.
    3. ``torch.cuda.synchronize()`` so in-flight kernels finish and
       the cached allocator bookkeeping is consistent.
    4. ``torch.cuda.empty_cache()`` so the cached allocator returns
       unused blocks to the driver. ``torch.cuda.ipc_collect()``
       additionally drops IPC handles that can hold tensors
       across the process boundary.
    """
    import gc

    import torch

    for key in ("asr", "align_model", "diarize", "_align_cache"):
        models.pop(key, None)
    # ``align_cache`` (no underscore) is the return-side key from
    # ``load_models``; it is a plain dict and does not hold GPU but
    # dropping it keeps the model-manager dict in lock-step with
    # what ``load_models`` returns.
    models.pop("align_cache", None)
    # ``metadata`` is small (a Python labels dict) and does not hold
    # GPU memory, but it is meaningless without ``align_model``;
    # drop it so transient reloads are forced to re-pull it from
    # ``whisperx.load_align_model``.
    models.pop("metadata", None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        # NOTE: torch.cuda.ipc_collect() is intentionally omitted.
        # In a single-process context it is unnecessary (IPC handles are
        # for inter-process GPU sharing) and can corrupt the CUDA context
        # in a way that makes subsequent whisperx.load_model() calls fail
        # silently — leaving self._models = {} and causing KeyError: 'asr'
        # on every subsequent job (confirmed 2026-09-01, job 1880+).


from audio import waveform_to_numpy


def _register_omegaconf_safe_globals() -> None:
    """Permit torch.load to unpickle pyannote.audio / WhisperX checkpoints.

    torch 2.6+ defaults torch.load(weights_only=True), which restricts the
    safe-global set tightly and rejects omegaconf (``ListConfig`` /
    ``DictConfig`` / ``AnyNode`` / ``ContainerMetadata`` / …) and a long
    tail of pyannote / lightning typed globals embedded in checkpoints.
    Enumerating every omegaconf / pyannote / lightning class and
    registering it via ``torch.serialization.add_safe_globals`` is a
    whack-a-mole exercise: every upstream release adds more globals.

    Instead, monkey-patch :func:`torch.load` so that when ``weights_only=True``
    raises :class:`pickle.UnpicklingError` *and* the file path exposes a
    location that's plausibly a known-trusted model source — the
    HuggingFace cache directory, the active Python
    ``site-packages`` tree (where WhisperX / pyannote.audio bundle
    their own assets), or the torch Hub directory — we transparently
    retry the same call with ``weights_only=False``. This is exactly the
    escape hatch documented in torch's own UnpicklingError message and
    the trusted roots we accept are supplied by the application's own
    configuration and the standard Python installation footprint.

    The wrap is idempotent via a marker attribute on ``torch.load`` so
    repeated ``_register_omegaconf_safe_globals`` calls do not stack
    wrappers.
    """
    try:
        import os
        import pickle
        import sys
        from os.path import realpath

        import torch
    except ImportError:
        return
    if getattr(torch.load, "_lifelog_safe_unpickle_wrapped", False):
        return  # idempotent guard — already installed on this process

    # The set of filesystem prefixes we treat as "trusted model sources":
    #  * ``MODEL_CACHE_DIR`` (default ``/root/.cache/huggingface``) — the
    #    operator-configurable HuggingFace cache. Anything downloaded
    #    through ``hf_hub_download`` ends up here.
    #  * ``PYANNOTE_CACHE_DIR`` (default ``~/.cache/torch/pyannote``) —
    #    where pyannote.audio stages Lightning model checkpoints it
    #    pulled via ``hf_hub_download``. This is technically a sub-cache
    #    of HuggingFace's but pyannote writes to a separate filesystem
    #    location, so we treat it as a sibling trust root.
    #  * Every ``sys.path`` directory: WhisperX bundles its VAD model
    #    under ``site-packages/whisperx/assets/pytorch_model.bin`` —
    #    operator-installed Python packages are by definition
    #    operator-approved at install time, so checkpoints shipped
    #    with them count as trusted model sources.
    trust_root_realpaths: tuple[str, ...] = tuple(
        realpath(p)
        for p in (
            os.getenv("MODEL_CACHE_DIR", "/root/.cache/huggingface"),
            os.getenv(
                "PYANNOTE_CACHE_DIR", os.path.expanduser("~/.cache/torch/pyannote")
            ),
        )
        if p
    )
    site_packages_realpaths: tuple[str, ...] = tuple(
        os.path.realpath(p)
        for p in sys.path
        if p and os.path.isdir(os.path.realpath(p))
    )

    def _candidate_is_trusted(candidate_path: str | None) -> bool:
        if not candidate_path:
            return False
        for tr in trust_root_realpaths:
            if candidate_path == tr or candidate_path.startswith(tr + os.sep):
                return True
        for sp in site_packages_realpaths:
            if candidate_path == sp or candidate_path.startswith(sp + os.sep):
                # Allow any file inside site-packages: pyannote,
                # whisperx, lightning_fabric, omegaconf all ship model
                # assets there. Treat operator-installed Python packages
                # as a trusted model source.
                return True
        return False

    def _file_like_reopen(candidate_path: str | None):
        """Return a fresh open() of a path or None if not a known path."""
        if not candidate_path or not os.path.isfile(candidate_path):
            return None
        try:
            return open(candidate_path, "rb")
        except OSError:
            return None

    def _resolve_retry_args_kwargs(args, kwargs):
        """Rebuild the (args, kwargs) tuple for the weights_only=False
        retry. If the caller passed a file-like whose underlying path
        we can resolve, we replace it with a fresh ``open(pre_rewound, "rb")``
        so the retry starts at the head of the file. If we cannot resolve
        the path OR the path is not under a trusted source, return
        ``(None, None)`` and let the caller re-raise."""
        candidate_path: str | None = None
        candidate = kwargs.get("f")
        if candidate is None and args:
            candidate = args[0]
        if isinstance(candidate, (str, bytes, os.PathLike)):
            try:
                candidate_path = os.path.realpath(candidate)
            except (TypeError, ValueError):
                candidate_path = None
        elif candidate is not None:
            for attr in ("path", "name", "full_name"):
                try:
                    cp = os.path.realpath(getattr(candidate, attr))
                    if cp:
                        candidate_path = cp
                        break
                except (TypeError, ValueError, AttributeError):
                    continue
        if not candidate_path or not _candidate_is_trusted(candidate_path):
            return None, None
        fresh = _file_like_reopen(candidate_path)
        if fresh is None:
            return args, kwargs
        if "f" in kwargs:
            new_kwargs = dict(kwargs)
            new_kwargs["f"] = fresh
            return args, new_kwargs
        return (fresh,) + args[1:], kwargs

    original_load = torch.load

    def _safe_unpickle_load(*args, **kwargs):
        try:
            return original_load(*args, **kwargs)
        except pickle.UnpicklingError:
            # Caller asked for weights_only=True explicitly? Honor that —
            # don't silently downgrade.
            if kwargs.get("weights_only") is True:
                raise
            retry_args, retry_kwargs = _resolve_retry_args_kwargs(args, kwargs)
            if retry_args is None:
                # Refusal: target file is not under a trusted source AND
                # we've decided not to silently retry.
                raise
            retry_kwargs = dict(retry_kwargs)
            retry_kwargs["weights_only"] = False
            return original_load(*retry_args, **retry_kwargs)

    _safe_unpickle_load._lifelog_safe_unpickle_wrapped = True
    torch.load = _safe_unpickle_load


def _patch_huggingface_hub_use_auth_token() -> None:
    """Bridge pyannote.audio 3.x's deprecated ``use_auth_token`` kwarg.
    pyannote.audio 3.4 calls ``huggingface_hub.hf_hub_download(..., use_auth_token=...)``.
    In huggingface_hub 1.0, ``use_auth_token`` was renamed to ``token``;
    pyannote.audio 3.4 has not been updated for that rename, so calling
    it on a current huggingface_hub raises ``TypeError: got an
    unexpected keyword argument 'use_auth_token'``. Wrap the function
    transparently: if a caller hands the legacy kwarg, translate it to
    ``token`` before delegating. Idempotent via marker attribute.
    """
    try:
        import functools

        import huggingface_hub
    except ImportError:
        return

    original = huggingface_hub.hf_hub_download
    if getattr(original, "_lifelog_use_auth_token_bridge_wrapped", False):
        return  # already wrapped, monorepo's other worker may have installed it

    @functools.wraps(original)
    def _use_auth_token_bridge(*args, **kwargs):
        if "use_auth_token" in kwargs:
            kwargs = dict(kwargs)
            use_auth_token = kwargs.pop("use_auth_token")
            if "token" not in kwargs and use_auth_token is not None:
                kwargs["token"] = use_auth_token
        return original(*args, **kwargs)

    _use_auth_token_bridge._lifelog_use_auth_token_bridge_wrapped = True
    huggingface_hub.hf_hub_download = _use_auth_token_bridge


def load_models() -> dict[str, Any]:
    """Load ASR, alignment, and diarization models once per worker process."""
    _register_omegaconf_safe_globals()
    _patch_huggingface_hub_use_auth_token()
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    device = os.getenv("ASR_DEVICE", "cuda")
    compute_type = os.getenv("ASR_COMPUTE_TYPE", "float16")
    model_name = os.getenv("ASR_MODEL", "large-v3")
    cache_dir = os.getenv("MODEL_CACHE_DIR", "/root/.cache/huggingface")
    asr = whisperx.load_model(
        model_name, device=device, compute_type=compute_type, download_root=cache_dir
    )
    align_language = os.getenv("ASR_LANGUAGE", "en")
    align_model, metadata = whisperx.load_align_model(
        language_code=align_language,
        device=device,
    )
    diarize = DiarizationPipeline(use_auth_token=os.environ["HF_TOKEN"], device=device)
    return {
        "asr": asr,
        "align_model": align_model,
        "metadata": metadata,
        "align_language": align_language,
        "align_cache": {},
        "diarize": diarize,
        "device": device,
        "compute_type": compute_type,
    }


def quick_transcribe(
    models: dict, audio_np: np.ndarray, sample_rate: int, language: str | None = None
) -> dict:
    """Run ASR only; alignment and diarization are intentionally skipped."""
    audio_np = waveform_to_numpy(audio_np)
    result = models["asr"].transcribe(audio_np, batch_size=4, language=language)
    segments = result.get("segments", [])
    return {"segments": segments, "full_transcript": {"segments": segments}}


def group_into_speaker_segments(segments: list[dict]) -> list[dict]:
    """Merge consecutive diarized entries for the same speaker."""
    if not segments:
        return []
    groups: list[dict] = []
    for index, segment in enumerate(segments):
        speaker = segment.get("speaker") or "Unknown"
        text = str(segment.get("text", "")).strip()
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        if groups and groups[-1]["speaker"] == speaker:
            group = groups[-1]
            group["end"] = end
            group["text"] = f"{group['text']} {text}".strip()
            group["segment_indices"].append(index)
        else:
            groups.append(
                {
                    "speaker": speaker,
                    "start": start,
                    "end": end,
                    "text": text,
                    "segment_indices": [index],
                }
            )
    return groups


def _extract_segment_wav(
    audio_np: np.ndarray,
    sample_rate: int,
    segments: list[dict],
    indices: list[int],
) -> str:
    """Extract selected segment ranges as base64-encoded mono PCM WAV."""
    audio_np = waveform_to_numpy(audio_np)
    if sample_rate <= 0:
        return ""
    slices = []
    for index in indices:
        if index < 0 or index >= len(segments):
            continue
        segment = segments[index]
        try:
            start = max(0, int(float(segment.get("start", 0.0)) * sample_rate))
            end = min(len(audio_np), int(float(segment.get("end", 0.0)) * sample_rate))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        slices.append(audio_np[start:end])
    if not slices:
        return ""
    samples = np.concatenate(slices)
    pcm = np.clip(samples * 32768.0, -32768, 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _as_segment_dicts(segments: Any) -> list[dict]:
    if isinstance(segments, list):
        return [dict(segment) for segment in segments]
    if hasattr(segments, "iterrows"):
        return [dict(row) for _, row in segments.iterrows()]
    return []


def _get_align_model(models: dict, language_code: str) -> tuple:
    """Load or retrieve a cached alignment model for the given language code."""
    import whisperx

    if (
        models.get("align_language") == language_code
        and models.get("align_model") is not None
    ):
        return models["align_model"], models["metadata"]
    align_cache = models.setdefault("_align_cache", {})
    if language_code in align_cache:
        return align_cache[language_code]
    align_model, metadata = whisperx.load_align_model(
        language_code=language_code,
        device=models["device"],
    )
    align_cache[language_code] = (align_model, metadata)
    return align_model, metadata


def transcribe_audio(
    models: dict, audio_np: np.ndarray, sample_rate: int, language: str | None = None
) -> dict:
    """Run ASR, alignment, diarization, and transient speaker-audio extraction."""
    audio_np = waveform_to_numpy(audio_np)
    asr_result = models["asr"].transcribe(audio_np, batch_size=4, language=language)
    raw_segments = _as_segment_dicts(asr_result.get("segments", []))
    if not raw_segments:
        return {
            "segments": [],
            "full_transcript": {"segments": []},
            "speaker_map": {},
            "speaker_segments": [],
        }

    detected_language = asr_result.get("language", "en")
    aligned_segments = raw_segments
    align_model = models.get("align_model")
    if align_model is not None:
        import whisperx

        align_model, metadata = _get_align_model(models, detected_language)
        aligned = whisperx.align(
            raw_segments,
            align_model,
            metadata,
            audio_np,
            models["device"],
            return_char_alignments=False,
        )
        aligned_segments = _as_segment_dicts(aligned.get("segments", aligned))

    diarization = models["diarize"](audio_np)
    import whisperx

    diarized = whisperx.assign_word_speakers(
        diarization, {"segments": aligned_segments}
    )
    segments = _as_segment_dicts(diarized.get("segments", aligned_segments))
    groups = group_into_speaker_segments(segments)
    speaker_segments = []
    for group in groups:
        segment = {
            key: value for key, value in group.items() if key != "segment_indices"
        }
        segment["audio"] = _extract_segment_wav(
            audio_np, sample_rate, segments, group["segment_indices"]
        )
        speaker_segments.append(segment)

    speaker_map = asr_result.get("speaker_map", {})
    if not isinstance(speaker_map, dict):
        speaker_map = {}
    return {
        "segments": segments,
        "full_transcript": {"segments": segments, "language": detected_language},
        "speaker_map": speaker_map,
        "speaker_segments": speaker_segments,
    }
