import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AudioPlayer from '../components/AudioPlayer';
import type { Speaker } from '../types';

const mockSegments: Speaker[] = [
  { id: 0, name: 'Alice', start: 0.0, end: 2.5, text: 'Hello' },
  { id: 1, name: 'Bob', start: 2.5, end: 5.0, text: 'World' },
  { id: 2, name: 'Unknown', start: 5.0, end: 7.0, text: 'Mystery' },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AudioPlayer', () => {
  it('renders play button', () => {
    render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    expect(screen.getByRole('button', { name: /play/i })).toBeInTheDocument();
  });

  it('toggles to pause after clicking play', async () => {
    const user = userEvent.setup();
    render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const button = screen.getByRole('button', { name: /play/i });
    await user.click(button);

    expect(button).toHaveTextContent('Pause');
  });

  it('toggles back to play after clicking pause', async () => {
    const user = userEvent.setup();
    render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const button = screen.getByRole('button', { name: /play/i });
    await user.click(button);
    await user.click(button);

    expect(button).toHaveTextContent('Play');
  });

  it('renders timeline segments', () => {
    const { container } = render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const timeline = container.querySelector('.timeline');
    const segments = timeline!.querySelectorAll('.segment');
    expect(segments).toHaveLength(3);
  });

  it('marks Unknown segments with unknown class', () => {
    const { container } = render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const timeline = container.querySelector('.timeline');
    const unknownSegment = timeline!.querySelectorAll('.segment')[2];
    expect(unknownSegment).toHaveClass('unknown');
  });

  it('shows segment titles with time ranges', () => {
    const { container } = render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const timeline = container.querySelector('.timeline');
    const segments = timeline!.querySelectorAll('.segment');

    expect(segments[0]).toHaveAttribute('title', 'Alice: 0.0s - 2.5s');
    expect(segments[1]).toHaveAttribute('title', 'Bob: 2.5s - 5.0s');
    expect(segments[2]).toHaveAttribute('title', 'Unknown: 5.0s - 7.0s');
  });

  it('renders audio element with src', () => {
    render(<AudioPlayer src="test.opus" segments={mockSegments} />);

    const audio = document.querySelector('audio');
    expect(audio).toHaveAttribute('src', 'test.opus');
  });

  it('renders empty timeline with no segments', () => {
    const { container } = render(<AudioPlayer src="test.opus" segments={[]} />);

    const timeline = container.querySelector('.timeline');
    expect(timeline).toBeEmptyDOMElement();
  });
});
