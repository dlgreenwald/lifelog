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

function renderCalendar() {
  return render(
    <MemoryRouter>
      <Calendar />
    </MemoryRouter>
  );
}

describe('Calendar', () => {
  it('renders month header', async () => {
    renderCalendar();

    await waitFor(() => {
      expect(screen.getByRole('heading')).toBeInTheDocument();
    });

    const heading = screen.getByRole('heading');
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
});
