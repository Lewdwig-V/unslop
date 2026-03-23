# v0.16.0 Surgical Builder Design Spec

**Date:** 2026-03-23
**Branch:** feat/diffi-minimizer
**Status:** Design-Locked

## Problem

The Builder operates in "blank slate" mode -- it receives specs and produces code from scratch in an isolated worktree. Two runs with identical specs can produce structurally different code because the Builder has no anchor to preserve existing structure. This causes Developer Vertigo: a single variable name change in the spec triggers method reordering, for-loop-to-map() swaps, and gratuitous reformatting throughout the file. Users lose trust, git blame becomes useless, and diffs are unreadable.

## Solution: Surgical Patching

Move from "Bulk Generation" to "Surgical Patching" as a core constraint of the Builder. The Builder receives its own prior output as a structural template (the "Last Successful Compilation Target"), a spec diff to focus its attention, and an explicit list of symbols it is authorized to modify. A deterministic Surgicality Linter enforces that protected symbols remain untouched.

## Core Architectural Decision: The "Compilation Target" Carve-Out

The existing code is not "user intent" -- it is a serialized state of the previous spec, a cold deterministic implementation with zero vibes, intents, or conversation history. Providing it to the Builder is State Synchronization, not a No-Peeking violation.

**Negative Constraint:** The Builder is prohibited from using the existing code as a reason to ignore a spec change. If the Spec Diff contradicts the Code, the Spec Diff wins. Always.

---

## 1. Symbol-Block Splitter

### Purpose

Decompose a source file into a map of `{symbol_name: code_block}` pairs for per-symbol comparison.

### Implementation: Tree-sitter CST

Tree-sitter produces Concrete Syntax Trees that preserve comments, whitespace, and exact formatting -- required for bit-level comparison of protected blocks. Tree-sitter grammars are community-maintained; adding a new language is a package install, not a regex profile.

**Language support (v0.16.0):** Python, JavaScript, TypeScript, Go. Additional languages via `tree-sitter-{lang}` packages.

**Fallback:** If no tree-sitter grammar is available for a file's language, fall back to a line-based heuristic (top-level definition boundaries via indentation/brace-depth) and emit a warning: `"WARNING: No Tree-sitter grammar for .{ext}. Surgicality check is less precise."`

### Algorithm

1. Strip the `@unslop-managed` header (lines matching the managed header pattern)
2. Parse with tree-sitter for the file's language
3. Extract top-level declaration nodes (function_definition, class_definition, and language equivalents)
4. Each top-level node becomes a named block including its decorators/annotations and leading comments
5. Everything before the first declaration splits into:
   - `__imports__`: all import statements (compared as a sorted set, not positionally)
   - `__constants__`: module-level assignments, each its own named entry (protected unless in `affected_symbols`)
6. Nested classes/functions belong to their parent block (not split further)

### Output Format

```python
{
    "__imports__": {"import random", "import time", "from dataclasses import dataclass", ...},
    "T": "T = TypeVar('T')\n",
    "MaxRetriesExceeded": "class MaxRetriesExceeded(Exception):\n    ...",
    "RetryConfig": "@dataclass(frozen=True)\nclass RetryConfig:\n    ...",
    "retry": "def retry(operation: Callable[[], T], ...) -> T:\n    ...",
}
```

### Normalization (applied before comparison, never to actual output)

- Strip trailing whitespace per line
- LF line endings (CRLF -> LF)
- Collapse consecutive blank lines to single blank line
- Strip leading/trailing blank lines from each block

After normalization, exact match required. No "it's just a docstring" exceptions.

---

## 2. Spec-Diff Parser + Affected Symbols Extraction

### Part 1: Spec-Diff Computation

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
    - "## Open Questions"
