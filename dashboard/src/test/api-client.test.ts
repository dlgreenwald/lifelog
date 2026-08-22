import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '../api/client';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  });
}

function errorResponse(status: number, text = 'Error') {
  return Promise.resolve({
    ok: false,
    status,
    statusText: text,
    json: () => Promise.resolve({}),
  });
}

describe('api client', () => {
  describe('fetchApi error handling', () => {
    it('throws on non-ok response', async () => {
      mockFetch.mockReturnValueOnce(errorResponse(500, 'Internal Server Error'));

      await expect(api.getTodos()).rejects.toThrow('API error: Internal Server Error');
    });

    it('throws on 404', async () => {
      mockFetch.mockReturnValueOnce(errorResponse(404, 'Not Found'));

      await expect(api.getRecording('999')).rejects.toThrow('API error: Not Found');
    });
  });

  describe('api.getCalendar', () => {
    it('fetches calendar for given year/month', async () => {
      const data = { dates: [{ date: '2024-01-15', count: 3 }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getCalendar(2024, 1);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/calendar/2024/1',
        expect.objectContaining({ headers: expect.any(Object) })
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.getRecordings', () => {
    it('fetches recordings for a date', async () => {
      const data = { recordings: [{ id: 1, summary: 'Chat' }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getRecordings('2024-01-15');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/recordings/2024-01-15',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.getRecording', () => {
    it('fetches single recording by id', async () => {
      const data = { id: 5, summary: 'Test', speakers: [] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getRecording('5');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/recording/5',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.getTodos', () => {
    it('fetches todos', async () => {
      const data = { todos: [{ id: 1, task: 'Buy milk', owner: 'Bob', priority: 'low', completed: false }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getTodos();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/todos',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.getTodosForDate', () => {
    it('fetches todos for a specific date', async () => {
      const data = { todos: [{ id: 1, task: 'Buy milk', completed: false }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getTodosForDate('2024-01-15');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/todos/2024-01-15',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.getTodosForRecording', () => {
    it('fetches todos for a recording', async () => {
      const data = { todos: [{ id: 1, task: 'Write proposal', completed: false }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getTodosForRecording('10');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/recording/10/todos',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.completeTodo', () => {
    it('marks a todo as completed', async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({ ok: true }));

      const result = await api.completeTodo(5, true);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/todos/5/complete',
        expect.objectContaining({ method: 'POST' })
      );
      expect(result).toEqual({ ok: true });
    });
  });

  describe('api.deleteTodo', () => {
    it('deletes a todo', async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({ ok: true }));

      const result = await api.deleteTodo(5);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/todos/5',
        expect.objectContaining({ method: 'DELETE' })
      );
      expect(result).toEqual({ ok: true });
    });
  });

  describe('api.getDecisions', () => {
    it('fetches decisions with default include_archived=false', async () => {
      const data = { decisions: [{ decision: 'Go', made_by: 'Alice' }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getDecisions();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/decisions?include_archived=false',
        expect.anything()
      );
      expect(result).toEqual(data);
    });

    it('fetches decisions with include_archived=true', async () => {
      const data = { decisions: [] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      await api.getDecisions(true);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/decisions?include_archived=true',
        expect.anything()
      );
    });
  });

  describe('api.getDecisionsForRecording', () => {
    it('fetches decisions for a recording', async () => {
      const data = { decisions: [{ decision: 'Go', made_by: 'Alice' }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getDecisionsForRecording('10');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/recording/10/decisions',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.archiveDecision', () => {
    it('archives a decision', async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({ ok: true }));

      const result = await api.archiveDecision(5, true);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/decisions/5/archive',
        expect.objectContaining({ method: 'POST' })
      );
      expect(result).toEqual({ ok: true });
    });
  });

  describe('api.deleteDecision', () => {
    it('deletes a decision', async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({ ok: true }));

      const result = await api.deleteDecision(5);

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/decisions/5',
        expect.objectContaining({ method: 'DELETE' })
      );
      expect(result).toEqual({ ok: true });
    });
  });

  describe('api.getUnknownSpeakers', () => {
    it('fetches unknown speakers', async () => {
      const data = { recordings: [{ id: 1, audio_filename: 'a.enc' }] };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.getUnknownSpeakers();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/dashboard/unknown-speakers',
        expect.anything()
      );
      expect(result).toEqual(data);
    });
  });

  describe('api.labelSpeaker', () => {
    it('POSTs speaker label with correct body', async () => {
      const data = { status: 'labeled', label: 'Alice' };
      mockFetch.mockReturnValueOnce(jsonResponse(data));

      const result = await api.labelSpeaker(10, 'Unknown', 'Alice');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/speakers/label',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recording_id: 10, speaker_id: 'Unknown', label: 'Alice' }),
        }
      );
      expect(result).toEqual(data);
    });
  });
});
