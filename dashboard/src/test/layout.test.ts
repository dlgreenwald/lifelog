import { describe, it, expect } from 'vitest';
import {
  getRecordingTimeRange,
  computeLayout,
  isWeekend,
  GUTTER,
  HOURS,
} from '../utils/layout';
import type { Recording } from '../types';

function makeRec(overrides: Partial<Recording> = {}): Recording {
  return {
    id: 'r1',
    user_id: 'u1',
    category: 'conversation',
    timestamp: '2026-09-21T10:00:00Z',
    duration_seconds: 60,
    file_path: '/audio/r1.ogg',
    encrypted: false,
    transcript: undefined,
    is_live: false,
    audio_range_start: undefined,
    audio_range_end: undefined,
    speaker_label: undefined,
    ...overrides,
  } as Recording;
}

describe('getRecordingTimeRange', () => {
  describe('audio_range_start / audio_range_end', () => {
    it('uses audio_range_start and audio_range_end when both present', () => {
      const rec = makeRec({
        audio_range_start: '09:15',
        audio_range_end: '09:45',
      });
      const result = getRecordingTimeRange(rec);
      expect(result.startMin).toBe(9 * 60 + 15); // 555
      expect(result.endMin).toBe(9 * 60 + 45);   // 585
    });

    it('clamps endMin to 1439 (end of day)', () => {
      const rec = makeRec({
        audio_range_start: '23:50',
        audio_range_end: '25:00', // invalid, > 24h
      });
      const result = getRecordingTimeRange(rec);
      expect(result.startMin).toBe(23 * 60 + 50); // 1430
      expect(result.endMin).toBe(1439);            // clamped
    });

    it('defaults to 30-minute block when only audio_range_start is set', () => {
      const rec = makeRec({
        audio_range_start: '14:00',
        audio_range_end: null,
      });
      const result = getRecordingTimeRange(rec);
      expect(result.startMin).toBe(14 * 60);       // 840
      expect(result.endMin).toBe(14 * 60 + 30);   // 870
    });

    it('parses HH:MM time-only strings', () => {
      const rec = makeRec({
        audio_range_start: '08:05',
        audio_range_end: '08:07',
      });
      const result = getRecordingTimeRange(rec);
      expect(result.startMin).toBe(8 * 60 + 5);  // 485
      expect(result.endMin).toBe(8 * 60 + 7);    // 487
    });
  });

  describe('is_live', () => {
    it('returns current time range when is_live is true', () => {
      // audio_range_start must be null to bypass the time parsing path
      const rec = makeRec({ is_live: true, audio_range_start: undefined, timestamp: undefined });
      const result = getRecordingTimeRange(rec);
      // startMin = 0 (no audio_range_start, no timestamp)
      // endMin = now in minutes, clamped to 1439
      expect(result.startMin).toBe(0);
      expect(result.endMin).toBeLessThanOrEqual(1439);
    });
  });

  describe('timestamp fallback', () => {
    it('falls back to timestamp when audio_range_start is absent', () => {
      const rec = makeRec({
        audio_range_start: null,
        timestamp: '2026-09-21T15:30:00Z',
      });
      const result = getRecordingTimeRange(rec);
      // The timestamp is in UTC; toUTCDate converts to local time
      // We just verify startMin is in a valid range
      expect(result.startMin).toBeGreaterThanOrEqual(0);
      expect(result.startMin).toBeLessThanOrEqual(1439);
      expect(result.endMin).toBe(result.startMin + 30);
    });
  });

  describe('no timestamp or range', () => {
    it('defaults to 0 start and 30-minute block', () => {
      const rec = makeRec({
        audio_range_start: undefined,
        timestamp: undefined,
        is_live: false,
      });
      const result = getRecordingTimeRange(rec);
      expect(result.startMin).toBe(0);
      expect(result.endMin).toBe(30);
    });
  });
});

