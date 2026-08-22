import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import TodoList from '../components/TodoList';
import { api } from '../api/client';
import type { Todo } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getTodos: vi.fn(),
    completeTodo: vi.fn(),
    deleteTodo: vi.fn(),
    createTodo: vi.fn(),
  },
}));

const mockApi = vi.mocked(api);

function makeTodo(overrides: Partial<Todo> = {}): Todo {
  return {
    id: 1,
    task: 'Buy groceries',
    owner: 'Bob',
    due: '2024-01-20',
    priority: 'low',
    completed: false,
    completed_at: null,
    recording_id: 10,
    recording_timestamp: '2024-01-15T10:00:00',
    created_at: '2024-01-15T10:00:00',
    ...overrides,
  };
}

const mockTodos: Todo[] = [
  makeTodo({ id: 1, task: 'Buy groceries', owner: 'Bob', priority: 'low' }),
  makeTodo({ id: 2, task: 'Fix critical bug', owner: 'Alice', due: null, priority: 'high' }),
  makeTodo({ id: 3, task: 'Write docs', owner: 'Charlie', due: '2024-02-01', priority: 'medium', recording_id: 11 }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TodoList', () => {
  it('renders todos after loading', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries')).toBeInTheDocument();
    });
    expect(screen.getByText('Fix critical bug')).toBeInTheDocument();
    expect(screen.getByText('Write docs')).toBeInTheDocument();
  });

  it('shows "No TODOs found" when empty', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No TODOs found')).toBeInTheDocument();
    });
  });

  it('displays todo owners', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/Bob/)).toBeInTheDocument();
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
    });
  });

  it('displays due dates when present', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/2024-01-20/)).toBeInTheDocument();
    });
  });

  it('hides due date when null', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Fix critical bug')).toBeInTheDocument();
    });

    const dueElements = screen.queryAllByText(/due:/);
    expect(dueElements).toHaveLength(2);
  });

  it('applies priority class names', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries').closest('li')).toHaveClass('priority-low');
      expect(screen.getByText('Fix critical bug').closest('li')).toHaveClass('priority-high');
    });
  });

  it('shows priority badges', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      const badges = screen.getAllByText(/^(high|medium|low)$/);
      expect(badges).toHaveLength(3);
    });
  });

  it('calls getTodos on mount', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    expect(mockApi.getTodos).toHaveBeenCalledTimes(1);
  });

  it('renders checkboxes for each todo', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      const checkboxes = screen.getAllByRole('checkbox');
      expect(checkboxes).toHaveLength(3);
    });
  });

  it('toggles todo completion on checkbox click', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });
    mockApi.completeTodo.mockResolvedValue({ ok: true });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries')).toBeInTheDocument();
    });

    const checkbox = screen.getAllByRole('checkbox')[0];
    await userEvent.click(checkbox);

    expect(mockApi.completeTodo).toHaveBeenCalledWith(1, true);
  });

  it('renders delete buttons for each todo', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      const deleteButtons = screen.getAllByRole('button', { name: /Delete todo/ });
      expect(deleteButtons).toHaveLength(3);
    });
  });

  it('deletes todo on delete button click', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: mockTodos });
    mockApi.deleteTodo.mockResolvedValue({ ok: true });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Buy groceries')).toBeInTheDocument();
    });

    const deleteBtn = screen.getAllByRole('button', { name: /Delete todo/ })[0];
    await userEvent.click(deleteBtn);

    expect(mockApi.deleteTodo).toHaveBeenCalledWith(1);

    await waitFor(() => {
      expect(screen.queryByText('Buy groceries')).not.toBeInTheDocument();
    });
  });

  it('hides completed todos older than 24h by default', async () => {
    const oldCompleted = makeTodo({
      id: 4,
      task: 'Old completed task',
      completed: true,
      completed_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    });
    const recentCompleted = makeTodo({
      id: 5,
      task: 'Recent completed task',
      completed: true,
      completed_at: new Date(Date.now() - 3600000).toISOString(),
    });
    mockApi.getTodos.mockResolvedValue({ todos: [oldCompleted, recentCompleted] });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('Recent completed task')).toBeInTheDocument();
    });
    expect(screen.queryByText('Old completed task')).not.toBeInTheDocument();
  });

  it('shows all completed when toggle is on', async () => {
    const oldCompleted = makeTodo({
      id: 4,
      task: 'Old completed task',
      completed: true,
      completed_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    });
    mockApi.getTodos.mockResolvedValue({ todos: [oldCompleted] });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.queryByText('Old completed task')).not.toBeInTheDocument();
    });

    const toggleBtn = screen.getByText('Show completed');
    await userEvent.click(toggleBtn);

    await waitFor(() => {
      expect(screen.getByText('Old completed task')).toBeInTheDocument();
    });
  });

  it('shows create form when add button clicked', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No TODOs found')).toBeInTheDocument();
    });

    const addBtn = screen.getByText('+ Add Todo');
    await userEvent.click(addBtn);

    expect(screen.getByPlaceholderText('Task *')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Owner')).toBeInTheDocument();
    expect(screen.getByText('Create')).toBeInTheDocument();
  });

  it('creates todo and prepends to list', async () => {
    mockApi.getTodos.mockResolvedValue({ todos: [] });
    mockApi.createTodo.mockResolvedValue({ id: 100 });

    render(<MemoryRouter><TodoList /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText('No TODOs found')).toBeInTheDocument();
    });

    // Open form
    await userEvent.click(screen.getByText('+ Add Todo'));

    // Fill form
    await userEvent.type(screen.getByPlaceholderText('Task *'), 'New task');
    const ownerInput = screen.getByPlaceholderText('Owner');
    await userEvent.clear(ownerInput);
    await userEvent.type(ownerInput, 'Alice');
    await userEvent.click(screen.getByText('Create'));

    await waitFor(() => {
      expect(mockApi.createTodo).toHaveBeenCalledWith({
        task: 'New task',
        owner: 'Alice',
        due: new Date().toISOString().slice(0, 10),
        priority: 'medium',
      });
    });

    // Todo should appear in the list
    await waitFor(() => {
      expect(screen.getByText('New task')).toBeInTheDocument();
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
    });
  });
});
