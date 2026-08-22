import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { formatDateTime } from '../utils/format';
import AudioPlayer from './AudioPlayer';
import type { Recording } from '../types';

export default function RecordingDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [recording, setRecording] = useState<Recording | null>(null);
  const [audioUrls, setAudioUrls] = useState<string[]>([]);

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

  const handleDelete = async () => {
    if (!id || isLive) return;
    if (!confirm('Delete this recording?')) return;
    await api.deleteRecording(id);
    navigate('/', { replace: true });
  };

  if (!recording) return <div>Loading...</div>;

  return (
    <div className="recording-detail">
      <h2>
        {isLive ? '🎙️ Live Recording' : `Recording from ${formatDateTime(recording.timestamp)}`}
        {isLive && <span className="live-badge"> LIVE</span>}
      </h2>

      {!isLive && (
        <button className="delete-button" onClick={handleDelete}>Delete</button>
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

      {recording.todos && recording.todos.length > 0 && (
        <div className="todos">
          <h3>TODOs</h3>
          <ul>
            {recording.todos.map((todo, i) => (
              <li key={i} className={`priority-${todo.priority}`}>
                <span>{todo.task}</span>
                <span> - {todo.owner}</span>
                {todo.due && <span> (due: {todo.due})</span>}
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
