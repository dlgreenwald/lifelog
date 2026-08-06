import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import TodoList from '../components/TodoList';
import { api } from '../api/client';
import type { Todo } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getTodos: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

const mockTodos: Todo[] = [
  { task: 'Buy groceries', owner: 'Bob', due: '2024-01-20', priority: 'low' },
  { task: 'Fix critical bug', owner: 'Alice', due: null, priority: 'high' },
  { task: 'Write docs', owner: 'Charlie', due: '2024-02-01', priority: 'medium' },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TodoList', () => {
  it('shows loading state then renders todos', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries')).toBeInTheDocument();
    });

    expect(screen.getByText('Fix critical bug')).toBeInTheDocument();
    expect(screen.getByText('Write docs')).toBeInTheDocument();
  });

  it('shows "No TODOs found" when empty', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText('No TODOs found')).toBeInTheDocument();
    });
  });

  it('displays todo owners', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText(/Bob/)).toBeInTheDocument();
    });
  });

  it('displays due dates when present', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText(/2024-01-20/)).toBeInTheDocument();
    });
  });

  it('hides due date when null', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText('Fix critical bug')).toBeInTheDocument();
    });

    // The "Fix critical bug" todo has null due - no due text for it
    const dueElements = screen.queryAllByText(/due:/);
    expect(dueElements).toHaveLength(2); // Only 2 of 3 have due dates
  });

  it('applies priority class names', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries').closest('li')).toHaveClass('priority-low');
      expect(screen.getByText('Fix critical bug').closest('li')).toHaveClass('priority-high');
      expect(screen.getByText('Write docs').closest('li')).toHaveClass('priority-medium');
    });
  });

  it('shows priority badges', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<TodoList />);

    await waitFor(() => {
      const badges = screen.getAllByText(/^(high|medium|low)$/);
      expect(badges).toHaveLength(3);
    });
  });

  it('calls getTodos on mount', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });

    render(<TodoList />);

    expect(mockApi.getTodos).toHaveBeenCalledTimes(1);
  });
});