```

### Part 2: Architect `affected_symbols` Derivation

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
- Existing code's symbol name list (from tree-sitter, names only -- not bodies)
- The spec text (to map requirements to symbols)

The Architect sees symbol *names*, not *implementations*. This preserves the No-Peeking boundary -- symbol names are already visible in the file tree.

### Edge Cases

**New symbols:** Tagged `(new)` in `affected_symbols`. Linter exempts from "must match old block" check.
```yaml
affected_symbols:
  - calculate_delay
  - format_backoff_report (new)
```

**Deleted symbols:** Tagged `(deleted)`. Linter verifies symbol was removed.
```yaml
affected_symbols:
  - legacy_retry (deleted)
```

---

## 3. Surgicality Linter (The Cold Audit Gate)

### Purpose

Deterministic post-hoc enforcement that the Builder only modified authorized symbols. Runs in the Orchestrator after Builder returns DONE, before worktree merge.

### Inputs

- `OLD_CODE`: existing managed file (Last Successful Compilation Target)
- `NEW_CODE`: Builder's output from worktree
- `affected_symbols`: from concrete spec frontmatter

### Algorithm

```
1. Parse OLD_CODE with tree-sitter -> old_symbols: {name: normalized_block}
2. Parse NEW_CODE with tree-sitter -> new_symbols: {name: normalized_block}
3. For each symbol in old_symbols:
     if symbol NOT in affected_symbols:
       if symbol NOT in new_symbols:
         FAIL("Protected symbol '{symbol}' was deleted")
       if normalize(old_symbols[symbol]) != normalize(new_symbols[symbol]):
         FAIL("Surgicality violation: '{symbol}' modified but not in affected_symbols")
4. For each symbol in new_symbols:
     if symbol NOT in old_symbols AND symbol NOT tagged (new) in affected_symbols:
       FAIL("Unauthorized new symbol '{symbol}' not declared in affected_symbols")
5. For each symbol tagged (deleted) in affected_symbols:
     if symbol in new_symbols:
       FAIL("Symbol '{symbol}' marked for deletion but still present")
6. PASS -- generate summary
```

### Preamble Rules

- `__imports__`: compared as a sorted set. New imports for affected symbols allowed. Removed imports for deleted symbols allowed. Reordering is not a violation.
- `__constants__`: each constant is a named symbol entry. Protected unless listed in `affected_symbols`.

### Rejection Output

```
REJECTED: Surgicality violation in src/retry.py

  Protected symbol 'RetryConfig' was modified.
  Affected symbols were: [calculate_delay, retry]

  Diff in protected symbol:
    - max_retries: int = 3
    + max_retries: int = 5

  Action: Re-dispatch Builder with tighter constraint,
          or escalate via BLOCKED_SCOPE if change is necessary.
```

### Retry on Failure

1. Builder's worktree is preserved (not discarded)
2. Re-dispatch Builder with violation report appended to prompt (mirrors `previous_failure` pattern)
3. Max 1 linter retry. Second failure auto-escalates to BLOCKED_SCOPE
4. If escalation budget also exhausted, becomes full BLOCKED

---

## 4. Builder Prompt Update

### New Context Blocks

The Builder's dispatch prompt gains three new sections for surgical syncs:

**Existing Code block:** The current managed file, labeled "Last Successful Compilation Target." Builder treats this as its structural template.

**Spec Diff block:** Summary of which spec sections changed. Focuses the Builder's attention on relevant requirements.

**Affected Symbols block:** Explicit authorization list. Builder is instructed: "You are authorized to modify ONLY these symbols. All other symbols must remain identical to the Existing Code."

### BLOCKED_SCOPE Awareness

The Builder is instructed that if it cannot satisfy the spec change within the authorized symbols, it must report `BLOCKED_SCOPE` with:
- Which protected symbol it needs
- Why the spec change requires it (must reference a spec requirement)
- What minimal change is needed
- Requested additions to `affected_symbols`

### Surgicality Linter Warning

The prompt explicitly warns: "The Surgicality Linter will verify your output. Any modification to a protected symbol triggers automatic rejection and retry."

### Surgicality Violation Injection

On linter retry, the violation report is injected (same pattern as `previous_failure`):

```
Previous Surgicality Violation:
  You modified protected symbol 'RetryConfig' which was not in your
  affected_symbols set [calculate_delay, retry].

  The specific unauthorized change:
    - max_retries: int = 3
    + max_retries: int = 5

  You MUST preserve 'RetryConfig' exactly as it appears in the
  Existing Code. If this is impossible, report BLOCKED_SCOPE.
