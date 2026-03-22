# Deterministic Infrastructure Design (Milestone B)

> Replace fragile mtime-based staleness with content hashing, consolidate config into a single JSON file, and add a CI-compatible freshness check to the orchestrator.

## Problem

Three infrastructure weaknesses undermine trust in unslop's tooling:

1. **mtime staleness is fragile.** Git checkouts, file copies, CI runners cloning fresh, and timezone differences all corrupt mtime-based detection. A file can appear fresh when it isn't, or stale when it is.
2. **config.md is prose.** Scripts must parse it with fragile regex or rely on the model. Structured config enables reliable, deterministic tooling.
3. **No CI/CD freshness check.** There's no way to enforce that all managed files are fresh before merge — the `status` command requires an LLM.

## Scope

Three changes, tightly coupled:

1. **Dual-hash header** — `spec-hash` + `output-hash` in the `@unslop-managed` header, replacing mtime-based staleness with content-based classification
2. **`config.json`** — single structured config file replacing `config.md`, with `_note` fields for model context
3. **`check-freshness` subcommand** — deterministic freshness check added to `orchestrator.py`, usable in CI and pre-push hooks

## Dual-Hash Header Format

### Current format (being replaced)

```python
# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.
# Generated from spec at 2026-03-22T14:32:00Z
```

### New format

```python
# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z
```

- Line 1: unchanged — contains the spec path
- Line 2: `spec-hash:<12hex> output-hash:<12hex> generated:<ISO8601>`
- Comment syntax varies by language (same table as generation skill)

### Hash details

- **Algorithm:** SHA-256, truncated to first 12 hex characters
- **`spec-hash`:** Hash of the spec file content at generation time (entire file, including frontmatter)
- **`output-hash`:** Hash of the managed file content *below the header* at generation time
- **Hashing scope:** The output-hash excludes the header lines. Hash starts from the first character of actual code/content. Apply Python `str.strip()` to the body content before hashing to normalize leading/trailing whitespace across platforms.
- **Hash timing:** Hash the final byte-exact output after any post-processing (formatting, linting) to avoid stale-hash errors from invisible whitespace changes.
- **`generated` timestamp:** Retained for human readability and relative-time display in status output. Not used for staleness classification.

### Write order in generation skill

1. Generate the file body (everything below the header)
2. Strip leading/trailing whitespace from body, hash → `output-hash`
3. Read and hash the spec file content → `spec-hash`
4. Write header line 1 (spec path)
5. Write header line 2 (hashes + timestamp)
6. Write the body

This ordering ensures the output-hash is computed before the header is written — the header is not included in the hash.

## Four-State Staleness Classification

Replaces the mtime-based three-state classification with content-hash-based four-state.

**Deviation from gap analysis:** The gap analysis defined three states, treating the "spec changed AND code changed" case as a variant of Stale (`stale (modified)`). This spec promotes it to a distinct Conflict state because losing manual edits should require explicit acknowledgment — a developer's emergency hotfix shouldn't be silently overwritten just because a spec also changed. The four-state model turns a potential data loss scenario into a controlled interaction.

### Classification algorithm

1. Read the managed file's `@unslop-managed` header. Extract `spec-hash` and `output-hash`.
2. Hash the current spec file content → `current-spec-hash`
3. Hash the current managed file content below the header → `current-output-hash`
4. Classify:

| `spec-hash` match? | `output-hash` match? | State | Meaning |
|---|---|---|---|
| Yes | Yes | **Fresh** | In sync |
| Yes | No | **Modified** | Code was edited directly; spec unchanged |
| No | Yes | **Stale** | Spec changed; code is safe to overwrite |
| No | No | **Conflict** | Both changed. Overwriting will lose manual edits |

### State behaviors

- **Fresh:** No action needed.
- **Stale:** Safe to regenerate. `generate`/`sync` proceed normally.
- **Modified:** `generate`/`sync` warn and require `--force` or user confirmation before overwriting. Status displays `(edited directly)`.
- **Conflict:** `generate`/`sync` block and require `--force` or user confirmation. Status displays `(spec and code both changed — regenerating will lose manual edits)`.

### Edge cases

