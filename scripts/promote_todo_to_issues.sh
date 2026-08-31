#!/usr/bin/env bash
# promote_todo_to_issues.sh
#
# Migrate items from the untracked root TODO.md into GitHub Issues using
# `gh issue create` with the label taxonomy documented in AGENTS.md
# ("Capture -> Issue -> PR Rule"):
#
#   area:        firmware | server | dashboard | transcription-worker | speaker-id | infra
#   priority:    high | medium | low
#   size:        small | medium | large
#   type:        idea    (always)
#
# Behavior:
#
#   * Default mode is DRY RUN -- print the gh issue create invocations that
#     WOULD be executed; no GitHub API calls.
#   * --apply                actually call the API.
#   * --rewrite              (only meaningful with --apply) drop migrated
#                            bullets from TODO.md after creation succeeds
#                            OR the issue already exists.
#   * --bootstrap-labels     (only meaningful with --apply) create the
#                            taxonomy labels via `gh label create` before
#                            the issue loop. Idempotent (`--force`). Use
#                            once per repo. Subsequent runs can omit it.
#
# Idempotency:
#
#   Before each `gh issue create`, the script fetches the full issue list
#   (state=all, max 1000) with `gh issue list --json number,title` and
#   indexes by title. If a title already exists, the item is skipped
#   (marked `migrate=already-exists`) and the existing issue URL is
#   printed. Subsequent runs of `--apply` therefore create no duplicates.
#
# Usage:
#   scripts/promote_todo_to_issues.sh                      # dry run
#   scripts/promote_todo_to_issues.sh --apply              # actually create
#   scripts/promote_todo_to_issues.sh --apply --rewrite    # create + trim file
#   scripts/promote_todo_to_issues.sh --apply --bootstrap-labels --rewrite
#   scripts/promote_todo_to_issues.sh --help
#
# Heuristic keyword map (first match wins; case-insensitive). Order in the
# script matters for ties -- anything matching earlier wins.
#   area/infra           CI / Docker build / tag-push automation
#   area/dashboard       dashboard|drag select|search|dark/light|layout|theme|upload via|two-?party|delete device
#   area/speaker-id      speaker|voiceprint|ecapa|("speakers", "speaker diarization", ...)
#   area/transcription-worker  whisper(x)?|asr|diarization|transcription
#   area/firmware        firmware|xiao|i2s|sd card|record on|continuous upload|indicator lights
#   area/server          llm|prompt|postgres|appointments|i[ck]?al|caldav|webdav|"conversations with only"
#
# Priority heuristics:
#   priority/high         mentions: "battery", "privacy", "security",
#                          "delete device", "deregister", "ota"
#   priority/medium       default
#   priority/low          mentions: "polish", "indicator", "stretch", "layout"
#
# Size heuristics:
#   size/large            mentions: "ota", "i[ck]?al", "webdav", "search with facets",
#                          "drag select", "dashboard triggers", "deletes with idp"
#   size/medium           default
#   size/small            mentions: "indicator", "name and listen", "name=",
#                          "two-?party preference", "record on demand"

set -euo pipefail

MODE="dry-run"
REWRITE=0
BOOTSTRAP_LABELS=0
TODO_FILE="TODO.md"

usage() {
  sed -n '2,40p' "$0" | sed 's/^# *//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)              MODE="apply" ;;
    --rewrite)            REWRITE=1 ;;
    --bootstrap-labels)   BOOTSTRAP_LABELS=1 ;;
    --help|-h)            usage ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

# ---------- Defensive preconditions ----------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found in PATH" >&2
  exit 2
fi

if [ ! -f "$TODO_FILE" ]; then
  echo "TODO.md not found at repo root; nothing to migrate." >&2
  exit 1
fi

gh auth status >/dev/null 2>&1 || {
  echo "gh is not authenticated; run 'gh auth login' first." >&2
  exit 2
}

# ---------- Label set --------------------------------------------------------
LABELS=(
  "idea"
  "area/firmware" "area/server" "area/dashboard"
  "area/transcription-worker" "area/speaker-id" "area/infra"
  "priority/high" "priority/medium" "priority/low"
  "size/small" "size/medium" "size/large"
)

bootstrap_labels() {
  echo "=== bootstrapping labels ===" >&2
  for label in "${LABELS[@]}"; do
    gh label create "$label" \
       --description "lifelog capture taxonomy" \
       --force 2>&1 | head -1 | sed "s/^/  /" >&2 || true
  done
}

# ---------- Heuristics ------------------------------------------------------
match_keywords() {
  # $1 = lowercase text, $2.. = regex alternation
  local text="$1"; shift
  for pat in "$@"; do
    if [[ "$text" =~ $pat ]]; then
      return 0
    fi
  done
  return 1
}