```

### When Surgical Context Is NOT Provided

Full regeneration mode (no Existing Code, no Spec Diff, no Affected Symbols, Linter skipped):
- First generation (no existing code)
- File state is `conflict` and user chose "Overwrite"
- `--force` flag
- `--refactor` flag

---

## 5. BLOCKED_SCOPE Protocol

### New Builder Status

Fourth status alongside DONE, DONE_WITH_CONCERNS, BLOCKED:

```
BLOCKED_SCOPE: Cannot satisfy spec change within authorized symbols.

Protected symbol requiring modification: RetryConfig
Reason: Spec now requires calculate_delay to return tuple[float, int].
        RetryConfig must add an include_attempt field.
Requested additions: [RetryConfig]
Minimal change description: Add include_attempt: bool = False field.
```

### Orchestrator Escalation Flow

```
Builder returns BLOCKED_SCOPE
    |
Orchestrator parses structured report
    |
Architect Review (Stage A, controlling session):
    |-- reads BLOCKED_SCOPE report
    |-- reads spec diff
    |-- reads requested symbol's name + type (tree-sitter, not body)
    |-- runs ripple-check on parent spec
    |
Three outcomes:
    |-- APPROVE: update affected_symbols, re-dispatch Builder
    |-- REDIRECT: Builder's interpretation is wrong, add constraint note, re-dispatch
    +-- ESCALATE: surface to user for decision
```

### Auto-Approve vs Escalate Decision

The Architect auto-approves when:
- Requested symbol is in the same file (internal scope)
- Change is additive (new field, new method) not destructive (rename/removal)
- `ripple-check` shows no downstream dependents affected

The Architect escalates to user when:
- Symbol is referenced in other specs' `depends-on` lists
- Change is destructive (removes or renames a public interface)
- `ripple-check` shows downstream files would become stale

### Scope Escalation Metadata

Preserved in concrete spec frontmatter for triage summary:
```yaml
scope_escalation:
  symbol: RetryConfig
  reason: "Return type change in calculate_delay requires new config field"
  approved_by: architect
```

Auto-approved escalations appear in the triage summary as a single line:
```
Scope widened: +RetryConfig (return type change required by calculate_delay)
```

### Iteration Budget (Complete)

```
Builder attempt 1
    -> DONE -> Surgicality Linter
                  -> PASS -> merge
                  -> FAIL -> retry with violation report
Builder attempt 2 (linter retry)
    -> DONE -> Surgicality Linter
                  -> PASS -> merge
                  -> FAIL -> auto-escalate to BLOCKED_SCOPE
    -> BLOCKED_SCOPE -> Architect review
                          -> APPROVE -> re-dispatch (attempt 3)
                          -> REDIRECT -> re-dispatch (attempt 3)
                          -> ESCALATE -> user decides
Builder attempt 3 (post-escalation)
    -> DONE -> Surgicality Linter -> PASS -> merge
    -> Any failure -> BLOCKED (user decides)
```

Maximum 3 Builder dispatches per file per sync. Matches existing convergence budget.

---

## 6. Triage Summary + --refactor Flag

### Triage Summary

Generated by the Orchestrator from Linter output. No LLM involved -- pure string formatting from ground truth.

**Surgical sync:**
```
Surgical sync: src/retry.py
  Modified: calculate_delay, retry (2 symbols)
  Preserved: RetryConfig, MaxRetriesExceeded, T (3 symbols)
  Imports: +1 added (typing.Tuple)
