import { Link } from 'react-router-dom';
import type { Recording } from '../types';

interface RecordingListProps {
  recordings: Recording[];
}

export default function RecordingList({ recordings }: RecordingListProps) {
  return (
    <div className="recording-list">
      {recordings.map((recording) => (
        <Link
          key={recording.id}
          to={`/recording/${recording.id}`}
          className="recording-item"
        >
          <div className="recording-time">
            {new Date(recording.timestamp).toLocaleTimeString()}
          </div>
          <div className="recording-summary">
            {recording.summary || 'No summary'}
          </div>
          {recording.speakers && recording.speakers.length > 0 && (
            <div className="recording-speakers">
              {recording.speakers.length} speaker(s)
            </div>
          )}
        </Link>
      ))}
    </div>
  );
}
