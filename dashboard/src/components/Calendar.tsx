import "react-day-picker/style.css";
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { format, parseISO, startOfISOWeek, endOfISOWeek, addDays, addWeeks } from 'date-fns';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Calendar as ShadcnCalendar } from '@/components/ui/calendar';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Separator } from '@/components/ui/separator';

import { useIsMobile } from '@/hooks/use-mobile';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@/components/ui/table';
import type { DateRange } from 'react-day-picker';
import { api } from '../api/client';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCalendar, faCheckSquare, faLightbulb, faUsers, faCog } from '@fortawesome/free-solid-svg-icons';
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
  const [searchParams, setSearchParams] = useSearchParams();

  // Initialize selected from URL params or default to this week
  const getInitialSelected = (): DateRange => {
    const from = searchParams.get('from');
    const to = searchParams.get('to');
    if (from && to) {
      const fromDate = parseISO(from);
      const toDate = parseISO(to);
      if (!isNaN(fromDate.getTime()) && !isNaN(toDate.getTime())) {
        return { from: fromDate, to: toDate };
      }
    }
    return getThisWeekRange();
  };
  const [selected, setSelectedState] = useState<DateRange | undefined>(getInitialSelected);
  // Separate state for mobile single-day selection
  const [selectedDay, setSelectedDay] = useState<Date | undefined>(
    getInitialSelected()?.from
  );
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  // Sync selected state with URL
  const setSelected = useCallback((range: DateRange | undefined) => {
    setSelectedState(range);
    if (range?.from && range?.to) {
      const params = new URLSearchParams();
      params.set('from', format(range.from, 'yyyy-MM-dd'));
      params.set('to', format(range.to, 'yyyy-MM-dd'));
      setSearchParams(params, { replace: true });
    }
  }, [setSearchParams]);

  // Sync state with URL on back/forward navigation
  useEffect(() => {
    const from = searchParams.get('from');
    const to = searchParams.get('to');
    if (from && to) {
      const fromDate = parseISO(from);
      const toDate = parseISO(to);
      if (!isNaN(fromDate.getTime()) && !isNaN(toDate.getTime())) {
        setSelectedState({ from: fromDate, to: toDate });
      }
    }
  }, [searchParams]);

  // Sync mobile single-day selection with range when switching views
  useEffect(() => {
    if (!isMobile && selected?.from) {
      // Switching to desktop - sync selectedDay to range's from
      setSelectedDay(selected.from);
    }
  }, [isMobile, selected?.from]);

  const [recordingsByDate, setRecordingsByDate] = useState<Map<string, Recording[]>>(new Map());
  const [activeRecording, setActiveRecording] = useState<Recording | null>(null);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [todosByDate, setTodosByDate] = useState<{ date: string; todos: Todo[] }[]>([]);
  const [incompleteTodoDates, setIncompleteTodoDates] = useState<Set<string>>(new Set());
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'work' | 'personal' | 'not_meaningful'>('all');
  const [currentMonth, setCurrentMonth] = useState(() => new Date());

  // Active recording polling
  const loadActive = useCallback(() => {
    api.getActiveRecording().then(setActiveRecording).catch(() => setActiveRecording(null));
  }, []);
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

  // Fetch incomplete todos for the entire visible month (for dot indicators)
  useEffect(() => {
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth() + 1;
    // Get all days in the month for dot indicators
    const daysInMonth = new Date(year, month, 0).getDate();
    const dates = Array.from({ length: daysInMonth }, (_, i) => {
      const d = new Date(year, month - 1, i + 1);
      return format(d, 'yyyy-MM-dd');
    });
    Promise.all(dates.map(date => api.getTodosForDate(date)))
      .then(results => {
        const incomplete = new Set<string>();
        dates.forEach((date, i) => {
          const todos: Todo[] = results[i].todos ?? [];
          if (todos.some((t: Todo) => !t.completed)) {
            incomplete.add(date);
          }
        });
        setIncompleteTodoDates(incomplete);
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
      });
  }, [selectedDates, categoryFilter]);

  // Merge active recording into the correct day's recordings so it shows as a block in the day view
  useEffect(() => {
    setRecordingsByDate(prev => {
      const next = new Map(prev);
      if (activeRecording) {
        const date = activeRecording.timestamp.split('T')[0];
        const existing = next.get(date) ?? [];
        const filtered = existing.filter(r => r.id !== activeRecording.id);
        next.set(date, [...filtered, activeRecording]);
      }
      return next;
    });
  }, [activeRecording]);

  // Load todos for all selected dates
  useEffect(() => {
    if (selectedDates.length === 0) return;
    Promise.all(selectedDates.map(date => api.getTodosForDate(date)))
      .then(results => {
        const grouped = selectedDates.map((date, i) => ({
          date,
          todos: results[i].todos ?? [],
        })).filter(g => g.todos.length > 0);
        setTodosByDate(grouped);
      })
      .catch(() => { setTodosByDate([]); });
  }, [selectedDates]);
  // Active recording polling
  useEffect(() => { loadActive(); }, [loadActive]);
  useEffect(() => {
    const interval = setInterval(loadActive, 5000);
    return () => clearInterval(interval);
  }, [loadActive]);

  const bookedDates = useMemo(() =>
    new Set(calendarDays.filter(d => d.count > 0).map(d => d.date)),
    [calendarDays]
  );

  // Track dates with incomplete todos for dot indicator
  const todoDates = useMemo(() =>
    incompleteTodoDates,
    [incompleteTodoDates]
  );

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
      setTodosByDate(prev =>
        prev.map(group => ({
          ...group,
          todos: group.todos.map(t =>
            t.id === todo.id
              ? { ...t, completed: newCompleted, completed_at: newCompleted ? new Date().toISOString() : null }
              : t
          ),
        }))
      );
    });
  }

  // Calendar only (for mobile drawer)
  // In mobile, use single day selection; in desktop, use range selection
  const handleMobileSelect = (day: Date | undefined) => {
    if (day) {
      setSelectedDay(day);
      setSelectedState({ from: day, to: day });
    }
  };

  // Mobile calendar - single day selection
  const mobileCalendar = (
    <div className="calendar-sidebar">
      <ShadcnCalendar
        mode="single"
        selected={selectedDay}
        onSelect={handleMobileSelect}
        numberOfMonths={1}
        onMonthChange={setCurrentMonth}
        modifiers={{
          booked: (date) => bookedDates.has(format(date, 'yyyy-MM-dd')),
          todo: (date) => todoDates.has(format(date, 'yyyy-MM-dd')),
        }}
        modifiersClassNames={{
          booked: 'has-recording-dot',
          todo: 'has-todo-dot',
        }}
        className="w-full h-full"
        classNames={{
          months: 'flex w-full flex-col flex-1',
          month: 'w-full flex flex-col',
          week: 'flex w-full',
        }}
      />
    </div>
  );

  // Desktop calendar - range selection
  const desktopCalendar = (
    <div className="calendar-sidebar">
      <ShadcnCalendar
        mode="range"
        selected={selected}
        onSelect={setSelected}
        numberOfMonths={1}
        onMonthChange={setCurrentMonth}
        modifiers={{
          booked: (date) => bookedDates.has(format(date, 'yyyy-MM-dd')),
          todo: (date) => todoDates.has(format(date, 'yyyy-MM-dd')),
        }}
        modifiersClassNames={{
          booked: 'has-recording-dot',
          todo: 'has-todo-dot',
        }}
        className="w-full h-full"
        classNames={{
          months: 'flex w-full flex-col flex-1',
          month: 'w-full flex flex-col',
          week: 'flex w-full',
        }}
      />
    </div>
  );

  const calendarInDrawer = isMobile ? mobileCalendar : desktopCalendar;

  // Full sidebar content (calendar + todos - for desktop)
  const sidebarContent = (
    <div className="calendar-sidebar">
      <ShadcnCalendar
        mode="range"
        selected={selected}
        onSelect={setSelected}
        numberOfMonths={1}
        onMonthChange={setCurrentMonth}
        modifiers={{
          booked: (date) => bookedDates.has(format(date, 'yyyy-MM-dd')),
          todo: (date) => todoDates.has(format(date, 'yyyy-MM-dd')),
        }}
        modifiersClassNames={{
          booked: 'has-recording-dot',
          todo: 'has-todo-dot',
        }}
      />

      {todosByDate.length > 0 && (
        <div className="day-todos">
          {todosByDate.map(({ date, todos }) => (
            <div key={date} className="todo-date-group">
              <h3>{format(parseISO(date), 'EEEE, MMM d')}</h3>
              <div className="todo-table-container">
                <Table>
                  <TableBody>
                    {todos.map(todo => (
                      <TableRow
                        key={todo.id}
                        className={todo.completed ? 'completed' : ''}
                      >
                        <TableCell className="w-8">
                          <Checkbox
                            id={`todo-${todo.id}-checkbox`}
                            checked={todo.completed}
                            onCheckedChange={() => handleToggleTodo(todo)}
                          />
                        </TableCell>
                        <TableCell className={todo.completed ? 'line-through text-muted-foreground' : 'font-medium'}>
                          {todo.task}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="calendar-view">
      {/* Preset quick-select buttons */}
      <div className="calendar-presets">
        <ButtonGroup orientation="horizontal">
          <Button variant="outline" size="sm" onClick={() => handlePreset('yesterday')}>Yesterday</Button>
          <Button variant="outline" size="sm" onClick={() => handlePreset('today')}>Today</Button>
          {!isMobile && (
            <>
              <Button variant="outline" size="sm" onClick={() => handlePreset('this-week')}>This Week</Button>
              <Button variant="outline" size="sm" onClick={() => handlePreset('last-week')}>Last Week</Button>
            </>
          )}
        </ButtonGroup>
        <ButtonGroup orientation="horizontal">
          <Button variant={categoryFilter === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('all')}>Both</Button>
          <Button variant={categoryFilter === 'work' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('work')}>Work</Button>
          <Button variant={categoryFilter === 'personal' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('personal')}>Home</Button>
          {!isMobile && (
            <Button variant={categoryFilter === 'not_meaningful' ? 'default' : 'outline'} size="sm" onClick={() => setCategoryFilter('not_meaningful')}>Other</Button>
          )}
        </ButtonGroup>
      </div>

      {isMobile ? (
        <div className="calendar-body calendar-body-mobile">
          {/* Day view stack - always visible on mobile */}
          <div className="day-views-scroll" style={{ flex: 1 }}>
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
          {/* Backdrop - click to close */}
          {calendarOpen && (
            <div className="mobile-calendar-backdrop" onClick={() => setCalendarOpen(false)} />
          )}
          {/* Slide-up calendar panel - appears above footer */}
          <div className={`mobile-calendar-panel ${calendarOpen ? 'open' : ''}`}>
            <div className="mobile-calendar-panel-content">
              {calendarInDrawer}
            </div>
          </div>
          {/* Bottom navigation bar for mobile */}
          <nav className="mobile-nav-bar">
            <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => setCalendarOpen(!calendarOpen)}>
              <FontAwesomeIcon icon={faCalendar} />
              <span>Calendar</span>
            </Button>
            <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/todos')}>
              <FontAwesomeIcon icon={faCheckSquare} />
              <span>TODOs</span>
            </Button>
            <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/decisions')}>
              <FontAwesomeIcon icon={faLightbulb} />
              <span>Decisions</span>
            </Button>
            <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/speakers')}>
              <FontAwesomeIcon icon={faUsers} />
              <span>Speakers</span>
            </Button>
            <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/settings')}>
              <FontAwesomeIcon icon={faCog} />
              <span>Settings</span>
            </Button>
          </nav>
        </div>
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
