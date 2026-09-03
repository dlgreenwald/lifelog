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

function getRecordingPosition(rec: Recording, dayHeightPx: number): { top: number; height: number } {
  const recDate = parseISO(rec.timestamp);
  const startMinutes = Math.max(0, recDate.getHours() * 60 + recDate.getMinutes());

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

  const topMinutes = Math.min(startMinutes, 24 * 60 - 1);
  const heightMinutes = Math.max(5, Math.min(durationMinutes, 120));

  return {
    top: (topMinutes / 1440) * dayHeightPx,
    height: (heightMinutes / 1440) * dayHeightPx,
  };
}

function isWeekend(dateStr: string): boolean {
  const d = parseISO(dateStr);
  const day = d.getDay();
  return day === 0 || day === 6;
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);

const DayView: FC<DayViewProps> = ({ date, recordings, onRecordingClick, hourLabelPosition, onDayScroll, onMount, isRightmost }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Use state so a re-render happens once we have the measured height.
  // useLayoutEffect runs synchronously before paint — no flash of wrong position.
  const [availableHeight, setAvailableHeight] = useState(0);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    if (onMount) onMount(date, el);

    const measured = el.clientHeight;
    const fullDayHeight = measured * 2;

    const hourEl = el.querySelector<HTMLElement>('.day-view-hours');
    if (hourEl) {
      hourEl.style.setProperty('--day-height-px', `${fullDayHeight}px`);
      hourEl.style.height = `${fullDayHeight}px`;
    }

    // Show 8am at top of visible window (8/12 of the way through the day)
    if (measured > 0) {
      el.scrollTop = (8 / 12) * measured;
    }

    setAvailableHeight(measured);
  }, [date]);

  // Track height changes (e.g. window resize)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const observer = new ResizeObserver(([entry]) => {
      const measured = Math.round(entry.contentRect.height);
      if (measured === 0) return;

      const fullDayHeight = measured * 2;
      const hourEl = el.querySelector<HTMLElement>('.day-view-hours');
      if (hourEl) {
        hourEl.style.setProperty('--day-height-px', `${fullDayHeight}px`);
        hourEl.style.height = `${fullDayHeight}px`;
      }
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

        {/* Recording blocks — absolute positioned within .day-view-hours */}
        {recordings.map(rec => {
          const { top, height } = getRecordingPosition(rec, dayHeightPx);
          const isLive = rec.is_live === true;
          return (
            <div
              key={rec.id}
              className={`recording-block ${isLive ? 'recording-block-live' : ''}`}
              style={{ top: `${top}px`, height: `${height}px` }}
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
                      {rec.summary.substring(0, 60)}{rec.summary.length > 60 ? '…' : ''}
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
