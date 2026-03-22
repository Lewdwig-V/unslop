# Change Requests Design (Milestone C)

> Surgical fixes and incremental mutations for managed files, with a structured lifecycle that reconciles every change back to the spec.

## Problem

Sometimes a managed file needs a targeted fix that doesn't warrant a full spec rewrite — a performance patch, a changed API endpoint, a discovered edge case. Currently, the only options are: edit the spec and regenerate (heavyweight for a one-line fix), or edit the managed file directly and accept a `modified`/`conflict` state (breaks the spec-driven invariant).

Change requests provide a structured middle path: record the intent, apply the fix, reconcile with the spec, and clean up. The managed file header stays consistent and the spec remains the source of truth.

## Scope

- A new `*.change.md` sidecar file format with stacked entries
- A new `/unslop:change` command for creating entries
- Integration into the generation skill's pre-generation pipeline (Phase 0c)
- Two processing flows: spec-first (`[pending]`) and code-first (`[tactical]`)
- Delete-on-promotion lifecycle — change.md is a temporary scratchpad, not a permanent archive
- `check-freshness` and `status` awareness of pending changes

## Change Entry Format

Change requests live in sidecar files alongside managed files: `src/retry.py.change.md` next to `src/retry.py` and `src/retry.py.spec.md`.

### Entry structure

```markdown
### [pending] Add jitter to backoff — 2026-03-22T15:00:00Z

Backoff should include random jitter (0-50% of delay) to prevent
thundering herd when multiple clients retry simultaneously.

---

### [tactical] Fix upstream API endpoint — 2026-03-22T16:30:00Z

The payments API moved from api.v2.payments.com to api.v3.payments.com.
Update the base URL constant.

---
```

- **Heading**: `### [status] Description — ISO8601 timestamp`
- **Status markers**: `[pending]` (standard spec-first flow) or `[tactical]` (fast path — code first, spec reconciliation after)
- **Body**: Natural language description of the change intent. Same register as specs — what, not how.
- **Separator**: `---` between entries
- **No frontmatter** — the file is pure stacked entries

### Parsing contract

- Entries are separated by `---`
- Status is extracted from the heading: regex `\[(\w+)\]`
- Entries are processed top-to-bottom (oldest first)
- The body is NOT code patches, diffs, or implementation instructions — it describes intent

## Processing Flows

### Standard flow (`[pending]`)

1. Model reads the entry + current spec
2. Model proposes a spec update that captures the change intent
3. User reviews and approves the spec update
4. Model regenerates code from updated spec (uses incremental mode)
5. Tests run — must pass
6. Entry is deleted from change.md
7. Hashes updated, commit

### Tactical flow (`[tactical]`)

1. Model reads the entry + current spec + current code
2. Model patches the managed file directly (incremental mode)
3. Tests run — must pass
4. Model drafts a spec update that reflects the code change
5. User reviews: "I've patched the code and updated the spec to match. Review and approve?"
6. On approval: entry deleted, hashes updated, commit
7. On rejection: entry stays `[tactical]`, code change reverts, user edits spec manually

### Mixed batch rules

When a file has both `[pending]` and `[tactical]` entries:

1. Process all `[pending]` entries first (they update the spec, which the tactical entries need as context)
2. Then process `[tactical]` entries
3. After all entries processed, compute final output-hash once (atomic transaction)
4. Delete all successfully promoted entries
5. If any entry fails (tests break, user rejects), stop — remaining entries stay in the file

## Generation Skill Integration

Change request consumption is added as Phase 0c in the generation skill's pre-generation pipeline:

```
Section 0: Pre-Generation Validation
  Phase 0a: Structural Validation        ← existing
  Phase 0b: Ambiguity Detection           ← existing
  Phase 0c: Change Request Consumption    ← NEW

Sections 1-6: Generation pipeline

Section 7: Post-Generation Review         ← existing
```

Phase 0c reads the `*.change.md` sidecar for the target file. If entries exist:
- Classify entries by status (`[pending]` vs `[tactical]`)
- Inject change intent into the generation context with clear priority
- Process in the order defined by mixed batch rules

This single integration point covers generate, sync, and dependency-triggered rebuilds — the generation skill is the funnel through which all code production flows.

### Context injection

The generation skill receives change entries as additional constraints:

> "You are updating `retry.py`. The current spec is [spec content]. There are pending change requests that extend this spec:
> 1. [pending] Add jitter to backoff — [entry body]
>
> Apply the pending logic to the spec first, then generate code from the updated spec."

For tactical entries:

> "After spec-based generation, apply these tactical fixes:
> 1. [tactical] Fix upstream API endpoint — [entry body]
>
> Patch the generated code, then propose a spec update to capture the fix permanently."

