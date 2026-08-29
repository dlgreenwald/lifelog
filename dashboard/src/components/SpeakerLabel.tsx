import { useState, useEffect } from 'react';
import { api } from '../api/client';

interface SpeakerEntry {
  name: string;
  labeled: boolean;
  recording_id: number;
  speaker_label: string;
}

export default function SpeakerLabel() {
  const [speakers, setSpeakers] = useState<SpeakerEntry[]>([]);
  const [selected, setSelected] = useState<SpeakerEntry | null>(null);
  const [label, setLabel] = useState('');

  useEffect(() => {
    api.getAllSpeakers().then((data: { speakers: SpeakerEntry[] }) => {
      setSpeakers(data.speakers);
    });
  }, []);

  const handleLabel = async () => {
    if (!selected || !label.trim()) return;
    await api.labelSpeaker(selected.recording_id, selected.speaker_label, label.trim());
    const updated = await api.getAllSpeakers();
    setSpeakers(updated.speakers);
    setSelected(null);
    setLabel('');
  };

  const unlabeled = speakers.filter(s => !s.labeled);
  const labeled = speakers.filter(s => s.labeled);

  return (
    <div className="speaker-label">
      <h2>Speakers</h2>

      {unlabeled.length > 0 && (
        <>
          <h3>Unlabeled ({unlabeled.length})</h3>
          <div className="unknown-list">
            {unlabeled.map((speaker) => (
              <div
                key={speaker.name}
                className={`segment ${selected?.name === speaker.name ? 'selected' : ''}`}
                onClick={() => setSelected(speaker)}
              >
                <span className="speaker-name">{speaker.name}</span>
                <audio
                  src={`/api/v1/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.speaker_label)}/audio`}
                  controls
                />
              </div>
            ))}
          </div>
        </>
      )}

      {labeled.length > 0 && (
        <>
          <h3>Labeled ({labeled.length})</h3>
          <div className="labeled-list">
            {labeled.map((speaker) => (
              <div key={speaker.name} className="segment labeled">
                <span className="speaker-name">{speaker.name}</span>
                <audio
                  src={`/api/v1/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.speaker_label)}/audio`}
                  controls
                />
              </div>
            ))}
          </div>
        </>
      )}

      {selected && (
        <div className="label-form">
          <h3>Label Speaker: {selected.name}</h3>
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
