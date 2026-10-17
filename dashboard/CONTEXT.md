# Dashboard

React SPA for browsing, playing, and annotating voice recordings.

## Language

**Recording**:
A voice recording captured by the ESP32-S3 wearable device, uploaded and processed through the pipeline. Contains audio, transcript, speaker segments, and an optional notes field.
_Avoid_: Audio clip, voice memo, entry

**Recording Notes**:
A single freeform markdown field on a Recording, owner-authored. Supports GFM (tables, strikethrough, task lists) and inline Mermaid diagrams. Persisted server-side as a TEXT column.
_Avoid_: Comment, annotation, memo

**Note Edit Mode**:
The state in which the owner can author or modify Recording Notes. Entered by clicking the pencil icon (edit affordance) in the notes panel. Exited via Save button. The editor does not take over the full screen — it is a small inline component alongside the audio player and transcript.
_Avoid_: Edit state, annotation mode

**Note View Mode**:
The default read-only rendered view of Recording Notes, displayed above the audio player in the detail panel. Mermaid diagram blocks render as styled `<pre>` code blocks. Empty notes show a subtle "Add notes" link.
_Avoid_: Read mode, display mode

**Detail Panel**:
The right-hand column of the dashboard when a Recording is selected. Contains, in top-to-bottom order: Recording metadata, LLM-generated summary, Recording Notes (view or edit mode), AudioPlayer, Speaker Segments.
_Avoid_: Right sidebar, recording detail, info panel