classify_area() {
  local t="${1,,}"
  # Order matters: dashboard before transcription-worker (because two-party
  # settings are owned by dashboard, not by the diarization engine); area/infra
  # before firmware so CI/deploy items don't fall into firmware.
  if match_keywords "$t" \
       "2-stage docker" "2 stage docker" "auto.deploy" "auto.tag" \
       "ci.yml" ".github/workflows" "tag pushes" \
       "docker images" "docker layers" "dockerfile"; then
    echo "area/infra"; return
  fi
  if match_keywords "$t" \
       "dashboard" "drag select" "search" "dark/light" "dark mode" "light mode" \
       "layout" "theme" "upload via dashboard" "two-party" "two party" \
       "delete device" "deregister" "settings page"; then
    echo "area/dashboard"; return
  fi
  if match_keywords "$t" \
       "voiceprint" "ecapa"; then
    echo "area/speaker-id"; return
  fi
  if match_keywords "$t" \
       "speakers" "speaker diarization" "speaker labeling" "speaker id"; then
    echo "area/speaker-id"; return
  fi
  if match_keywords "$t" \
       "whisper" "asr" "diarization" "transcription" "transcribe"; then
    echo "area/transcription-worker"; return
  fi
  if match_keywords "$t" \
       "firmware" "xiao" "i2s" "sd card" "sdcard" \
       "record on" "record for" "continuous upload" "batch upload" \
       "indicator lights"; then
    echo "area/firmware"; return
  fi
  if match_keywords "$t" \
       "llm" "prompt" "postgres" "appointments" "ical" "caldav" "webdav" \
       "conversations with only"; then
    echo "area/server"; return
  fi
  echo "needs-triage"
}

classify_priority() {
  local t="${1,,}"
  if match_keywords "$t" \
       "battery" "privacy" "security" "delete device" "deregister" \
       "ota" "deactivate"; then
    echo "priority/high"; return
  fi
  if match_keywords "$t" \
       "polish" "indicator" "stretch" "layout"; then
    echo "priority/low"; return
  fi
  echo "priority/medium"
}

classify_size() {
  local t="${1,,}"
  if match_keywords "$t" \
       "facets" "search with" "drag select" "ota" \
       "ical" "caldav" "webdav" "dashboard triggers"; then
    echo "size/large"; return
  fi
  if match_keywords "$t" \
       "indicator" "name and listen" "name=" "two-party" "two party" \
       "record on demand" "record for a time" "record for a period" \
       "continuous upload vs batch"; then
    echo "size/small"; return
  fi
  echo "size/medium"
}

# ---------- Parse TODO.md ----------------------------------------------------
# Items live under ## Aspirational subsections (### Infra / CI, ### Server / LLM,
# etc.) as multi-line bullets: the first line begins with "- " and continuation
# lines are indented 2+ spaces. We aggregate each bullet + its continuation
# into one issue. The ## Done and ## Not in this file sections are skipped.
items=()
section_state=0
current=""

flush_current() {
  if [ -n "$current" ]; then
    items+=("$current")
  fi
  current=""
}

