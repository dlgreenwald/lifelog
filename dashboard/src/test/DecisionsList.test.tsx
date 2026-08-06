import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import DecisionsList from '../components/DecisionsList';
import { api } from '../api/client';
import type { Decision } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getDecisions: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const mockDecisions: Decision[] = [
  { decision: 'Launch v2 on Friday', made_by: 'Alice', context: 'Discussed timeline with team' },
  { decision: 'Use PostgreSQL', made_by: 'Bob', context: '' },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DecisionsList', () => {
  it('renders decisions', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<DecisionsList />);

    await waitFor(() => {
      expect(screen.getByText('Launch v2 on Friday')).toBeInTheDocument();
    });

    expect(screen.getByText('Use PostgreSQL')).toBeInTheDocument();
  });

  it('shows "No decisions found" when empty', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<DecisionsList />);

    await waitFor(() => {
      expect(screen.getByText('No decisions found')).toBeInTheDocument();
    });
  });

  it('displays who made each decision', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<DecisionsList />);

    await waitFor(() => {
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
      expect(screen.getByText(/Bob/)).toBeInTheDocument();
    });
  });

  it('shows context when present', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<DecisionsList />);

    await waitFor(() => {
      expect(screen.getByText('Discussed timeline with team')).toBeInTheDocument();
    });
  });

  it('does not show context paragraph when empty string', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: mockDecisions });

    render(<DecisionsList />);

    await waitFor(() => {
      expect(screen.getByText('Use PostgreSQL')).toBeInTheDocument();
    });

    // The second decision has empty context - no <p class="context"> for it
    const contextParagraphs = screen.getAllByText(/Discussed/);
    expect(contextParagraphs).toHaveLength(1);
  });

  it('calls getDecisions on mount', async () => {
    mockApi.getDecisions.mockResolvedValue({ decisions: [] });

    render(<DecisionsList />);

    expect(mockApi.getDecisions).toHaveBeenCalledTimes(1);
  });
});
