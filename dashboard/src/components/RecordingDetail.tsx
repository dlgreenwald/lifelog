import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { formatDateTime } from '../utils/format';
import AudioPlayer from './AudioPlayer';
import type { Recording, Todo, Decision, Speaker } from '../types';

function revokeAudioUrl(url: string): void {
  if (typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(url);
}

export default function RecordingDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [recording, setRecording] = useState<Recording | null>(null);
  const [audioUrls, setAudioUrls] = useState<string[]>([]);
  const [recordingTodos, setRecordingTodos] = useState<Todo[]>([]);
  const [recordingDecisions, setRecordingDecisions] = useState<Decision[]>([]);
  const [showTodoForm, setShowTodoForm] = useState(false);
  const [todoFormTask, setTodoFormTask] = useState('');
  const [todoFormOwner, setTodoFormOwner] = useState('Me');
  const [todoFormDue, setTodoFormDue] = useState(() => new Date().toISOString().slice(0, 10));
  const [todoFormPriority, setTodoFormPriority] = useState('medium');

  const [showDecisionForm, setShowDecisionForm] = useState(false);
  const [decisionFormText, setDecisionFormText] = useState('');
  const [decisionFormMadeBy, setDecisionFormMadeBy] = useState('Me');
  const [decisionFormContext, setDecisionFormContext] = useState('');
  const [decisionFormReason, setDecisionFormReason] = useState('');

  const [searchParams] = useSearchParams();
  const highlightQuery = searchParams.get('q') || '';
  /** Meilisearch _matchesPosition: field name → [{start, length}, ...] */
  const highlightMatches: Record<string, Array<{ start: number; length: number }>> | null = (() => {
    const raw = searchParams.get('matches');
    if (!raw) return null;
    try { return JSON.parse(atob(raw)); } catch { return null; }
  })();

  /**
   * Apply Meilisearch _matchesPosition highlights to a segment's text.
   * Offsets are relative to the full indexed transcript; we adjust them
   * to be relative to this segment's position within the full text.
   */
  function highlightSegment(
    rawText: string,
    range: { start: number; end: number },
  ): React.ReactNode {
    const text = rawText;
    if (!highlightMatches) {
      // Fallback: word-boundary regex on query terms
      if (!highlightQuery.trim()) return text;
      const terms = highlightQuery.trim().split(/\s+/).filter(Boolean);
      if (!terms.length) return text;
      const pattern = new RegExp(
        `\\b(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, 'gi'
      );
      const parts = text.split(pattern);
      if (parts.length === 1) return text;
      return <>{parts.map((part, i) =>
        i % 2 === 1 ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700 rounded px-0.5">{part}</mark> : part
      )}</>;
    }
    const allRanges = highlightMatches['text'];
    if (!allRanges || allRanges.length === 0) return text;

    // Filter ranges that fall within this segment's character span
    const localRanges: Array<{ start: number; end: number }> = [];
    for (const r of allRanges) {
      const rStart = r.start;
      const rEnd = r.start + r.length;
      if (rEnd < range.start || rStart >= range.end) continue; // outside this segment
      localRanges.push({
        start: Math.max(0, rStart - range.start),
        end: Math.min(text.length, rEnd - range.start),
      });
    }
    if (localRanges.length === 0) return text;

    // Sort and merge overlapping ranges
    const sorted = [...localRanges].sort((a, b) => a.start - b.start);
    const merged: Array<{ start: number; end: number }> = [];
    for (const r of sorted) {
      const last = merged[merged.length - 1];
      if (last && r.start <= last.end) last.end = Math.max(last.end, r.end);
      else merged.push({ start: r.start, end: r.end });
    }

    const parts: React.ReactNode[] = [];
    let pos = 0;
    for (const { start, end } of merged) {
      if (start > pos) parts.push(text.slice(pos, start));
      parts.push(<mark key={pos} className="bg-yellow-200 dark:bg-yellow-700 rounded px-0.5">{text.slice(start, end)}</mark>);
      pos = end;
    }
    if (pos < text.length) parts.push(text.slice(pos));
    return <>{parts}</>;
  }

  const isLive = id?.startsWith('active-');
  const numericRecordingId = id && !isLive ? Number(id) : undefined;
  const audioUrlsByFilename = useRef(new Map<string, string>());
  const pendingAudioFilenames = useRef(new Set<string>());
  const audioRecordingId = useRef<string | null>(null);
  useEffect(() => {
    if (!recording) return;
    const recordingKey = id ?? null;
    if (audioRecordingId.current !== recordingKey) {
      audioUrlsByFilename.current.forEach(revokeAudioUrl);
      audioUrlsByFilename.current.clear();
      pendingAudioFilenames.current.clear();
      audioRecordingId.current = recordingKey;
      setAudioUrls([]);
    }

    const filenames = recording.audio_filenames?.length
      ? recording.audio_filenames
      : recording.audio_filename ? [recording.audio_filename] : [];
    if (filenames.length === 0) {
      setAudioUrls([]);
      return;
    }

    const missing = filenames.filter(
      (filename) => !audioUrlsByFilename.current.has(filename) &&
        !pendingAudioFilenames.current.has(filename),
    );
    missing.forEach((filename) => pendingAudioFilenames.current.add(filename));
    let cancelled = false;
    Promise.allSettled(missing.map(async (filename) => {
      try {
        const url = await api.fetchAudio(`/dashboard/audio/${filename}`);
        return { filename, url };
      } finally {
        pendingAudioFilenames.current.delete(filename);
      }
    })).then((results) => {
      const newlyFetched: string[] = [];
      if (cancelled) {
        results.forEach((result) => {
          if (result.status === 'fulfilled') newlyFetched.push(result.value.url);
        });
        newlyFetched.forEach(revokeAudioUrl);
        return;
      }
      results.forEach((result) => {
        if (result.status === 'fulfilled') {
          audioUrlsByFilename.current.set(result.value.filename, result.value.url);
        }
      });
      setAudioUrls(
        filenames.flatMap((filename) => {
          const url = audioUrlsByFilename.current.get(filename);
          return url ? [url] : [];
        }),
      );
    });

    return () => { cancelled = true; };
  }, [recording, id]);

  useEffect(() => () => {
    audioUrlsByFilename.current.forEach(revokeAudioUrl);
    audioUrlsByFilename.current.clear();
  }, []);


  const loadRecording = useCallback(() => {
    if (!id) return;
    if (isLive) {
      api.getActiveRecording().then(setRecording).catch(() => setRecording(null));
    } else {
      api.getRecording(id).then(setRecording);
    }
  }, [id, isLive]);

  useEffect(() => { loadRecording(); }, [loadRecording]);

  // Auto-refresh for live recordings
  useEffect(() => {
    if (!isLive) return;
    const interval = setInterval(loadRecording, 5000);
    return () => clearInterval(interval);
  }, [isLive, loadRecording]);


  // Fetch todos for this recording
  useEffect(() => {
    if (recording && !isLive && id) {
      api.getTodosForRecording(id).then((data: { todos: Todo[] }) => {
        setRecordingTodos(data.todos);
      }).catch(() => setRecordingTodos([]));
    }
  }, [recording, isLive, id]);

  // Fetch decisions for this recording
  useEffect(() => {
    if (recording && !isLive && id) {
      api.getDecisionsForRecording(id).then((data: { decisions: Decision[] }) => {
        setRecordingDecisions(data.decisions);
      }).catch(() => setRecordingDecisions([]));
    }
  }, [recording, isLive, id]);



  const handleTodoToggle = async (todo: Todo) => {
    const newCompleted = !todo.completed;
    await api.completeTodo(todo.id, newCompleted);
    setRecordingTodos(prev =>
      prev.map(t =>
        t.id === todo.id
          ? { ...t, completed: newCompleted, completed_at: newCompleted ? new Date().toISOString() : null }
          : t
      )
    );
  };

  const handleTodoDelete = async (todoId: number) => {
    await api.deleteTodo(todoId);
    setRecordingTodos(prev => prev.filter(t => t.id !== todoId));
  };

  const handleCreateTodo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!todoFormTask.trim()) return;
    const result: unknown = await api.createTodo({
      task: todoFormTask.trim(),
      owner: todoFormOwner || 'Me',
      due: todoFormDue || undefined,
      priority: todoFormPriority,
      recording_id: numericRecordingId,
    });
    const todoId =
      result && typeof result === 'object' && 'id' in result && typeof result.id === 'number'
        ? result.id
        : Date.now();
    setRecordingTodos(prev => [
      {
        id: todoId,
        task: todoFormTask.trim(),
        owner: todoFormOwner || 'Me',
        due: todoFormDue || null,
        priority: todoFormPriority as 'high' | 'medium' | 'low',
        completed: false,
        completed_at: null,
        recording_id: numericRecordingId ?? null,
        recording_timestamp: null,
        speaker_id: null,
        created_at: new Date().toISOString(),
      },
      ...prev,
    ]);
    setTodoFormTask('');
    setTodoFormOwner('Me');
    setTodoFormDue(new Date().toISOString().slice(0, 10));
    setTodoFormPriority('medium');
    setShowTodoForm(false);
  };

  const handleCreateDecision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!decisionFormText.trim()) return;
    const result: unknown = await api.createDecision({
      decision: decisionFormText.trim(),
      made_by: decisionFormMadeBy || 'Me',
      context: decisionFormContext || undefined,
      reason: decisionFormReason || undefined,
      recording_id: numericRecordingId,
    });
    const decisionId =
      result && typeof result === 'object' && 'id' in result && typeof result.id === 'number'
        ? result.id
        : Date.now();
    setRecordingDecisions(prev => [
      {
        id: decisionId,
        decision: decisionFormText.trim(),
        made_by: decisionFormMadeBy || 'Me',
        context: decisionFormContext || null,
        reason: decisionFormReason || null,
        archived: false,
        recording_id: numericRecordingId ?? null,
        recording_timestamp: null,
        speaker_id: null,
        created_at: new Date().toISOString(),
      },
      ...prev,
    ]);
    setDecisionFormText('');
    setDecisionFormMadeBy('Me');
    setDecisionFormContext('');
    setDecisionFormReason('');
    setShowDecisionForm(false);
  };

  const handleDelete = async () => {
    if (!id || isLive) return;
    if (!confirm('Delete this recording?')) return;
    await api.deleteRecording(id);
    navigate('/', { replace: true });
  };

  const [reprocessing, setReprocessing] = useState(false);
  const handleReprocess = async () => {
    if (!id || isLive || reprocessing) return;
    if (!confirm('Reprocess this recording? It will be regenerated at the next hourly run.')) return;
    setReprocessing(true);
    try {
      await api.reprocessRecording(id);
      navigate('/', { replace: true });
    } catch {
      setReprocessing(false);
    }
  };

  const handleCategoryChange = async (category: string) => {
    if (!id || isLive) return;
    await api.updateRecordingCategory(id, category);
    setRecording(prev => prev ? { ...prev, category } : null);
  };

  // Build the full concatenated transcript text (matches how it's indexed in Meilisearch)
  // so character offsets from _matchesPosition map correctly.
  const rawSegments: Array<{ name: string; text: string }> = (
    recording?.transcript?.segments ?? []
  ).map(seg => ({
    name: seg.name ?? seg.speaker ?? 'Unknown',
    text: seg.text ?? '',
  }));


  const segmentCharRanges: Array<{ start: number; end: number }> = (() => {
    const ranges: Array<{ start: number; end: number }> = [];
    let pos = 0;
    for (const seg of rawSegments) {
      const prefix = seg.text.trim() ? `${seg.name}: ` : '';
      const text = seg.text.trim();
      const segText = prefix + text;
      ranges.push({ start: pos, end: pos + segText.length });
      pos += segText.length + 1; // +1 for space separator
    }
    return ranges;
  })();

  const uniqueSpeakers = rawSegments.reduce<Speaker[]>((acc, seg, i) => {
    if (!acc.some(a => a.name === seg.name)) {
      acc.push({ id: i, name: seg.name, start: 0, end: 0, text: seg.text });
    }
    return acc;
  }, []);

  if (!recording) return <div>Loading...</div>;

  return (
    <div className="recording-detail">
      <h2>
        {isLive ? '🎙️ Live Recording' : <>{recording.title}<span className="recording-time"> : {formatDateTime(recording.timestamp)}</span></>}
        {isLive && <span className="live-badge"> LIVE</span>}
      </h2>

      {!isLive && (
        <>
          <button className="delete-button" onClick={handleDelete}>Delete</button>
          <button
            className="reprocess-button"
            onClick={handleReprocess}
            disabled={reprocessing || recording.pending_reprocessing}
          >
            {reprocessing || recording.pending_reprocessing ? 'Reprocessing…' : 'Reprocess'}
          </button>
          <div className="category-buttons">
            <span className="category-label">Category:</span>
            {['work', 'personal', 'not_meaningful'].map(cat => (
              <button
                key={cat}
                className={`category-btn ${recording.category === cat ? 'active' : ''}`}
                onClick={() => handleCategoryChange(cat)}
              >
                {cat === 'not_meaningful' ? 'Other' : cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>
        </>
      )}

      {recording.long_summary && (
        <div className="summary">
          <h3>Summary</h3>
          <p>{recording.long_summary}</p>
        </div>
      )}

      {rawSegments.length > 0 && (
        <>
          <div className="speakers">
            <h3>Transcript</h3>
            <ul>
              {rawSegments.map((seg, i) => {
                const text = seg.text.trim();
                const range = segmentCharRanges[i] ?? { start: 0, end: 0 };
                return (
                  <li key={i} className={!isLive && seg.name === 'Unknown' ? 'unknown' : ''}>
                    {!isLive && <span className="speaker-name">{seg.name}: </span>}
                    {highlightSegment(text, range)}
                  </li>
                );
              })}
            </ul>
          </div>
          {!isLive && uniqueSpeakers.filter(s => s.name === 'Unknown' || s.name.startsWith('SPEAKER_')).length > 0 && (
            <div className="speaker-labels">
              <h4>Label speakers:</h4>
              <ul>
                {uniqueSpeakers
                  .filter(s => s.name === 'Unknown' || s.name.startsWith('SPEAKER_'))
                  .map((speaker, i) => (
                    <li key={i}>
                      <span>{speaker.name}</span>
                      {speaker.speaker_id != null && (
                        <button onClick={() => labelSpeaker(speaker)}>Label</button>
                      )}
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </>
      )}

      {audioUrls.length > 0 && (
        <div className="audio-player">
          <h3>Audio</h3>
          <AudioPlayer
            sources={audioUrls}
            segments={rawSegments.map((s, i) => ({
              id: i,
              name: s.name,
              text: s.text,
              start: 0,
              end: 0,
            }))}
          />
        </div>
      )}

      <div className="decisions">
        <h3>Decisions</h3>
        {!isLive && (
          <button className="add-button" onClick={() => setShowDecisionForm(!showDecisionForm)}>
            {showDecisionForm ? 'Cancel' : '+ Add Decision'}
          </button>
        )}
        {showDecisionForm && (
          <form className="create-form" onSubmit={handleCreateDecision}>
            <input
              type="text"
              placeholder="Decision *"
              value={decisionFormText}
              onChange={e => setDecisionFormText(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="Made by"
              value={decisionFormMadeBy}
              onChange={e => setDecisionFormMadeBy(e.target.value)}
            />
            <textarea
              placeholder="Context (optional)"
              value={decisionFormContext}
              onChange={e => setDecisionFormContext(e.target.value)}
              rows={2}
            />
            <textarea
              placeholder="Reason (optional)"
              value={decisionFormReason}
              onChange={e => setDecisionFormReason(e.target.value)}
              rows={2}
            />
            <button type="submit">Create</button>
          </form>
        )}
        {recordingDecisions.length > 0 ? (
          <ul>
            {recordingDecisions.map(decision => (
              <li key={decision.id} className={decision.archived ? 'decision-archived' : ''}>
                <strong>{decision.decision}</strong>
                <span> - {decision.made_by}</span>
                {decision.archived && (
                  <span className="decision-archive-badge">Archived</span>
                )}
                {decision.context && <p className="context">{decision.context}</p>}
                {decision.reason && <p className="decision-reason">{decision.reason}</p>}
                <div>
                  <button onClick={async () => {
                    await api.archiveDecision(decision.id, !decision.archived);
                    setRecordingDecisions(prev =>
                      prev.map(d => d.id === decision.id ? { ...d, archived: !d.archived } : d)
                    );
                  }}>
                    {decision.archived ? 'Unarchive' : 'Archive'}
                  </button>
                  <button className="todo-delete" onClick={async () => {
                    await api.deleteDecision(decision.id);
                    setRecordingDecisions(prev => prev.filter(d => d.id !== decision.id));
                  }}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          !showDecisionForm && <p>No decisions found</p>
        )}
      </div>

      <div className="todos">
        <h3>TODOs</h3>
        {!isLive && (
          <button className="add-button" onClick={() => setShowTodoForm(!showTodoForm)}>
            {showTodoForm ? 'Cancel' : '+ Add Todo'}
          </button>
        )}
        {showTodoForm && (
          <form className="create-form" onSubmit={handleCreateTodo}>
            <input
              type="text"
              placeholder="Task *"
              value={todoFormTask}
              onChange={e => setTodoFormTask(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="Owner"
              value={todoFormOwner}
              onChange={e => setTodoFormOwner(e.target.value)}
            />
            <input
              type="date"
              placeholder="Due date"
              value={todoFormDue}
              onChange={e => setTodoFormDue(e.target.value)}
            />
            <select value={todoFormPriority} onChange={e => setTodoFormPriority(e.target.value)}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <button type="submit">Create</button>
          </form>
        )}
        {recordingTodos.length > 0 ? (
          <ul>
            {recordingTodos.map(todo => (
              <li
                key={todo.id}
                className={`priority-${todo.priority} ${todo.completed ? 'completed' : ''}`}
              >
                <input
                  type="checkbox"
                  className="todo-checkbox"
                  checked={todo.completed}
                  onChange={() => handleTodoToggle(todo)}
                />
                <span className="todo-task">{todo.task}</span>
                <span> - {todo.owner}</span>
                {todo.due && <span> (due: {todo.due})</span>}
                <span className="priority-badge">{todo.priority}</span>
                <button
                  className="todo-delete"
                  onClick={() => handleTodoDelete(todo.id)}
                  aria-label={`Delete todo: ${todo.task}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : (
          !showTodoForm && <p>No TODOs found</p>
        )}
      </div>
    </div>
  );

  async function labelSpeaker(speaker: { id: number; name: string; speaker_id?: number }) {
    if (!speaker.speaker_id) return;
    const name = prompt(`Enter a new name for ${speaker.name}:`);
    if (!name?.trim()) return;
    await api.renameSpeaker(speaker.speaker_id, name.trim());
    // Reload recording to reflect updated labels
    const recordingId = recording!.id as number;
    const updated = await api.getRecording(String(recordingId));
    setRecording(updated);
  }
}
