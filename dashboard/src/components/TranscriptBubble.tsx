import React from "react";
import { Bubble, BubbleContent, BubbleGroup } from "@/components/ui/bubble";
import type { TranscriptSegment } from "@/types";

interface TranscriptBubbleProps {
  segments: TranscriptSegment[];
  /** Hide speaker labels (used for live recordings). */
  hideSpeakerLabels?: boolean;
  /** Override speaker label display (shown outside the group). */
  speakerLabel?: (name: string) => string;
  /**
   * Pre-rendered highlighted transcript text from Meilisearch _formatted.
   * When present and contains [[hilite]] markers, rendered directly
   * (bypasses per-segment rendering so speaker context is preserved in the text).
   */
  highlightedText?: string | null;
}

interface Group {
  name: string;
  /** Global indices into the original segments array. */
  indices: number[];
}

/** Group consecutive segments by speaker name, preserving order. */
function groupSegments(segments: TranscriptSegment[]): Group[] {
  const groups: Group[] = [];
  segments.forEach((seg, i) => {
    const name = seg.name ?? seg.speaker ?? "Unknown";
    const last = groups[groups.length - 1];
    if (last && last.name === name) {
      last.indices.push(i);
    } else {
      groups.push({ name, indices: [i] });
    }
  });
  return groups;
}

/**
 * Render a string containing [[hilite]]...[[/hilite]] markers as JSX.
 * Used for Meilisearch pre-rendered highlighted text.
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

const defaultLabel = (name: string) => name;

/**
 * Parse fmt_text (Meilisearch _formatted.text) back into per-segment records
 * with speaker labels and [[hilite]] markers preserved in the text field.
 *
 * fmt_text format: "SPEAKER_00: segment text SPEAKER_01: next text..."
 * _matchesPosition['text'] offsets are relative to this same speaker-prefixed
 * concatenated text, so the [[hilite]] markers in fmt_text are already at the
 * correct character positions.
 */
function parseFormattedTranscript(highlightedText: string): TranscriptSegment[] {
  // Pattern matches "SPEAKER_XX:" or "Speaker Name:" prefixes before segment text.
  // Handles SPEAKER_00, SPEAKER_01, etc. and arbitrary speaker display names.
  const SEGMENT_PATTERN = /(?:(SPEAKER_\d+|[A-Z][A-Za-z ]+?):\s*)(.*?)(?=(?:\s*SPEAKER_\d+|\s*[A-Z][A-Za-z ]+?:)|$)/gs;
  const segments: TranscriptSegment[] = [];
  let match: RegExpExecArray | null;
  SEGMENT_PATTERN.lastIndex = 0;
  while ((match = SEGMENT_PATTERN.exec(highlightedText)) !== null) {
    const raw = match[2] ?? "";
    // Strip trailing whitespace that would otherwise accumulate across segments.
    const text = raw.trimEnd();
    if (text) {
      segments.push({ text, name: match[1] ?? "Unknown", start: 0, end: 0 });
    }
  }
  return segments;
}

export default function TranscriptBubble({
  segments,
  hideSpeakerLabels,
  speakerLabel = defaultLabel,
  highlightedText,
}: TranscriptBubbleProps) {
  // When navigating from search results, Meilisearch passes the full
  // pre-highlighted transcript as fmt_text with [[hilite]] markers embedded
  // at _matchesPosition offsets. Parse it back into per-segment records so
  // speaker grouping (and renderFormatted per-segment) works correctly.
  const segmentsToRender =
    highlightedText?.includes("[[hilite]]")
      ? parseFormattedTranscript(highlightedText)
      : segments;

  const groups = groupSegments(segmentsToRender);

  return (
    <div className="flex flex-col gap-4">
      {groups.map((group, gi) => (
        <div key={gi} className="flex flex-col gap-1">
          {/* Speaker label shown once per group — outside all bubbles. */}
          {!hideSpeakerLabels && (
            <span className="px-3 text-xs font-medium text-muted-foreground">
              {speakerLabel(group.name)}
            </span>
          )}
          <BubbleGroup>
            <Bubble>
              <BubbleContent>
                {group.indices.map((segIdx) => {
                  const text = segmentsToRender[segIdx].text ?? "";
                  if (text.includes("[[hilite]]")) return renderFormatted(text);
                  // Join consecutive utterances with a space; add newline between
                  // same-speaker turns so it reads like a transcript.
                  return (
                    <React.Fragment key={segIdx}>
                      {segIdx > group.indices[0] ? " " : null}
                      {text}
                    </React.Fragment>
                  );
                })}
              </BubbleContent>
            </Bubble>
          </BubbleGroup>
        </div>
      ))}
    </div>
  );
}
