import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

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
    <div className="flex flex-col h-full px-4">
      <h2 className="text-xl font-semibold tracking-tight mb-4">Speakers</h2>

      {unlabeled.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-3">Unlabeled ({unlabeled.length})</h3>
          <div className="flex flex-col gap-3">
            {unlabeled.map((speaker) => (
              <div
                key={speaker.name}
                className={`rounded-lg border bg-card p-4 cursor-pointer transition-colors ${selected?.name === speaker.name ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'}`}
                onClick={() => setSelected(speaker)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-card-foreground">{speaker.name}</span>
                </div>
                <audio
                  src={`/api/v1/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.speaker_label)}/audio`}
                  controls
                  className="w-full h-8"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {labeled.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-3">Labeled ({labeled.length})</h3>
          <div className="flex flex-col gap-2">
            {labeled.map((speaker) => (
              <div
                key={speaker.name}
                className="rounded-lg border bg-card p-4 flex items-center justify-between opacity-70"
              >
                <span className="text-sm font-medium text-card-foreground">{speaker.name}</span>
                <audio
                  src={`/api/v1/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.speaker_label)}/audio`}
                  controls
                  className="w-64 h-8"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {selected && (
        <div className="mt-4 rounded-lg border bg-card p-4">
          <h3 className="text-sm font-medium mb-3 text-card-foreground">Label Speaker: {selected.name}</h3>
          <div className="flex gap-3">
            <Input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="Enter speaker name"
              className="flex-1"
            />
            <Button onClick={handleLabel} disabled={!label.trim()}>
              Label &amp; Re-identify
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
