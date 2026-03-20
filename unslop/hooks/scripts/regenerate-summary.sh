#!/bin/bash
set -euo pipefail

if ! command -v jq &>/dev/null; then
  exit 0
fi

if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  exit 0
fi

# Read hook input from stdin
input=$(cat)

# Extract the file path from tool input
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.file // empty')

# Only act on *.spec.md files
if [[ -z "$file_path" ]] || [[ "$file_path" != *.spec.md ]]; then
  exit 0
fi

# Check if .unslop/ exists in the project
if [ ! -d "$CLAUDE_PROJECT_DIR/.unslop" ]; then
  exit 0
fi

# Signal to Claude that the alignment summary should be regenerated
echo '{"systemMessage": "Spec file modified. Regenerate .unslop/alignment-summary.md."}'
