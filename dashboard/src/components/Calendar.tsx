import "react-day-picker/style.css";
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { format, parseISO, startOfISOWeek, endOfISOWeek, addDays, addWeeks } from 'date-fns';
import { useNavigate } from 'react-router-dom';
import { Calendar as ShadcnCalendar } from '@/components/ui/calendar';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Drawer, DrawerClose, DrawerContent, DrawerFooter, DrawerTrigger } from '@/components/ui/drawer';
import { useIsMobile } from '@/hooks/use-mobile';
import type { DateRange } from 'react-day-picker';
import { api } from '../api/client';
import DayView from './DayView';
import type { Recording, CalendarDay, Todo } from '../types';

function getThisWeekRange(): DateRange {
  const today = new Date();
  return { from: startOfISOWeek(today), to: endOfISOWeek(today) };
}

function getLastWeekRange(): DateRange {
  const today = new Date();
  const lastWeek = addWeeks(today, -1);
  return { from: startOfISOWeek(lastWeek), to: endOfISOWeek(lastWeek) };
}

export default function Calendar() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  const [selected, setSelected] = useState<DateRange | undefined>(getThisWeekRange());
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const [recordingsByDate, setRecordingsByDate] = useState<Map<string, Recording[]>>(new Map());
  const [activeRecording, setActiveRecording] = useState<Recording | null>(null);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [dayTodos, setDayTodos] = useState<Todo[]>([]);
  const [currentMonth, setCurrentMonth] = useState(() => new Date());
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'work' | 'personal' | 'not_meaningful'>('all');

  // Shared scroll manager: all day-view scroll els registered here
  const scrollElsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  // Track which column the user last scrolled, to ignore synthetic scroll events from sync
  const lastScrolledRef = useRef<string | null>(null);

  const handleDayViewMount = useCallback((date: string, el: HTMLDivElement) => {
    scrollElsRef.current.set(date, el);
  }, []);

  const handleDayViewScroll = useCallback((date: string, el: HTMLDivElement) => {
    // Ignore scroll events from columns we programmatically scrolled (feedback loop guard)
    if (lastScrolledRef.current === date) {
      lastScrolledRef.current = null;
      return;
    }
    const scrollTop = el.scrollTop;
    lastScrolledRef.current = date;
    for (const [otherDate, otherEl] of scrollElsRef.current) {
      if (otherDate !== date && otherEl) {
        otherEl.scrollTop = scrollTop;
      }
    }
  }, []);

  // Build ordered array of selected date strings — memoized so useEffect deps are stable.
  const fromTime = selected?.from instanceof Date ? selected.from.getTime() : undefined;
  const toTime = selected?.to instanceof Date ? selected.to.getTime() : undefined;
  const selectedDates = useMemo(() => {
    if (!selected?.from || !selected?.to) return [] as string[];
    const dates: string[] = [];
    let d = selected.from;
    while (d <= selected.to) {
      dates.push(format(d, 'yyyy-MM-dd'));
      d = addDays(d, 1);
    }
    return dates;
  }, [fromTime, toTime]);

  // Fetch booked dates for current month view
  useEffect(() => {
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth() + 1;
    api.getCalendar(year, month).then((data: { dates: CalendarDay[] }) => {
      setCalendarDays(data.dates);
    });
  }, [currentMonth]);

  // Fetch recordings for all selected dates in parallel
  useEffect(() => {
    Promise.all(selectedDates.map(date => api.getRecordings(date, categoryFilter === 'all' ? undefined : categoryFilter)))
      .then(results => {
        const map = new Map<string, Recording[]>();
        selectedDates.forEach((date, i) => {
          map.set(date, results[i].recordings ?? []);
        });
        setRecordingsByDate(map);
        setLoading(false);
      })
  }, [selectedDates, categoryFilter]);
  // Load todos for the first selected date
  useEffect(() => {
    if (selectedDates.length === 0) return;
    api.getTodosForDate(selectedDates[0]).then((data: { todos: Todo[] }) => {
      setDayTodos(data.todos);
    }).catch(() => setDayTodos([]));
  }, [selectedDates]);

  // Active recording polling
  const loadActive = useCallback(() => {
    api.getActiveRecording().then(setActiveRecording).catch(() => setActiveRecording(null));
  }, []);

  useEffect(() => { loadActive(); }, [loadActive]);

  useEffect(() => {
    const interval = setInterval(loadActive, 5000);
    return () => clearInterval(interval);
  }, [loadActive]);

  const bookedDates = useMemo(() =>
    new Set(calendarDays.filter(d => d.count > 0).map(d => d.date)),
    [calendarDays]
  );

  // react-day-picker v10 calls onSelect with 4 args
  function handleSelect(
    range: DateRange | undefined,
    _triggerDate: Date,
    _modifiers: unknown,
    _e: React.MouseEvent | React.KeyboardEvent
  ) {
    if (!range) { setSelected(undefined); return; }
    let { from, to } = range;
    if (!from) { setSelected(undefined); return; }
    const prevFrom = selectedRef.current?.from;
    const prevTo = selectedRef.current?.to;
    if (prevFrom instanceof Date && prevTo instanceof Date) {
      const dayDiff = (prevFrom.getTime() - from.getTime()) / 86_400_000;
      const fromEqualsPrevFrom = from.getTime() === prevFrom.getTime();
      if (fromEqualsPrevFrom && to && to < prevTo) {
        // Clicked a date within the old range (from = prevFrom, to is between prevFrom and prevTo)
        // e.g. Aug31-Sep6 clicked on Sep1 → range=Aug31-Sep1, from=prevFrom, to<prevTo
        // → Reset to to so the user gets a fresh single-day from the clicked date
        from = to;
        to = to;
      } else if (dayDiff > 3) {
        // Clicked more than 3 days before the previous from: fresh start
        to = from;
      }
    }
    if (to) {
      const maxTo = addDays(from, 6);
      if (to > maxTo) { to = maxTo; }
    }
    const next = { from, to };
    setSelected(next);
    selectedRef.current = next;
  }

  function handlePreset(preset: 'today' | 'yesterday' | 'this-week' | 'last-week') {
    const today = new Date();
    switch (preset) {
      case 'today': {
        const next = { from: today, to: today };
        setSelected(next);
        selectedRef.current = next;
        break;
      }
      case 'yesterday': {
        const yesterday = addDays(today, -1);
        const next = { from: yesterday, to: yesterday };
        setSelected(next);
        selectedRef.current = next;
        break;
      }
      case 'this-week': {
        const next = getThisWeekRange();
        setSelected(next);
        selectedRef.current = next;
        break;
      }
      case 'last-week': {
        const next = getLastWeekRange();
        setSelected(next);
        selectedRef.current = next;
        break;
      }
    }
  }

  function handleToggleTodo(todo: Todo) {
    const newCompleted = !todo.completed;
    api.completeTodo(todo.id, newCompleted).then(() => {
      setDayTodos(prev =>
        prev.map(t =>
          t.id === todo.id
            ? { ...t, completed: newCompleted, completed_at: newCompleted ? new Date().toISOString() : null }
            : t
        )
      );
    });
  }

  function handleDeleteTodo(todoId: number) {
    api.deleteTodo(todoId).then(() => {
      setDayTodos(prev => prev.filter(t => t.id !== todoId));
    });
  }

  const sidebarContent = (
    <div className="calendar-sidebar">
      <ShadcnCalendar
        mode="range"
        selected={selected}
        onSelect={handleSelect}
        numberOfMonths={1}
        onMonthChange={setCurrentMonth}
        modifiers={{ booked: (date) => bookedDates.has(format(date, 'yyyy-MM-dd')) }}
        modifiersClassNames={{ booked: 'has-recording-dot' }}
        className="calendar-component"
      />

      {activeRecording && (
        <div className="active-recording-panel">
          <h3>Recording in progress</h3>
          <DayView
            date={activeRecording.timestamp?.split('T')[0] ?? ''}
            recordings={[activeRecording]}
            onRecordingClick={(id) => navigate(`/recording/${id}`)}
            hourLabelPosition="left"
          />
        </div>
      )}

      {dayTodos.length > 0 && (
        <div className="day-todos">
          <h3>TODOs for {selectedDates[0]}</h3>
          <ul>
            {dayTodos.map(todo => (
              <li
                key={todo.id}
                className={`priority-${todo.priority} ${todo.completed ? 'completed' : ''}`}
              >
                <input
                  type="checkbox"
                  className="todo-checkbox"
                  checked={todo.completed}
                  onChange={() => handleToggleTodo(todo)}
                />
                <span className="todo-task">{todo.task}</span>
                <span> - {todo.owner}</span>
                {todo.due && <span> (due: {todo.due})</span>}
                <span className="priority-badge">{todo.priority}</span>
                <button
                  className="todo-delete"
                  onClick={() => handleDeleteTodo(todo.id)}
                  aria-label={`Delete todo: ${todo.task}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );

  return (
    <div className="calendar-view">
      {/* Preset quick-select buttons */}
      <div className="calendar-presets">
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => handlePreset('today')}>Today</Button>
          <Button variant="outline" size="sm" onClick={() => handlePreset('yesterday')}>Yesterday</Button>
          <Button variant="outline" size="sm" onClick={() => handlePreset('this-week')}>This Week</Button>
          <Button variant="outline" size="sm" onClick={() => handlePreset('last-week')}>Last Week</Button>
        </div>
        <div className="flex gap-1">
          <Button variant={categoryFilter === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('all')}>Both</Button>
          <Button variant={categoryFilter === 'work' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('work')}>Work</Button>
          <Button variant={categoryFilter === 'personal' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('personal')}>Home</Button>
          <Button variant={categoryFilter === 'not_meaningful' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('not_meaningful')}>Other</Button>
        </div>
      </div>

      {isMobile ? (
        <Drawer>
          <DrawerTrigger asChild>
            <Button variant="outline">Open Calendar</Button>
          </DrawerTrigger>
          <DrawerContent>
            <div className="p-4">{sidebarContent}</div>
            <DrawerFooter>
              <DrawerClose asChild>
                <Button variant="outline">Close</Button>
              </DrawerClose>
            </DrawerFooter>
          </DrawerContent>
        </Drawer>
      ) : (
        <div className="calendar-body">
          <div className="calendar-sidebar-wrap">
            <Separator orientation="vertical" className="sidebar-divider" />
            {sidebarContent}
          </div>

          {/* Day view stack */}
          <div className="day-views-scroll">
            {loading ? (
              <p>Loading...</p>
            ) : selectedDates.length === 0 ? (
              <p>Select a date range to view recordings</p>
            ) : (
              <div className="day-views-row">
                {[...selectedDates].sort().map((date, i) => {
                  const isLeftmost = i === 0;
                  const isRightmost = i === selectedDates.length - 1;
                  const hourLabelPosition: 'left' | 'right' | 'none' =
                    selectedDates.length === 1
                      ? 'left'
                      : (isLeftmost ? 'left' : isRightmost ? 'right' : 'none');
                  return (
                    <div key={date} className="day-view-column">
                      <div className="day-view-header">
                        {format(parseISO(date), 'EEE, MMM d')}
                      </div>
                      <DayView
                        date={date}
                        recordings={recordingsByDate.get(date) ?? []}
                        onRecordingClick={(id) => navigate(`/recording/${id}`)}
                        hourLabelPosition={hourLabelPosition}
                        onMount={handleDayViewMount}
                        onDayScroll={handleDayViewScroll}
                        isRightmost={isRightmost}
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
