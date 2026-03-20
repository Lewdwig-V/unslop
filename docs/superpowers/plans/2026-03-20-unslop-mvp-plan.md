# unslop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the unslop Claude Code plugin MVP — marketplace metadata, 6 commands, 3 skills, 2 hooks, and the alignment summary system.

**Architecture:** Skills-heavy plugin with thin commands that load skills for orchestration. No external tooling — pure prompt-driven. Commands delegate to superpowers for TDD and planning. Hooks auto-generate alignment summaries and load context on session start.

**Tech Stack:** Claude Code plugin system (markdown commands, skills, JSON hooks), bash for hook scripts, superpowers plugin dependency.

**Spec:** `docs/superpowers/specs/2026-03-20-unslop-mvp-design.md`

---

### Task 1: Marketplace & Plugin Manifests

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Create the marketplace manifest**

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "unslop",
  "description": "Spec-driven code management — treats specs as source of truth, generated code as disposable output",
  "owner": {
    "name": "lewdwig",
    "email": ""
  },
  "plugins": [
    {
      "name": "unslop",
      "source": "./unslop",
      "description": "Rescue vibe-coded prototypes into spec-driven development. Takeover pipeline extracts specs from existing code, validates against tests, and manages regeneration."
    }
  ]
}
```

Write this to `.claude-plugin/marketplace.json`.

- [ ] **Step 2: Create the plugin manifest**

```json
{
  "name": "unslop",
  "version": "0.1.0",
  "description": "Spec-driven code management — extract intent, validate against tests, regenerate from specs",
  "author": {
    "name": "lewdwig"
  },
  "repository": "https://github.com/lewdwig/unslop",
  "license": "MPL-2.0",
  "keywords": ["spec-driven", "codegen", "takeover", "vibe-coding", "code-management"]
}
```

Write this to `unslop/.claude-plugin/plugin.json`.

- [ ] **Step 3: Verify directory structure**

Run: `find .claude-plugin unslop/.claude-plugin -type f`
Expected: both `marketplace.json` and `plugin.json` present at correct paths.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/marketplace.json unslop/.claude-plugin/plugin.json
git commit -m "feat: add marketplace and plugin manifests"
```

---

### Task 2: spec-language Skill

This skill is loaded by multiple commands, so it comes first.

**Files:**
- Create: `unslop/skills/spec-language/SKILL.md`

- [ ] **Step 1: Write the spec-language skill**

This skill teaches the model how to write specs. It must cover:

1. **YAML frontmatter** with `name`, `description`, `version` fields
2. **Description field** — critical for triggering. Should mention: "Use when writing, drafting, reviewing, or editing unslop spec files (*.spec.md). Activates for spec creation, takeover spec drafting, and spec editing guidance."
3. **Core principle**: specs describe intent, not implementation
4. **Vocabulary guide** with positive/negative example pairs:
   - Good: "Messages are stored in SQLite with a monotonic sequence ID"
   - Bad: "Use INSERT OR REPLACE with a rowid alias column"
   - Good: "Retries use exponential backoff with jitter, max 5 attempts"
   - Bad: "sleep(2**attempt + random.uniform(0,1))"
   - Good: "Validation rejects inputs over 1MB"
   - Bad: "if len(data) > 1_048_576: raise ValueError"
   - Good: "HTTP responses are cached for 5 minutes"
   - Bad: "Use a dict with time.time() keys and prune entries older than 300"
5. **When to be specific**: constraints, invariants, error behavior, boundary conditions, concurrency guarantees
6. **When to be vague**: data structures, algorithms, variable names, internal control flow
7. **Register guidance**: "If your spec reads like commented-out code, it's over-specified. If it reads like a product brief with no constraints, it's under-specified."
8. **Suggested headings** (not required): Purpose, Behavior, Constraints, Dependencies, Error Handling
9. **Skeleton template** for new specs (used by `/unslop:spec` when no existing file):

