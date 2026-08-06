import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { Todo } from '../types';

export default function TodoList() {
  const [todos, setTodos] = useState<Todo[]>([]);

  useEffect(() => {
    api.getTodos().then((data: { todos: Todo[] }) => {
      setTodos(data.todos);
    });
  }, []);

  return (
    <div className="todo-list">
      <h2>TODOs</h2>
      {todos.length === 0 ? (
        <p>No TODOs found</p>
      ) : (
        <ul>
          {todos.map((todo, i) => (
            <li key={i} className={`priority-${todo.priority}`}>
              <strong>{todo.task}</strong>
              <span> - {todo.owner}</span>
              {todo.due && <span> (due: {todo.due})</span>}
              <span className="priority-badge">{todo.priority}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
