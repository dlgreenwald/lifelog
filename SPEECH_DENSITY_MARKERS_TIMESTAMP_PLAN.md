# Speech Density Markers & Timestamp Normalization — Implementation Plan

## Context

ASR transcripts from multi-chunk sessions have a known timestamp discrepancy: per-chunk word-level timings are chunk-relative, but segment-level times are globalized during merge. The downstream LLM receives no time-derived signals about conversation structure (silence vs. gap, fragmentary vs. sustained speech). This adds two components: a pipeline fix for the word-timing bug, and a new density-marker service injected into the finalize pipeline.

---

## Approach

### Part A — Pipeline Fix (word timing globalization)

**File**: `server/src/lifelog/worker.py`, `_shifted_segments()` at line 844.

**Change**: When shifting segment `start`/`end` by `offset`, also shift every `word.start` and `word.end` inside `segment.get("words", [])`.

```python
# After shifting segment start/end:
words = item.get("words")
if isinstance(words, list):
    shifted_words = []
    for w in words:
        w_item = dict(w)
        if isinstance(w_item.get("start"), (int, float)):
            w_item["start"] += offset
        if isinstance(w_item.get("end"), (int, float)):
            w_item["end"] += offset
        shifted_words.append(w_item)
    item["words"] = shifted_words
```

**Test**: `transcription-worker/test_pipeline.py` — new `test_shifted_segments_preserves_word_timings`:
- Input: 2 segments from a 600s-offset chunk, each with `words: [{start: 0.5, end: 1.2, word: "hello"}]`
- Call `_shifted_segments(segments, 600.0)` — need to import `_shifted_segments` from `lifelog.worker` (the function is module-level, testable)
- Assert each segment's `start`/`end` shifted by 600, AND each word's `start`/`end` shifted by 600

**Note**: `_shifted_segments` lives in `worker.py` which imports heavy ML libs. The test should either: (a) import and patch the ML mocks before importing worker, or (b) move `_shifted_segments` to a separate pure-python module (e.g., `lifelog/pipeline/timestamp_utils.py`) so it can be tested without ML imports. **Option (b) is preferred** — move `_shifted_segments` to `server/src/lifelog/pipeline/timestamp_utils.py` and update the import in `worker.py`.

---

### Part B — Density Marker Service

**New file**: `server/src/lifelog/pipeline/density.py`

Pure function, no LLM calls, no I/O. All thresholds in one `DensityConfig` dataclass.

#### `DensityConfig` defaults
```python
@dataclass
class DensityConfig:
    gap_threshold_seconds: float = 30.0   # GAP_THRESHOLD
    window_seconds: float = 300.0         # W
    min_window_fraction: float = 0.5      # truncated window = W/2 guard
    merge_tolerance: float = 0.5          # interval union tolerance
    sparse_max: float = 0.10
    light_max: float = 0.30
    moderate_max: float = 0.60
    mature_min_seconds: float = 1800.0     # 30 min
    long_running_min_seconds: float = 3600.0  # 60 min
    chunk_length_seconds: float = 0.0      # 0 = skip Phase 0 diagnosis
```

#### Phase 0 — `diagnose_timestamps(segments, config) -> dict`
- For every segment with `words`, compare `words[0].start` vs `segment.start` and `words[-1].end` vs `segment.end`.
- Try CHUNK candidates = [300, 600, 900, 1200]; for each, check if `segment.start − words[0].start ≈ CHUNK * floor(segment.start / CHUNK)` within ±0.05s for ≥95% of segments.
- If a CHUNK fits: return `{"chunk_length": CHUNK, "fit_pct": pct, "misfits": [...], "normalizations": [], "stop": False}`.
- If no CHUNK fits: return `{"chunk_length": None, "fit_pct": 0.0, "misfits": [], "normalizations": [], "stop": True}` — caller logs warning and skips density computation.
- Phase 0 always runs first; `stop: True` halts the pipeline.

#### Normalization — `normalize_segment_words(segment) -> tuple[dict, bool]`
- If `abs(words[0].start − segment.start) > 2.0`: compute `offset = segment.start − words[0].start`.
- Verify: (a) word times monotonically non-decreasing, (b) `words[-1].end + offset ≈ segment.end` within ±0.05s.
- If consistent: add `offset` to all word `start`/`end`; return `(normalized, True)`.
- If inconsistent: strip `words` from segment; return `(segment, False)`.
- Called from `compute_speech_density` before building the timeline; results collected into `diagnosis["normalizations"]`.