```markdown
# [filename] spec

## Purpose
[What this file does and why it exists]

## Behavior
[What it should do — the observable contract]

## Constraints
[Bounds, limits, invariants, error conditions]

## Dependencies
[External services, libraries, or other managed files it relies on]
```

Write to `unslop/skills/spec-language/SKILL.md`.

- [ ] **Step 2: Verify skill structure**

Run: `find unslop/skills/spec-language -type f`
Expected: `SKILL.md` present.

- [ ] **Step 3: Commit**

```bash
git add unslop/skills/spec-language/SKILL.md
git commit -m "feat: add spec-language skill — vocabulary guide and writing discipline"
```

---

### Task 3: generation Skill

**Files:**
- Create: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Write the generation skill**

This skill teaches the model how to generate code from a spec. It must cover:

1. **YAML frontmatter** — description: "Use when generating or regenerating code from unslop spec files. Activates during /unslop:generate, /unslop:sync, and the generation step of /unslop:takeover."
2. **"Read only the spec" discipline**:
   - "You MUST generate code from the spec file alone. Do not read the existing generated file — it is about to be overwritten. Do not read archived originals. The spec is the single source of truth."
3. **@unslop-managed header format**:
   - Line 1: `@unslop-managed — do not edit directly. Edit <spec-path> instead.`
   - Line 2: `Generated from spec at <ISO 8601 timestamp>`
   - Comment syntax table:

     | Extension | Comment syntax |
     |---|---|
     | .py, .rb, .sh, .yaml, .yml | `#` |
     | .js, .ts, .jsx, .tsx, .java, .c, .cpp, .go, .rs, .swift, .kt | `//` |
     | .html, .xml, .svg | `<!-- -->` |
     | .css, .scss | `/* */` |
     | .lua | `--` |
     | .sql | `--` |
     | .hs | `--` |

   - For unknown extensions, use `//` as default
4. **TDD integration**: "Use the superpowers test-driven-development skill. Write tests that validate the spec's constraints first, then implement. The tests ARE the acceptance criteria."
5. **Idiomatic output**: "Generated code should be idiomatic for its language. Do not transliterate the spec into code. The spec says what; you decide how — within the constraints."
6. **Config awareness**: "Read `.unslop/config.md` for the project's test command before running tests."

Write to `unslop/skills/generation/SKILL.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add generation skill — code generation discipline and managed file conventions"
```

---

### Task 4: takeover Skill

**Files:**
- Create: `unslop/skills/takeover/SKILL.md`

- [ ] **Step 1: Write the takeover skill**

This is the most complex skill. It orchestrates the full takeover pipeline. Must cover:

1. **YAML frontmatter** — description: "Use when running the unslop takeover pipeline to bring existing code under spec management. Orchestrates discovery, spec drafting, archiving, generation, and the convergence validation loop."
2. **Pipeline overview** — the 6 steps as a numbered checklist
3. **Step 1: Discover**
   - Read the target file
   - Find tests by convention patterns: `*_test.py`, `test_*.py`, `*.test.ts`, `*.test.js`, `*.spec.ts`, `*.spec.js`, `__tests__/*.ts`, `__tests__/*.js`, `*_test.go`, `*_test.rb`, `spec/*_spec.rb`
   - If no tests: warn clearly — "Takeover without tests means the spec is unvalidated. The convergence loop cannot run. Proceed only if the user confirms."
4. **Step 2: Draft Spec**
   - "Use the unslop/spec-language skill for writing guidance"
   - Read the code AND its tests
   - Extract intent: what does this code accomplish? What are its contracts? What are its error conditions?
   - Do NOT copy implementation details into the spec
   - Present draft to user: "Review this spec. Does it capture what this code is supposed to do? I'll regenerate fresh code from this spec alone, so anything missing will be lost."
   - Wait for user approval before proceeding
5. **Step 3: Archive**
   - Archive path: `.unslop/archive/<relative-path>.<ISO8601-compact-timestamp>` (e.g., `.unslop/archive/src/retry.py.2026-03-20T143200Z`)
   - Create parent directories as needed
   - This is a safety net — the user can manually recover if needed