- **Header missing or malformed:** Classify as `unmanaged (no header)`. Treat the same as a file not yet managed by unslop.
- **Spec file missing:** Report as an error — the managed file references a spec that no longer exists.
- **New header format on old files:** Files with the old timestamp-only header (no hashes) are classified as `old_format` — a distinct edge case state. No mtime fallback is attempted (mtime is the very thing being replaced). Status displays `(old header — regenerate to update)`. Generate/sync treat `old_format` the same as `stale` — safe to regenerate, which updates the header to the new format.

## `config.json`

### Format

`.unslop/config.json` replaces `.unslop/config.md`.

**Deviation from gap analysis:** The gap analysis proposed a dual-file approach (`config.md` for humans + `config.json` for scripts). This spec uses a single `config.json` with `_note` fields instead. Rationale: a dual-file strategy creates sync risk — editing `config.md` without updating `config.json` causes scripts to read stale data. Single source of truth eliminates this class of bugs. The `_note` fields provide the same contextual information the model would have gotten from prose.

Schema:

```json
{
  "test_command": "pytest",
  "test_command_note": "Detected from pyproject.toml",
  "exclude_patterns": [],
  "exclude_patterns_note": "Additional directory patterns to exclude from discovery, beyond defaults"
}
```

- **Naming rule:** Any field whose name ends with `_note` is informational and MUST NOT be read by scripts. Scripts ignore `*_note` fields; the model reads them for context.
- Scripts read the data fields; the model reads both data and notes
- Only fields that scripts actually consume are included — YAGNI

### Migration

- `/unslop:init` writes `config.json` instead of `config.md`
- If `config.md` exists but `config.json` doesn't, commands/scripts read `config.md` as fallback and suggest running `/unslop:init` to migrate
- If both exist, `config.json` takes precedence
- `/unslop:init` on a project with `config.md` migrates to `config.json` and deletes `config.md` in the same commit

### What reads what

| Consumer | Reads | Why |
|---|---|---|
| Scripts (orchestrator, validate_spec) | `config.json` | Structured data, no parsing ambiguity |
| Model (generation skill, commands) | `config.json` | Model reads JSON; `_note` fields provide context |
| Session hook (`load-context.sh`) | `config.json` | Extracts test command via `jq` for context injection |

## `check-freshness` Subcommand

New subcommand added to `orchestrator.py`:

```bash
python orchestrator.py check-freshness [directory]
# Exit 0: all managed files are fresh
# Exit 1: one or more files are stale, modified, or in conflict
# Output: JSON summary on stdout
```

### Algorithm

1. Discover all `*.spec.md` files in the directory (defaults to `.`, recursive)
2. For each spec, derive the managed file path (strip `.spec.md`)
3. Read the managed file's first 5 lines, find `@unslop-managed` header
4. Extract `spec-hash` and `output-hash` from header line 2
5. Compute current spec hash and current output hash
6. Classify using the 4-state table
7. Report results and exit non-zero if any file is not fresh

### Header parsing

Shared function in `orchestrator.py`, reusable across subcommands:

1. Read the first 5 lines of the managed file (accommodates shebangs, docstrings)
2. Find a line containing `@unslop-managed` — extract the spec path (between "Edit " and " instead")
3. Find a line containing `spec-hash:` — extract both hashes via regex: `spec-hash:(\w{12})` and `output-hash:(\w{12})`
4. Strip the leading comment syntax before matching (detect from file extension, same table as generation skill)

### Output format

```json
{
  "status": "pass",
  "files": [
    {"managed": "src/retry.py", "spec": "src/retry.py.spec.md", "state": "fresh"}
  ],
  "summary": "1 fresh"
}
```

```json
{
  "status": "fail",
  "files": [
    {"managed": "src/retry.py", "spec": "src/retry.py.spec.md", "state": "fresh"},
    {"managed": "src/parser.py", "spec": "src/parser.py.spec.md", "state": "stale"},
    {"managed": "src/adapter.py", "spec": "src/adapter.py.spec.md", "state": "conflict",
     "hint": "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."}
  ],
  "summary": "1 fresh, 1 stale, 1 conflict"
}
```

- `status` is `pass` if all files are fresh, `fail` otherwise
- `hint` field included for conflict and modified states to provide actionable guidance

