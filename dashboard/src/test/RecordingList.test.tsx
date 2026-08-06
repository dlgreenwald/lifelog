import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RecordingList from '../components/RecordingList';
import type { Recording } from '../types';

const mockRecordings: Recording[] = [
  {
    id: 1,
    timestamp: '2024-01-15T10:30:00',
    summary: 'Morning standup',
    speakers: [
      { id: 0, name: 'Alice', start: 0, end: 5, text: 'Hi' },
      { id: 1, name: 'Bob', start: 5, end: 10, text: 'Hello' },
    ],
    todos: null,
    calendar: null,
    notes: null,
    conversation_changes: null,
    audio_filename: 'rec1.opus',
  decisions: null,
  },
  {
    id: 2,
    timestamp: '2024-01-15T14:00:00',
    summary: null,
    speakers: null,
    todos: null,
    calendar: null,
    notes: null,
    conversation_changes: null,
    audio_filename: null,
  decisions: null,
  },
];

function renderList(recordings: Recording[] = mockRecordings) {
  return render(
    <MemoryRouter>
      <RecordingList recordings={recordings} />
    </MemoryRouter>
  );
}

describe('RecordingList', () => {
  it('renders recording summaries', () => {
    renderList();

    expect(screen.getByText('Morning standup')).toBeInTheDocument();
    expect(screen.getByText('No summary')).toBeInTheDocument();
  });

  it('shows speaker count when speakers exist', () => {
    renderList();

    expect(screen.getByText('2 speaker(s)')).toBeInTheDocument();
  });

  it('does not show speaker count for recordings without speakers', () => {
    renderList();

    const speakerCounts = screen.getAllByText(/speaker\(s\)/);
    expect(speakerCounts).toHaveLength(1);
  });

  it('links to recording detail', () => {
    renderList();

    const links = screen.getAllByRole('link');
    expect(links[0]).toHaveAttribute('href', '/recording/1');
    expect(links[1]).toHaveAttribute('href', '/recording/2');
  });

  it('renders empty list gracefully', () => {
    const { container } = renderList([]);

    const list = container.querySelector('.recording-list');
    expect(list).toBeEmptyDOMElement();
  });
});