6. **Step 4: Generate**
   - "Use the unslop/generation skill for code generation discipline"
   - "CRITICAL: Do NOT read the archived original. Generate from the spec ONLY."
   - Write the generated file with `@unslop-managed` header
7. **Step 5: Validate**
   - Read test command from `.unslop/config.md`
   - Run tests
   - If all green: commit spec + generated file, update alignment summary
   - If red: enter convergence loop
8. **Step 6: Convergence Loop**
   - Maximum 3 iterations
   - For each iteration:
     a. Analyze test failures — what behavior is missing?
     b. Identify the missing semantic constraint — what does the spec need to say?
     c. Enrich the spec — add the constraint in spec-language voice (intent, not implementation)
     d. Regenerate from the enriched spec (still no peeking at original)
     e. Re-run tests
   - If green: done, commit
   - If max iterations reached: stop. Show user: which tests still fail, what constraints were added, note that original is in archive. Ask for help.
   - "NEVER patch the generated code directly. Always enrich the spec and regenerate."
9. **Abandonment state**: "On max iterations: keep the draft spec (user can fix it), keep the last generated attempt (user can see what failed), original remains in archive."

Write to `unslop/skills/takeover/SKILL.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/takeover/SKILL.md
git commit -m "feat: add takeover skill — pipeline orchestration and convergence loop"
```

---

### Task 5: init Command

**Files:**
- Create: `unslop/commands/init.md`

- [ ] **Step 1: Write the init command**

YAML frontmatter:
```yaml
---
description: Initialize unslop in the current project
---
```

Command body (instructions for Claude):

1. Check if `.unslop/` already exists. If yes, inform user it's already initialized and offer to re-detect the test command.
2. Create `.unslop/` directory and `.unslop/archive/` subdirectory.
3. Create `.unslop/.gitignore` with contents:
   ```
   archive/
   feedback.md
   ```
4. Detect test command:
   - Check for `package.json` — if it has a `"test"` script, use `npm test`
   - Check for `pyproject.toml` or `pytest.ini` — use `pytest`
   - Check for `Makefile` with a `test` target — use `make test`
   - Check for `Cargo.toml` — use `cargo test`
   - Check for `go.mod` — use `go test ./...`
   - If multiple detected or none detected, ask the user with AskUserQuestion
5. Write `.unslop/config.md`:
   ```markdown
   # unslop configuration

   Test command: `<detected command>`
   ```
6. Create `.unslop/alignment-summary.md`:
   ```markdown
   # unslop alignment summary
   <!-- Auto-generated by unslop. Do not edit manually. -->

   ## Managed files

   No managed files yet. Use /unslop:takeover or /unslop:spec to get started.
   ```
7. Commit the `.unslop/` directory.

Write to `unslop/commands/init.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat: add /unslop:init command"
```

---

### Task 6: spec Command

**Files:**
- Create: `unslop/commands/spec.md`

- [ ] **Step 1: Write the spec command**

YAML frontmatter:
```yaml
---
description: Create or edit a spec for a source file
argument-hint: <file-path>
---
```

Command body (instructions for Claude):

1. The argument `$ARGUMENTS` is the path to the source file (e.g., `src/retry.py`).
2. Use the unslop/spec-language skill for guidance on spec writing voice.
3. Derive the spec path: replace the file extension with `.spec.md` (e.g., `src/retry.py` → `src/retry.spec.md`).
4. If the spec file already exists: read it and present it to the user for editing. Done.
5. If the target source file exists (but no spec yet):
   - Read the source file
   - Draft a spec capturing intent, not implementation
   - Write the draft to the spec path
   - Present to user for review and editing
6. If neither the source file nor spec exists:
   - Create a skeleton spec using the template from the spec-language skill
   - Write it to the spec path
   - Present to user for editing