describe('computeLayout', () => {
  const dayHeightPx = 1440; // 1px per minute
  const containerWidth = 800;

  it('returns empty array for empty recordings', () => {
    expect(computeLayout([], dayHeightPx, containerWidth)).toEqual([]);
  });

  it('returns empty array when containerWidth is 0', () => {
    const recs = [makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '09:30' })];
    expect(computeLayout(recs, dayHeightPx, 0)).toEqual([]);
  });

  it('assigns lane 0 to a single recording', () => {
    const recs = [makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '09:30' })];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    expect(result).toHaveLength(1);
    expect(result[0].lane).toBe(0);
    expect(result[0].left).toBe(GUTTER);
  });

  it('assigns lane 0 to non-overlapping recordings', () => {
    const recs = [
      makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '09:30' }),
      makeRec({ id: 'r2', audio_range_start: '10:00', audio_range_end: '10:30' }),
    ];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    expect(result[0].lane).toBe(0);
    expect(result[1].lane).toBe(0);
    // They don't share a column, but both should be lane 0 (no collision)
    expect(result[0].left).toBe(result[1].left);
  });

  it('places overlapping recordings in different lanes', () => {
    const recs = [
      makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '10:00' }),
      makeRec({ id: 'r2', audio_range_start: '09:30', audio_range_end: '10:30' }), // overlaps r1
    ];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    expect(result).toHaveLength(2);
    expect(result[0].lane).not.toBe(result[1].lane);
    expect(result[0].left).not.toBe(result[1].left);
  });

  it('three mutually overlapping recordings all get different lanes', () => {
    const recs = [
      makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '11:00' }),
      makeRec({ id: 'r2', audio_range_start: '09:30', audio_range_end: '11:30' }),
      makeRec({ id: 'r3', audio_range_start: '10:00', audio_range_end: '12:00' }),
    ];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    const lanes = result.map((r) => r.lane);
    expect(new Set(lanes)).toHaveLength(3);
  });

  it('computes correct pixel top and height', () => {
    // 09:00 = 540 minutes, 09:30 = 570 minutes
    const recs = [makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '09:30' })];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    const top = result[0].top;
    const height = result[0].height;
    // top = (540 / 1440) * 1440 = 540px
    // height = (30 / 1440) * 1440 = 30px
    expect(top).toBeCloseTo(540, 1);
    expect(height).toBeCloseTo(30, 1);
  });

  it('chain collision: new collision expands entire chain', () => {
    // r1: 09:00-10:00, r2: 09:15-09:45 (overlaps r1), r3: 09:30-10:30 (overlaps r2 but not r1 visually)
    // When r3 collides with r2's chain, r1 should also expand
    const recs = [
      makeRec({ id: 'r1', audio_range_start: '09:00', audio_range_end: '10:00' }),
      makeRec({ id: 'r2', audio_range_start: '09:15', audio_range_end: '09:45' }),
      makeRec({ id: 'r3', audio_range_start: '09:30', audio_range_end: '10:30' }),
    ];
    const result = computeLayout(recs, dayHeightPx, containerWidth);
    // All three should be in the same collision chain, each in its own lane
    expect(result).toHaveLength(3);
    const lanes = result.map((r) => r.lane);
    expect(new Set(lanes)).toHaveLength(3);
  });
});

describe('isWeekend', () => {
  it('returns true for Saturday', () => {
    expect(isWeekend('2026-09-19')).toBe(true); // Saturday
  });

  it('returns true for Sunday', () => {
    expect(isWeekend('2026-09-20')).toBe(true); // Sunday
  });

  it('returns false for Monday', () => {
    expect(isWeekend('2026-09-21')).toBe(false); // Monday
  });

  it('returns false for a weekday', () => {
    expect(isWeekend('2026-09-23')).toBe(false); // Wednesday
  });
});

describe('exports', () => {
  it('GUTTER is a positive number', () => {
    expect(GUTTER).toBeGreaterThan(0);
  });

  it('HOURS has 24 entries (0–23)', () => {
    expect(HOURS).toHaveLength(24);
    expect(HOURS[0]).toBe(0);
    expect(HOURS[23]).toBe(23);
  });
});
