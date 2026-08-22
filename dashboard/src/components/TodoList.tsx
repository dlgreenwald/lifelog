import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { Todo } from '../types';

const ONE_DAY_MS = 86400000;

export default function TodoList() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [showCompleted, setShowCompleted] = useState(false);

  useEffect(() => {
    api.getTodos().then((data: { todos: Todo[] }) => {
      setTodos(data.todos);
    });
  }, []);

  const handleToggle = async (todo: Todo) => {
    const newCompleted = !todo.completed;
    await api.completeTodo(todo.id, newCompleted);
    setTodos(prev =>
      prev.map(t =>
        t.id === todo.id
          ? {
              ...t,
              completed: newCompleted,
              completed_at: newCompleted ? new Date().toISOString() : null,
            }
          : t
      )
    );
  };

  const handleDelete = async (todoId: number) => {
    await api.deleteTodo(todoId);
    setTodos(prev => prev.filter(t => t.id !== todoId));
  };

  const filteredTodos = showCompleted
    ? todos
    : todos.filter(t => {
        if (!t.completed) return true;
        // Show recently completed (within 24h), hide old
        if (!t.completed_at) return true;
        return Date.now() - new Date(t.completed_at).getTime() < ONE_DAY_MS;
      });

  return (
    <div className="todo-list">
      <h2>TODOs</h2>
      {todos.length === 0 ? (
        <p>No TODOs found</p>
      ) : (
        <>
          <button
            className="toggle-completed"
            onClick={() => setShowCompleted(!showCompleted)}
          >
            {showCompleted ? 'Hide completed' : 'Show completed'}
          </button>
          <ul>
            {filteredTodos.map(todo => (
              <li
                key={todo.id}
                className={`priority-${todo.priority} ${todo.completed ? 'completed' : ''}`}
              >
                <input
                  type="checkbox"
                  className="todo-checkbox"
                  checked={todo.completed}
                  onChange={() => handleToggle(todo)}
                />
                <span className="todo-task">{todo.task}</span>
                <span> - {todo.owner}</span>
                {todo.due && <span> (due: {todo.due})</span>}
                <span className="priority-badge">{todo.priority}</span>
                <button
                  className="todo-delete"
                  onClick={() => handleDelete(todo.id)}
                  aria-label={`Delete todo: ${todo.task}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
