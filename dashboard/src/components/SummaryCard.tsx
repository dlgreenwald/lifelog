import React, { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Pencil, Save, X } from "lucide-react";
import { Editable, useEditor } from "@wysimark/react";
import { api } from "../api/client";

interface SummaryCardProps {
  /** The recording ID, required for saving edits. */
  recordingId?: string;
  /** The current summary markdown. */
  markdown: string;
  /** Called after a successful save so the parent can update its state. */
  onSummaryChanged?: (summary: string) => void;
}

/**
 * Render [[hilite]]...[[/hilite]] markers inside a string as <mark> elements.
 * Used for Meilisearch search highlighting within markdown content.
 */
function renderFormatted(text: string): React.ReactNode {
  if (!text) return text;
  const parts = text.split(/(\[\[hilite\]\]|\[\[\/hilite\]\])/);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((part, i) =>
        part === "[[hilite]]" ? null
        : part === "[[/hilite]]" ? null
        : parts[i - 1] === "[[hilite]]"
          ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700 rounded px-0.5">{part}</mark>
          : part
      )}
    </>
  );
}

/**
 * Walk React children and apply renderFormatted to any text nodes that contain [[hilite]].
 * This handles the case where the markdown paragraph itself contains the markers.
 */
function walkAndFormat(node: React.ReactNode): React.ReactNode {
  if (typeof node === "string") {
    return renderFormatted(node);
  }
  if (Array.isArray(node)) {
    return <>{node.map(walkAndFormat)}</>;
  }
  if (React.isValidElement(node) && node.props && typeof node.props === "object") {
    const { children, ...rest } = node.props as { children?: React.ReactNode };
    if (children === undefined) return node;
    return React.cloneElement(node as React.ReactElement<Record<string, unknown>>, rest, walkAndFormat(children));
  }
  return node;
}

/**
 * Pre-process markdown to normalize common LLM formatting issues so react-markdown
 * parses them correctly.
 * - Inserts a blank line before standalone list items so react-markdown (which
 *   requires blank lines between block elements) can parse them as a proper list.
 */
function preprocessMarkdown(text: string): string {
  return text.replace(/(?!\n)\n(- |\* )/g, "\n\n$1");
}

export default function SummaryCard({ recordingId, markdown, onSummaryChanged }: SummaryCardProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState(markdown);

  const editor = useEditor({});

  const handleSave = useCallback(async () => {
    if (!editor || !recordingId) return;
    setSaving(true);
    setError(null);
    try {
      const newMarkdown = editor.getMarkdown();
      await api.updateRecordingSummary(recordingId, newMarkdown);
      onSummaryChanged?.(newMarkdown);
      setDraft(newMarkdown);
      setEditing(false);
    } catch {
      setError("Failed to save summary. Please try again.");
    } finally {
      setSaving(false);
    }
  }, [editor, recordingId, onSummaryChanged]);

  const handleCancel = useCallback(() => {
    setDraft(markdown);
    setEditing(false);
    setError(null);
  }, [markdown]);

  const handleEnterEdit = useCallback(() => {
    setDraft(markdown);
    setEditing(true);
  }, [markdown]);

  const isEditable = Boolean(recordingId);

  if (!editing) {
    return (
      <div className="summary">
        <div className="summary-header">
          <h3>Summary</h3>
          {isEditable && (
            <button
              className="summary-edit-btn"
              onClick={handleEnterEdit}
              aria-label="Edit summary"
            >
              <Pencil size={14} />
            </button>
          )}
        </div>
        <div className="summary-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p>{walkAndFormat(children)}</p>,
              li: ({ children }) => <li>{walkAndFormat(children)}</li>,
            }}
          >
            {preprocessMarkdown(markdown)}
          </ReactMarkdown>
        </div>
      </div>
    );
  }

  return (
    <div className="summary summary-editing">
      <div className="summary-header">
        <h3>Summary</h3>
      </div>
      <div className="summary-body">
        <div className="summary-editor-wrapper">
          <Editable
            editor={editor}
            value={draft}
            onChange={setDraft}
            placeholder="Add a summary…"
            className="summary-editor"
          />
        </div>
        {error && <p className="summary-error">{error}</p>}
        <div className="summary-actions">
          <button className="summary-save-btn" onClick={handleSave} disabled={saving}>
            <Save size={14} />
            {saving ? "Saving…" : "Save"}
          </button>
          <button className="summary-cancel-btn" onClick={handleCancel} disabled={saving}>
            <X size={14} />
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
