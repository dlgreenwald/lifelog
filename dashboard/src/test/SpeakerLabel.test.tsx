import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SpeakerLabel from '../components/SpeakerLabel';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getAllSpeakers: vi.fn(),
    renameSpeaker: vi.fn(),
    mergeSpeakers: vi.fn(),
    deleteSpeaker: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const alice = { id: 1, name: 'Alice Ashford', voiceprint_count: 2, recording_id: 5 };
const bob = { id: 2, name: 'Bob Brown', voiceprint_count: 1, recording_id: null };

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getAllSpeakers.mockResolvedValue({ speakers: [alice, bob] });
});

describe('SpeakerLabel', () => {
  it('renders speaker names and voiceprint counts', async () => {
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Alice Ashford')).toBeInTheDocument();
    });
    expect(screen.getByText('Bob Brown')).toBeInTheDocument();
    expect(screen.getByText('2 voiceprints')).toBeInTheDocument();
    expect(screen.getByText('1 voiceprints')).toBeInTheDocument();
    expect(mockApi.getAllSpeakers).toHaveBeenCalled();
  });

  it('renders audio preview only for speakers with a recording', async () => {
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-audio-1')).toBeInTheDocument();
    });
    const audio = screen.getByTestId('speaker-audio-1') as HTMLAudioElement;
    expect(audio.getAttribute('src')).toBe(
      '/api/v1/dashboard/recording/5/speaker/Alice%20Ashford/audio'
    );
    expect(screen.queryByTestId('speaker-audio-2')).not.toBeInTheDocument();
  });

  it('rename flow calls renameSpeaker with the speaker id and new name', async () => {
    const user = userEvent.setup();
    mockApi.renameSpeaker.mockResolvedValue({ ok: true });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Alice Ashford')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('rename-button-1'));
    const input = screen.getByTestId('rename-input-1');
    await user.clear(input);
    await user.type(input, 'Alicia Ashford');
    await user.click(screen.getByTestId('rename-save-1'));

    await waitFor(() => {
      expect(mockApi.renameSpeaker).toHaveBeenCalledWith(1, 'Alicia Ashford');
    });
    // refresh via a second getAllSpeakers call
    await waitFor(() => {
      expect(mockApi.getAllSpeakers).toHaveBeenCalledTimes(2);
    });
  });

  it('delete confirm calls deleteSpeaker and refreshes', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockApi.deleteSpeaker.mockResolvedValue({ ok: true });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Bob Brown')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-button-2'));

    await waitFor(() => {
      expect(mockApi.deleteSpeaker).toHaveBeenCalledWith(2);
    });
    await waitFor(() => {
      expect(mockApi.getAllSpeakers).toHaveBeenCalledTimes(2);
    });
  });

  it('delete cancelled does not call deleteSpeaker', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Bob Brown')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-button-2'));

    expect(mockApi.deleteSpeaker).not.toHaveBeenCalled();
  });

  it('selecting two speakers and merging calls mergeSpeakers', async () => {
    const user = userEvent.setup();
    mockApi.mergeSpeakers.mockResolvedValue({ ok: true });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText('Alice Ashford')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('merge-check-1'));
    await user.click(screen.getByTestId('merge-check-2'));
    await user.click(screen.getByTestId('merge-button'));

    await waitFor(() => {
      expect(mockApi.mergeSpeakers).toHaveBeenCalledWith(1, 2);
    });
    await waitFor(() => {
      expect(mockApi.getAllSpeakers).toHaveBeenCalledTimes(2);
    });
  });

  it('shows empty state when no speakers', async () => {
    mockApi.getAllSpeakers.mockResolvedValue({ speakers: [] });
    render(<SpeakerLabel />);

    await waitFor(() => {
      expect(screen.getByText(/No speakers enrolled yet/)).toBeInTheDocument();
    });
  });
});
