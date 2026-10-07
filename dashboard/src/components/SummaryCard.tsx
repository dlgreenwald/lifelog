import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface SummaryCardProps {
  markdown: string;
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
 * - Handles lines that start with "- " but have no preceding blank line.
 */
function preprocessMarkdown(text: string): string {
  // Insert blank line before a line that starts with "- " or "* " when
  // the previous line is not blank.
  return text.replace(/(?!\n)\n(- |\* )/g, "\n\n$1");
}

export default function SummaryCard({ markdown }: SummaryCardProps) {
  return (
    <div className="summary">
      <h3>Summary</h3>
      <div className="summary-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Apply [[hilite]] processing to text nodes within paragraphs/lists
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
