import type { UserManager } from 'oidc-client-ts';

const API_BASE = '/api/v1';

let _getToken: (() => Promise<string | null>) | null = null;
let _userManager: UserManager | null = null;

export function setAuthProvider(tokenGetter: () => Promise<string | null>, userManager: UserManager) {
  _getToken = tokenGetter;
  _userManager = userManager;
}

async function fetchApi(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (_getToken) {
    const token = await _getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  let response = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // On 401 — try refresh token, then retry once
  if (response.status === 401 && _userManager) {
    try {
      const refreshed = await _userManager.signinSilent();
      if (refreshed?.access_token) {
        headers['Authorization'] = `Bearer ${refreshed.access_token}`;
        response = await fetch(`${API_BASE}${path}`, { ...options, headers });
      }
    } catch {
      _userManager.signinRedirect();
      return;
    }
  }

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