## `/unslop:change` Command

```
/unslop:change src/retry.py "add jitter to backoff"
/unslop:change src/retry.py "fix payments API endpoint" --tactical
/unslop:change src/retry.py   # no message — prompts for elaboration
```

### What the command does

1. **Parse arguments**: Extract file path, description, and `--tactical` flag from `$ARGUMENTS`
2. **Verify**: File exists, `.unslop/` initialized, file is managed (has `@unslop-managed` header)
3. **Create or append**: If `src/retry.py.change.md` exists, append. If not, create.
4. **Write the entry**: `### [pending|tactical] <description> — <timestamp>`
5. **Prompt for detail**: If no description provided, ask user to elaborate. If one-liner provided, ask if they want to add more detail.
6. **Execute or defer**:
   - `--tactical`: Execute the tactical flow immediately (patch code, propose spec update, user gate)
   - `[pending]` (default): Inform user the change is queued: "Change recorded. Run `/unslop:generate` or `/unslop:sync src/retry.py` to apply."

### Deferred execution rationale

`[pending]` changes are consumed during generate/sync, not when created. This lets users batch multiple changes before triggering a (potentially expensive) regeneration cycle. The change command stays lightweight — just writes the entry.

`[tactical]` changes execute immediately because the developer wants the fix now and is willing to reconcile the spec as part of the same interaction.

## Edge Cases and Guards

### Guard rails

| Condition | Behavior |
|---|---|
| File not managed (no `@unslop-managed` header) | Error: "File is not managed by unslop. Run `/unslop:takeover` or `/unslop:spec` first." |
| File in `conflict` state | Error: "File has unresolved conflicts. Resolve with `/unslop:sync --force` before adding changes." |
| File in `modified` state + `--tactical` | Warn: "File was edited directly. The tactical change will be applied on top of direct edits. Proceed?" |
| Spec file missing | Error: "Spec not found. The managed file references a spec that no longer exists." |
| Change.md has 5+ pending entries | Warn: "This file has N pending changes. Consider running `/unslop:generate` to process them before adding more." |

### Interaction with other commands

| Command | Change.md behavior |
|---|---|
| `/unslop:generate` | Processes all pending changes across all managed files (Phase 0c) |
| `/unslop:sync <file>` | Processes changes for that specific file only |
| `/unslop:status` | Shows pending change count per file |
| `/unslop:takeover` | Ignores change.md — takeover replaces everything |
| `check-freshness` | Files with pending changes are non-fresh (`pending_changes` state) |
| `/unslop:change` | Creates/appends entries; executes immediately for `--tactical` |

## Status Integration

`/unslop:status` shows pending changes:

```
Managed files:
  fresh    src/retry.py        <- src/retry.py.spec.md
           Δ 2 pending changes [1 pending, 1 tactical]
  stale    src/parser.py       <- src/parser.py.spec.md (spec changed)
```

## check-freshness Integration

The orchestrator's `check-freshness` subcommand detects `*.change.md` files. A managed file that is hash-fresh but has pending changes is reported as `pending_changes`:

```json
{"managed": "src/retry.py", "spec": "src/retry.py.spec.md", "state": "pending_changes",
 "hint": "1 pending, 1 tactical change request awaiting processing."}
```

This is non-fresh (exit 1) — pending changes represent unreconciled intent that CI should flag.

## Promotion (Lifecycle)

When a change entry is successfully processed:

1. **Spec updated**: The change intent is now captured permanently in the spec
2. **Code regenerated**: The managed file reflects the updated spec
3. **Hashes reconciled**: Both `spec-hash` and `output-hash` are current
4. **Entry deleted**: The processed entry is removed from change.md
5. **File cleanup**: If change.md is now empty, the file itself is deleted
6. **Commit**: All changes (spec update, code regeneration, change.md deletion) are committed together

Git history preserves the full audit trail. The change.md file's existence is a "work in progress" signal — its absence means the component is clean.

## Plugin Structure Changes

```
unslop/
├── commands/
│   └── change.md              # NEW — /unslop:change command
├── skills/
│   └── generation/
│       └── SKILL.md           # MODIFIED — Phase 0c added
├── commands/
│   ├── generate.md            # MODIFIED — change.md consumption note
│   ├── sync.md                # MODIFIED — change.md consumption note
│   └── status.md              # MODIFIED — pending changes display
└── scripts/
    └── orchestrator.py        # MODIFIED — check-freshness detects *.change.md
```

## Backwards Compatibility

- Existing managed files without change.md sidecars are unaffected
- The generation skill's Phase 0c is a no-op when no change.md exists
- `check-freshness` only reports `pending_changes` when a change.md file is present
- No migration required — change.md files are created on demand by the change command
