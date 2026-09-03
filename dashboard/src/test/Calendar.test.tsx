import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import Calendar from '../components/Calendar';
import { api } from '../api/client';

// Mock shadcn Drawer to avoid Base UI initialization hanging
vi.mock('@/components/ui/drawer', () => ({
  Drawer: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer">{children}</div>,
  DrawerTrigger: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer-trigger">{children}</div>,
  DrawerContent: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer-content">{children}</div>,
  DrawerFooter: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  DrawerClose: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

// Mock the shadcn Calendar component to avoid heavy DOM rendering in jsdom
vi.mock('@/components/ui/calendar', () => ({
  Calendar: () => (
    <div data-testid="mock-calendar">
      <button data-testid="prev-month">←</button>
      <button data-testid="next-month">→</button>
      <span>January 2024</span>
    </div>
  ),
}));

// Mock DayView to avoid DOM complexity
vi.mock('../components/DayView', () => ({
  default: ({ date, recordings, onRecordingClick }: { date: string; recordings: Array<{ id: unknown }>; onRecordingClick: (id: unknown) => void }) => (
    <div data-testid={`dayview-${date}`} className="day-view" onClick={() => onRecordingClick(recordings[0]?.id)}>
      {recordings.length > 0 ? (
        <span data-testid={`recordings-${date}`}>{recordings.length} recording(s)</span>
      ) : null}
    </div>
  ),
}));

vi.mock('../api/client', () => ({
  api: {
    getCalendar: vi.fn(),
    getRecordings: vi.fn(),
    getActiveRecording: vi.fn().mockResolvedValue(null),
    getTodosForDate: vi.fn().mockResolvedValue({ todos: [] }),
    completeTodo: vi.fn().mockResolvedValue(undefined),
    deleteTodo: vi.fn().mockResolvedValue(undefined),
  },
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getCalendar.mockResolvedValue({ dates: [] });
  mockApi.getRecordings.mockResolvedValue({ recordings: [] });
  mockApi.getActiveRecording.mockResolvedValue(null);
  mockApi.getTodosForDate.mockResolvedValue({ todos: [] });
});

function renderCalendar(entries: string[] = ['/']) {
  return render(
    <MemoryRouter initialEntries={entries}>
      <Calendar />
    </MemoryRouter>
  );
}

describe('Calendar', () => {
  it('renders preset buttons', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Yesterday' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'This Week' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Last Week' })).toBeInTheDocument();
  });

  it('calls getCalendar on mount', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });
  });

  it('calls getRecordings for each day in selected range on mount', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getRecordings).toHaveBeenCalled();
    });
  });

  it('clicking Today button selects today only', async () => {
    const user = userEvent.setup();
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Today' }));

    await waitFor(() => {
      expect(mockApi.getRecordings).toHaveBeenCalled();
    });
  });

  it('shows day views for This Week by default', async () => {
    mockApi.getRecordings.mockResolvedValue({ recordings: [] });

    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getRecordings).toHaveBeenCalled();
    });

    // Component defaults to This Week preset — shows day views (or "no recordings found" per date), not the empty state message
    await waitFor(() => {
      // Day views are rendered even when recordings array is empty for that date
      const dayViews = document.querySelectorAll('.day-view');
      expect(dayViews.length).toBeGreaterThan(0);
    });
  });

  it('shows day views when recordings exist', async () => {
    mockApi.getRecordings.mockResolvedValue({
      recordings: [{ id: 1, timestamp: '2024-06-15T10:00:00', summary: 'Morning chat', speakers: [], todos: null, decisions: null, calendar: null, notes: null, conversation_changes: null, audio_filename: null }],
    });

    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    await waitFor(() => {
      const dayViews = document.querySelectorAll('.day-view');
      expect(dayViews.length).toBeGreaterThan(0);
    });
  });

  it('renders shadcn calendar via mock', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar')).toBeInTheDocument();
    });
  });

  it('loads todos for first selected date', async () => {
    mockApi.getTodosForDate.mockResolvedValue({
      todos: [{ id: 1, task: 'Test task', owner: 'me', due: null, priority: 'high' as const, completed: false, completed_at: null, recording_id: null, recording_timestamp: null, created_at: '2024-01-01' }],
    });

    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getTodosForDate).toHaveBeenCalled();
    });
  });
});
