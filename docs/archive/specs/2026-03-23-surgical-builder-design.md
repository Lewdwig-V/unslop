# v0.16.0 Surgical Builder Design Spec

**Date:** 2026-03-24
**Status:** Design-Locked (Surgical Lite -- replaces the full Surgicality Linter spec)

## Problem

The Builder operates in "blank slate" mode -- it receives specs and produces code from scratch in an isolated worktree. Two runs with identical specs can produce structurally different code because the Builder has no anchor to preserve existing structure. This causes Developer Vertigo: a single variable name change in the spec triggers method reordering, for-loop-to-map() swaps, and gratuitous reformatting throughout the file. Users lose trust, git blame becomes useless, and diffs are unreadable.

## Solution: Surgical Lite

Give the Builder its own prior output as a structural template (the "Compilation Target"), a spec diff to focus its attention, and an explicit list of symbols it is authorized to modify. A soft post-hoc check warns if the Builder drifted beyond its authorization. No new dependencies. No new Builder status codes.

### Design principles

1. **Prompt-first, lint-second.** The Builder receives focused context (compilation target + spec diff + affected symbols) and is instructed to minimize changes. A post-hoc check catches drift but does not reject -- it warns.
2. **Zero new dependencies.** Uses Python's `ast` module (already used by `symbol_audit.py`) for the post-hoc check. No tree-sitter, no compiled libraries.
3. **Escape hatch, not escalation protocol.** If surgical mode produces a bad result, the user runs `--refactor` for full regeneration. No BLOCKED_SCOPE, no Architect escalation flow.
4. **Python-first.** The `ast`-based post-hoc check works for Python. Other languages get prompt enforcement only, with the soft check deferred to a future version that adds tree-sitter.

### What this spec defers

The original design specified a deterministic Surgicality Linter with tree-sitter, a BLOCKED_SCOPE Builder status, language-specific import comparison, and a 4-PR implementation plan. These are deferred to v0.17.0 pending validation data: if Surgical Lite's prompt-based approach produces minimal diffs in practice, the hard linter is premature optimization. If it doesn't, the data justifies the dependency.

---

## Core Architectural Decision: The "Compilation Target" Carve-Out

The existing managed code is not "user intent" -- it is a serialized state of the previous spec, a cold deterministic implementation with zero vibes, intents, or conversation history. Providing it to the Builder is State Synchronization, not a No-Peeking violation.

**Negative Constraint:** The Builder is prohibited from using the existing code as a reason to ignore a spec change. If the Spec Diff contradicts the Code, the Spec Diff wins. Always.

---

## Relationship to Existing Generation Modes

The generation skill currently defines two modes:
- **Mode A (Full Regeneration):** Builder generates from scratch. Current default.
- **Mode B (Incremental, `--incremental` flag):** Builder reads the existing file and produces targeted diffs.

Surgical mode **replaces both** as the new default for files that already exist:

| Scenario | v0.15.0 | v0.16.0 |
|----------|---------|---------|
| First generation (no existing code) | Mode A | Mode A (unchanged) |
| Existing file, spec changed | Mode A (default) or Mode B (`--incremental`) | **Surgical** (new default) |
| User wants full restructure | Mode A | `--refactor` flag (equivalent to Mode A) |

**Mode B (`--incremental`) is deprecated.** Surgical mode subsumes it with better context. The `--incremental` flag becomes an alias for the new default behavior and emits a deprecation warning: `"--incremental is deprecated. Surgical mode is now the default. Use --refactor for full regeneration."`

---

## 1. Spec-Diff Computation

When a spec changes, the Orchestrator computes a section-level diff.

**Mechanism:**
- Old spec: `git show HEAD:<spec_path>` (last committed version)
- New spec: current file on disk (after Architect's Stage A update)
- Parse both into `{section_heading: content}` maps, compare values

**Output:**
```yaml
spec_diff:
  changed_sections:
    - "## Behavior"
    - "## Error Handling"
  unchanged_sections:
    - "## Purpose"
    - "## Constraints"
```

This is computed by the Orchestrator and passed to the Architect during Stage A.2. No new script needed -- section-level markdown diffing is a simple string operation.

---

## 2. Affected Symbols Derivation

During Stage A.2, the Architect produces the `affected_symbols` list. Written to concrete spec frontmatter:

```yaml
---
source-spec: src/retry.py.spec.md
target-language: python
affected_symbols:
  - calculate_delay
  - retry
reason: "Behavior section changed delay calculation formula"
---
```

**Architect's inputs:**
- The `spec_diff` (which sections changed)
- Existing code's symbol name list (from `symbol_audit.py`'s `_extract_public_symbols`, names only -- not bodies)
- The spec text (to map requirements to symbols)

The Architect sees symbol *names*, not *implementations*. This preserves the No-Peeking boundary -- symbol names are already visible in the file tree.

### Edge Cases

**New symbols:** Tagged `(new)` in `affected_symbols`. Post-hoc check exempts from "must match old block."
```yaml
affected_symbols:
  - calculate_delay
  - format_backoff_report (new)
```

**Deleted symbols:** Tagged `(deleted)`. Post-hoc check verifies symbol was removed.
```yaml
affected_symbols:
  - legacy_retry (deleted)
```

### Multi-Target Concrete Specs

For multi-target concrete specs, each target gets its own `affected_symbols` list in the `targets[]` array:

```yaml
---
source-spec: src/retry.spec.md
targets:
  - path: src/retry.py
    language: python
    affected_symbols:
      - calculate_delay
      - retry
  - path: frontend/src/retry.ts
    language: typescript
    affected_symbols:
      - calculateDelay
      - retry
reason: "Behavior section changed delay calculation formula"
---
```