while IFS= read -r line; do
  if [[ "$line" =~ ^##\  ]]; then
    if [[ "$line" =~ ^##\ Aspirational ]]; then
      section_state=1
    else
      flush_current
      section_state=0
    fi
    continue
  fi
  if [ "$section_state" -eq 0 ]; then
    continue
  fi
  if [[ "$line" =~ ^-\  ]]; then
    flush_current
    current="${line#- }"
    continue
  fi
  # Continuation: indented and we already have a current item.
  if [ -n "$current" ] && [[ "$line" =~ ^\ \  ]]; then
    current="${current} ${line#"${line%%[![:space:]]*}"}"
    continue
  fi
  # Blank line resets the current bullet.
  if [ -z "$line" ]; then
    flush_current
  fi
done < "$TODO_FILE"
flush_current

if [ "${#items[@]}" -eq 0 ]; then
  echo "no unchecked items under '## Aspirational' sections -- nothing to migrate." >&2
  exit 0
fi

echo "found ${#items[@]} unchecked item(s) under Aspirational sections" >&2
echo "" >&2

# ---------- Pre-fetch existing issues for idempotency -----------------------
# Build a JSON title -> url mapping from one gh issue list call. Items whose
# joined text already appears as an issue title are marked
# `migrate=already-exists` and skipped during the apply phase.
declare -A existing_urls=()
declare -A existing_numbers=()

if [ "$MODE" = "apply" ]; then
  echo "=== fetching existing issues for idempotency check ===" >&2
  if ! gh issue list --state all --json number,title,url --limit 1000 \
       > /tmp/promote_todo_existing.$$ 2>/dev/null; then
    echo "  failed to list existing issues; aborting apply so we don't risk duplicates" >&2
    exit 3
  fi
  while IFS=$'\t' read -r title url num; do
    [ -z "$title" ] && continue
    existing_urls["$title"]="$url"
    existing_numbers["$title"]="$num"
  done < <(jq -r '.[] | "\(.title)\t\(.url)\t\(.number)"' /tmp/promote_todo_existing.$$)
  rm -f /tmp/promote_todo_existing.$$
  echo "  indexed ${#existing_urls[@]} existing issue title(s)" >&2
fi

# ---------- Build the operation list ----------------------------------------
declare -a titles=()
declare -a bodies=()
declare -a labels=()
declare -a migrate=()

for raw in "${items[@]}"; do
  area=$(classify_area "$raw")
  priority=$(classify_priority "$raw")
  size=$(classify_size "$raw")

  if [ "$area" = "needs-triage" ]; then
    if [ "$MODE" = "dry-run" ]; then
      echo "  unclassified -> will prompt interactively on --apply" >&2
      titles+=("$raw")
      bodies+=("")
      labels+=("NEEDS-TRIAGE")
      migrate+=("skip")
      continue
    fi
    # apply mode: prompt for area
    echo "" >&2
    echo "  needs triage: $raw" >&2
    PS3="    choose area: "
    select a in \
      "area/firmware" "area/server" "area/dashboard" \
      "area/transcription-worker" "area/speaker-id" "area/infra" "skip"; do
      [ -n "$a" ] && break
    done
    if [ -z "$a" ] || [ "$a" = "skip" ]; then
      echo "  skipped" >&2
      continue
    fi
    area="$a"
  fi

  # Idempotency: if the same title already exists, mark and skip.
  if [ "$MODE" = "apply" ] && [ -n "${existing_urls[$raw]:-}" ]; then
    titles+=("$raw")
    bodies+=("")
    labels+=("idea,$area,$priority,$size")
    migrate+=("already-exists")
    continue
  fi

  body=$(cat <<EOF
Captured from the root TODO.md (untracked). Promoted via scripts/promote_todo_to_issues.sh on $(date -u +%Y-%m-%d).

## Original aspirational note

> $raw

## Implementation sketch

_TODO: refine on first review of this issue. If this is a multi-PR idea, replace this section with a checklist of sub-PRs and link each one with \`Part of #\${THIS_ISSUE_NO}\`._
EOF
)

  titles+=("$raw")
  bodies+=("$body")
  labels+=("idea,$area,$priority,$size")
  migrate+=("yes")
done

# ---------- Optional label bootstrap ---------------------------------------
if [ "$MODE" = "apply" ] && [ "$BOOTSTRAP_LABELS" -eq 1 ]; then
  bootstrap_labels
fi

# ---------- Dry-run / apply -------------------------------------------------
echo ""
echo "=== migration plan ==="
i=0
total=${#titles[@]}
while [ "$i" -lt "$total" ]; do
  echo ""
  echo "[$((i+1))/$total] ${titles[$i]}"
  echo "      labels: ${labels[$i]}"
  case "${migrate[$i]}" in
    yes)
      echo "      migrate: yes (will create)"
      if [ "$MODE" = "dry-run" ]; then
        cmd="gh issue create --title \"${titles[$i]}\" --label \"${labels[$i]}\" --body-file <(printf '%s' \"${bodies[$i]}\")"
        echo "      would run: $cmd"
      fi
      ;;
    already-exists)
      url="${existing_urls[${titles[$i]}]:-<unknown>}"
      echo "      migrate: already-exists (skipping)"
      echo "      existing: $url"
      ;;
    skip)
      echo "      migrate: skipped (unclassified)"
      ;;
  esac
  i=$((i+1))
done

if [ "$MODE" = "dry-run" ]; then
  echo ""
  echo "dry run complete; re-run with --apply to actually create issues," >&2
  echo "optionally with --rewrite to remove migrated bullets from TODO.md." >&2
  exit 0
fi

# Apply: actually create issues for any item still marked "yes".
echo ""
echo "=== applying ==="
created_urls=()
i=0
total=${#titles[@]}
while [ "$i" -lt "$total" ]; do
  if [ "${migrate[$i]}" != "yes" ]; then
    i=$((i+1))
    continue
  fi
  url=$(printf '%s' "${bodies[$i]}" | gh issue create \
          --title "${titles[$i]}" \
          --label "${labels[$i]}" \
          --body-file -)
  echo "  created: $url"
  created_urls+=("$url")
  i=$((i+1))
done

if [ "$REWRITE" -eq 1 ]; then
  echo ""
  echo "=== rewriting TODO.md (--rewrite) ===" >&2
  tmp="$(mktemp)"
  : > "$tmp"
  for title in "${titles[@]}"; do
    awk -v needle="- [ ] $title" '
      $0 == needle { next }
      { print }
    ' "$TODO_FILE" > "$tmp"
    cp "$tmp" "$TODO_FILE"
  done
  rm -f "$tmp"
  echo "TODO.md rewritten to drop migrated bullets." >&2
fi

echo ""
echo "summary: ${#created_urls[@]} created, $(grep -c '^already-exists$' <<<"$(printf '%s\n' "${migrate[@]}")" || echo 0) skipped (already exist)."
