import { useState, useEffect, useCallback } from 'react';
import { format } from 'date-fns';
import { api } from '../api/client';
import RecordingList from './RecordingList';
import type { Recording, CalendarDay } from '../types';

export default function Calendar() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [activeRecording, setActiveRecording] = useState<Recording | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [dailySummary, setDailySummary] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth() + 1;

  useEffect(() => {
    api.getCalendar(year, month).then((data: { dates: CalendarDay[] }) => {
      setCalendarDays(data.dates);
    });
  }, [year, month]);

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
      api.getRecordings(selectedDate, categoryFilter ?? undefined).then((data: { recordings: Recording[] }) => {
        setRecordings(data.recordings);
        setLoading(false);
      });
      api.getDailySummary(selectedDate).then((data: { daily_summary: { daily_summary: Record<string, string> } | null }) => {
        setDailySummary(data.daily_summary?.daily_summary ?? null);
      }).catch(() => setDailySummary(null));
    }
  }, [selectedDate, categoryFilter]);

  const handlePrevMonth = () => {
    setCurrentDate(new Date(year, month - 2, 1));
  };

  const handleNextMonth = () => {
    setCurrentDate(new Date(year, month, 1));
  };

  const handleDateClick = (day: number) => {
    const dateStr = format(new Date(year, month - 1, day), 'yyyy-MM-dd');
    setSelectedDate(dateStr);
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
                  <p style={{ whiteSpace: 'pre-wrap' }}>{text}</p>
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
        </div>
      )}
    </div>
  );
}
