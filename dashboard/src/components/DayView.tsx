import { useEffect, useLayoutEffect, useRef, useState, type FC } from 'react';
import { format } from 'date-fns';
import { Separator } from '@/components/ui/separator';
import { Spinner } from '@/components/ui/spinner';
import type { Recording } from '../types';
import { toUTCDate } from '../utils/format';

interface DayViewProps {
  date: string;
  recordings: Recording[];
  onRecordingClick: (id: number | string) => void;
  /** 'left' = show left-aligned hour labels, 'right' = right-aligned, 'none' = hidden */
  hourLabelPosition: 'left' | 'right' | 'none';
  onDayScroll?: (date: string, el: HTMLDivElement) => void;
  onMount?: (date: string, el: HTMLDivElement) => void;
  isRightmost?: boolean;
}
function getRecordingTimeRange(rec: Recording): { startMin: number; endMin: number } {
  // Use audio_range_start for position when available (actual audio time, not upload time).
  // Fall back to timestamp if audio_range_start is not set.
  // All timestamps are UTC naive from PostgreSQL — parse as UTC with toUTCDate.
  let startMin = 0;
  if (rec.audio_range_start) {
    const s = toUTCDate(rec.audio_range_start);
    startMin = Math.max(0, s.getHours() * 60 + s.getMinutes());
  } else {
    const recDate = toUTCDate(rec.timestamp);
    startMin = Math.max(0, recDate.getHours() * 60 + recDate.getMinutes());
  }

  // For live recordings, use current time as the end so the block grows in real-time.
  if (rec.is_live) {
    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const endMin = Math.min(nowMin, 24 * 60 - 1);
    return { startMin, endMin };
  }

  let durationMinutes = 30;
  if (rec.audio_range_start && rec.audio_range_end) {
    const s = toUTCDate(rec.audio_range_start);
    const e = toUTCDate(rec.audio_range_end);
    const sMin = s.getHours() * 60 + s.getMinutes();
    const eMin = e.getHours() * 60 + e.getMinutes();
    if (eMin > sMin) {
      durationMinutes = eMin - sMin;
    }
  }

  const endMin = Math.min(startMin + durationMinutes, 24 * 60 - 1);
  return { startMin, endMin };
}

interface RecordingLayout {
  rec: Recording;
  top: number;
  height: number;
  left: number;
  width: number;
}

const GUTTER = 3;

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
function computeLayout(recordings: Recording[], dayHeightPx: number, containerWidth: number): RecordingLayout[] {
  if (recordings.length === 0 || containerWidth <= 0) return [];

  // Compute time ranges
  const withRanges = recordings.map(rec => {
    const { startMin, endMin } = getRecordingTimeRange(rec);
    const heightMin = Math.max(30, endMin - startMin);
    return { rec, startMin, endMin, heightMin };
  });

  // Sort by start time
  withRanges.sort((a, b) => a.startMin - b.startMin);

  // Union-Find to track collision chains
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
      const px = this.find(x), py = this.find(y);
      if (px === py) return;
      if (this.rank[px] < this.rank[py]) this.parent[px] = py;
      else if (this.rank[px] > this.rank[py]) this.parent[py] = px;
      else { this.parent[py] = px; this.rank[px]++; }
    }
    getMembers(x: number): number[] {
      const root = this.find(x);
      return this.parent
        .map((_, i) => this.find(i) === root ? i : -1)
        .filter(i => i >= 0);
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
        uf.union(currentIdx, i); // Merge collision chains
      }
    }

    if (colliding.length === 0) {
      numColsForRec[currentIdx] = 1;
      laneForRec[currentIdx] = 0;
    } else {
      // All recordings in the merged chain share the same numCols
      const chain = uf.getMembers(currentIdx);
      chain.forEach(idx => { numColsForRec[idx] = Math.max(numColsForRec[idx], chain.length); });
      numColsForRec[currentIdx] = chain.length;

      // Assign lane: sort chain by startMin, assign sequentially
      chain.sort((a, b) => withRanges[a].startMin - withRanges[b].startMin);
      chain.forEach((idx, pos) => { laneForRec[idx] = pos; });
    }
  });

  // Build layout entries
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
    };
  });
}

