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

# Triage routing table -- ensures the model routes through specs, not direct edits
triage="## unslop workflow routing
This project uses spec-driven development. Managed files have \`@unslop-managed\` headers.
- Code change/refactor: \`/unslop:change <file> \"description\"\` then \`/unslop:generate\` or \`/unslop:sync <file>\`
- Quick targeted fix: \`/unslop:change <file> \"description\" --tactical\`
- Quality/safety review: \`/unslop:harden <spec-path>\` (takes the spec, not the managed file)
- Check staleness: \`/unslop:status\`
- Bring existing code under spec: \`/unslop:takeover <file>\`
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
If you notice friction with the unslop workflow during this session -- note them in .unslop/feedback.md before the session ends."

  # Output as plain text for SessionStart
  printf '%s\n' "$output"
fi
