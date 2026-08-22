import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import RecordingDetail from '../components/RecordingDetail';
import { api } from '../api/client';
import type { Recording } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getRecording: vi.fn(),
    getTodosForRecording: vi.fn().mockResolvedValue({ todos: [] }),
    getDecisionsForRecording: vi.fn().mockResolvedValue({ decisions: [] }),
    archiveDecision: vi.fn().mockResolvedValue({ ok: true }),
    deleteDecision: vi.fn().mockResolvedValue({ ok: true }),
    completeTodo: vi.fn().mockResolvedValue({ ok: true }),
    deleteTodo: vi.fn().mockResolvedValue({ ok: true }),
    fetchAudio: vi.fn().mockResolvedValue('blob:mock'),
    getActiveRecording: vi.fn().mockResolvedValue(null),
    deleteRecording: vi.fn().mockResolvedValue({ ok: true }),
    reprocessRecording: vi.fn().mockResolvedValue({ ok: true }),
    updateRecordingCategory: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

const mockApi = vi.mocked(api);

const mockRecording: Recording = {
  id: 10,
  timestamp: '2024-01-15T10:30:00',
  summary: 'Discussed Q1 roadmap and assigned tasks.',
  speakers: [
    { id: 0, name: 'Alice', start: 0.0, end: 3.0, text: 'Let us plan Q1.' },
    { id: 1, name: 'Bob', start: 3.0, end: 6.0, text: 'Sounds good.' },
  ],
  todos: null,
  calendar: [{ event: 'Kickoff meeting', time: '2024-01-22 10:00', participants: 'All' }],
  notes: ['Q1 focus on reliability'],
  conversation_changes: [],
  audio_filename: 'rec10.enc',
  decisions: null,
};

function renderDetail(id = '10') {
  return render(
    <MemoryRouter initialEntries={[`/recording/${id}`]}>
      <Routes>
        <Route path="/recording/:id" element={<RecordingDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RecordingDetail', () => {
  it('shows loading state initially', () => {
    mockApi.getRecording.mockReturnValue(new Promise(() => {}));

    renderDetail();

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders recording summary after load', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Discussed Q1 roadmap and assigned tasks.')).toBeInTheDocument();
    });
  });

  it('renders speakers list', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText(/Let us plan Q1/)).toBeInTheDocument();
      expect(screen.getByText(/Sounds good/)).toBeInTheDocument();
    });
  });

  it('marks Unknown speakers with unknown class', async () => {
    const withUnknown = {
      ...mockRecording,
      speakers: [
        ...mockRecording.speakers!,
        { id: 2, name: 'Unknown', start: 6.0, end: 8.0, text: 'Mystery' },
      ],
    };
    mockApi.getRecording.mockResolvedValue(withUnknown);

    renderDetail();

    await waitFor(() => {
      const unknownLi = screen.getByText(/Mystery/).closest('li');
      expect(unknownLi).toHaveClass('unknown');
    });
  });

  it('renders TODOs section', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);
    mockApi.getTodosForRecording.mockResolvedValue({
      todos: [
        {
          id: 1,
          task: 'Write proposal',
          owner: 'Alice',
          due: '2024-01-20',
          priority: 'high',
          completed: false,
          completed_at: null,
          recording_id: 10,
          recording_timestamp: '2024-01-15T10:30:00',
          created_at: '2024-01-15T10:30:00',
        },
      ],
    });

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Write proposal')).toBeInTheDocument();
    });

    expect(screen.getByText('Write proposal').closest('li')).toHaveTextContent('Alice');
  });

  it('renders decisions section', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);
    mockApi.getDecisionsForRecording.mockResolvedValue({
      decisions: [
        {
          id: 1,
          decision: 'Go with plan A',
          made_by: 'Alice',
          context: 'Discussed options',
          reason: null,
          archived: false,
          recording_id: 10,
          recording_timestamp: '2024-01-15T10:30:00',
          created_at: '2024-01-15T10:30:00',
        },
      ],
    });

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Go with plan A')).toBeInTheDocument();
    });
  });

  it('renders audio player when audio_filename exists', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Audio')).toBeInTheDocument();
      expect(document.querySelector('audio')).toBeTruthy();
    });
  });

  it('does not render audio player when no audio_filename', async () => {
    const noAudio = { ...mockRecording, audio_filename: null };
    mockApi.getRecording.mockResolvedValue(noAudio);

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Discussed Q1 roadmap and assigned tasks.')).toBeInTheDocument();
    });

    expect(screen.queryByText('Audio')).not.toBeInTheDocument();
  });

  it('calls getRecording with route param id', async () => {
    mockApi.getRecording.mockResolvedValue(mockRecording);

    renderDetail('42');

    await waitFor(() => {
      expect(mockApi.getRecording).toHaveBeenCalledWith('42');
    });
  });
});
