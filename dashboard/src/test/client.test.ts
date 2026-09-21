import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, setAuthProvider } from '../api/client';
import type { UserManager } from 'oidc-client-ts';
import type { MockInstance } from 'vitest';

// ── helpers ───────────────────────────────────────────────────────────────────

// Track the spy so we can assert on call arguments after each API call
let fetchSpy: MockInstance<[input: RequestInfo | URL, init?: RequestInit | undefined], Promise<Response>>;

function mockFetch(response: unknown, ok = true) {
  const mockResponse = {
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Error',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(response),
  } as unknown as Response;
  fetchSpy.mockResolvedValue(mockResponse);
}

function lastCall(): [input: RequestInfo | URL, init?: RequestInit] | undefined {
  const calls = fetchSpy.mock.calls;
  return calls[calls.length - 1];
}

// ── setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  // Use spyOn on the actual global fetch so the api module's fetch calls
  // (which capture the global at runtime, not at import time) hit our spy
  fetchSpy = vi.spyOn(globalThis, 'fetch');
});

afterEach(() => {
  fetchSpy.mockRestore();
});

// ── setAuthProvider ───────────────────────────────────────────────────────────

describe('setAuthProvider', () => {
  it('stores the token getter and userManager', () => {
    const tokenGetter = vi.fn(() => Promise.resolve('token'));
    const um = { signinRedirect: vi.fn() } as unknown as UserManager;
    setAuthProvider(tokenGetter, um);
    expect(tokenGetter).toBeDefined();
  });
});

// ── api.getCalendar ───────────────────────────────────────────────────────────

describe('api.getCalendar', () => {
  it('calls /dashboard/calendar/<year>/<month>', async () => {
    mockFetch({ recordings: [] });
    await api.getCalendar(2026, 9);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/dashboard/calendar/2026/9',
      expect.any(Object),
    );
  });

  it('returns parsed JSON', async () => {
    const data = { recordings: [{ id: 1 }] };
    mockFetch(data);
    const result = await api.getCalendar(2026, 9);
    expect(result).toEqual(data);
  });
});

// ── api.getRecordings ─────────────────────────────────────────────────────────

describe('api.getRecordings', () => {
  it('encodes date in path', async () => {
    mockFetch([]);
    await api.getRecordings('2026-09-20');
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/dashboard/recordings/2026-09-20',
      expect.any(Object),
    );
  });

  it('appends category query param', async () => {
    mockFetch([]);
    await api.getRecordings('2026-09-20', 'work');
    const url = lastCall()![0] as string;
    expect(url).toContain('?category=work');
  });
});

// ── api.completeTodo ─────────────────────────────────────────────────────────

describe('api.completeTodo', () => {
  it('calls PATCH with completed state', async () => {
    mockFetch({ id: 1, completed: true });
    await api.completeTodo(42, true);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/dashboard/todos/42/complete',
      expect.any(Object),
    );
  });
});

// ── api.createTodo ─────────────────────────────────────────────────────────────

describe('api.createTodo', () => {
  it('POSTs the todo data', async () => {
    mockFetch({ id: 1, task: 'Test' });
    await api.createTodo({ task: 'Test', priority: 'high' });
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/dashboard/todos',
      expect.objectContaining({ method: 'POST' }),
    );
    const call = lastCall()!;
    const body = JSON.parse((call[1]?.body as string) ?? '{}');
    expect(body.task).toBe('Test');
    expect(body.priority).toBe('high');
  });
});

// ── api.search ─────────────────────────────────────────────────────────────────

describe('api.search', () => {
  it('calls GET /search with query params', async () => {
    mockFetch({ hits: [], totalHits: 0 });
    await api.search({ q: 'hello', offset: 10 });
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/search?q=hello&offset=10',
      expect.any(Object),
    );
  });

  it('returns parsed search results', async () => {
    mockFetch({ hits: [{ id: 1 }], totalHits: 1 });
    const result = await api.search({ q: 'hello' });
    expect(result.hits).toHaveLength(1);
  });
});

// ── api.getSearchFacets ───────────────────────────────────────────────────────

describe('api.getSearchFacets', () => {
  it('calls GET /search/facets', async () => {
    mockFetch({ categories: {} });
    await api.getSearchFacets();
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/search/facets',
      expect.any(Object),
    );
  });
});

// ── api.getSettings ───────────────────────────────────────────────────────────

describe('api.getSettings', () => {
  it('calls GET /dashboard/settings', async () => {
    mockFetch({ language: 'en', llm_context: '' });
    await api.getSettings();
    // GET is the default method — explicit method omitted in fetch call
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/dashboard/settings',
      expect.any(Object),
    );
  });
});

// ── api.saveSettings ───────────────────────────────────────────────────────────

describe('api.saveSettings', () => {
  it('POSTs settings data', async () => {
    mockFetch({ language: 'fr', llm_context: 'ctx' });
    await api.saveSettings({ language: 'fr', llm_context: 'ctx' });
    const call = lastCall()!;
    const body = JSON.parse((call[1]?.body as string) ?? '{}');
    expect(body.language).toBe('fr');
  });
});

// ── api.reindexSearch ─────────────────────────────────────────────────────────

describe('api.reindexSearch', () => {
  it('POSTs to /search/reindex', async () => {
    mockFetch({ status: 'ok' });
    await api.reindexSearch();
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/search/reindex',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

// ── fetchApi error handling ──────────────────────────────────────────────────

describe('fetchApi error handling', () => {
  it('throws on non-ok response', async () => {
    const errorResponse = {
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ detail: 'error' }),
    } as unknown as Response;
    fetchSpy.mockResolvedValue(errorResponse);

    await expect(api.getCalendar(2026, 9)).rejects.toThrow('API error: Internal Server Error');
  });
});
