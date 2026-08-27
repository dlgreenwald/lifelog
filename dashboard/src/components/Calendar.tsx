import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { format, parse } from 'date-fns';
import { api } from '../api/client';
import RecordingList from './RecordingList';
import type { Recording, CalendarDay, Todo } from '../types';

/** Safely render a daily summary value that may be a nested object. */
function renderSummaryValue(val: unknown): string {
  if (typeof val === 'string') return val;
  if (typeof val === 'object' && val !== null && 'summary' in val) {
    const s = (val as Record<string, unknown>).summary;
    if (typeof s === 'string') return s;
  }
  return String(val ?? '');
}

export default function Calendar() {
  const [searchParams, setSearchParams] = useSearchParams();
  const today = format(new Date(), 'yyyy-MM-dd');
  const todayMonth = format(new Date(), 'yyyy-MM');

  const selectedDate = searchParams.get('date') ?? today;
  const currentMonthParam = searchParams.get('month') ?? todayMonth;
  const [currentDate, setCurrentDate] = useState(() => parse(currentMonthParam, 'yyyy-MM', new Date()));

  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [activeRecording, setActiveRecording] = useState<Recording | null>(null);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [dailySummary, setDailySummary] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [dayTodos, setDayTodos] = useState<Todo[]>([]);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth() + 1;

  useEffect(() => {
    api.getCalendar(year, month).then((data: { dates: CalendarDay[] }) => {
      setCalendarDays(data.dates);
    });
  }, [year, month]);

  useEffect(() => {
    const parsed = parse(currentMonthParam, 'yyyy-MM', new Date());
    setCurrentDate(prev => {
      if (format(prev, 'yyyy-MM') !== currentMonthParam) return parsed;
      return prev;
    });
  }, [currentMonthParam]);

  const loadActive = useCallback(() => {
    api.getActiveRecording().then(setActiveRecording).catch(() => setActiveRecording(null));
  }, []);

  useEffect(() => { loadActive(); }, [loadActive]);

  // Auto-refresh active recording
  useEffect(() => {
    const interval = setInterval(loadActive, 5000);
    return () => clearInterval(interval);
  }, [loadActive]);

  useEffect(() => {
    if (selectedDate) {
      setLoading(true);
      setDailySummary(null);
      setDayTodos([]);
      api.getRecordings(selectedDate, categoryFilter ?? undefined).then((data: { recordings: Recording[] }) => {
        setRecordings(data.recordings);
        setLoading(false);
      });
      api.getDailySummary(selectedDate).then((data: { daily_summary: { daily_summary: Record<string, string> } | null }) => {
        const raw = data.daily_summary?.daily_summary ?? null;
        // LLM may return a string instead of a structured object; normalize for Object.entries()
        setDailySummary(typeof raw === 'string' ? { 'Summary': raw } : raw);
      }).catch(() => setDailySummary(null));
      api.getTodosForDate(selectedDate).then((data: { todos: Todo[] }) => {
        setDayTodos(data.todos);
      }).catch(() => setDayTodos([]));
    }
  }, [selectedDate, categoryFilter]);

  const handlePrevMonth = () => {
    const newDate = new Date(year, month - 2, 1);
    setCurrentDate(newDate);
    setSearchParams(prev => { prev.set('month', format(newDate, 'yyyy-MM')); return prev; });
  };

  const handleNextMonth = () => {
    const newDate = new Date(year, month, 1);
    setCurrentDate(newDate);
    setSearchParams(prev => { prev.set('month', format(newDate, 'yyyy-MM')); return prev; });
  };

  const handleDateClick = (day: number) => {
    const dateStr = format(new Date(year, month - 1, day), 'yyyy-MM-dd');
    setSearchParams(prev => { prev.set('date', dateStr); return prev; });
  };

  const handleToggleTodo = async (todo: Todo) => {
    const newCompleted = !todo.completed;
    await api.completeTodo(todo.id, newCompleted);
    setDayTodos(prev =>
      prev.map(t =>
        t.id === todo.id
          ? { ...t, completed: newCompleted, completed_at: newCompleted ? new Date().toISOString() : null }
          : t
      )
    );
  };

  const handleDeleteTodo = async (todoId: number) => {
    await api.deleteTodo(todoId);
    setDayTodos(prev => prev.filter(t => t.id !== todoId));
  };

  const daysInMonth = new Date(year, month, 0).getDate();
  const firstDayOfMonth = new Date(year, month - 1, 1).getDay();

  const calendarDaysList = [];
  for (let i = 0; i < firstDayOfMonth; i++) {
    calendarDaysList.push(<div key={`empty-${i}`} className="calendar-day empty" />);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = format(new Date(year, month - 1, day), 'yyyy-MM-dd');
    const hasRecording = calendarDays.some((d) => d.date === dateStr);
    calendarDaysList.push(
      <div
        key={day}
        className={`calendar-day ${hasRecording ? 'has-recording' : ''} ${
          selectedDate === dateStr ? 'selected' : ''
        }`}
        onClick={() => handleDateClick(day)}
      >
        {day}
        {hasRecording && <div className="recording-dot" />}
      </div>
    );
  }

  return (
    <div className="calendar-view">
      <div className="calendar-header">
        <button onClick={handlePrevMonth}>←</button>
        <h2>
          {format(currentDate, 'MMMM yyyy')}
        </h2>
        <button onClick={handleNextMonth}>→</button>
      </div>
      <div className="calendar-grid">
        <div className="calendar-weekday">Sun</div>
        <div className="calendar-weekday">Mon</div>
        <div className="calendar-weekday">Tue</div>
        <div className="calendar-weekday">Wed</div>
        <div className="calendar-weekday">Thu</div>
        <div className="calendar-weekday">Fri</div>
        <div className="calendar-weekday">Sat</div>
        {calendarDaysList}
      </div>

      {activeRecording && (
        <div className="recordings-panel active-recording">
          <h3>🎙️ Recording in progress</h3>
          <RecordingList recordings={[activeRecording]} />
        </div>
      )}

      {selectedDate && (
        <div className="recordings-panel">
          {dailySummary && Object.keys(dailySummary).length > 0 && (
            <div className="daily-summary">
              <h3>Daily Summary</h3>
              {Object.entries(dailySummary).map(([section, text]) => (
                <div key={section}>
                  <h4>{section}</h4>
                  <p style={{ whiteSpace: 'pre-wrap' }}>{renderSummaryValue(text)}</p>
                </div>
              ))}
            </div>
          )}
          <div className="recordings-list">
            <h3>Recordings for {selectedDate}</h3>
            <div className="category-filter">
              <button
                className={categoryFilter === null ? 'active' : ''}
                onClick={() => setCategoryFilter(null)}
              >
                Both
              </button>
              <button
                className={categoryFilter === 'work' ? 'active' : ''}
                onClick={() => setCategoryFilter('work')}
              >
                Work
              </button>
              <button
                className={categoryFilter === 'personal' ? 'active' : ''}
                onClick={() => setCategoryFilter('personal')}
              >
                Personal
              </button>
              <button
                className={categoryFilter === 'not_meaningful' ? 'active' : ''}
                onClick={() => setCategoryFilter('not_meaningful')}
              >
                Other
              </button>
            </div>
            {loading ? (
              <p>Loading...</p>
            ) : recordings.length === 0 ? (
              <p>No recordings found</p>
            ) : (
              <RecordingList recordings={recordings} />
            )}
          </div>
          {dayTodos.length > 0 && (
            <div className="day-todos">
              <h3>TODOs for {selectedDate}</h3>
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
      )}
    </div>
  );
}
