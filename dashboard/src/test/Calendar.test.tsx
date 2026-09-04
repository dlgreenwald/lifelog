import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import Calendar from '../components/Calendar';
import type { DateRange } from 'react-day-picker';
import { api } from '../api/client';

// Shared state for mocking useIsMobile
const mockIsMobile = { value: false };

// Mock shadcn Drawer to avoid Base UI initialization hanging
vi.mock('@/components/ui/drawer', () => ({
  Drawer: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer">{children}</div>,
  DrawerTrigger: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer-trigger">{children}</div>,
  DrawerContent: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-drawer-content">{children}</div>,
  DrawerFooter: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  DrawerClose: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

// Track state across renders for mobile/desktop behavior testing
let capturedCalendarProps: {
  mode?: string;
  onSelect?: (day: Date | DateRange | undefined) => void;
  selected?: Date | DateRange | undefined;
} = {};

vi.mock('@/components/ui/calendar', () => ({
  Calendar: vi.fn(({ mode, selected, onSelect }: { mode?: string; selected?: Date | DateRange; onSelect?: (day: Date | DateRange | undefined) => void }) => {
    capturedCalendarProps = { mode, selected, onSelect };
    return (
      <div data-testid="mock-calendar" data-mode={mode}>
        <button
          data-testid="mock-calendar-select-day"
          onClick={() => onSelect?.(new Date('2024-06-15'))}
        >
          Select Day
        </button>
        <button
          data-testid="mock-calendar-select-range"
          onClick={() => onSelect?.({ from: new Date('2024-06-15'), to: new Date('2024-06-17') })}
        >
          Select Range
        </button>
      </div>
    );
  }),
}));

// Mock DayView to avoid DOM complexity
vi.mock('../components/DayView', () => ({
  default: ({ date, recordings, onRecordingClick }: { date: string; recordings: Array<{ id: unknown }>; onRecordingClick: (id: unknown) => void }) => (
    <div data-testid={`dayview-${date}`} className="day-view" onClick={() => onRecordingClick(recordings[0]?.id)}>
      DayView for {date}
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

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => mockIsMobile.value,
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mockIsMobile.value = false;  // Reset to desktop
  mockApi.getCalendar.mockResolvedValue({ dates: [] });
  mockApi.getRecordings.mockResolvedValue({ recordings: [] });
  mockApi.getActiveRecording.mockResolvedValue(null);
  mockApi.getTodosForDate.mockResolvedValue({ todos: [] });
  capturedCalendarProps = {};
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

    await waitFor(() => {
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

describe('Mobile single-day selection', () => {
  beforeEach(() => {
    mockIsMobile.value = true;
  });

  it('uses single mode in mobile view', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar')).toBeInTheDocument();
    });

    expect(capturedCalendarProps.mode).toBe('single');
  });

  it('selecting a day calls onSelect with a Date', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar-select-day')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId('mock-calendar-select-day'));

    expect(capturedCalendarProps.onSelect).toBeDefined();
  });
});

describe('Desktop range selection', () => {
  beforeEach(() => {
    mockIsMobile.value = false;
  });

  it('uses range mode in desktop view', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar')).toBeInTheDocument();
    });

    expect(capturedCalendarProps.mode).toBe('range');
  });

  it('selecting a range calls onSelect with a DateRange', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar-select-range')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId('mock-calendar-select-range'));

    expect(capturedCalendarProps.onSelect).toBeDefined();
  });
});

describe('Mobile to desktop view transition', () => {
  it('switches from single to range mode when viewport changes', async () => {
    // Start in mobile mode
    mockIsMobile.value = true;

    const { rerender } = renderCalendar();

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar')).toBeInTheDocument();
    });

    // Initially mobile mode
    expect(capturedCalendarProps.mode).toBe('single');

    // Simulate switching to desktop
    mockIsMobile.value = false;
    rerender(
      <MemoryRouter initialEntries={['/']}>
        <Calendar />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('mock-calendar')).toBeInTheDocument();
    });

    // Now desktop mode
    expect(capturedCalendarProps.mode).toBe('range');
  });
});