For single-target specs, `affected_symbols` remains at top-level frontmatter.

---

## 3. Builder Prompt Update

The Builder's dispatch prompt gains three new sections for surgical syncs:

### Existing Code block

The current managed file, labeled "Last Successful Compilation Target." Builder treats this as its structural template.

### Spec Diff block

Summary of which spec sections changed. Focuses the Builder's attention on relevant requirements.

### Affected Symbols block

Explicit authorization list:

> "You are authorized to modify ONLY these symbols: [calculate_delay, retry]. All other symbols, including their docstrings, type signatures, and internal logic, must remain identical to the Existing Code. Copy them verbatim. Do not reformat, reorder, or 'improve' protected symbols."

### When Surgical Context Is NOT Provided

Full regeneration mode (no Existing Code, no Spec Diff, no Affected Symbols):
- First generation (no existing code)
- File state is `conflict` and user chose "Overwrite"
- `--refactor` flag (explicit opt-in to full regen)

**Note on `--force`:** Retains existing meaning ("proceed on modified/conflict files without confirmation"). Does NOT bypass surgical mode. To bypass surgical mode, use `--refactor`.

---

## 4. Optional Drift Check (Diagnostic Tool)

The `check-drift` CLI command is available as a standalone diagnostic for users who want to verify the Builder respected its Affected Symbols boundary after a surgical sync. It is **not part of the default pipeline** -- the Surgical Context prompt blocks are the primary enforcement mechanism, and they work for all languages equally.

```
python orchestrator.py check-drift <old-file> <new-file> --affected s1,s2,s3
```

Currently Python-only (uses `ast` for symbol extraction). Non-Python files return `skipped: true`. Useful for spot-checking, not for gating.

**Design principle:** unslop does not privilege any language. The Surgical Builder's core value -- Compilation Target, Spec Diff, Affected Symbols -- is language-agnostic prompt context. Language-specific tooling (like the Python drift check) is opt-in diagnostic, never automatic pipeline.

---

## 5. Triage Summary

After merge, the controlling session emits a triage summary. No LLM involved.

**Surgical sync:**
```
Sync complete: src/retry.py.spec.md
  Mode: surgical
  Affected symbols: calculate_delay, retry
  Tests: 12 passed
```

**Full regeneration:**
```
Generation complete: src/retry.py.spec.md
  Mode: full regeneration (--refactor)
  Tests: 12 passed
```

---

## 6. `--refactor` Flag

Added to `/unslop:sync` and `/unslop:generate`. Bypasses surgical mode entirely:

1. Stage A (Architect) runs normally
2. Stage A.2 (Strategist) runs with directive: "Ignore existing implementation structure"
3. Stage B (Builder) receives specs but NO Existing Code, NO Spec Diff, NO Affected Symbols
4. Identical to current v0.15.0 full-regen behavior

`--refactor` is the opt-out from surgical mode, not a new feature. The default shifts from full-regen to surgical; `--refactor` restores the old behavior.

---

## Modified File Handling

When the Orchestrator detects `modified` state (user hand-edited the code) before a surgical sync:

```
src/retry.py has manual edits (modified state). The spec also changed.
  [a] Overwrite -- discard manual edits, regenerate from spec
  [b] Absorb -- incorporate manual edits into the spec first, then regenerate
  [c] Skip -- leave this file alone for now
```

Option (b) routes to `/unslop:change`. The Builder never sees a `modified` file without the user's explicit decision.

---

## Files Changed

### Modified
- `unslop/skills/generation/SKILL.md` -- add Surgical Context blocks (Existing Code, Spec Diff, Affected Symbols), update mode dispatch logic
- `unslop/commands/sync.md` -- add `--refactor` flag, update dispatch to surgical default, modified-file pre-flight
- `unslop/commands/generate.md` -- add `--refactor` flag, update dispatch to surgical default
- `unslop/scripts/validation/symbol_audit.py` -- extend with `check_drift()` function for post-hoc soft check
- `unslop/scripts/orchestrator.py` -- add `spec-diff` CLI subcommand, re-export `check_drift`
- `unslop/.claude-plugin/plugin.json` -- version bump to 0.16.0

### No new files

All functionality fits into existing modules. The spec-diff computation is a simple function added to the orchestrator. The drift check extends `symbol_audit.py`.

---

## Implementation Plan (Single PR)

One PR ships the full feature:

1. **Extend `symbol_audit.py`** with `check_drift(old_path, new_path, affected_symbols)` -- returns a drift report with warnings for any protected symbol that changed. Uses `ast` for Python, skips for other languages.
2. **Add spec-diff function** to orchestrator -- section-level markdown comparison, exposed as `spec-diff` CLI subcommand.
3. **Update generation SKILL.md** -- add Surgical Context blocks, update mode dispatch logic, `--refactor` documentation.
4. **Update sync.md and generate.md** -- surgical default, `--refactor` flag, `--incremental` deprecation, modified-file pre-flight.
5. **Tests** for `check_drift()` and spec-diff computation.
6. **Version bump** to 0.16.0.

---

## Validation Criteria

Run against `stress-tests/jitter/src/retry.py` with a one-line spec change (e.g., change max retries from 3 to 5):

- **Success:** Builder's diff touches only the affected symbol(s). No method reordering, no reformatting of protected symbols.
- **Acceptable:** Builder touches 1-2 additional symbols. Drift warning fires. User accepts.
- **Failure:** Builder gratuitously reformats the entire file despite surgical context. This would justify the full Surgicality Linter (tree-sitter, hard gate, BLOCKED_SCOPE) in v0.17.0.

The validation result determines whether v0.17.0 invests in deterministic enforcement or moves on to other milestones.
