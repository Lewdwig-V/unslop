#!/bin/bash
set -euo pipefail

# Read hook input from stdin
input=$(cat)

# Extract the file path from tool input
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.file // empty')

# Only act on *.spec.md files
if [[ -z "$file_path" ]] || [[ "$file_path" != *.spec.md ]]; then
  exit 0
fi

# Check if .unslop/ exists in the project
if [ ! -d "$CLAUDE_PROJECT_DIR/.unslop" ]; then
  exit 0
fi

# Signal to Claude that the alignment summary should be regenerated
echo '{"systemMessage": "A spec file was modified. Regenerate .unslop/alignment-summary.md by scanning all *.spec.md files. For each spec, read the first few lines to extract intent (the first sentence or Purpose section). List each managed file with its spec path, staleness status, and one-line intent summary."}'
