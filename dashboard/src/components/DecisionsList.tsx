import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Archive, RotateCcw, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import type { Decision } from '../types';
import { Button } from '@/components/ui/button';

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
      prev.map(d => d.id === decision.id ? { ...d, archived: !decision.archived } : d)
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
    <div className="flex flex-col h-full px-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold tracking-tight">Decisions</h2>
        <Button
          size="sm"
          onClick={() => setShowForm(prev => !prev)}
          className="add-button"
          style={{ backgroundColor: 'hsl(221.2,83.2%,53.3%)', color: 'hsl(0,0%,98%)', border: 'none' }}
        >
          <Plus className="h-4 w-4 mr-1" />
          {showForm ? 'Cancel' : '+ Add Decision'}
        </Button>
      </div>

      {showForm && (
        <form className="create-form mb-4 rounded-lg border bg-card p-4 shadow-sm space-y-3" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Decision *"
            value={formDecision}
            onChange={e => setFormDecision(e.target.value)}
            required
            autoFocus
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <input
            type="text"
            placeholder="Made by"
            value={formMadeBy}
            onChange={e => setFormMadeBy(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <textarea
            placeholder="Context (optional)"
            value={formContext}
            onChange={e => setFormContext(e.target.value)}
            rows={2}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 resize-none"
          />
          <textarea
            placeholder="Reason (optional)"
            value={formReason}
            onChange={e => setFormReason(e.target.value)}
            rows={2}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 resize-none"
          />
          <Button
            type="submit"
            size="sm"
            style={{ backgroundColor: 'hsl(221.2,83.2%,53.3%)', color: 'hsl(0,0%,98%)', border: 'none' }}
          >
            Create
          </Button>
        </form>
      )}

      <button
        className="toggle-archived"
        onClick={() => setShowArchived(prev => !prev)}
      >
        {showArchived ? 'Hide archived' : 'Show archived'}
      </button>

      {decisions.length === 0 ? (
        <p className="text-sm text-muted-foreground py-12 text-center">No decisions yet — click "Add Decision" above to create one.</p>
      ) : (
        <ul className="rounded-lg border bg-card text-card-foreground shadow-sm" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {decisions.map((decision, i) => (
            <li
              key={decision.id}
              className={`px-4 py-3 ${decision.archived ? 'opacity-60' : ''} ${decision.recording_id ? 'cursor-pointer hover:bg-muted/50' : ''} transition-colors ${i > 0 ? 'border-t border-border' : ''}`}
              onClick={() => {
                if (decision.recording_id) navigate(`/recording/${decision.recording_id}`);
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <strong className="text-sm font-semibold">{decision.decision}</strong>
                  <span className="text-sm text-muted-foreground"> - {decision.made_by}</span>
                  {decision.archived && (
                    <span className="decision-archive-badge ml-2 text-xs font-medium">Archived</span>
                  )}
                  {decision.context && (
                    <p className="context mt-1.5 text-xs text-muted-foreground border-l-2 border-muted-foreground/30 pl-2">{decision.context}</p>
                  )}
                  {decision.reason && (
                    <p className="decision-reason mt-1 text-xs text-muted-foreground italic border-l-2 border-primary/40 pl-2">{decision.reason}</p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-muted-foreground"
                    onClick={() => handleArchive(decision)}
                  >
                    {decision.archived ? (
                      <><RotateCcw className="h-3 w-3 mr-1" />Unarchive</>
                    ) : (
                      <><Archive className="h-3 w-3 mr-1" />Archive</>
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-foreground hover:text-destructive"
                    onClick={() => handleDelete(decision.id)}
                  >
                    <Trash2 className="h-3 w-3 mr-1" />Delete
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
