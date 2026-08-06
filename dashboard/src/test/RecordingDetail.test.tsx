import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import RecordingDetail from '../components/RecordingDetail';
import { api } from '../api/client';
import type { Recording } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getRecording: vi.fn(),
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
  todos: [
    { task: 'Write proposal', owner: 'Alice', due: '2024-01-20', priority: 'high' },
  ],
  calendar: [{ event: 'Kickoff meeting', time: '2024-01-22 10:00', participants: 'All' }],
  notes: ['Q1 focus on reliability'],
  conversation_changes: [],
  audio_filename: 'rec10.enc',
  decisions: [{ decision: 'Go with plan A', made_by: 'Alice', context: 'Discussed options' }],
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

    renderDetail();

    await waitFor(() => {
      expect(screen.getByText('Write proposal')).toBeInTheDocument();
    });

    // Verify Alice is listed as owner in the TODO
    expect(screen.getByText('Write proposal').closest('li')).toHaveTextContent('Alice');
  });

  it('renders decisions section', async () => {
    const withDecisions = {
      ...mockRecording,
      decisions: [{ decision: 'Go with plan A', made_by: 'Alice' }],
    };
    mockApi.getRecording.mockResolvedValue(withDecisions);

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
      expect(document.querySelector('audio')).toHaveAttribute(
        'src',
        '/api/v1/dashboard/audio/rec10.enc'
      );
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