7. After user is satisfied: inform them to run `/unslop:generate` to produce the managed file.
8. Do NOT archive, regenerate, or run tests. That's what takeover and generate do.

Write to `unslop/commands/spec.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/spec.md
git commit -m "feat: add /unslop:spec command"
```

---

### Task 7: takeover Command

**Files:**
- Create: `unslop/commands/takeover.md`

- [ ] **Step 1: Write the takeover command**

YAML frontmatter:
```yaml
---
description: Run the takeover pipeline on an existing file
argument-hint: <file-path>
---
```

Command body (instructions for Claude):

1. The argument `$ARGUMENTS` is the path to the existing source file.
2. Verify `.unslop/` exists. If not, tell user to run `/unslop:init` first.
3. Verify the target file exists. If not, suggest `/unslop:spec` instead.
4. Use the unslop/takeover skill to orchestrate the full pipeline.
5. Use the unslop/spec-language skill for spec drafting guidance.
6. Use the unslop/generation skill for code generation discipline.
7. Read the test command from `.unslop/config.md`.
8. After successful takeover, update `.unslop/alignment-summary.md` with the new managed file entry.

This command is thin — it sets up context and delegates to the takeover skill.

Write to `unslop/commands/takeover.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/takeover.md
git commit -m "feat: add /unslop:takeover command"
```

---

### Task 8: generate Command

**Files:**
- Create: `unslop/commands/generate.md`

- [ ] **Step 1: Write the generate command**

YAML frontmatter:
```yaml
---
description: Regenerate all stale managed files from their specs
---
```

Command body (instructions for Claude):

1. Verify `.unslop/` exists. If not, tell user to run `/unslop:init` first.
2. Use the unslop/generation skill for code generation discipline.
3. Read the test command from `.unslop/config.md`.
4. Scan the project for all `*.spec.md` files.
5. For each spec file:
   - Derive the managed file path (strip `.spec.md`, restore original extension)
   - If the managed file doesn't exist: it's a new file — generate it
   - If the managed file exists: compare timestamps. If spec is newer than managed file, it's stale — regenerate
   - If fresh: skip
6. For each stale/new file:
   - Read only the spec
   - Generate code with `@unslop-managed` header
   - Run the test command
   - If green: report success
   - If red: report failures and STOP. Do NOT enter a convergence loop. The user edited the spec deliberately — they should see what broke and fix it.
7. After all files processed, update `.unslop/alignment-summary.md`.

Write to `unslop/commands/generate.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "feat: add /unslop:generate command"
```

---

### Task 9: sync Command

**Files:**
- Create: `unslop/commands/sync.md`

- [ ] **Step 1: Write the sync command**

YAML frontmatter:
```yaml
---
description: Regenerate one specific managed file from its spec
argument-hint: <file-path>
---
```

Command body (instructions for Claude):

1. The argument `$ARGUMENTS` is the path to the managed file (e.g., `src/retry.py`).
2. Verify `.unslop/` exists.
3. Use the unslop/generation skill.
4. Derive the spec path: replace extension with `.spec.md`.
5. Verify the spec exists. If not, suggest `/unslop:spec` first.
6. Read only the spec. Generate code with `@unslop-managed` header.
7. Read test command from `.unslop/config.md`. Run tests.
8. If green: report success. If red: report failures and stop.
9. Update `.unslop/alignment-summary.md`.

This is identical to generate but scoped to a single file.

Write to `unslop/commands/sync.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "feat: add /unslop:sync command"
```

---

### Task 10: status Command

**Files:**
- Create: `unslop/commands/status.md`

- [ ] **Step 1: Write the status command**

YAML frontmatter:
```yaml
---
description: List managed files and their staleness status
---
```

Command body (instructions for Claude):

