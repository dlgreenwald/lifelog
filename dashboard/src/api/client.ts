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
  fetchAudio: async (path: string): Promise<string> => {
    const headers: Record<string, string> = {};
    if (_getToken) {
      const token = await _getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const resp = await fetch(`${API_BASE}${path}`, { headers });
    if (!resp.ok) throw new Error(`Audio fetch failed: ${resp.statusText}`);
    const blob = await resp.blob();
    return URL.createObjectURL(blob);
  },
  getCalendar: (year: number, month: number) =>
    fetchApi(`/dashboard/calendar/${year}/${month}`),
  getRecordings: (date: string, category?: string) =>
    fetchApi(`/dashboard/recordings/${date}${category ? `?category=${category}` : ''}`),
  getRecording: (id: string) => fetchApi(`/dashboard/recording/${id}`),
  getTodos: () => fetchApi('/dashboard/todos'),
  getTodosForDate: (date: string) => fetchApi(`/dashboard/todos/${date}`),
  getTodosForRecording: (recordingId: string) =>
    fetchApi(`/dashboard/recording/${recordingId}/todos`),
  completeTodo: (todoId: number, completed: boolean) =>
    fetchApi(`/dashboard/todos/${todoId}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ completed }),
    }),
  deleteTodo: (todoId: number) =>
    fetchApi(`/dashboard/todos/${todoId}`, { method: 'DELETE' }),
  createTodo: (data: { task: string; owner?: string; due?: string; priority?: string; recording_id?: number }) =>
    fetchApi('/dashboard/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  getDecisions: (includeArchived = false) =>
    fetchApi(`/dashboard/decisions?include_archived=${includeArchived}`),
  getDecisionsForRecording: (recordingId: string) =>
    fetchApi(`/dashboard/recording/${recordingId}/decisions`),
  archiveDecision: (decisionId: number, archived: boolean) =>
    fetchApi(`/dashboard/decisions/${decisionId}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived }),
    }),
  deleteDecision: (decisionId: number) =>
    fetchApi(`/dashboard/decisions/${decisionId}`, { method: 'DELETE' }),
  createDecision: (data: { decision: string; made_by?: string; context?: string; reason?: string; recording_id?: number }) =>
    fetchApi('/dashboard/decisions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  getUnknownSpeakers: () => fetchApi('/dashboard/unknown-speakers'),
  getAllSpeakers: () => fetchApi('/dashboard/speakers/all'),
  deleteRecording: (id: string) =>
    fetchApi(`/dashboard/recording/${id}`, { method: 'DELETE' }),
  reprocessRecording: (id: string) =>
    fetchApi(`/dashboard/recording/${id}/reprocess`, { method: 'POST' }),
  updateRecordingCategory: (id: string, category: string) =>
    fetchApi(`/dashboard/recording/${id}/category`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category }),
    }),
  getDailySummary: (date: string) => fetchApi(`/dashboard/daily-summary/${date}`),
  getActiveRecording: () => fetchApi('/dashboard/active-recording'),
  renameSpeaker: (speakerId: number, name: string) =>
    fetchApi('/speakers/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker_id: speakerId, name }),
    }),
  mergeSpeakers: (sourceId: number, targetId: number) =>
    fetchApi('/speakers/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }),
  deleteSpeaker: (id: number) =>
    fetchApi(`/speakers/${id}`, { method: 'DELETE' }),
  getSettings: () => fetchApi('/dashboard/settings'),
  saveSettings: (data: { language: string; llm_context: string }) =>
    fetchApi('/dashboard/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  search: (params: {
    q: string;
    kind?: string;
    status?: string;
    speaker?: string;
    date_from?: string;
    date_to?: string;
    participants?: string;
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    sp.set('q', params.q);
    if (params.kind) sp.set('kind', params.kind);
    if (params.status) sp.set('status', params.status);
    if (params.speaker) sp.set('speaker', params.speaker);
    if (params.date_from) sp.set('date_from', params.date_from);
    if (params.date_to) sp.set('date_to', params.date_to);
    if (params.participants) sp.set('participants', params.participants);
    if (params.limit !== undefined) sp.set('limit', String(params.limit));
    if (params.offset !== undefined) sp.set('offset', String(params.offset));
    return fetchApi(`/search?${sp.toString()}`);
  },
  getSearchFacets: () => fetchApi('/search/facets'),
  reindexSearch: () => fetchApi('/search/reindex', { method: 'POST' }),
};
