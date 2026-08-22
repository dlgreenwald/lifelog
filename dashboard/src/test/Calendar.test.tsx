import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Calendar from '../components/Calendar';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getCalendar: vi.fn(),
    getRecordings: vi.fn(),
    getActiveRecording: vi.fn().mockResolvedValue(null),
    getDailySummary: vi.fn().mockResolvedValue({ daily_summary: null }),
    getTodosForDate: vi.fn().mockResolvedValue({ todos: [] }),
    completeTodo: vi.fn().mockResolvedValue({ ok: true }),
    deleteTodo: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  mockApi.getCalendar.mockResolvedValue({ dates: [] });
  mockApi.getRecordings.mockResolvedValue({ recordings: [] });
});

function renderCalendar(entries: string[] = ['/']) {
  return render(
    <MemoryRouter initialEntries={entries}>
      <Calendar />
    </MemoryRouter>
  );
}

describe('Calendar', () => {
  it('renders month header', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 2 })).toBeInTheDocument();
    });

    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading.textContent).toMatch(/\w+ \d{4}/);
  });

  it('calls getCalendar on mount', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });
  });

  it('navigates to previous month', async () => {
    const user = userEvent.setup();
    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    const initialCount = mockApi.getCalendar.mock.calls.length;
    const prevButton = screen.getByText('←');
    await user.click(prevButton);

    await waitFor(() => {
      expect(mockApi.getCalendar.mock.calls.length).toBeGreaterThan(initialCount);
    });
  });

  it('navigates to next month', async () => {
    const user = userEvent.setup();
    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    const initialCount = mockApi.getCalendar.mock.calls.length;
    const nextButton = screen.getByText('→');
    await user.click(nextButton);

    await waitFor(() => {
      expect(mockApi.getCalendar.mock.calls.length).toBeGreaterThan(initialCount);
    });
  });

  it('fetches recordings when date is clicked', async () => {
    const user = userEvent.setup();
    mockApi.getRecordings.mockResolvedValue({
      recordings: [{ id: 1, timestamp: '2024-01-15T10:00:00', summary: 'Morning chat' }],
    });

    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    const dayElements = screen.getAllByText(/^\d{1,2}$/);
    if (dayElements.length > 0) {
      await user.click(dayElements[0]);

      await waitFor(() => {
        expect(mockApi.getRecordings).toHaveBeenCalled();
      });
    }
  });

  it('shows recordings panel after selecting date', async () => {
    const user = userEvent.setup();
    mockApi.getRecordings.mockResolvedValue({
      recordings: [{ id: 1, timestamp: '2024-01-15T10:00:00', summary: 'Morning chat' }],
    });

    renderCalendar();

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    const dayElements = screen.getAllByText(/^\d{1,2}$/);
    if (dayElements.length > 0) {
      await user.click(dayElements[0]);

      await waitFor(() => {
        expect(screen.getByText(/Recordings for/)).toBeInTheDocument();
      });
    }
  });

  it('defaults to today when no date param in URL', async () => {
    renderCalendar(['/']);

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    // Should show recordings panel (selectedDate defaults to today)
    expect(screen.getByText(/Recordings for/)).toBeInTheDocument();
  });

  it('selects date from URL search params', async () => {
    renderCalendar(['/?date=2024-06-15&month=2024-06']);

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    expect(screen.getByText('Recordings for 2024-06-15')).toBeInTheDocument();
  });

  it('clicking a date updates URL search params', async () => {
    const user = userEvent.setup();
    mockApi.getRecordings.mockResolvedValue({
      recordings: [{ id: 1, timestamp: '2024-06-20T10:00:00', summary: 'Afternoon chat' }],
    });

    renderCalendar(['/?month=2024-06']);

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    // Click day 15
    const day15 = screen.getByText('15', { selector: '.calendar-day' });
    await user.click(day15);

    await waitFor(() => {
      expect(screen.getByText('Recordings for 2024-06-15')).toBeInTheDocument();
    });
  });

  it('loads month from URL search params', async () => {
    renderCalendar(['/?month=2024-03']);

    await waitFor(() => {
      expect(mockApi.getCalendar).toHaveBeenCalled();
    });

    // Should display March 2024 in the header
    expect(screen.getByText('March 2024')).toBeInTheDocument();
  });
});
