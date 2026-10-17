import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AudioPlayer from '../components/AudioPlayer';
import { api } from '../api/client';
import type { Speaker } from '../types';

vi.mock('../api/client', () => ({
  api: {
    fetchAudio: vi.fn().mockResolvedValue('blob:mock-audio'),
  },
}));

const mockSegments: Speaker[] = [
  { id: 0, name: 'Alice', start: 0.0, end: 2.5, text: 'Hello', audio_filename: 'alice.enc' },
  { id: 1, name: 'Bob', start: 2.5, end: 5.0, text: 'World', audio_filename: 'bob.enc' },
  { id: 2, name: 'Unknown', start: 5.0, end: 7.0, text: 'Mystery', audio_filename: 'unknown.enc' },
];

const emptyFilenameSegments: Speaker[] = [
  { id: 0, name: 'Alice', start: 0.0, end: 2.5, text: 'Hello' }, // no audio_filename
  { id: 1, name: 'Bob', start: 2.5, end: 5.0, text: 'World', audio_filename: '' }, // empty audio_filename
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AudioPlayer', () => {
  it('renders play button', () => {
    render(<AudioPlayer segments={mockSegments} />);
    expect(screen.getByRole('button', { name: /play/i })).toBeInTheDocument();
  });

  it('toggles to pause after clicking play', async () => {
    const user = userEvent.setup();
    render(<AudioPlayer segments={mockSegments} />);
    const button = screen.getByRole('button', { name: /play/i });
    await user.click(button);
    expect(button).toHaveTextContent('Pause');
  });

  it('toggles back to play after clicking pause', async () => {
    const user = userEvent.setup();
    render(<AudioPlayer segments={mockSegments} />);
    const button = screen.getByRole('button', { name: /play/i });
    await user.click(button);
    await user.click(button);
    expect(button).toHaveTextContent('Play');
  });

  it('renders timeline segments', () => {
    const { container } = render(<AudioPlayer segments={mockSegments} />);
    const timeline = container.querySelector('.timeline');
    const segments = timeline!.querySelectorAll('.segment');
    expect(segments).toHaveLength(3);
  });

  it('marks Unknown segments with unknown class', () => {
    const { container } = render(<AudioPlayer segments={mockSegments} />);
    const timeline = container.querySelector('.timeline');
    const unknownSegment = timeline!.querySelectorAll('.segment')[2];
    expect(unknownSegment).toHaveClass('unknown');
  });

  it('shows segment titles with time ranges', () => {
    const { container } = render(<AudioPlayer segments={mockSegments} />);
    const timeline = container.querySelector('.timeline');
    const segments = timeline!.querySelectorAll('.segment');
    expect(segments[0]).toHaveAttribute('title', 'Alice: 0.0s \u2013 2.5s');
    expect(segments[1]).toHaveAttribute('title', 'Bob: 2.5s \u2013 5.0s');
    expect(segments[2]).toHaveAttribute('title', 'Unknown: 5.0s \u2013 7.0s');
  });

  it('renders audio element', () => {
    render(<AudioPlayer segments={mockSegments} />);
    expect(document.querySelector('audio')).toBeInTheDocument();
  });

  it('renders empty timeline with no segments', () => {
    const { container } = render(<AudioPlayer segments={[]} />);
    const timeline = container.querySelector('.timeline');
    expect(timeline).toBeEmptyDOMElement();
  });

  it('ignores segments without audio_filename from timeline', () => {
    // Segments without audio are excluded from the playable timeline
    const noAudioSegments: Speaker[] = [
      { id: 0, name: 'Unknown', start: 0, end: 1, text: '', audio_filename: '' },
      { id: 1, name: 'Alice', start: 0, end: 1, text: 'Hello' }, // no audio_filename
    ];
    const { container } = render(<AudioPlayer segments={noAudioSegments} />);
    // No playable segments, so timeline renders empty
    expect(container.querySelectorAll('.timeline .segment')).toHaveLength(0);
  });

  it('pre-fetches audio for segments on mount', async () => {
    render(<AudioPlayer segments={mockSegments} />);
    // First 60s includes all 3 segments
    expect(api.fetchAudio).toHaveBeenCalledWith('/dashboard/audio/alice.enc');
    expect(api.fetchAudio).toHaveBeenCalledWith('/dashboard/audio/bob.enc');
    expect(api.fetchAudio).toHaveBeenCalledWith('/dashboard/audio/unknown.enc');
  });

  it('does not show errored segments in timeline until load failure', () => {
    // errored only includes segments that had audio_filename but fetch failed
    // emptyFilenameSegments have no audio_filename, so they don't appear in playable or errored
    const { container } = render(<AudioPlayer segments={emptyFilenameSegments} />);
    expect(container.querySelectorAll('.timeline .segment')).toHaveLength(0);
  });
});
