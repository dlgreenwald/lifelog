export interface Recording {
  id: number;
  timestamp: string;
  summary: string | null;
  speakers: Speaker[] | null;
  todos: Todo[] | null;
  decisions: Decision[] | null;
  calendar: CalendarEvent[] | null;
  notes: string[] | null;
  conversation_changes: ConversationChange[] | null;
  audio_filename: string | null;
  audio_filenames?: string[];
}

export interface Speaker {
  id: number;
  name: string;
  start: number;
  end: number;
  text: string;
}

export interface Todo {
  task: string;
  owner: string;
  due: string | null;
  priority: 'high' | 'medium' | 'low';
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
  decision: string;
  made_by: string;
  context: string;
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
