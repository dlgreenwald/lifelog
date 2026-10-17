import { useState, useCallback } from 'react';
import { Pencil, Save, X } from 'lucide-react';
import { Editable, useEditor } from '@wysimark/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../api/client';

interface NotesPanelProps {
  recordingId: string;
  /** The current notes content — null or empty string means empty. */
  notes: string | null;
  /** Called after a successful save so the parent can update its state. */
  onNotesChanged: (notes: string) => void;
}

export default function NotesPanel({ recordingId, notes, onNotesChanged }: NotesPanelProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Local draft while editing — initialized from props, updated by wysimark's onChange
  const [draft, setDraft] = useState(notes ?? '');

  // Defensive: coerce to string
  const safeNotes = typeof notes === 'string' ? notes : '';
  const isEmpty = !safeNotes || safeNotes.trim() === '';

  const editor = useEditor({});

  const handleSave = useCallback(async () => {
    if (!editor) return;
    setSaving(true);
    setError(null);
    try {
      // wysimark stores markdown — getMarkdown returns raw markdown source
      const markdown = editor.getMarkdown();
      await api.updateRecordingNotes(recordingId, markdown);
      onNotesChanged(markdown);
      setDraft(markdown);
      setEditing(false);
    } catch {
      setError('Failed to save notes. Please try again.');
    } finally {
      setSaving(false);
    }
  }, [editor, recordingId, onNotesChanged]);

  const handleCancel = useCallback(() => {
    // Reset draft to current saved notes
    setDraft(safeNotes);
    setEditing(false);
    setError(null);
  }, [safeNotes]);

  const handleEnterEdit = useCallback(() => {
    // Sync draft to current saved value before entering edit mode
    setDraft(safeNotes);
    setEditing(true);
  }, [safeNotes]);

  if (!editing) {
    return (
      <div className="notes-panel">
        <div className="notes-header">
          <h3>Notes</h3>
          {!isEmpty && (
            <button
              className="notes-edit-btn"
              onClick={handleEnterEdit}
              aria-label="Edit notes"
            >
              <Pencil size={14} />
            </button>
          )}
        </div>
        <div className="notes-body">
          {isEmpty ? (
            <button
              className="notes-add-link"
              onClick={handleEnterEdit}
            >
              Add notes
            </button>
          ) : (
            <div className="notes-view">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Render mermaid code blocks as styled pre blocks (no live rendering in view mode)
                  pre: ({ children }) => <pre className="notes-mermaid-block">{children}</pre>,
                }}
              >
                {safeNotes}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="notes-panel notes-panel-editing">
      <div className="notes-header">
        <h3>Notes</h3>
      </div>
      <div className="notes-body">
        <div className="notes-editor-wrapper">
          <Editable
            editor={editor}
            value={draft}
            onChange={setDraft}
            placeholder="Add notes…"
            className="notes-editor"
          />
        </div>
        {error && <p className="notes-error">{error}</p>}
        <div className="notes-actions">
          <button className="notes-save-btn" onClick={handleSave} disabled={saving}>
            <Save size={14} />
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button className="notes-cancel-btn" onClick={handleCancel} disabled={saving}>
            <X size={14} />
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
