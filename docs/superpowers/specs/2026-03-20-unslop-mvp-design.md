# unslop MVP Design

> Spec-driven code management plugin for Claude Code. Treats specs as the source of truth, generated code as disposable output.

## Overview

unslop is a Claude Code plugin that rescues vibe-coded prototypes into disciplined software engineering practice. It extracts intent from existing code into spec files, then regenerates code from those specs — validating against existing tests that the spec fully captures the original semantics.

This document covers the MVP: `spec`, `takeover`, `generate`/`sync`, `status`, and the alignment summary system. A roadmap for the full plugin vision is included at the end.

## Approach

**Skills-heavy, prompt-driven.** Commands are thin entry points that load skills and invoke superpowers workflows. The heavy lifting — spec drafting, generation discipline, the takeover convergence loop — lives in skills that guide the model's behavior. No external tooling (MCP servers, orchestration scripts) in the MVP. If the prompt-only convergence loop proves unreliable, we'll add tooling selectively for just the parts that fail.

## Plugin Structure

```
unslop/                              # repo root = marketplace root
├── .claude-plugin/
│   └── marketplace.json             # marketplace manifest (points to ./unslop)
├── unslop/                          # the actual plugin
│   ├── .claude-plugin/
│   │   └── plugin.json              # plugin manifest
│   ├── commands/
│   │   ├── init.md                  # /unslop:init
│   │   ├── spec.md                  # /unslop:spec <file>
│   │   ├── takeover.md              # /unslop:takeover <file>
│   │   ├── generate.md              # /unslop:generate
│   │   ├── sync.md                  # /unslop:sync <file>
│   │   └── status.md                # /unslop:status
│   ├── skills/
│   │   ├── spec-language/
│   │   │   └── SKILL.md             # vocabulary guide, positive/negative examples
│   │   ├── generation/
│   │   │   └── SKILL.md             # generation discipline, managed file conventions
│   │   └── takeover/
│   │       └── SKILL.md             # takeover pipeline orchestration
│   └── hooks/
│       ├── hooks.json               # spec-change-detector + session-context hooks
│       └── scripts/
│           ├── regenerate-summary.sh
│           └── load-context.sh
├── README.md
└── LICENSE
```

Installation:
```
/plugin marketplace add <username>/unslop
/plugin install unslop@unslop
```

## Spec Format

Freeform markdown. No rigid schema — discipline is enforced by the spec-language skill, not structural validation. Inspired by CodeSpeak's approach: trust the model to interpret well-written intent.

Specs live alongside their source files:
```
src/
  retry.py          # managed — do not edit
  retry.spec.md     # edit this
  retry_test.py     # human-owned — ground truth
```

The writing discipline: intent, not implementation.

| Write this | Not this |
|---|---|
| Messages are stored in SQLite with a monotonic sequence ID | Use INSERT OR REPLACE with a rowid alias column |
| Retries use exponential backoff with jitter, max 5 attempts | sleep(2**attempt + random.uniform(0,1)) |
| Validation rejects inputs over 1MB | if len(data) > 1_048_576: raise ValueError |

If a spec reads like commented-out code, it's over-specified.

## Managed File Conventions

Managed files carry a header comment:
```python
# @unslop-managed — do not edit directly. Edit src/retry.spec.md instead.
# Generated from spec at 2026-03-20T14:32:00Z
```

Comment syntax is detected from file extension (`#`, `//`, `/* */`, `<!-- -->`, etc.). The header contains:
- The `@unslop-managed` marker
- Path to the spec file
- Generation timestamp (ISO 8601)

## Spec Command

### `/unslop:spec <file>`
The "starting fresh" entry point. For new files that don't exist yet, or existing files you want to spec before managing:

1. Load the spec-language skill
2. Create `<file>.spec.md` alongside the target path
3. If the target file already exists: read it and draft a spec (same as takeover step 2, but without the archive/regenerate/validate pipeline)
4. If the target file doesn't exist: create a skeleton spec with conventional headings as suggestions
5. Present the spec to the user for editing

