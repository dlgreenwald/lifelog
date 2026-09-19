export interface TranscriptSegment {
  start?: number;
  end?: number;
  text?: string;
  speaker?: string;
  name?: string;
}

export interface Recording {
  id: number | string;
  timestamp: string;
  summary: string | null;
  title: string | null;
  long_summary: string | null;
  transcript?: { segments?: TranscriptSegment[] };
  speakers: Speaker[] | null;
  todos: Todo[] | null;
  is_live?: boolean;
  pending_reprocessing?: boolean;
  decisions: Decision[] | null;
  calendar: CalendarEvent[] | null;
  notes: string[] | null;
  conversation_changes: ConversationChange[] | null;
  audio_filename: string | null;
  audio_filenames?: string[];
  category?: string;
  session_id?: number | null;
  partition_index?: number;
  audio_range_start?: string | null;
  audio_range_end?: string | null;
}

export interface Speaker {
  id: number;
  name: string;
  start: number;
  end: number;
  text: string;
  speaker_id?: number;
}

export interface SpeakerSummary {
  id: number;
  name: string;
  voiceprint_count: number;
  recording_id: number | null;
}

export interface Todo {
  id: number;
  task: string;
  owner: string;
  due: string | null;
  priority: 'high' | 'medium' | 'low';
  completed: boolean;
  completed_at: string | null;
  recording_id: number | null;
  recording_timestamp: string | null;
  speaker_id: number | null;
  created_at: string;
}

export interface CalendarEvent {
  event: string;
  time: string;
  participants: string;
}

export interface ConversationChange {
  from_topic: string;
  to_topic: string;
  speaker: string;
  timestamp: string | null;
}

export interface Decision {
  id: number;
  decision: string;
  made_by: string;
  context: string | null;
  reason: string | null;
  archived: boolean;
  recording_id: number | null;
  recording_timestamp: string | null;
  speaker_id: number | null;
  created_at: string;
}

export interface CalendarDay {
  date: string;
  count: number;
}

export interface UnknownSpeaker {
  id: number;
  timestamp: string;
  speakers: Speaker[];
  audio_filename: string;
}

export interface UserSettings {
    language: string;
    llm_context: string;
}

export interface SearchHit {
  id: string;
  conversation_id: number;
  turn: number;
  text: string;
  title: string;
  speaker: string;
  kind: 'turn' | 'summary' | 'decision' | 'todo';
  date: string;
  status?: 'open' | 'done';
  _matchesPosition?: Record<string, Array<{ start: number; length: number }>>;
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
  limit: number;
  offset: number;
  processingTimeMs: number;
  query: string;
}

export interface Facets {
  kinds: string[];
  speakers: string[];
  statuses: string[];
  participants: string[];
}
