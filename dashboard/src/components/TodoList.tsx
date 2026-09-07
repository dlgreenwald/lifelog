import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, X } from 'lucide-react';
import { api } from '../api/client';
import type { Todo } from '../types';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

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
        if (!t.completed_at) return true;
        return Date.now() - new Date(t.completed_at).getTime() < ONE_DAY_MS;
      });

  return (
    <div className="flex flex-col h-full px-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold tracking-tight">TODOs</h2>
        <Button
          size="sm"
          onClick={() => setShowForm(prev => !prev)}
          className="add-button"
          style={{ backgroundColor: 'hsl(221.2,83.2%,53.3%)', color: 'hsl(0,0%,98%)', border: 'none' }}
        >
          <Plus className="h-4 w-4 mr-1" />
          {showForm ? 'Cancel' : '+ Add Todo'}
        </Button>
      </div>

      {showForm && (
        <form className="create-form mb-4 rounded-lg border bg-card p-4 shadow-sm space-y-3" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Task *"
            value={formTask}
            onChange={e => setFormTask(e.target.value)}
            required
            autoFocus
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <input
            type="text"
            placeholder="Owner"
            value={formOwner}
            onChange={e => setFormOwner(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <div className="flex gap-3">
            <input
              type="date"
              placeholder="Due date"
              value={formDue}
              onChange={e => setFormDue(e.target.value)}
              className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
            <select
              value={formPriority}
              onChange={e => setFormPriority(e.target.value)}
              className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <Button
            type="submit"
            size="sm"
            style={{ backgroundColor: 'hsl(221.2,83.2%,53.3%)', color: 'hsl(0,0%,98%)', border: 'none' }}
          >
            Create
          </Button>
        </form>
      )}

      {todos.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center">No TODOs found</p>
      ) : (
        <>
          <button
            className="toggle-completed"
            onClick={() => setShowCompleted(prev => !prev)}
          >
            {showCompleted ? 'Hide completed' : 'Show completed'}
          </button>

          <ul className="rounded-lg border bg-card text-card-foreground shadow-sm" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {filteredTodos.map((todo, i) => (
              <li
                key={todo.id}
                className={`priority-${todo.priority} ${todo.completed ? 'completed' : ''} clickable group flex items-start gap-3 px-4 py-3 transition-colors ${todo.recording_id ? 'cursor-pointer hover:bg-muted/50' : ''} ${todo.completed ? 'opacity-60' : ''} ${i > 0 ? 'border-t border-border' : ''}`}
                onClick={() => {
                  if (todo.recording_id) navigate(`/recording/${todo.recording_id}`);
                }}
              >
                <Checkbox
                  checked={todo.completed}
                  onCheckedChange={() => handleToggle(todo)}
                  onClick={e => e.stopPropagation()}
                  className="todo-checkbox mt-0.5 shrink-0"
                  aria-label={`Mark "${todo.task}" as ${todo.completed ? 'incomplete' : 'complete'}`}
                />
                <div className="flex-1 min-w-0">
                  <span className="todo-task text-sm font-medium leading-tight">{todo.task}</span>
                  <span className="text-sm text-muted-foreground"> - {todo.owner}</span>
                  {todo.due && <span className="text-sm text-muted-foreground"> (due: {todo.due})</span>}
                </div>
                <span className="priority-badge text-xs font-medium" style={{
                  backgroundColor: todo.priority === 'high' ? '#fee2e2' : todo.priority === 'medium' ? '#fef3c7' : '#dcfce7',
                  color: todo.priority === 'high' ? '#991b1b' : todo.priority === 'medium' ? '#92400e' : '#166534',
                }}>{todo.priority}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="todo-delete h-7 w-7 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={e => { e.stopPropagation(); handleDelete(todo.id); }}
                  aria-label={`Delete todo: ${todo.task}`}
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
