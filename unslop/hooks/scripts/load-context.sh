#!/bin/bash
set -euo pipefail

# Check if .unslop/ exists in the project
if [ ! -d "$CLAUDE_PROJECT_DIR/.unslop" ]; then
  exit 0
fi

output=""

# Load alignment summary if it exists
summary_file="$CLAUDE_PROJECT_DIR/.unslop/alignment-summary.md"
if [ -f "$summary_file" ]; then
  summary=$(cat "$summary_file")
  output="$summary"
fi

# Load config if it exists
config_file="$CLAUDE_PROJECT_DIR/.unslop/config.md"
if [ -f "$config_file" ]; then
  config=$(cat "$config_file")
  output="$output

---
$config"
fi

# Add feedback prompt
output="$output

---
If you notice friction with the unslop workflow during this session — spec-language patterns that did not generate well, convergence loop behaviors that felt wrong, missing constraints, or workflow steps that could be streamlined — note them in .unslop/feedback.md before the session ends."

if [ -n "$output" ]; then
  # Escape for JSON
  json_output=$(echo "$output" | jq -Rs .)
  echo "{\"systemMessage\": $json_output}"
fi