### CI usage

```yaml
# GitHub Actions
- name: Check managed file freshness
  run: python unslop/scripts/orchestrator.py check-freshness .
```

```bash
# Pre-push hook (generated by init)
#!/bin/sh
python3 "$(git rev-parse --show-toplevel)/unslop/scripts/orchestrator.py" \
    check-freshness "$(git rev-parse --show-toplevel)"
```

### Unit spec handling

For `*.unit.spec.md` files, the managed file paths come from the `## Files` section rather than filename derivation. The `check-freshness` subcommand reads the `## Files` section, resolves paths relative to the spec's directory, and checks each listed file's header. The unit is classified by its worst-case file state (if any file is conflict, the unit is conflict).

### Exit behavior

Files in `modified` or `conflict` state are treated as non-fresh and cause exit 1. A deliberately edited managed file will block CI — this is intentional. The developer must either revert the edit, update the spec to match, or regenerate with `--force`.

### What it does NOT do

- Generate or regenerate files — that's the model's job
- Run tests — it only checks hash freshness
- Require an LLM — this is fully deterministic Python

## Updates to Existing Components

### Generation skill

- Section 2 (header format): Update to write the new dual-hash header
- Remove the placeholder comment about "when dual-hash staleness from Gap 2 is implemented"
- Add the write-order instructions (generate body → hash → write header → write body)
- **Incremental mode:** After applying targeted edits, re-hash the full body content and update the header with new `output-hash`, `spec-hash`, and timestamp. The body changes via diff, then the complete body is hashed for the header.
- Update all references from `config.md` to `config.json` (Sections 1 and 5 reference `.unslop/config.md`)

### Status command

- Replace mtime-based classification with hash-based 4-state classification
- Add `conflict` state display
- Call `orchestrator.py check-freshness` for the deterministic classification, or do inline classification (the command can hash files directly since it's reading them anyway)

### Generate command

- Replace mtime staleness check with hash-based check
- Add `--force` flag for overwriting modified/conflict files
- Warn before overwriting modified files; block on conflict unless `--force`
- Update references from `config.md` to `config.json`

### Sync command

- Same changes as generate — hash-based staleness, `--force` for modified/conflict
- Update references from `config.md` to `config.json`

### Init command

- Write `config.json` instead of `config.md`
- Migration: detect existing `config.md`, convert to `config.json`, delete `config.md`
- Read `exclude_patterns` from `config.json` when calling orchestrator discover

### `load-context.sh` hook

- Read `config.json` via `jq` instead of `cat`-ing `config.md`
- Fallback: if `jq` not available, read `config.json` as plain text (still valid for context injection, just not parsed)

### Orchestrator

- New `check-freshness` subcommand
- New shared `parse_header()` function for reading `@unslop-managed` headers
- New shared `compute_hash()` function for SHA-256 truncated to 12 chars
- `discover` subcommand reads `exclude_patterns` from `config.json` if it exists

## Backwards Compatibility

- **Old headers without hashes:** Classified as `old_format`. Generate/sync treat this as stale — regeneration updates the header to the new dual-hash format.
- **`config.md` without `config.json`:** Commands read `config.md` as fallback. Suggest running `/unslop:init` to migrate.
- **Both `config.md` and `config.json` present:** `config.json` takes precedence. Init deletes `config.md` during migration.
- **No `jq` available:** `load-context.sh` falls back to reading `config.json` as plain text for context injection. The orchestrator doesn't need `jq` — it reads JSON via Python's `json` module.

## Plugin Structure Changes

```
unslop/
├── scripts/
│   ├── orchestrator.py       # updated — check-freshness, parse_header, compute_hash
│   └── validate_spec.py      # unchanged
├── skills/
│   └── generation/
│       └── SKILL.md          # updated — Section 2 (new header format)
├── commands/
│   ├── init.md               # updated — config.json, migration
│   ├── generate.md           # updated — hash-based staleness, --force
│   ├── sync.md               # updated — hash-based staleness, --force
│   └── status.md             # updated — 4-state classification
└── hooks/
    └── scripts/
        └── load-context.sh   # updated — reads config.json
```
