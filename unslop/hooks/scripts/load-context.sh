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

# Load config if it exists
config_file="$CLAUDE_PROJECT_DIR/.unslop/config.md"
if [ -f "$config_file" ]; then
  config=$(cat "$config_file")
  output="$output

---
$config"
  has_content=true
fi

# Only emit if there's actual content
if [ "$has_content" = true ]; then
  output="$output

---
If you notice friction with the unslop workflow during this session — spec-language patterns that did not generate well, convergence loop behaviors that felt wrong, missing constraints, or workflow steps that could be streamlined — note them in .unslop/feedback.md before the session ends."

  # Output as plain text for SessionStart
  printf '%s\n' "$output"
fi
