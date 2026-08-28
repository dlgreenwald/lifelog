import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { UnknownSpeaker } from '../types';

export default function SpeakerLabel() {
  const [unknownSegments, setUnknownSegments] = useState<UnknownSpeaker[]>([]);
  const [selectedSegment, setSelectedSegment] = useState<UnknownSpeaker | null>(null);
  const [label, setLabel] = useState('');

  useEffect(() => {
    api.getUnknownSpeakers().then((data: { recordings: UnknownSpeaker[] }) => {
      setUnknownSegments(data.recordings);
    });
  }, []);

  const unresolvedSpeakerId = (recording: UnknownSpeaker): string => {
    const speaker = (recording.speakers ?? []).find(
      (item) => item.name === 'Unknown' || item.name.startsWith('SPEAKER_'),
    );
    return speaker?.name ?? 'Unknown';
  };

  const handleLabel = async () => {
    if (!selectedSegment || !label.trim()) return;

    await api.labelSpeaker(selectedSegment.id, unresolvedSpeakerId(selectedSegment), label);

    const updated = await api.getUnknownSpeakers();
    setUnknownSegments(updated.recordings);
    setSelectedSegment(null);
    setLabel('');
  };

  return (
    <div className="speaker-label">
      <h2>Label Unknown Speakers</h2>

      <div className="unknown-list">
        {unknownSegments.map((segment) => (
          <div
            key={segment.id}
            className={`segment ${selectedSegment?.id === segment.id ? 'selected' : ''}`}
            onClick={() => setSelectedSegment(segment)}
          >
            <span>{segment.timestamp}</span>
            <span>Unknown Speaker</span>
            <audio
              src={`/api/v1/dashboard/recording/${segment.id}/speaker/${encodeURIComponent(unresolvedSpeakerId(segment))}/audio`}
              controls
            />
          </div>
        ))}
      </div>

      {selectedSegment && (
        <div className="label-form">
          <h3>Label Speaker</h3>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Enter speaker name"
          />
          <button onClick={handleLabel} disabled={!label.trim()}>
            Label & Re-identify
          </button>
        </div>
      )}
    </div>
  );
}
