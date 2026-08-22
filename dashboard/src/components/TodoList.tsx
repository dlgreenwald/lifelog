import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Todo } from '../types';

const ONE_DAY_MS = 86400000;

export default function TodoList() {
  const navigate = useNavigate();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [showCompleted, setShowCompleted] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formTask, setFormTask] = useState('');
  const [formOwner, setFormOwner] = useState('Me');
  const [formDue, setFormDue] = useState(() => new Date().toISOString().slice(0, 10));
  const [formPriority, setFormPriority] = useState('medium');

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

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTask.trim()) return;
    const result: unknown = await api.createTodo({
      task: formTask.trim(),
      owner: formOwner || 'Me',
      due: formDue || undefined,
      priority: formPriority,
    });
    // Prepend optimistic todo (server returns { id })
    const todoId =
      result && typeof result === 'object' && 'id' in result && typeof result.id === 'number'
        ? result.id
        : Date.now();
    setTodos(prev => [
      {
        id: todoId,
        task: formTask.trim(),
        owner: formOwner || 'Me',
        due: formDue || null,
        priority: formPriority as 'high' | 'medium' | 'low',
        completed: false,
        completed_at: null,
        recording_id: null,
        recording_timestamp: null,
        created_at: new Date().toISOString(),
      },
      ...prev,
    ]);
    setFormTask('');
    setFormOwner('Me');
    setFormDue(new Date().toISOString().slice(0, 10));
    setFormPriority('medium');
    setShowForm(false);
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
      <button className="add-button" onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : '+ Add Todo'}
      </button>
      {showForm && (
        <form className="create-form" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Task *"
            value={formTask}
            onChange={e => setFormTask(e.target.value)}
            required
          />
          <input
            type="text"
            placeholder="Owner"
            value={formOwner}
            onChange={e => setFormOwner(e.target.value)}
          />
          <input
            type="date"
            placeholder="Due date"
            value={formDue}
            onChange={e => setFormDue(e.target.value)}
          />
          <select value={formPriority} onChange={e => setFormPriority(e.target.value)}>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <button type="submit">Create</button>
        </form>
      )}
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
                className={`priority-${todo.priority} ${todo.completed ? 'completed' : ''} clickable`}
                onClick={() => {
                  if (todo.recording_id) navigate(`/recording/${todo.recording_id}`);
                }}
              >
                <input
                  type="checkbox"
                  className="todo-checkbox"
                  checked={todo.completed}
                  onChange={e => { e.stopPropagation(); handleToggle(todo); }}
                />
                <span className="todo-task">{todo.task}</span>
                <span> - {todo.owner}</span>
                {todo.due && <span> (due: {todo.due})</span>}
                <span className="priority-badge">{todo.priority}</span>
                <button
                  className="todo-delete"
                  onClick={e => { e.stopPropagation(); handleDelete(todo.id); }}
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
