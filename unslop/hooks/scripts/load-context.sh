#!/bin/bash
set -euo pipefail

# Drain stdin (SessionStart sends input we don't need)
cat > /dev/null

if ! command -v jq &>/dev/null; then
  exit 0
fi

if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  exit 0
fi

# Check if .unslop/ exists in the project
if [ ! -d "$CLAUDE_PROJECT_DIR/.unslop" ]; then
  exit 0
fi

output=""
has_content=false

# Load alignment summary if it exists
summary_file="$CLAUDE_PROJECT_DIR/.unslop/alignment-summary.md"
if [ -f "$summary_file" ]; then
  summary=$(cat "$summary_file")
  output="$summary"
  has_content=true
fi

# Load config if it exists — prefer config.json, fall back to config.md (legacy)
config_file="$CLAUDE_PROJECT_DIR/.unslop/config.json"
if [ ! -f "$config_file" ]; then
  config_file="$CLAUDE_PROJECT_DIR/.unslop/config.md"
fi
if [ -f "$config_file" ]; then
  config=$(cat "$config_file")
  output="$output

---
$config"
  has_content=true
fi

# Load diagnostic cache (previous convergence failures)
failure_dir="$CLAUDE_PROJECT_DIR/.unslop/last-failure"
if [ -d "$failure_dir" ]; then
  failure_files=$(find "$failure_dir" -name '*.md' -type f 2>/dev/null)
  if [ -n "$failure_files" ]; then
    failure_summary="## Previous failures (from .unslop/last-failure/)
These files had Builder failures in a previous session. The failure reports are injected into the next Builder dispatch automatically."
    for f in $failure_files; do
      fname=$(basename "$f" .md)
      # Extract first non-empty line as a compact summary
      first_line=$(grep -m1 '.' "$f" 2>/dev/null || echo "(empty report)")
      failure_summary="$failure_summary
- \`$fname\`: $first_line"
    done
    output="$output

---
$failure_summary"
    has_content=true
  fi
fi

# Triage routing table -- ensures the model routes through specs, not direct edits
triage="## unslop workflow routing
This project uses spec-driven development. Managed files have \`@unslop-managed\` headers.
- Code change/refactor: \`/unslop:change <file> \"description\"\` then \`/unslop:generate\` or \`/unslop:sync <file>\`
- Quick targeted fix: \`/unslop:change <file> \"description\" --tactical\`
- Quality/safety review: \`/unslop:harden <spec-path>\` (takes the spec, not the managed file)
- Cross-spec consistency: \`/unslop:coherence\` (all) or \`/unslop:coherence <spec-path>\` (targeted)
- Check staleness: \`/unslop:status\`
- Bring existing code under spec: \`/unslop:takeover <file>\`
- Harden tests: \`/unslop:cover <file>\` (mutation-driven coverage growth)
- Create new file: \`/unslop:spec <file>\` then \`/unslop:sync <file>\`
- Direct edit of managed file: warn once (shows as modified in status), then proceed."
output="$output

---
$triage"
has_content=true

# Only emit if there's actual content
if [ "$has_content" = true ]; then
  output="$output

---
If you notice friction with the unslop workflow during this session, offer to raise it as a GitHub issue at https://github.com/Lewdwig-V/unslop/issues with actionable improvement suggestions."

  # Output as plain text for SessionStart
  printf '%s\n' "$output"
fi