1. Verify `.unslop/` exists.
2. Scan the project for all `*.spec.md` files.
3. For each spec:
   - Derive managed file path
   - If managed file doesn't exist: list under "Unmanaged specs"
   - If managed file exists:
     - Read the `@unslop-managed` header to get generation timestamp
     - Compare spec mtime vs managed file mtime vs generation timestamp
     - **Fresh**: managed file mtime <= generation timestamp, spec mtime <= generation timestamp
     - **Stale**: spec mtime > generation timestamp
     - **Modified**: managed file mtime > generation timestamp AND spec mtime <= generation timestamp
     - If header is missing or malformed: report as "unmanaged (no header)"
4. Display results in format:
   ```
   Managed files:
     fresh    src/retry.py        <- retry.spec.md
     stale    src/parser.py       <- parser.spec.md (spec edited 2h ago)
     modified src/adapter.py      <- adapter.spec.md (edited directly)

   Unmanaged specs:
     src/utils.spec.md  (no managed file — run /unslop:generate)
   ```
5. If no specs found at all: suggest getting started with `/unslop:spec` or `/unslop:takeover`.

Write to `unslop/commands/status.md`.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/status.md
git commit -m "feat: add /unslop:status command"
```

---

### Task 11: Hooks — spec-change-detector and session-context

**Files:**
- Create: `unslop/hooks/hooks.json`
- Create: `unslop/hooks/scripts/regenerate-summary.sh`
- Create: `unslop/hooks/scripts/load-context.sh`

- [ ] **Step 1: Write the summary regeneration script**

`unslop/hooks/scripts/regenerate-summary.sh`:

```bash
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
```

- [ ] **Step 2: Write the context loading script**

`unslop/hooks/scripts/load-context.sh`:

```bash
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
```

- [ ] **Step 3: Write hooks.json**

`unslop/hooks/hooks.json`:

```json
{
  "description": "unslop hooks — detect spec changes and load context on session start",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/regenerate-summary.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/load-context.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/load-context.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Make scripts executable**

Run: `chmod +x unslop/hooks/scripts/regenerate-summary.sh unslop/hooks/scripts/load-context.sh`

- [ ] **Step 5: Commit**

```bash
git add unslop/hooks/hooks.json unslop/hooks/scripts/
git commit -m "feat: add hooks — spec change detection, session context loading, feedback prompt"
```

---

### Task 12: Verify Complete Plugin Structure

- [ ] **Step 1: Verify file tree matches design spec**

Run: `find . -not -path './.git/*' -not -path './docs/*' -type f | sort`

Expected structure:
```
./.claude-plugin/marketplace.json
./LICENSE
./README.md
./unslop/.claude-plugin/plugin.json
./unslop/commands/generate.md
./unslop/commands/init.md
./unslop/commands/spec.md
./unslop/commands/status.md
./unslop/commands/sync.md
./unslop/commands/takeover.md
./unslop/hooks/hooks.json
./unslop/hooks/scripts/load-context.sh
./unslop/hooks/scripts/regenerate-summary.sh
./unslop/skills/generation/SKILL.md
./unslop/skills/spec-language/SKILL.md
./unslop/skills/takeover/SKILL.md
```

- [ ] **Step 2: Verify all commands have valid frontmatter**

Read each command file and confirm YAML frontmatter parses correctly (has `description` field at minimum).

- [ ] **Step 3: Verify all skills have valid frontmatter**

Read each SKILL.md and confirm YAML frontmatter has `name` and `description` fields.

- [ ] **Step 4: Verify hooks.json is valid JSON**

Run: `jq . unslop/hooks/hooks.json`
Expected: valid JSON output, no errors.

- [ ] **Step 5: Verify hook scripts run without errors on empty input**

Run: `echo '{}' | bash unslop/hooks/scripts/regenerate-summary.sh`
Expected: clean exit (0), no output (file_path is empty, so it skips).

Run: `echo '{}' | CLAUDE_PROJECT_DIR=/tmp bash unslop/hooks/scripts/load-context.sh`
Expected: clean exit (0), no output (.unslop doesn't exist in /tmp).

- [ ] **Step 6: Final commit if any fixes were needed**

```bash
git add -A && git commit -m "fix: address verification issues" || echo "Nothing to fix"
```
