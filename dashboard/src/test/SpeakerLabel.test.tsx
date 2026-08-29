import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SpeakerLabel from '../components/SpeakerLabel';
import { api } from '../api/client';
import type { UnknownSpeaker } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getUnknownSpeakers: vi.fn(),
    getAllSpeakers: vi.fn(),
    labelSpeaker: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const mockUnknowns: UnknownSpeaker[] = [
  { id: 5, timestamp: '2024-01-15T10:00:00', speakers: [], audio_filename: 'rec1.enc' },
  { id: 8, timestamp: '2024-01-16T14:00:00', speakers: [], audio_filename: 'rec2.enc' },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getUnknownSpeakers.mockResolvedValue({ recordings: mockUnknowns });
  mockApi.getAllSpeakers.mockResolvedValue({
    speakers: [
      { name: 'Unknown', labeled: false, recording_id: 5, speaker_label: 'Unknown' },
      { name: 'Alice', labeled: true, recording_id: 5, speaker_label: 'Alice' },
    ],
  });
});

describe('SpeakerLabel', () => {
  it('loads and displays unknown speakers', async () => {
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    expect(mockApi.getAllSpeakers).toHaveBeenCalled();
  });

  it('shows label form when segment is clicked', async () => {
    const user = userEvent.setup();
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    // Click on the first unlabeled segment (within .unknown-list)
    const firstSegment = document.querySelector('.unknown-list .segment');
    await user.click(firstSegment!);

    expect(screen.getByText('Label Speaker: Unknown')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Enter speaker name')).toBeInTheDocument();
  });

  it('disables label button when input is empty', async () => {
    const user = userEvent.setup();
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('Unknown')[0].closest('.segment')!);

    const button = screen.getByRole('button', { name: /label/i });
    expect(button).toBeDisabled();
  });

  it('enables label button when input has text', async () => {
    const user = userEvent.setup();
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('Unknown')[0].closest('.segment')!);
    await user.type(screen.getByPlaceholderText('Enter speaker name'), 'Alice');

    const button = screen.getByRole('button', { name: /label/i });
    expect(button).toBeEnabled();
  });

  it('submits label and refreshes list', async () => {
    const user = userEvent.setup();
    mockApi.labelSpeaker.mockResolvedValue({ status: 'labeled', label: 'Alice' });
    mockApi.getAllSpeakers
      .mockResolvedValueOnce({
        speakers: [{ name: 'Unknown', labeled: false, recording_id: 5, speaker_label: 'Unknown' }],
      })
      .mockResolvedValueOnce({ speakers: [] });

    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('Unknown')[0].closest('.segment')!);
    await user.type(screen.getByPlaceholderText('Enter speaker name'), 'Alice');
    await user.click(screen.getByRole('button', { name: /label/i }));

    await waitFor(() => {
      expect(mockApi.labelSpeaker).toHaveBeenCalledWith(5, 'Unknown', 'Alice');
    });
    await waitFor(() => {
      expect(mockApi.getAllSpeakers).toHaveBeenCalledTimes(2);
    });
  });

  it('shows empty state when no unknowns', async () => {
    mockApi.getAllSpeakers.mockResolvedValue({ speakers: [] });

    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.queryByText('Label Speaker')).not.toBeInTheDocument();
    });
  });

  it('highlights selected segment', async () => {
    const user = userEvent.setup();
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(1);
    });

    const segments = screen.getAllByText('Unknown');
    await user.click(segments[0].closest('.segment')!);

    const selectedSegment = segments[0].closest('.segment');
    expect(selectedSegment).toHaveClass('selected');
  });
});