#### Core functions
- `build_speech_timeline(segments, config) -> list[tuple[float, float]]` — collect validated intervals (use segment interval if words absent/invalid), merge overlapping/touching via union with `merge_tolerance`.
- `detect_gaps(intervals, rec_start, rec_end, config) -> list[dict]` — all gaps between intervals; emit markers only for gaps `>= gap_threshold_seconds`.
- `compute_density(window_start, window_end, all_intervals, config) -> float` — total overlap of `all_intervals` with window divided by window duration.
- `band_density(d, config) -> str` — `sparse | light | moderate | dense | insufficient data`.
- `elapsed_band(seconds_since_first_speech, config) -> str` — `young | mature | long-running`.
- `format_gap_marker(gap, trailing_band, leading_band, elapsed_band) -> str` — `[gap: X min Y sec | speech before: <band> | speech after: <band> | elapsed: <band>]`.
- `inject_markers(transcript_segments, markers) -> str` — reconstruct transcript with marker lines inserted between appropriate segments. Format: `f"[{speaker}]: {text}"` per segment, marker line between segments at gap boundary.

#### Main entry point
```python
def compute_speech_density(
    segments: list[dict],
    config: DensityConfig | None = None,
) -> tuple[str, list[dict], dict]:
    """
    Returns (annotated_transcript, machine_markers, diagnosis_report).
    - annotated_transcript: segment text with [gap: ...] lines injected.
    - machine_markers: [{at_seconds, gap_seconds, trailing_density, leading_density,
                         trailing_band, leading_band, elapsed_band}, ...].
    - diagnosis_report: Phase 0 output + normalizations log.
    """
```

**Transcript reconstruction**: iterate `segments` in order; output `f"[{seg.get('speaker','Unknown')}]: {seg.get('text','')}"` per segment. Between segments, insert marker line if gap exists between `segments[i]['end']` and `segments[i+1]['start']`. Gaps at recording start → `no prior speech`; gaps at recording end → `none`.

**Edge-anchored windows** (spec §5):
- `trailing_window = [max(rec_start, gap_end_of_prior − W), gap_end_of_prior)` — gap excluded
- `leading_window = [gap_start_of_following, min(rec_end, gap_start_of_following + W))` — gap excluded
- If available window duration `< W/2` → band = `insufficient data`
- Gap at recording start → trailing_band = `no prior speech`
- Gap at recording end → leading_band = `none`

---

### Part C — Move `_shifted_segments` to Pure Module

**New file**: `server/src/lifelog/pipeline/timestamp_utils.py`

```python
"""Pure timestamp utility functions for ASR transcript processing."""

def shifted_segments(segments: list[dict], offset: float) -> list[dict]:
    """Shift segment and word-level timings by offset seconds."""
    ...

def partition_segments(
    segments: list[dict],
    gap_threshold_seconds: float = 300.0,
) -> list[list[dict]]:
    """Partition speaker_segments into groups separated by gaps >= threshold."""
    ...
```

**Update**: in `worker.py`, delete the local `_shifted_segments` and `_partition_segments` definitions; replace with:
```python
from lifelog.pipeline.timestamp_utils import shifted_segments, partition_segments
# Update call sites:
# _shifted_segments → shifted_segments
# _partition_segments → partition_segments  (existing function at line 866)
```

**Import chain**: `worker.py` → `pipeline/timestamp_utils.py` → no ML deps → testable without conftest mocks.

---

### Part D — Integration into `_finalize_completed_sessions`

**File**: `server/src/lifelog/worker.py`, `_finalize_completed_sessions()`.

**Call site**: after `speaker_segments` is built and sorted (`speaker_segments.sort(...)`, ~line 1265), before the `for part_idx, partition in enumerate(final_partitions)` loop.

```python
from lifelog.pipeline.density import compute_speech_density, DensityConfig

# After: speaker_segments is built and sorted
rec_start = speaker_segments[0]["start"] if speaker_segments else 0.0
rec_end = speaker_segments[-1]["end"] if speaker_segments else 0.0

density_config = DensityConfig()
annotated_transcript, density_markers, diagnosis = compute_speech_density(
    speaker_segments, density_config
)
if diagnosis.get("stop"):
    logger.warning(
        "density_diagnosis_failed_chunk_model",
        session_id=session["id"],
        diagnosis=diagnosis,
    )
else:
    logger.info(
        "density_markers_computed",
        session_id=session["id"],
        marker_count=len(density_markers),
    )
```

**Making markers visible to LLM**: prepend to `llm_context` before each `summarize_partition` call:
```python
marker_context = f"[Speech density markers]\n{annotated_transcript}\n\n"
effective_llm_context = marker_context + (llm_context or "")
# Use effective_llm_context in summarize_partition calls
```

