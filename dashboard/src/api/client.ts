const API_BASE = '/api/v1';

async function fetchApi(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...options.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return response.json();
}

export const api = {
  getCalendar: (year: number, month: number) =>
    fetchApi(`/dashboard/calendar/${year}/${month}`),
  getRecordings: (date: string) => fetchApi(`/dashboard/recordings/${date}`),
  getRecording: (id: string) => fetchApi(`/dashboard/recording/${id}`),
  getTodos: () => fetchApi('/dashboard/todos'),
  getDecisions: () => fetchApi('/dashboard/decisions'),
  getUnknownSpeakers: () => fetchApi('/dashboard/unknown-speakers'),
  labelSpeaker: (recordingId: number, speakerId: string, label: string) =>
    fetchApi('/speakers/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recording_id: recordingId, speaker_id: speakerId, label }),
    }),
};
