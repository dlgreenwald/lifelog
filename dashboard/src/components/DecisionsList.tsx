import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Decision } from '../types';

export default function DecisionsList() {
  const navigate = useNavigate();
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formDecision, setFormDecision] = useState('');
  const [formMadeBy, setFormMadeBy] = useState('Me');
  const [formContext, setFormContext] = useState('');
  const [formReason, setFormReason] = useState('');

  useEffect(() => {
    api.getDecisions(showArchived).then((data: { decisions: Decision[] }) => {
      setDecisions(data.decisions);
    });
  }, [showArchived]);

  const handleArchive = async (decision: Decision) => {
    await api.archiveDecision(decision.id, !decision.archived);
    setDecisions(prev =>
      prev.map(d => (d.id === decision.id ? { ...d, archived: !d.archived } : d))
    );
  };

  const handleDelete = async (decisionId: number) => {
    await api.deleteDecision(decisionId);
    setDecisions(prev => prev.filter(d => d.id !== decisionId));
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formDecision.trim()) return;
    const result: unknown = await api.createDecision({
      decision: formDecision.trim(),
      made_by: formMadeBy || 'Me',
      context: formContext || undefined,
      reason: formReason || undefined,
    });
    const decisionId =
      result && typeof result === 'object' && 'id' in result && typeof result.id === 'number'
        ? result.id
        : Date.now();
    setDecisions(prev => [
      {
        id: decisionId,
        decision: formDecision.trim(),
        made_by: formMadeBy || 'Me',
        context: formContext || null,
        reason: formReason || null,
        archived: false,
        recording_id: null,
        recording_timestamp: null,
        created_at: new Date().toISOString(),
      },
      ...prev,
    ]);
    setFormDecision('');
    setFormMadeBy('Me');
    setFormContext('');
    setFormReason('');
    setShowForm(false);
  };

  return (
    <div className="decisions-list">
      <h2>Decisions</h2>
      <button className="add-button" onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : '+ Add Decision'}
      </button>
      {showForm && (
        <form className="create-form" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Decision *"
            value={formDecision}
            onChange={e => setFormDecision(e.target.value)}
            required
          />
          <input
            type="text"
            placeholder="Made by"
            value={formMadeBy}
            onChange={e => setFormMadeBy(e.target.value)}
          />
          <textarea
            placeholder="Context (optional)"
            value={formContext}
            onChange={e => setFormContext(e.target.value)}
            rows={2}
          />
          <textarea
            placeholder="Reason (optional)"
            value={formReason}
            onChange={e => setFormReason(e.target.value)}
            rows={2}
          />
          <button type="submit">Create</button>
        </form>
      )}
      <button
        className="toggle-archived"
        onClick={() => setShowArchived(prev => !prev)}
      >
        {showArchived ? 'Hide archived' : 'Show archived'}
      </button>
      {decisions.length === 0 ? (
        <p>No decisions found</p>
      ) : (
        <ul>
          {decisions.map(decision => (
            <li
              key={decision.id}
              className={`${decision.archived ? 'decision-archived' : ''} clickable`}
              onClick={() => {
                if (decision.recording_id) navigate(`/recording/${decision.recording_id}`);
              }}
            >
              <strong>{decision.decision}</strong>
              <span> - {decision.made_by}</span>
              {decision.archived && (
                <span className="decision-archive-badge">Archived</span>
              )}
              {decision.context && <p className="context">{decision.context}</p>}
              {decision.reason && <p className="decision-reason">{decision.reason}</p>}
              <div onClick={e => e.stopPropagation()}>
                <button onClick={() => handleArchive(decision)}>
                  {decision.archived ? 'Unarchive' : 'Archive'}
                </button>
                <button className="todo-delete" onClick={() => handleDelete(decision.id)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
