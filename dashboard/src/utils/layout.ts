/**
 * Pure layout helpers for DayView — time-to-pixel conversion and
 * collision-aware recording block placement.
 */

import { toUTCDate } from './format';
import type { Recording } from '../types';

export interface RecordingLayout {
  rec: Recording;
  top: number;
  height: number;
  left: number;
  width: number;
  lane: number;
}

export const GUTTER = 3;

/**
 * Convert a recording's timestamps to minute-of-day values.
 * Returns startMin and endMin clamped to [0, 1439].
 */
export function getRecordingTimeRange(
  rec: Recording,
): { startMin: number; endMin: number } {
  let startMin = 0;
  if (rec.audio_range_start) {
    const [h, m] = rec.audio_range_start.split(':').map(Number);
    startMin = h * 60 + m;
  } else if (rec.timestamp) {
    const recDate = toUTCDate(rec.timestamp);
    startMin = Math.max(0, recDate.getHours() * 60 + recDate.getMinutes());
  }

  if (rec.is_live) {
    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const endMin = Math.min(nowMin, 24 * 60 - 1);
    return { startMin, endMin };
  }

  let durationMinutes = 30;
  if (rec.audio_range_start && rec.audio_range_end) {
    const [sh, sm] = rec.audio_range_start.split(':').map(Number);
    const [eh, em] = rec.audio_range_end.split(':').map(Number);
    const sMin = sh * 60 + sm;
    const eMin = eh * 60 + em;
    if (eMin > sMin) {
      durationMinutes = eMin - sMin;
    }
  }

  const endMin = Math.min(startMin + durationMinutes, 24 * 60 - 1);
  return { startMin, endMin };
}

/**
 * Assigns overlapping recordings to side-by-side columns (lanes).
 * Uses Union-Find to track collision chains — when a recording collides
 * with any member of a chain, the ENTIRE chain is updated to the new size.
 *
 * Collision = prev's visual block overlaps current's visual block:
 *   prev.startMin < currentVisualEnd && current.startMin < prevVisualEnd
 *
 * All recordings in the same collision chain share:
 *   - numCols = chain size (max size ever reached)
 *   - Lane positions assigned by start time order
 */
export function computeLayout(
  recordings: Recording[],
  dayHeightPx: number,
  containerWidth: number,
): RecordingLayout[] {
  if (recordings.length === 0 || containerWidth <= 0) return [];

  const withRanges = recordings.map((rec) => {
    const { startMin, endMin } = getRecordingTimeRange(rec);
    const heightMin = Math.max(30, endMin - startMin);
    return { rec, startMin, endMin, heightMin };
  });

  withRanges.sort((a, b) => a.startMin - b.startMin);

  class UF {
    parent: number[];
    rank: number[];
    constructor(n: number) {
      this.parent = Array.from({ length: n }, (_, i) => i);
      this.rank = Array(n).fill(0);
    }
    find(x: number): number {
      if (this.parent[x] !== x) this.parent[x] = this.find(this.parent[x]);
      return this.parent[x];
    }
    union(x: number, y: number): void {
      const px = this.find(x);
      const py = this.find(y);
      if (px === py) return;
      if (this.rank[px] < this.rank[py]) this.parent[px] = py;
      else if (this.rank[px] > this.rank[py]) this.parent[py] = px;
      else {
        this.parent[py] = px;
        this.rank[px]++;
      }
    }
    getMembers(x: number): number[] {
      const root = this.find(x);
      return this.parent
        .map((_, i) => (this.find(i) === root ? i : -1))
        .filter((i) => i >= 0);
    }
  }

  const uf = new UF(withRanges.length);
  const numColsForRec: number[] = withRanges.map(() => 1);
  const laneForRec: number[] = withRanges.map(() => 0);

  withRanges.forEach((current, currentIdx) => {
    const currVisualEnd = current.startMin + current.heightMin;
    const colliding: number[] = [];

    for (let i = 0; i < currentIdx; i++) {
      const prev = withRanges[i];
      const prevVisualEnd = prev.startMin + prev.heightMin;
      if (prev.startMin < currVisualEnd && current.startMin < prevVisualEnd) {
        colliding.push(i);
        uf.union(currentIdx, i);
      }
    }

    if (colliding.length === 0) {
      numColsForRec[currentIdx] = 1;
      laneForRec[currentIdx] = 0;
    } else {
      const chain = uf.getMembers(currentIdx);
      chain.forEach((idx) => {
        numColsForRec[idx] = Math.max(numColsForRec[idx], chain.length);
      });
      numColsForRec[currentIdx] = chain.length;

      chain.sort((a, b) => withRanges[a].startMin - withRanges[b].startMin);
      chain.forEach((idx, pos) => {
        laneForRec[idx] = pos;
      });
    }
  });

  return withRanges.map((wr, i) => {
    const numCols = numColsForRec[i];
    const laneIdx = laneForRec[i];
    const colWidth = (containerWidth - GUTTER * 2) / numCols;
    const left = laneIdx * colWidth + GUTTER;
    return {
      rec: wr.rec,
      top: (wr.startMin / 1440) * dayHeightPx,
      height: (wr.heightMin / 1440) * dayHeightPx,
      left,
      width: colWidth - GUTTER * 2,
      lane: laneIdx,
    };
  });
}

/** Returns true for Saturday (0) and Sunday (6) — day-of-week from a YYYY-MM-DD string. */
export function isWeekend(dateStr: string): boolean {
  // dateStr is YYYY-MM-DD — no timezone needed for day-of-week
  const d = new Date(dateStr + 'T00:00:00');
  const day = d.getDay();
  return day === 0 || day === 6;
}

export const HOURS = Array.from({ length: 24 }, (_, i) => i);
