import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { formatDateTime } from '../utils/format';
import AudioPlayer from './AudioPlayer';
import type { Recording, Todo, Decision } from '../types';

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

  const isLive = id?.startsWith('active-');
  const numericRecordingId = id && !isLive ? Number(id) : undefined;

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

  useEffect(() => {
    if (!recording) return;
    const filenames = recording.audio_filenames?.length
      ? recording.audio_filenames
      : recording.audio_filename
        ? [recording.audio_filename]
        : [];
    if (filenames.length === 0) return;

    Promise.all(
      filenames.map((f) => api.fetchAudio(`/dashboard/audio/${f}`))
    ).then(setAudioUrls);

    return () => audioUrls.forEach((url) => URL.revokeObjectURL(url));
  }, [recording]);

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

  if (!recording) return <div>Loading...</div>;

  return (
    <div className="recording-detail">
      <h2>
        {isLive ? '🎙️ Live Recording' : `Recording from ${formatDateTime(recording.timestamp)}`}
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

      {recording.summary && (
        <div className="summary">
          <h3>Summary</h3>
          <p>{recording.summary}</p>
        </div>
      )}

      {recording.speakers && recording.speakers.length > 0 && (
        <div className="speakers">
          <h3>Transcript</h3>
          <ul>
            {recording.speakers.map((speaker, i) => (
              <li key={i} className={speaker.name === 'Unknown' ? 'unknown' : ''}>
                {speaker.name}: {speaker.text}
                {speaker.name === 'Unknown' && (
                  <button onClick={() => labelSpeaker(speaker)}>Label</button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {audioUrls.length > 0 && (
        <div className="audio-player">
          <h3>Audio</h3>
          <AudioPlayer
            sources={audioUrls}
            segments={recording.speakers || []}
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

  function labelSpeaker(speaker: { id: number; name: string }) {
    console.log('Label speaker:', speaker);
  }
}
