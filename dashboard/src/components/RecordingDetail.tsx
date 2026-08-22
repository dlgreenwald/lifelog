import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { formatDateTime } from '../utils/format';
import AudioPlayer from './AudioPlayer';
import type { Recording, Todo } from '../types';

export default function RecordingDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [recording, setRecording] = useState<Recording | null>(null);
  const [audioUrls, setAudioUrls] = useState<string[]>([]);
  const [recordingTodos, setRecordingTodos] = useState<Todo[]>([]);

  const isLive = id?.startsWith('active-');

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

      {recording.decisions && recording.decisions.length > 0 && (
        <div className="decisions">
          <h3>Decisions</h3>
          <ul>
            {recording.decisions.map((decision, i) => (
              <li key={i}>
                <strong>{decision.decision}</strong>
                <span> - {decision.made_by}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {recordingTodos.length > 0 && (
        <div className="todos">
          <h3>TODOs</h3>
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
        </div>
      )}
    </div>
  );

  function labelSpeaker(speaker: { id: number; name: string }) {
    console.log('Label speaker:', speaker);
  }
}
