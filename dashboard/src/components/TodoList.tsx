import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, X, ArrowUp, ArrowDown } from 'lucide-react';
import { api } from '../api/client';
import type { Todo } from '../types';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

const ONE_DAY_MS = 86400000;
type SortField = 'created_at' | 'priority';

export default function TodoList() {
  const navigate = useNavigate();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [showCompleted, setShowCompleted] = useState(false);
  const [sortBy, setSortBy] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
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

  const cycleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortDir('asc');
    }
  };

  const filteredTodos = (showCompleted
    ? todos
    : todos.filter(t => {
        if (!t.completed) return true;
        if (!t.completed_at) return true;
        return Date.now() - new Date(t.completed_at).getTime() < ONE_DAY_MS;
      }))
    .slice()
    .sort((a, b) => {
      if (sortBy === 'created_at') {
        const diff = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        return sortDir === 'asc' ? diff : -diff;
      }
      const PRIORITY_ORDER: Record<string, number> = { high: 1, medium: 2, low: 3 };
      const diff = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      return sortDir === 'asc' ? diff : -diff;
    });

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

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
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Sort:</span>
              <button
                className={`sort-btn flex items-center gap-1 text-sm px-2 py-1 rounded border ${sortBy === 'created_at' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground hover:bg-muted/50'}`}
                onClick={() => cycleSort('created_at')}
              >
                Created
                {sortBy === 'created_at' && (sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
              </button>
              <button
                className={`sort-btn flex items-center gap-1 text-sm px-2 py-1 rounded border ${sortBy === 'priority' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground hover:bg-muted/50'}`}
                onClick={() => cycleSort('priority')}
              >
                Priority
                {sortBy === 'priority' && (sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
              </button>
            </div>
            <button
              className="toggle-completed text-sm"
              onClick={() => setShowCompleted(prev => !prev)}
            >
              {showCompleted ? 'Hide completed' : 'Show completed'}
            </button>
          </div>

          <ul className="rounded-lg border bg-card text-card-foreground shadow-sm" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            <li className="grid grid-cols-[auto_1fr_auto_auto_auto] gap-3 px-4 py-2 border-b border-border bg-muted/30 text-xs font-medium text-muted-foreground">
              <div className="w-5"></div>
              <div>Task</div>
              <div className="w-16 text-right">Created</div>
              <div className="w-16 text-center">Priority</div>
              <div className="w-7"></div>
            </li>
            {filteredTodos.map((todo, i) => (
              <li
                key={todo.id}
                className={`group grid grid-cols-[auto_1fr_auto_auto_auto] gap-3 px-4 py-3 items-center ${todo.completed ? 'opacity-60' : ''} ${todo.recording_id ? 'cursor-pointer hover:bg-muted/50' : ''} transition-colors ${i > 0 ? 'border-t border-border' : ''}`}
                onClick={() => {
                  if (todo.recording_id) navigate(`/recording/${todo.recording_id}`);
                }}
              >
                <Checkbox
                  checked={todo.completed}
                  onCheckedChange={() => handleToggle(todo)}
                  onClick={e => e.stopPropagation()}
                  className="shrink-0"
                  aria-label={`Mark "${todo.task}" as ${todo.completed ? 'incomplete' : 'complete'}`}
                />
                <div className="min-w-0">
                  <span className="text-sm font-medium leading-tight block truncate">{todo.task}</span>
                  <span className="text-xs text-muted-foreground"> - {todo.owner}{todo.due ? ` (due: ${todo.due})` : ''}</span>
                </div>
                <div className="w-16 text-right text-xs text-muted-foreground tabular-nums shrink-0">
                  {formatDate(todo.created_at)}
                </div>
                <div className="w-16 text-center shrink-0">
                  <span className="text-xs font-medium" style={{
                    backgroundColor: todo.priority === 'high' ? '#fee2e2' : todo.priority === 'medium' ? '#fef3c7' : '#dcfce7',
                    color: todo.priority === 'high' ? '#991b1b' : todo.priority === 'medium' ? '#92400e' : '#166534',
                    padding: '2px 6px',
                    borderRadius: '4px',
                  }}>{todo.priority}</span>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity"
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