After the user is happy with the spec, they run `/unslop:generate` to produce the managed file.

This is simpler than takeover — no archiving, no convergence loop. It's for when you want to write the spec first and generate code from it, rather than extracting a spec from existing code.

## Takeover Pipeline

When a user runs `/unslop:takeover src/retry.py`:

### Step 1: Discover
- Read the target file and find its tests (by convention: `*_test.py`, `test_*.py`, `*.test.ts`, `*.spec.ts`, etc.)
- If no tests found: warn that the spec will be unvalidated, but proceed if the user confirms

### Step 2: Draft Spec
- Load the spec-language skill
- Generate `<file>.spec.md` from the code and its tests
- Write intent, not implementation
- **User reviews the draft spec before proceeding** — this is the "do you agree this captures your intent?" gate

### Step 3: Archive
- Move original to `.unslop/archive/<relative-path>.<timestamp>` (preserving directory structure, e.g., `.unslop/archive/src/retry.py.2026-03-20T143200Z`)
- Safety net, not a versioning system
- Archive directory is gitignored

### Step 4: Generate
- Load the generation skill
- Generate fresh code from the spec only — no peeking at the archived original
- Add `@unslop-managed` header comment
- Invoke superpowers TDD cycle for implementation

### Step 5: Validate
- Run the project's test command
- If green: done, commit spec + generated file
- If red: enter convergence loop

### Step 6: Convergence Loop (max 3 iterations)
- Analyze test failures
- Identify the missing semantic constraint in the spec
- Enrich the spec (not the code)
- Regenerate from the enriched spec
- Re-run tests
- If green: done
- If red + iterations remaining: loop
- If red + max iterations: stop, show the user what's failing, ask for help

On abandonment (max iterations reached): keep the draft spec (so the user can fix it), keep the last generated attempt (so the user can see what failed), and note that the original remains in the archive for manual recovery.

The "no peeking" rule is enforced by the generation skill's instructions. This is where the prompt-only approach may be weakest — and exactly what we're testing.

## Generation & Sync

### `/unslop:generate` (all stale files)
1. Scan for all `*.spec.md` files
2. Find corresponding managed files by naming convention
3. Compare timestamps — spec newer than generated file = stale
4. For each stale file: regenerate from spec, run tests
5. If green: update header timestamp. If red: report failures and stop.

### `/unslop:sync <file>` (single file)
Same as generate but for one specific file.

### Key distinction from takeover
Generate does **not** enter a convergence loop. If tests fail, it reports and stops. The user edited the spec deliberately — if it's broken, they fix the spec and re-run. The convergence loop is only for takeover, where the spec was machine-drafted.

## Status

### `/unslop:status`
Scans the project and reports managed file states:

```
Managed files:
  fresh   src/retry.py        <- retry.spec.md
  stale   src/parser.py       <- parser.spec.md (spec edited 2h ago)
  modified src/adapter.py     <- adapter.spec.md (3 lines changed directly)

Unmanaged specs:
  src/utils.spec.md  (no managed file)
```

Three states:
- **Fresh** — generated file is newer than spec, no direct edits
- **Stale** — spec edited since last generation
- **Modified** — someone edited the managed file directly

Detection: compare file modification times. The `@unslop-managed` header timestamp detects direct edits (file mtime newer than generation timestamp, spec unchanged). Heuristic for MVP — git-based detection is a roadmap item.

## Alignment Summary

Auto-generated file at `.unslop/alignment-summary.md`. Committed to git.

```markdown
# unslop alignment summary
<!-- Auto-generated. Do not edit. -->

## Managed files

- `src/retry.py` <- `src/retry.spec.md` (fresh, generated 2026-03-20T14:32:00Z)
  Intent: Exponential backoff retry wrapper with jitter, max 5 attempts

- `src/parser.py` <- `src/parser.spec.md` (stale)
  Intent: Parses incoming webhook payloads into normalized event objects
```

### Hooks

