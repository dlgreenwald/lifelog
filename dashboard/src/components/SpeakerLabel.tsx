import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { SpeakerSummary } from '../types';

export default function SpeakerLabel() {
  const [speakers, setSpeakers] = useState<SpeakerSummary[]>([]);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [checked, setChecked] = useState<number[]>([]);

  const refresh = async () => {
    const data = await api.getAllSpeakers();
    setSpeakers((data as { speakers: SpeakerSummary[] }).speakers);
  };

  useEffect(() => {
    refresh();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRename = async (speaker: SpeakerSummary) => {
    if (!renameValue.trim()) return;
    await api.renameSpeaker(speaker.id, renameValue.trim());
    setRenamingId(null);
    setRenameValue('');
    await refresh();
  };

  const handleDelete = async (speaker: SpeakerSummary) => {
    const confirmed = window.confirm(
      `Delete ${speaker.name}? Their voiceprints are removed and past recordings revert to raw labels.`
    );
    if (!confirmed) return;
    await api.deleteSpeaker(speaker.id);
    await refresh();
  };

  const toggleChecked = (id: number) => {
    setChecked(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const handleMerge = async () => {
    if (checked.length !== 2) return;
    const [sourceId, targetId] = checked;
    await api.mergeSpeakers(sourceId, targetId);
    setChecked([]);
    await refresh();
  };

  return (
    <div className="flex flex-col h-full px-4">
      <h2 className="text-xl font-semibold tracking-tight mb-4">Speakers</h2>

      {speakers.length === 0 && (
        <p className="text-muted-foreground">No speakers enrolled yet.</p>
      )}

      <ul className="flex flex-col gap-3">
        {speakers.map(speaker => (
          <li
            key={speaker.id}
            data-testid={`speaker-${speaker.id}`}
            className="flex items-center gap-3 rounded-lg border bg-card p-3"
          >
            <input
              type="checkbox"
              aria-label={`Select ${speaker.name} for merge`}
              checked={checked.includes(speaker.id)}
              onChange={() => toggleChecked(speaker.id)}
              data-testid={`merge-check-${speaker.id}`}
            />
            <span className="font-medium" data-testid={`speaker-name-${speaker.id}`}>
              {speaker.name}
            </span>
            <span className="text-sm text-muted-foreground">
              {speaker.voiceprint_count} voiceprints
            </span>
            {speaker.recording_id != null && (
              <audio
                controls
                src={`/api/v1/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.name)}/audio`}
                data-testid={`speaker-audio-${speaker.id}`}
              />
            )}
            {renamingId === speaker.id ? (
              <>
                <Input
                  value={renameValue}
                  onChange={e => setRenameValue(e.target.value)}
                  aria-label={`New name for ${speaker.name}`}
                  data-testid={`rename-input-${speaker.id}`}
                />
                <Button
                  size="sm"
                  onClick={() => handleRename(speaker)}
                  data-testid={`rename-save-${speaker.id}`}
                >
                  Save
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setRenamingId(speaker.id);
                  setRenameValue(speaker.name);
                }}
                data-testid={`rename-button-${speaker.id}`}
              >
                Rename
              </Button>
            )}
            <Button
              size="sm"
              variant="destructive"
              onClick={() => handleDelete(speaker)}
              data-testid={`delete-button-${speaker.id}`}
            >
              Delete
            </Button>
          </li>
        ))}
      </ul>

      {checked.length === 2 && (
        <Button onClick={handleMerge} className="mt-4 self-start" data-testid="merge-button">
          Merge Selected
        </Button>
      )}
    </div>
  );
}
