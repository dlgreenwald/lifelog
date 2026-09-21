import { useEffect, useLayoutEffect, useRef, useState, type FC } from 'react';
import { format } from 'date-fns';
import { Separator } from '@/components/ui/separator';
import { Spinner } from '@/components/ui/spinner';
import type { Recording } from '../types';
import { toUTCDate } from '../utils/format';
import {
  computeLayout,
  isWeekend,
  HOURS,
} from '../utils/layout';

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
          const categoryClass = rec.category === 'work' ? 'category-work' : rec.category === 'personal' ? 'category-home' : rec.category === 'not_meaningful' ? 'category-other' : 'category-other';
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
                    {format(toUTCDate(rec.timestamp), 'HH:mm')} {rec.title}
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
