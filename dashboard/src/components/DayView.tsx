import { useEffect, useLayoutEffect, useRef, useState, type FC } from 'react';
import { format, parseISO } from 'date-fns';
import { Separator } from '@/components/ui/separator';
import { Spinner } from '@/components/ui/spinner';
import type { Recording } from '../types';

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
  const recDate = parseISO(rec.timestamp);
  const startMin = Math.max(0, recDate.getHours() * 60 + recDate.getMinutes());

  let durationMinutes = 30;
  if (rec.audio_range_start && rec.audio_range_end) {
    const s = parseISO(rec.audio_range_start);
    const e = parseISO(rec.audio_range_end);
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
 * Single recording takes full width; 2+ overlapping recordings are lane-allocated.
 */
function computeLayout(recordings: Recording[], dayHeightPx: number, containerWidth: number): RecordingLayout[] {
  if (recordings.length === 0 || containerWidth <= 0) return [];

  // Single recording: take full width
  if (recordings.length === 1) {
    const rec = recordings[0];
    const { startMin, endMin } = getRecordingTimeRange(rec);
    const heightMin = Math.max(30, Math.min(endMin - startMin, 120));
    return [{
      rec,
      top: (startMin / 1440) * dayHeightPx,
      height: (heightMin / 1440) * dayHeightPx,
      left: GUTTER,
      width: containerWidth - GUTTER * 2,
    }];
  }

  // Compute time ranges for all recordings
  const withRanges = recordings.map(rec => {
    const { startMin, endMin } = getRecordingTimeRange(rec);
    const heightMin = Math.max(30, Math.min(endMin - startMin, 120));
    return { rec, startMin, endMin, heightMin };
  });

  // Sort by start time
  withRanges.sort((a, b) => a.startMin - b.startMin);

  // Lane algorithm: track end time of last recording in each lane
  const lanes: Array<{ endMin: number }> = [];

  return withRanges.map(({ rec, startMin, endMin, heightMin }) => {
    // Find first lane that doesn't overlap the lane's last recording
    let laneIdx = lanes.findIndex(l => l.endMin <= startMin);
    if (laneIdx === -1) {
      laneIdx = lanes.length;
      lanes.push({ endMin });
    } else {
      lanes[laneIdx].endMin = endMin;
    }

    const numCols = lanes.length;
    const colWidth = (containerWidth - GUTTER * 2) / numCols;
    const left = laneIdx * colWidth + GUTTER;

    return {
      rec,
      top: (startMin / 1440) * dayHeightPx,
      height: (heightMin / 1440) * dayHeightPx,
      left,
      width: colWidth - GUTTER * 2,
    };
  });
}

function isWeekend(dateStr: string): boolean {
  const d = parseISO(dateStr);
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
          return (
            <div
              key={rec.id}
              className={`recording-block ${isLive ? 'recording-block-live' : ''}`}
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
                    {format(parseISO(rec.timestamp), 'HH:mm')}
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