**spec-change-detector** (PostToolUse on Write/Edit):
- Checks if the written/edited file matches `*.spec.md`
- If yes: regenerates `alignment-summary.md` by scanning all specs

**session-context** (SessionStart + PostCompact):
- Loads `.unslop/alignment-summary.md` into context if it exists
- Gives the model immediate orientation on what's managed

The summary is a guard against context drift — after compaction or in a new session, the model knows what specs exist and what each file does without reading every spec.

## Init

### `/unslop:init`
Run once per project:

1. Create `.unslop/` directory with `.unslop/archive/`
2. Create `.unslop/.gitignore` — ignores `archive/` and `feedback.md`
3. Detect test command:
   - `package.json` with test script -> `npm test`
   - `pytest.ini` / `pyproject.toml` with pytest -> `pytest`
   - `Makefile` with test target -> `make test`
   - `Cargo.toml` -> `cargo test`
   - `go.mod` -> `go test ./...`
   - If ambiguous or not found -> ask the user
4. Write `.unslop/config.md`:
   ```markdown
   # unslop configuration

   Test command: `pytest`
   ```
5. Create empty `alignment-summary.md`
6. Commit the `.unslop/` directory

Config is markdown, not JSON — the model reads it as natural context, the user edits it as prose.

## Skills

### `spec-language.md`
Teaches the model how to write specs. Vocabulary guide with positive/negative examples. Register guidance. When to be specific (constraints, invariants, error behavior) vs when to be vague (implementation details). Loaded by takeover and available on-demand during spec editing.

### `generation.md`
Teaches the model how to generate code from a spec. "Read only the spec" discipline. `@unslop-managed` header format and comment syntax per language. Invokes superpowers TDD. Output should be idiomatic, not a transliteration. Loaded by takeover, generate, sync.

### `takeover.md`
Orchestrates the full takeover pipeline. Step-by-step instructions, convergence loop protocol, "no peeking" reinforcement, archive conventions. Loaded by takeover command only.

### Skill loading pattern
Commands reference skills inline:
```
Use the unslop/spec-language skill for guidance on spec writing voice.
Use the unslop/generation skill for code generation discipline.
```
Loaded on demand through superpowers' skill system. Commands stay thin.

## Feedback Loop

The plugin encourages models that use it to suggest improvements to unslop's own workflows.

### Mechanism
The session-context hook includes a prompt in the loaded context:

> If you noticed friction with the unslop workflow during this session — spec-language patterns that didn't generate well, convergence loop behaviors that felt wrong, missing constraints, or workflow steps that could be streamlined — note them in `.unslop/feedback.md` before the session ends.

`.unslop/feedback.md` is an append-only log. Each entry includes:
- Date and which command/skill triggered the observation
- What happened vs what should have happened
- Suggested improvement

This file is gitignored (it's project-local observations, not team documentation). The user brings it back to the unslop plugin repo as input for plugin development.

### Why this matters
The models using unslop in real projects have the best vantage point on what works and what doesn't. This closes the loop: use the plugin -> model notices friction -> feedback captured -> plugin author improves the plugin.

## Roadmap

### Phase 2: Hardening
- Pre-commit hook — warn/block commits to managed files edited directly
- `/unslop:unmanage <file>` — remove from management, keep last generated version
- Convergence loop tooling — if prompt-only loop is unreliable, add orchestration script
- Git-based staleness detection (replace mtime heuristic)

### Phase 3: Domain Skills & Extensibility
- `unslop/domain/` directory — user-contributed domain priors (FastAPI, React, Terraform, etc.)
- Domain skill scaffolding in init
- Spec inheritance — shared constraints across specs

### Phase 4: Team & CI
- CI integration — generate on stale specs, verify tests pass in PRs
- Spec review workflow — PR templates that surface spec diffs
- MCP server (if needed) — structured state management, cross-file dependency tracking

### Phase 5: Ecosystem
- Marketplace growth — domain skills as additional plugins
- CodeSpeak interop — import/export between formats
- Multi-file specs — one spec generating multiple coordinated files
