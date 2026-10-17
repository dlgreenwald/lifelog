# Recording Notes: editor choice

The notes feature on a Recording uses Wysimark for edit mode and react-markdown for read-only view mode.

## Context

Recording Notes needed a WYSIWYG markdown editor. Three candidates were evaluated during the `/grilling` session:

- **TipTap + react-markdown** — TipTap stores HTML (not markdown), requiring HTML→markdown parsing on every load. The `tiptap-mermaid` extension is a thin community package with limited maintenance. TipTap also carries significant bundle weight (~3MB).
- **Milkdown** — native markdown model, unified Editor + Reader, but Mermaid integration requires a custom code-block renderer.
- **Wysimark** — stores raw markdown (not HTML), zero parsing on load, GFM-native, small bundle.

## Decision

Chose **Wysimark (edit) + react-markdown (view)**.

## Why Wysimark over TipTap

- Wysimark stores **raw markdown** — no HTML parsing needed on load, no conversion needed on save.
- TipTap stores **HTML** (ProseMirror doc format) — requires `markdown-it` to parse existing markdown on load, and the HTML output must be stored as-is (or re-serialized to markdown with a lossier round-trip).
- TipTap's `tiptap-mermaid` extension is a thin community package (`tiptap-mermaid@1.0.0`) with limited maintenance.
- Wysimark bundle weight is negligible compared to TipTap + mermaid.

## Why not Milkdown

Milkdown's unified model is elegant but its Mermaid integration requires a custom code-block renderer. The additional complexity did not justify the benefit given Wysimark's simpler data model.

## Consequences

- Notes are stored as **raw markdown** in the database — no HTML conversion, clean round-trips.
- Mermaid blocks in view mode render as styled `<pre>` blocks (code display). Full live Mermaid rendering in view mode is deferred.
- The `onChange` callback from Wysimark is throttled to 1 second by default. `editor.getMarkdown()` bypasses the throttle for save operations.
