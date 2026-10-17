import { useEffect, useState, useRef, useMemo } from 'react';
import { api } from '../api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from '@/components/ui/table';
import type { SpeakerSummary } from '../types';

type SortColumn = 'name' | 'voiceprint_count' | 'is_self';
type SortDirection = 'asc' | 'desc';

export default function SpeakerLabel() {
  const [speakers, setSpeakers] = useState<SpeakerSummary[]>([]);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [checked, setChecked] = useState<number[]>([]);
  const [sortColumn, setSortColumn] = useState<SortColumn>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  // Blob URLs per speaker ID — only created on first play
  const blobUrls = useRef(new Map<number, string>());

  const handleAudioPlay = async (speaker: SpeakerSummary, audioEl: HTMLAudioElement) => {
    const speakerId = speaker.id;
    if (blobUrls.current.has(speakerId)) return;

    const path = `/dashboard/recording/${speaker.recording_id}/speaker/${encodeURIComponent(speaker.name)}/audio`;
    const blobUrl = await api.fetchAudio(path);
    blobUrls.current.set(speakerId, blobUrl);
    audioEl.src = blobUrl;
    audioEl.load();
    // May be blocked by autoplay policy in some browsers — silent fallback, user clicks again
    audioEl.play().catch(() => {});
  };

  const refresh = async () => {
    const data = await api.getAllSpeakers();
    setSpeakers((data as { speakers: SpeakerSummary[] }).speakers);
  };

  useEffect(() => {
    refresh();
    return () => {
      for (const url of blobUrls.current.values()) {
        URL.revokeObjectURL(url);
      }
    };
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

  const handleToggleSelf = async (speaker: SpeakerSummary) => {
    if (speaker.is_self) {
      await api.unmarkAsSelf(speaker.id);
    } else {
      await api.markAsSelf(speaker.id);
    }
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

  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      setSortDirection(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  const sorted = useMemo(() => {
    return [...speakers].sort((a, b) => {
      let cmp = 0;
      if (sortColumn === 'name') {
        cmp = a.name.localeCompare(b.name);
      } else if (sortColumn === 'voiceprint_count') {
        cmp = a.voiceprint_count - b.voiceprint_count;
      } else if (sortColumn === 'is_self') {
        cmp = (a.is_self === b.is_self) ? 0 : a.is_self ? -1 : 1;
      }
      return sortDirection === 'asc' ? cmp : -cmp;
    });
  }, [speakers, sortColumn, sortDirection]);

  const SortIcon = ({ column }: { column: SortColumn }) => {
    if (sortColumn !== column) return <span className="text-muted-foreground ml-1">↕</span>;
    return sortDirection === 'asc'
      ? <span className="ml-1 text-foreground">↑</span>
      : <span className="ml-1 text-foreground">↓</span>;
  };

  return (
    <div className="flex flex-col h-full overflow-hidden px-4 py-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold tracking-tight">Speakers</h2>
        {checked.length === 2 && (
          <Button onClick={handleMerge} size="sm" data-testid="merge-button">
            Merge Selected
          </Button>
        )}
      </div>

      {speakers.length === 0 ? (
        <p className="text-muted-foreground">No speakers enrolled yet.</p>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <span className="sr-only">Select for merge</span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => handleSort('name')}>
                  Name <SortIcon column="name" />
                </TableHead>
                <TableHead className="cursor-pointer select-none w-32 text-right" onClick={() => handleSort('voiceprint_count')}>
                  Voiceprints <SortIcon column="voiceprint_count" />
                </TableHead>
                <TableHead className="cursor-pointer select-none w-28 text-center" onClick={() => handleSort('is_self')}>
                  Me? <SortIcon column="is_self" />
                </TableHead>
                <TableHead className="w-48">Audio</TableHead>
                <TableHead className="w-48">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map(speaker => (
                <TableRow key={speaker.id} data-testid={`speaker-${speaker.id}`}>
                  <TableCell>
                    <input
                      type="checkbox"
                      aria-label={`Select ${speaker.name} for merge`}
                      checked={checked.includes(speaker.id)}
                      onChange={() => toggleChecked(speaker.id)}
                      data-testid={`merge-check-${speaker.id}`}
                    />
                  </TableCell>
                  <TableCell>
                    <span data-testid={`speaker-name-${speaker.id}`}>{speaker.name}</span>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {speaker.voiceprint_count}
                  </TableCell>
                  <TableCell className="text-center">
                    <Button
                      size="sm"
                      variant={speaker.is_self ? 'default' : 'outline'}
                      onClick={() => handleToggleSelf(speaker)}
                      data-testid={`self-button-${speaker.id}`}
                      className="h-7 px-2 text-xs"
                    >
                      {speaker.is_self ? 'This is me ✓' : 'This is me'}
                    </Button>
                  </TableCell>
                  <TableCell>
                    {speaker.recording_id != null && (
                      <audio
                        controls
                        preload="none"
                        className="h-7 w-40"
                        data-testid={`speaker-audio-${speaker.id}`}
                        onPlay={e => handleAudioPlay(speaker, e.currentTarget)}
                      />
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {renamingId === speaker.id ? (
                        <>
                          <Input
                            value={renameValue}
                            onChange={e => setRenameValue(e.target.value)}
                            aria-label={`New name for ${speaker.name}`}
                            data-testid={`rename-input-${speaker.id}`}
                            className="h-7 w-28"
                          />
                          <Button
                            size="sm"
                            onClick={() => handleRename(speaker)}
                            data-testid={`rename-save-${speaker.id}`}
                            className="h-7"
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
                          className="h-7 px-2 text-xs"
                        >
                          Rename
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleDelete(speaker)}
                        data-testid={`delete-button-${speaker.id}`}
                        className="h-7 px-2 text-xs"
                      >
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