```

**With scope escalation:**
```
Surgical sync: src/retry.py
  Scope widened: +RetryConfig (return type change required by calculate_delay)
  Modified: calculate_delay, retry, RetryConfig (3 symbols)
  Preserved: MaxRetriesExceeded, T (2 symbols)
```

**Full regeneration:**
```
Full regeneration: src/retry.py
  Mode: --refactor (structural optimization requested)
  Symbols: 4 written
```

### --refactor Flag

Added to `/unslop:sync` and `/unslop:generate`. Bypasses surgical mode entirely:

1. Intent Lock fires normally
2. Stage A (Architect) runs normally
3. Stage A.2 (Strategist) runs with directive: "Ignore existing implementation structure"
4. Stage B (Builder) receives specs but NO Existing Code, NO Spec Diff, NO Affected Symbols
5. Surgicality Linter is skipped
6. Identical to current v0.15.0 full-regen behavior

`--refactor` is the opt-out from surgical mode, not a new feature. The default shifts from full-regen to surgical; `--refactor` restores the old behavior.

### BLOCKED Hint

When surgical sync exhausts all 3 attempts:
```
BLOCKED: src/retry.py -- surgical sync exhausted after 3 attempts.

The spec change may require structural reorganization beyond symbol-level
patching. Consider:
  - /unslop:sync src/retry.py --refactor  (full regeneration)
  - Review the spec for decomposition opportunities
```

---

## Modified File Handling

When the Orchestrator detects `modified` state (user hand-edited the code) before a surgical sync:

```
Conflict: src/retry.py has manual edits (modified state).
The spec also changed. Choose:
  [a] Overwrite -- discard manual edits, regenerate from spec
  [b] Absorb -- incorporate manual edits into the spec first, then regenerate
  [c] Skip -- leave this file alone for now
```

Option (b) routes to `/unslop:change`. The Builder never sees a `modified` file without the user's explicit decision.

---

## Implementation Plan (Vertical Slice -- Approach 3)

Validated against `stress-tests/jitter/src/retry.py` end to end.

### PR #1: Symbol-Block Splitter + Normalization Engine

- New module: `unslop/scripts/surgical/splitter.py`
- Tree-sitter integration: parse file, extract top-level symbols
- Normalization functions for whitespace/newline handling
- Tests against `stress-tests/jitter/src/retry.py` (4 symbols + imports + constants)
- Language support: Python, JS/TS, Go

### PR #2: Spec-Diff Parser + Architect affected_symbols Extraction

- New module: `unslop/scripts/surgical/spec_diff.py`
- Section-level markdown diff (old spec via `git show`, new spec from disk)
- Orchestrator command: `spec-diff <spec_path>` for debugging
- Update Stage A.2 instructions to produce `affected_symbols` in concrete spec frontmatter
- Test: modify `retry.py.spec.md` Behavior section, verify affected symbols list

### PR #3: Surgicality Linter + Builder Prompt + BLOCKED_SCOPE Protocol

- New module: `unslop/scripts/surgical/linter.py`
- Linter algorithm: parse both files, compare non-affected blocks
- Update `skills/generation/SKILL.md`: Surgical Context blocks, BLOCKED_SCOPE status
- Update sync/generate commands: escalation loop, iteration budget
- Integration test: one-line spec change to `retry.py`, verify minimal diff
- Integration test: Builder drift triggers rejection and retry

### PR #4: Generalization + Edge Cases

- Multi-target surgical sync (parallel Builders, each with own affected_symbols)
- Unit spec handling (multiple files under one spec)
- Testless takeover compatibility (surgical mode skipped for first-gen)
- `--refactor` flag implementation
- Modified file pre-flight check (overwrite/absorb/skip prompt)

---

## Dependency Map

```
PR #1 (Splitter)
    |
    v
PR #2 (Spec-Diff + affected_symbols)
    |
    v
PR #3 (Linter + Builder Prompt + BLOCKED_SCOPE)
    |
    v
PR #4 (Generalization)
```

Strictly sequential. Each PR builds on the prior one's infrastructure.
