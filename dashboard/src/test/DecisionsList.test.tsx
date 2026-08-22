import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DecisionsList from '../components/DecisionsList';
import { api } from '../api/client';
import type { Decision } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getDecisions: vi.fn(),
    archiveDecision: vi.fn(),
    deleteDecision: vi.fn(),
    createDecision: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const mockDecisions: Decision[] = [
  {
    id: 1,
    decision: 'Launch v2 on Friday',
    made_by: 'Alice',
    context: 'Discussed timeline with team',
    reason: 'Deadline pressure from stakeholders',
    archived: false,
    recording_id: 10,
    recording_timestamp: '2024-01-15T10:00:00',
    created_at: '2024-01-15T10:00:00',
  },
  {
    id: 2,
    decision: 'Use PostgreSQL',
    made_by: 'Bob',
    context: '',
    reason: null,
    archived: false,
    recording_id: 10,
    recording_timestamp: '2024-01-15T10:00:00',
    created_at: '2024-01-15T10:05:00',
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DecisionsList', () => {
  it('renders decisions', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Launch v2 on Friday')).toBeInTheDocument();
    });

    expect(screen.getByText('Use PostgreSQL')).toBeInTheDocument();
  });

  it('shows "No decisions found" when empty', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No decisions found')).toBeInTheDocument();
    });
  });

  it('displays who made each decision', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
      expect(screen.getByText(/Bob/)).toBeInTheDocument();
    });
  });

  it('shows context when present', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Discussed timeline with team')).toBeInTheDocument();
    });
  });

  it('shows reason when present', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Deadline pressure from stakeholders')).toBeInTheDocument();
    });
  });

  it('calls getDecisions on mount', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    expect(mockApi.getDecisions).toHaveBeenCalledWith(false);
  });

  it('toggles show archived', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(mockApi.getDecisions).toHaveBeenCalledWith(false);
    });

    fireEvent.click(screen.getByText('Show archived'));

    await waitFor(() => {
      expect(mockApi.getDecisions).toHaveBeenCalledWith(true);
    });
  });

  it('archives a decision', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });
    mockApi.archiveDecision.mockResolvedValue({ ok: true });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Launch v2 on Friday')).toBeInTheDocument();
    });

    const archiveButtons = screen.getAllByText('Archive');
    fireEvent.click(archiveButtons[0]);

    expect(mockApi.archiveDecision).toHaveBeenCalledWith(1, true);
  });

  it('deletes a decision', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });
    mockApi.deleteDecision.mockResolvedValue({ ok: true });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Launch v2 on Friday')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByText('Delete');
    fireEvent.click(deleteButtons[0]);

    expect(mockApi.deleteDecision).toHaveBeenCalledWith(1);
  });

  it('shows create form when add button clicked', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No decisions found')).toBeInTheDocument();
    });

    const addBtn = screen.getByText('+ Add Decision');
    fireEvent.click(addBtn);

    expect(screen.getByPlaceholderText('Decision *')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Made by')).toBeInTheDocument();
    expect(screen.getByText('Create')).toBeInTheDocument();
  });

  it('creates decision and prepends to list', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });
    mockApi.createDecision.mockResolvedValue({ id: 200 });

    render(<MemoryRouter><DecisionsList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No decisions found')).toBeInTheDocument();
    });

    // Open form
    fireEvent.click(screen.getByText('+ Add Decision'));

    // Fill form
    fireEvent.change(screen.getByPlaceholderText('Decision *'), { target: { value: 'Use PostgreSQL' } });
    fireEvent.change(screen.getByPlaceholderText('Made by'), { target: { value: 'Alice' } });
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() => {
      expect(mockApi.createDecision).toHaveBeenCalledWith({
        decision: 'Use PostgreSQL',
        made_by: 'Alice',
        context: undefined,
        reason: undefined,
      });
    });

    // Decision should appear in the list
    await waitFor(() => {
      expect(screen.getByText('Use PostgreSQL')).toBeInTheDocument();
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
    });
  });
});
