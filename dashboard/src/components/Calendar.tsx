import { useState, useEffect } from 'react';
import { format } from 'date-fns';
import { api } from '../api/client';
import RecordingList from './RecordingList';
import type { Recording, CalendarDay } from '../types';

export default function Calendar() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [calendarDays, setCalendarDays] = useState<CalendarDay[]>([]);
  const [loading, setLoading] = useState(false);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth() + 1;

  useEffect(() => {
    api.getCalendar(year, month).then((data: { dates: CalendarDay[] }) => {
      setCalendarDays(data.dates);
    });
  }, [year, month]);

  useEffect(() => {
    if (selectedDate) {
      setLoading(true);
      api.getRecordings(selectedDate).then((data: { recordings: Recording[] }) => {
        setRecordings(data.recordings);
        setLoading(false);
      });
    }
  }, [selectedDate]);

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
      {selectedDate && (
        <div className="recordings-panel">
          <h3>Recordings for {selectedDate}</h3>
          {loading ? (
            <p>Loading...</p>
          ) : recordings.length === 0 ? (
            <p>No recordings found</p>
          ) : (
            <RecordingList recordings={recordings} />
          )}
        </div>
      )}
    </div>
  );
}
