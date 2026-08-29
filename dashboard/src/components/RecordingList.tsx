import { Link } from 'react-router-dom';
import { formatTime } from '../utils/format';
import type { Recording } from '../types';

interface RecordingListProps {
  recordings: Recording[];
}

function getEndTime(rec: Recording): string | null {
  const speakers = rec.speakers;
  if (!speakers || speakers.length === 0) return null;
  const maxEnd = Math.max(...speakers.map(s => s.end ?? 0));
  if (maxEnd <= 0) return null;
  const start = new Date(rec.timestamp.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(rec.timestamp)
    ? rec.timestamp : rec.timestamp + 'Z');
  const end = new Date(start.getTime() + maxEnd * 1000);
  return end.toLocaleTimeString('en-US', { timeZone: 'America/New_York' });
}

export default function RecordingList({ recordings }: RecordingListProps) {
  // Group recordings by session for split display
  const withSessionKey = recordings.map((r) => ({
    recording: r,
    sessionKey: r.session_id != null ? String(r.session_id) : `standalone-${r.id}`,
  }));

  // Detect split sessions (same session_id, multiple recordings)
  const sessionCounts = new Map<string, number>();
  for (const item of withSessionKey) {
    sessionCounts.set(item.sessionKey, (sessionCounts.get(item.sessionKey) ?? 0) + 1);
  }

  // Track session boundaries for dividers
  const showDividerBefore = new Set<string>();
  let prevSessionKey: string | null = null;
  for (const item of withSessionKey) {
    if (prevSessionKey !== null && prevSessionKey !== item.sessionKey) {
      showDividerBefore.add(item.sessionKey);
    }
    prevSessionKey = item.sessionKey;
  }

  return (
    <div className="recording-list">
      {withSessionKey.map(({ recording, sessionKey }) => {
        const partitionIndex = recording.partition_index ?? 0;
        return (
          <div key={recording.id}>
            {showDividerBefore.has(sessionKey) && (
              <div className="recording-divider" />
            )}
            <Link
              to={`/recording/${recording.id}`}
              className={`recording-item${partitionIndex > 0 ? ' recording-item-partition' : ''}`}
            >
              <div className="recording-time">
                {formatTime(recording.timestamp)}
                {(() => {
                  const endTime = getEndTime(recording);
                  return endTime ? <> to {endTime}</> : null;
                })()}
              </div>
              <div className="recording-summary">
                {recording.summary || 'No summary'}
              </div>
              {recording.speakers && recording.speakers.length > 0 && (
                <div className="recording-speakers">
                  {new Set(recording.speakers.map(s => s.name)).size} speaker(s)
                </div>
              )}
            </Link>
          </div>
        );
      })}
    </div>
  );
}