function isWeekend(dateStr: string): boolean {
  // dateStr is YYYY-MM-DD — no timezone needed for day-of-week
  const d = new Date(dateStr + 'T00:00:00');
  const day = d.getDay();
  return day === 0 || day === 6;
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);

const DayView: FC<DayViewProps> = ({ date, recordings, onRecordingClick, hourLabelPosition, onDayScroll, onMount, isRightmost }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollInitRef = useRef(false);
  const prevDateRef = useRef<string | undefined>(undefined);

  const [availableHeight, setAvailableHeight] = useState(0);
  const [containerWidth, setContainerWidth] = useState(0);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    if (onMount) onMount(date, el);

    const measured = el.clientHeight;
    const measuredWidth = el.clientWidth;
    const fullDayHeight = measured * 2;

    const hourEl = el.querySelector<HTMLElement>('.day-view-hours');
    if (hourEl) {
      hourEl.style.setProperty('--day-height-px', `${fullDayHeight}px`);
      hourEl.style.height = `${fullDayHeight}px`;
    }

    if (prevDateRef.current !== date) {
      scrollInitRef.current = false;
      prevDateRef.current = date;
    }
    if (!scrollInitRef.current && measured > 0) {
      el.scrollTop = (8 / 12) * measured;
      scrollInitRef.current = true;
    }

    setAvailableHeight(measured);
    setContainerWidth(measuredWidth);
  }, [date]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const observer = new ResizeObserver(([entry]) => {
      const measured = Math.round(entry.contentRect.height);
      const measuredWidth = Math.round(entry.contentRect.width);
      if (measured === 0) return;

      const fullDayHeight = measured * 2;
      const hourEl = el.querySelector<HTMLElement>('.day-view-hours');
      if (hourEl) {
        hourEl.style.setProperty('--day-height-px', `${fullDayHeight}px`);
        hourEl.style.height = `${fullDayHeight}px`;
      }
      setAvailableHeight(measured);
      if (measuredWidth > 0) setContainerWidth(measuredWidth);
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const handleScroll = () => {
    if (scrollRef.current && onDayScroll) {
      onDayScroll(date, scrollRef.current);
    }
  };

  const weekend = isWeekend(date);
  const dayHeightPx = availableHeight * 2;

  const layouts = computeLayout(recordings, dayHeightPx, containerWidth);
  const layoutById = new Map(layouts.map(l => [String(l.rec.id), l]));

  return (
    <div className={`day-view ${weekend ? 'weekend' : ''} ${isRightmost ? 'day-view-rightmost' : ''}`} ref={scrollRef} onScroll={handleScroll}>
      <div className="day-view-hours">
        {HOURS.map(hour => (
          <div key={hour} className="day-view-hour-row">
            {hourLabelPosition !== 'none' && (
              <span className={`hour-label hour-label-${hourLabelPosition}`}>
                {hour.toString().padStart(2, '0')}:00
              </span>
            )}
            <Separator orientation="horizontal" className="hour-grid-line" />
          </div>
        ))}

        {recordings.map(rec => {
          const layout = layoutById.get(String(rec.id));
          if (!layout) return null;
          const { top, height, left, width } = layout;
          const isLive = rec.is_live === true;
          const categoryClass = rec.category === 'work' ? 'category-work' : rec.category === 'personal' ? 'category-home' : rec.category === 'not_meaningful' ? 'category-other' : '';
          return (
            <div
              key={rec.id}
              className={`recording-block ${isLive ? 'recording-block-live' : ''} ${categoryClass}`.trim()}
              style={{ top: `${top}px`, height: `${height}px`, left: `${left}px`, width: `${width}px` }}
              onClick={() => onRecordingClick(rec.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onRecordingClick(rec.id); }}
            >
              {isLive ? (
                <div className="live-recording-content">
                  <Spinner className="size-4" />
                  <span className="live-recording-text">Recording...</span>
                </div>
              ) : (
                <div className="recording-block-content">
                  <span className="recording-block-time">
                    {format(toUTCDate(rec.timestamp), 'HH:mm')}
                  </span>
                  {rec.summary && (
                    <span className="recording-block-summary">
                      {rec.summary.substring(0, 200)}{rec.summary.length > 200 ? '…' : ''}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DayView;
