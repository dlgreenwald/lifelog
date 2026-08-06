import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import AudioPlayer from './AudioPlayer';
import type { Recording } from '../types';

export default function RecordingDetail() {
  const { id } = useParams<{ id: string }>();
  const [recording, setRecording] = useState<Recording | null>(null);

  useEffect(() => {
    if (id) {
      api.getRecording(id).then(setRecording);
    }
  }, [id]);

  if (!recording) return <div>Loading...</div>;

  return (
    <div className="recording-detail">
      <h2>Recording from {new Date(recording.timestamp).toLocaleString()}</h2>

      <div className="summary">
        <h3>Summary</h3>
        <p>{recording.summary}</p>
      </div>

      {recording.speakers && recording.speakers.length > 0 && (
        <div className="speakers">
          <h3>Speakers</h3>
          <ul>
            {recording.speakers.map((speaker) => (
              <li key={speaker.id} className={speaker.name === 'Unknown' ? 'unknown' : ''}>
                {speaker.name}: {speaker.text}
                {speaker.name === 'Unknown' && (
                  <button onClick={() => labelSpeaker(speaker)}>Label</button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {recording.audio_filename && (
        <div className="audio-player">
          <h3>Audio</h3>
          <AudioPlayer
            src={`/api/v1/dashboard/audio/${recording.audio_filename}`}
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
    // In a real app, this would open a modal to label the speaker
    console.log('Label speaker:', speaker);
  }
}
