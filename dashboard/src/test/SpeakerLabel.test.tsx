import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SpeakerLabel from '../components/SpeakerLabel';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getAllSpeakers: vi.fn(),
    labelSpeaker: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SpeakerLabel', () => {
  it('loads and displays unlabeled speakers', async () => {
    mockApi.getAllSpeakers.mockResolvedValue({
      speakers: [
        { name: 'SPEAKER_00', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_00' },
        { name: 'SPEAKER_01', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_01' },
      ],
    });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('SPEAKER_00').length).toBeGreaterThanOrEqual(1);
    });
    expect(mockApi.getAllSpeakers).toHaveBeenCalled();
  });

  it('shows label form when segment is clicked', async () => {
    const user = userEvent.setup();
    mockApi.getAllSpeakers.mockResolvedValue({
      speakers: [
        { name: 'SPEAKER_00', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_00' },
      ],
    });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('SPEAKER_00').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('SPEAKER_00')[0].closest('div[style], [class*="cursor-pointer"]')!);

    await waitFor(() => {
      expect(screen.getByText(/Label Speaker: SPEAKER_00/)).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText('Enter speaker name')).toBeInTheDocument();
  });

  it('disables label button when input is empty', async () => {
    const user = userEvent.setup();
    mockApi.getAllSpeakers.mockResolvedValue({
      speakers: [
        { name: 'SPEAKER_00', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_00' },
      ],
    });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('SPEAKER_00').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('SPEAKER_00')[0].closest('[class*="cursor-pointer"]')!);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /label/i })).toBeInTheDocument();
    });
    const button = screen.getByRole('button', { name: /label/i });
    expect(button).toBeDisabled();
  });

  it('enables label button when input has text', async () => {
    const user = userEvent.setup();
    mockApi.getAllSpeakers.mockResolvedValue({
      speakers: [
        { name: 'SPEAKER_00', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_00' },
      ],
    });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('SPEAKER_00').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('SPEAKER_00')[0].closest('[class*="cursor-pointer"]')!);
    await user.type(screen.getByPlaceholderText('Enter speaker name'), 'Alice');

    const button = screen.getByRole('button', { name: /label/i });
    expect(button).toBeEnabled();
  });

  it('submits label and refreshes list', async () => {
    const user = userEvent.setup();
    mockApi.labelSpeaker.mockResolvedValue({ status: 'labeled', label: 'Alice' });
    mockApi.getAllSpeakers
      .mockResolvedValueOnce({
        speakers: [{ name: 'SPEAKER_00', labeled: false, recording_id: 5, speaker_label: 'SPEAKER_00' }],
      })
      .mockResolvedValueOnce({ speakers: [] });

    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getAllByText('SPEAKER_00').length).toBeGreaterThanOrEqual(1);
    });

    await user.click(screen.getAllByText('SPEAKER_00')[0].closest('[class*="cursor-pointer"]')!);
    await user.type(screen.getByPlaceholderText('Enter speaker name'), 'Alice');
    await user.click(screen.getByRole('button', { name: /label/i }));

    await waitFor(() => {
      expect(mockApi.labelSpeaker).toHaveBeenCalledWith(5, 'SPEAKER_00', 'Alice');
    });
    await waitFor(() => {
      expect(mockApi.getAllSpeakers).toHaveBeenCalledTimes(2);
    });
  });

  it('shows empty state when no speakers', async () => {
    mockApi.getAllSpeakers.mockResolvedValue({ speakers: [] });

    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.queryByText('Label Speaker')).not.toBeInTheDocument();
    });
  });

  it('displays labeled speakers', async () => {
    mockApi.getAllSpeakers.mockResolvedValue({
      speakers: [
        { name: 'Alice', labeled: true, recording_id: 5, speaker_label: 'SPEAKER_00' },
      ],
    });

    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Labeled (1)')).toBeInTheDocument();
      expect(screen.getByText('Alice')).toBeInTheDocument();
    });
  });
});
