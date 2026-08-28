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
}

export interface Speaker {
  id: number;
  name: string;
  start: number;
  end: number;
  text: string;
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