**Splits vs. density**: when topic splits create multiple partitions, density is computed once on the full `speaker_segments`; the same `annotated_transcript` is available to all partitions via `llm_context`.

---

### Part E — Tests

**New file**: `server/tests/test_density.py`

Each test is a standalone `def test_...()`:

| Test | Setup | Assertion |
|---|---|---|
| `test_merged_intervals_no_double_count` | `[(0,10),(9,20),(25,35)]` | `[(0,20),(25,35)]` |
| `test_gap_5min_preserves_speech_both_sides` | gap at 300s, speech both sides | trailing_density > 0 AND leading_density > 0 |
| `test_gap_near_start_no_crash` | gap at 5s | trailing_band = `no prior speech`, no exception |
| `test_gap_near_end_no_crash` | gap at rec_end − 5s | leading_band = `none`, no exception |
| `test_truncated_window_insufficient_data` | available window 100s < W/2=150s | band = `insufficient data` |
| `test_word_timing_fallback_to_segment_interval` | words fail consistency check | segment interval used, words stripped |
| `test_timestamp_normalization_multi_chunk` | 3 segments, offsets 0/600/1200s, one segment has inconsistent words | all consistent words normalized; inconsistent segment → words discarded |
| `test_density_markers_return_format` | session with gaps | each marker dict has all 7 required keys |
| `test_marker_injection_preserves_segment_order` | 3 segments, gap at 10s | output contains all 3 segment lines + 1 marker line, in order |
| `test_shifted_segments_preserves_word_timings` | segment with words, offset=600 | `words[0].start` and `words[-1].end` both shifted by 600 |

**Reference acceptance test** (session with known gaps — implementer should use session 930 or another session with multi-chunk audio that produces detectable gaps):
- Verify markers exist for expected gap positions
- Verify no markers are injected inside the dense 2323–2819 stretch (if that region exists in the reference data)

**Pipeline fix regression test** (`transcription-worker/test_pipeline.py`):
- `test_shifted_segments_preserves_word_timings` — import `shifted_segments` from the new `timestamp_utils` module

---

## Critical Files & Anchors

| File | Symbol / Region | Reason |
|---|---|---|
| `server/src/lifelog/worker.py:844` | `_shifted_segments()` — misses word times | Move to `pipeline/timestamp_utils.py` |
| `server/src/lifelog/worker.py:1265` | `speaker_segments.sort(...)` | Where merged segments are ready; call density here |
| `server/src/lifelog/worker.py:1354` | `summarize_partition(named_part, llm_context=...)` | Where annotated transcript enters LLM context |
| `server/src/lifelog/pipeline/` | `llm.py` | New `density.py` and `timestamp_utils.py` go here |
| `transcription-worker/pipeline.py:467` | `transcribe_audio()` | Source of segments with `words` field; confirmed present |
| `server/tests/test_session.py` | existing finalize tests | Pattern for mocking db and LLM calls |

---

## Verification

**Unit tests**: `cd server && .venv/bin/python -m pytest tests/test_density.py tests/test_session.py -v -k "density or split or shifted"` — all pass.

**Pipeline fix**: `cd transcription-worker && python -m pytest test_pipeline.py -v -k shifted` — passes.

**Lint**: `cd server && .venv/bin/ruff check src/lifelog/pipeline/density.py src/lifelog/pipeline/timestamp_utils.py src/lifelog/worker.py tests/test_density.py` — zero errors.

**Existing test suite**: `cd server && .venv/bin/python -m pytest tests/ -q` — all existing tests still pass.

---

## Assumptions & Contingencies

- **Word timings present in `speaker_segments`**: `transcribe_audio` in the transcription worker calls `group_into_speaker_segments` which preserves the `words` field from whisperx alignment. If `words` are absent (e.g., quick jobs skip alignment), normalization is a no-op and the segment interval is used. Phase 0 diagnosis will show low fit % and `stop: True` in that case.
- **CHUNK length candidates**: [300, 600, 900, 1200] seconds. If the actual chunk length differs (e.g. 150s), add it to the candidate list in `diagnose_timestamps`.
- **Reference acceptance test data**: session 930 is available and has multi-chunk structure. Use it or another session with known gap positions. If no suitable session exists in dev DB, the acceptance test can be marked `pytest.mark.skip(reason="no reference session")` and filled in later.
- **ML import isolation**: moving `_shifted_segments` to `pipeline/timestamp_utils.py` breaks the import cycle with `worker.py` and allows testing without the heavy `conftest.py` mock layer.
