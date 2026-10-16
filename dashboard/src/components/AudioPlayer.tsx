import { useRef, useState, useEffect, useCallback } from 'react';
import type { Speaker } from '../types';
import { api } from '../api/client';

const SEGMENT_GAP_MS = 500; // silent gap between segments
const READ_AHEAD_SECONDS = 60; // preload this many seconds ahead of playhead

interface AudioPlayerProps {
  segments: Speaker[];
}

/** Find segments whose original-timeline end falls at or before `cutoffSeconds`. */
/** Map compressed-time position to original-timeline position, using segment durations. */
function compressedToOriginal(compressedTime: number, segments: Speaker[]): number {
  let acc = 0;
  for (const seg of segments) {
    const dur = seg.end - seg.start;
    if (acc + dur >= compressedTime) {
      return seg.start + (compressedTime - acc);
    }
    acc += dur;
  }
  return segments.length > 0 ? segments[segments.length - 1].end : 0;
}

/** Which segment index contains the given original-timeline position? */
function segmentIndexAt(originalTime: number, segments: Speaker[]): number {
  for (let i = 0; i < segments.length; i++) {
    if (segments[i].start <= originalTime && originalTime <= segments[i].end) {
      return i;
    }
  }
  return -1;
}

export default function AudioPlayer({ segments }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);

  // Blob cache — filename → object URL (ref to avoid re-renders on cache writes)
  const blobCache = useRef(new Map<string, string>());
  const loaded = useRef(new Set<string>());
  const failed = useRef(new Set<string>());
  const pending = useRef(new Set<string>());

  // Refs for gap timer and loading state communicated across event handlers
  const gapTimer = useRef<number | null>(null);
  const isWaitingForLoad = useRef(false);

  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentSegIdx, setCurrentSegIdx] = useState(0);
  // Current position in compressed time (sum of played segment durations)
  const [compressedTime, setCompressedTime] = useState(0);

  // Valid playable segments (have audio_filename and valid time range)
  const playable = segments.filter(
    (s) =>
      s.audio_filename &&
      Number.isFinite(s.start) &&
      Number.isFinite(s.end) &&
      s.start >= 0 &&
      s.end > s.start,
  );

  // Segments that had audio_filename but fetch failed — distinct from playable
  const errored = segments.filter(
    (s) =>
      s.audio_filename &&
      failed.current.has(s.audio_filename),
  );

  const minStart = playable.length > 0 ? Math.min(...playable.map((s) => s.start)) : 0;
  const maxEnd = playable.length > 0 ? Math.max(...playable.map((s) => s.end)) : 1;
  const visibleRange = maxEnd - minStart || 1;

  /** Fetch a single filename's audio and cache the blob URL. Returns true on success. */
  const fetchOne = useCallback(
    (filename: string): Promise<boolean> => {
      if (!filename || loaded.current.has(filename) || pending.current.has(filename)) {
        return Promise.resolve(loaded.current.has(filename));
      }
      pending.current.add(filename);

      return api
        .fetchAudio(`/dashboard/audio/${filename}`)
        .then((url) => {
          // Revoke old blob if we're overwriting (shouldn't happen normally)
          const existing = blobCache.current.get(filename);
          if (existing && typeof URL.revokeObjectURL === 'function') {
            URL.revokeObjectURL(existing);
          }
          blobCache.current.set(filename, url);
          loaded.current.add(filename);
          return true;
        })
        .catch(() => {
          failed.current.add(filename);
          return false;
        })
        .finally(() => {
          pending.current.delete(filename);
          setIsLoading(pending.current.size > 0);
        });
    },
    [],
  );

  /** Pre-fetch all segments whose end <= `cutoffSeconds` in original timeline. */
  const prefetchUpTo = useCallback(
    (cutoffSeconds: number) => {
      const toFetch = playable.filter((s) => s.end <= cutoffSeconds && !loaded.current.has(s.audio_filename!));
      toFetch.forEach((s) => { void fetchOne(s.audio_filename!); });
    },
    [playable, fetchOne],
  );

  /** Fetch ALL remaining segments not yet loaded. */
  const fetchAll = useCallback(() => {
    const toFetch = playable.filter((s) => !loaded.current.has(s.audio_filename!));
    toFetch.forEach((s) => { void fetchOne(s.audio_filename!); });
  }, [playable, fetchOne]);

  // Phase 1: preload first 60 seconds of audio on mount
  useEffect(() => {
    prefetchUpTo(READ_AHEAD_SECONDS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Revoke blob URLs on unmount
  useEffect(() => {
    return () => {
      if (typeof URL.revokeObjectURL === 'function') {
        blobCache.current.forEach((url) => URL.revokeObjectURL(url));
      }
      blobCache.current.clear();
      loaded.current.clear();
      failed.current.clear();
      pending.current.clear();
      clearTimeout(gapTimer.current ?? undefined);
      gapTimer.current = null;
    };
  }, []);

  /** Load and immediately play segment at index `idx`. */
  const loadAndPlay = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= playable.length) {
        setIsPlaying(false);
        return;
      }
      const seg = playable[idx];
      const filename = seg.audio_filename!;
      const blobUrl = blobCache.current.get(filename);

      if (!blobUrl) {
        // Segment not yet loaded — wait for it
        isWaitingForLoad.current = true;
        setIsLoading(true);
        // Kick off fetch; the load event will trigger play once ready
        void fetchOne(filename).then((ok) => {
          if (!ok) {
            // Fetch failed — skip this segment
            isWaitingForLoad.current = false;
            setIsLoading(false);
            // Try next segment
            const next = idx + 1;
            if (next < playable.length) {
              setCurrentSegIdx(next);
              loadAndPlay(next);
            } else {
              setIsPlaying(false);
            }
            return;
          }
          isWaitingForLoad.current = false;
          setIsLoading(false);
          loadAndPlay(idx);
        });
        return;
      }

      const audio = audioRef.current;
      if (!audio) return;

      // Seek to start of this segment within its compressed duration
      audio.src = blobUrl;
      audio.load();
      audio.play()?.catch(() => {
        // Autoplay blocked — silently stop
        setIsPlaying(false);
      });
      setCurrentSegIdx(idx);

      // Compute compressed time at start of this segment
      let acc = 0;
      for (let i = 0; i < idx; i++) {
        acc += playable[i].end - playable[i].start;
      }
      setCompressedTime(acc);
    },
    [playable, fetchOne],
  );

  /** Start playing from the beginning (or resume). */
  const handlePlay = useCallback(() => {
    if (isPlaying) {
      audioRef.current?.pause();
      setIsPlaying(false);
      if (gapTimer.current !== null) {
        clearTimeout(gapTimer.current);
        gapTimer.current = null;
      }
      return;
    }

    fetchAll(); // Phase 2: fetch everything on first play press

    const idx = currentSegIdx;
    loadAndPlay(idx);
    setIsPlaying(true);
  }, [isPlaying, currentSegIdx, loadAndPlay, fetchAll]);

  /** Advance to next segment after the current one finishes. */
  const advanceToNext = useCallback(() => {
    const next = currentSegIdx + 1;
    if (next >= playable.length) {
      setIsPlaying(false);
      return;
    }
    setCurrentSegIdx(next);
    loadAndPlay(next);
  }, [currentSegIdx, playable.length, loadAndPlay]);

  const handleTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !isPlaying) return;

    // Update compressed time: accumulate durations of all segments up to current,
    // plus current segment's elapsed time
    let acc = 0;
    for (let i = 0; i < currentSegIdx; i++) {
      acc += playable[i].end - playable[i].start;
    }
    // audio.currentTime is relative to the current blob (starts at 0 for the segment)
    acc += audio.currentTime;
    setCompressedTime(acc);

    // Pre-fetch segments within READ_AHEAD_SECONDS of current original position
    const originalNow = compressedToOriginal(acc, playable);
    prefetchUpTo(originalNow + READ_AHEAD_SECONDS);
  }, [isPlaying, currentSegIdx, playable, prefetchUpTo]);

  const handleEnded = useCallback(() => {
    if (gapTimer.current !== null) return; // already scheduled
    setIsPlaying(false);

    // Schedule gap then advance
    gapTimer.current = window.setTimeout(() => {
      gapTimer.current = null;
      advanceToNext();
    }, SEGMENT_GAP_MS);
  }, [advanceToNext]);

  /** Seek to a position in the original audio timeline. */
  const handleSeek = useCallback(
    (originalTime: number) => {
      // Pause gap timer if active
      if (gapTimer.current !== null) {
        clearTimeout(gapTimer.current);
        gapTimer.current = null;
      }

      const segIdx = segmentIndexAt(originalTime, playable);
      if (segIdx < 0) return;

      // Fetch all segments up to and including segIdx if not yet loaded
      const needed = playable.slice(0, segIdx + 1).filter((s) => !loaded.current.has(s.audio_filename!));
      if (needed.length > 0) {
        setIsLoading(true);
        void Promise.all(needed.map((s) => fetchOne(s.audio_filename!))).then(() => {
          setIsLoading(false);
          setCurrentSegIdx(segIdx);
          loadAndPlay(segIdx);
        });
      } else {
        setCurrentSegIdx(segIdx);
        loadAndPlay(segIdx);
      }
      setIsPlaying(true);
    },
    [playable, fetchOne, loadAndPlay],
  );

  const currentSegment = playable[currentSegIdx];
  const currentOriginalTime = compressedToOriginal(compressedTime, playable);

  return (
    <div className="audio-player">
      <audio
        ref={audioRef}
        onTimeUpdate={handleTimeUpdate}
        onEnded={handleEnded}
        onWaiting={() => {
          if (isWaitingForLoad.current) setIsLoading(true);
        }}
        onCanPlay={() => {
          if (isWaitingForLoad.current) {
            isWaitingForLoad.current = false;
            setIsLoading(false);
          }
        }}
      />

      <button onClick={handlePlay} disabled={isLoading && !isPlaying}>
        {isLoading && !isPlaying ? 'Loading…' : isPlaying ? 'Pause' : 'Play'}
      </button>

      {isLoading && <span className="loading-indicator">Loading audio…</span>}

      <div className="timeline">
        {playable.map((seg, i) => {
          const isActive = i === currentSegIdx;
          const isErrored = !seg.audio_filename || failed.current.has(seg.audio_filename);
          return (
            <div
              key={i}
              className={`segment ${isActive ? 'active' : ''} ${isErrored ? 'errored' : ''} ${seg.name === 'Unknown' ? 'unknown' : ''}`}
              style={{
                left: `${((seg.start - minStart) / visibleRange) * 100}%`,
                width: `${((seg.end - seg.start) / visibleRange) * 100}%`,
              }}
              onClick={() => handleSeek(seg.start)}
              title={`${seg.name}: ${seg.start.toFixed(1)}s – ${seg.end.toFixed(1)}s`}
            />
          );
        })}
        {/* Red markers for segments with no audio */}
        {errored.map((seg) => {
          const globalIdx = segments.indexOf(seg);
          return (
            <div
              key={`errored-${globalIdx}`}
              className="segment errored"
              style={{
                left: `${((seg.start - minStart) / visibleRange) * 100}%`,
                width: `${((seg.end - seg.start) / visibleRange) * 100}%`,
              }}
              title={`No audio: ${seg.name}`}
            />
          );
        })}
        {/* Playhead */}
        {isPlaying && (
          <div
            className="playhead"
            style={{ left: `${((currentOriginalTime - minStart) / visibleRange) * 100}%` }}
          />
        )}
      </div>

      {currentSegment && (
        <div className="current-speaker">
          {currentSegment.name}: {currentSegment.text?.slice(0, 60)}
          {currentSegment.text && currentSegment.text.length > 60 ? '…' : ''}
        </div>
      )}

      {playable.length > 1 && (
        <span className="source-indicator">
          Part {currentSegIdx + 1} of {playable.length}
        </span>
      )}
    </div>
  );
}
