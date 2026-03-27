# Remove Mechanical Drift Detection, Add `/unslop:weed`

**Date:** 2026-03-27
**Status:** Draft
**Replaces:** 2026-03-24-lsp-semantic-layer-design.md

## Motivation

The LSP semantic query layer and the Python AST-based symbol audit both attempt to detect drift mechanically -- by comparing symbol names, signatures, and source text between files. This approach has two fundamental problems:

1. **It detects structural drift, not intent drift.** A function can have the same name, same signature, and completely different behavior. The spec says "retry with backoff, max 3 attempts" and the code retries with backoff but has no cap -- symbol audit sees nothing wrong.

2. **It requires language-specific tooling.** The LSP layer was built to extend symbol audit beyond Python. But every language needs its own server, its own setup, its own fallback path. This is a tooling treadmill that grows with every language the plugin supports.

The correct approach is LLM-native: the model reads the spec and the code and applies judgment. Intent drift is a judgment problem. If the plugin cannot detect drift without recourse to language servers or AST parsers, that is a gap in the specification language, not a gap in tooling.

## Part 1: Removal -- Mechanical Drift Detection

### What Gets Removed

**LSP semantic query layer (entire module):**
- `scripts/validation/lsp_queries.py`
- `tests/test_lsp_queries.py`

**AST-based symbol audit (functions, not file):**

From `scripts/validation/symbol_audit.py`, remove:
- `_extract_public_symbols()`
- `audit_symbols()`
- `_extract_symbol_sources()`
- `_normalize_source()`
- `_parse_affected_tag()`
- `_manifest_to_source_map()`
- `check_drift()`
- `main()` CLI entry point

Keep in `symbol_audit.py`:
- `compute_spec_diff()` -- pure markdown section comparison, no code analysis
- `_parse_md_sections()` -- helper for `compute_spec_diff`

Rename the file to `spec_diff.py` to reflect its reduced scope.

**Orchestrator (`scripts/orchestrator.py`):**
- Remove imports/re-exports: `audit_symbols`, `check_drift`, `SymbolInfo`, `SymbolManifest`, `get_symbol_manifest`
- Remove CLI dispatch for `symbol-audit` and `check-drift` subcommands
- Keep `compute_spec_diff` import and dispatch

**MCP server (`scripts/mcp_server.py`):**
- Remove `unslop_symbol_audit` tool
- Remove `unslop_check_drift` tool

**Tests (`tests/test_symbol_audit.py`):**
- Remove all `audit_symbols` and `check_drift` test cases
- Keep `compute_spec_diff` tests
- Rename file to `test_spec_diff.py`

**Skills:**
- `skills/generation/SKILL.md` -- remove references to LSP, symbol audit, drift check in post-generation validation. Replace with a note that `/unslop:weed` is the mechanism for drift detection.
- `skills/takeover/SKILL.md` -- remove references to `get_symbol_manifest()` for public symbol counting.

**Commands:**
- `commands/init.md` -- remove the `validation/` placeholder reference if it only exists for symbol_audit.

**Design docs:**
- `docs/superpowers/specs/2026-03-24-lsp-semantic-layer-design.md` -- mark as superseded
- `docs/superpowers/plans/2026-03-24-lsp-semantic-layer-plan.md` -- mark as superseded

### What Stays Unchanged

- Hash-based freshness system (`scripts/freshness/checker.py`) -- 4-state classification (fresh/modified/stale/conflict) is orthogonal. It answers "did things change?" not "did intent drift?"
- `compute_spec_diff()` -- markdown-level section comparison, used to show which spec sections changed during hardening
- Transitive staleness, ghost staleness, principles-hash -- all hash-based, all stay

## Part 2: `/unslop:weed` -- LLM-Native Drift Detection

### Purpose

Compare what a spec *intends* against what the code *actually does*. Surface meaningful discrepancies as concerns. Offer per-finding remediation.

### Invocation

```
/unslop:weed                     # all modified files
/unslop:weed src/retry.py        # single file
/unslop:weed --all               # all managed files (modified + fresh)
```

### Phase 1: Target Selection

1. Check `.unslop/` exists.
2. If a file path argument is provided, validate it is a managed file (has `@unslop-managed` header and a corresponding `.spec.md`). Error if not.
3. If no argument:
   - Scan for all managed files using the same mechanism as `/unslop:status`.
   - Default: select files classified as `modified` (code edited directly, spec unchanged).
   - With `--all`: select all managed files regardless of classification.
4. If no targets found, report "No files to weed." and exit.

### Phase 2: Analysis

For each target file:

1. Read the spec file (abstract spec `*.spec.md`).
2. Read the concrete spec (`*.impl.md`) if it exists.
3. Read the managed file (the generated/edited code).
4. Prompt the model to compare spec intent against code behavior and identify **concerns**.

A concern is a meaningful discrepancy between what the spec says and what the code does. Not a style issue. Not a naming preference. A place where behavior has drifted from intent.

Each concern has:

| Field | Description |
|-------|-------------|
| **title** | Short description, e.g., "Unbounded retry loop" |
| **direction** | `spec-behind` (code is right, spec incomplete) or `code-drifted` (spec is right, code diverged) |
| **spec-reference** | Which section(s) of the spec are relevant |
| **code-reference** | File path + line range |
| **rationale** | Why this is a meaningful discrepancy |

**Direction heuristic:** If the file is `modified` (code edited directly), lean toward `spec-behind` -- the human edit was probably intentional. If the file is `fresh` (generated), lean toward `code-drifted` -- the generator probably missed something. The model can override this heuristic with its own judgment.

### Phase 3: Report

Display all findings grouped by file, all at once, before any remediation:

```
Weed report: 2 files, 4 concerns

  src/auth/handler.py  (modified)
    1. [spec-behind] Unbounded retry loop
       Spec ## Retry Policy says "retry with backoff" but doesn't cap retries.
       Code caps at 5 (handler.py:42-58). Spec should document the cap.

    2. [code-drifted] Silent exception swallowing
       Spec ## Error Handling says "propagate all errors to caller."
       Code catches ConnectionError and returns None (handler.py:61-65).

  src/auth/tokens.py  (modified)
    3. [spec-behind] Token refresh adds jitter
       Spec ## Refresh says "refresh token before expiry."
       Code adds 0-5s jitter to avoid thundering herd (tokens.py:88-94).
       Spec should document the jitter strategy.

    4. [code-drifted] Missing token revocation
       Spec ## Lifecycle says "tokens can be revoked."
       Code has no revocation path (tokens.py).
```

If no concerns are found: "No drift detected across N files."

### Phase 4: Remediation

Walk through each finding one at a time:

For each concern, present the finding and ask:

**If `spec-behind`:**
> Concern 1: "Unbounded retry loop" -- spec should document the retry cap.
> (u) Update spec to match code  |  (s) Skip  |  (q) Quit remediation

If the user chooses "update spec": edit the spec file directly. Add or modify the relevant section to reflect what the code actually does. The file will then show as `stale` in `/unslop:status` (spec changed, code unchanged) -- but since the spec now matches the code, the next sync will be a no-op or trivially confirmed.

**If `code-drifted`:**
> Concern 2: "Silent exception swallowing" -- code should propagate errors per spec.
> (r) Regenerate to match spec  |  (s) Skip  |  (q) Quit remediation

If the user chooses "regenerate": mark the file for sync. Do NOT regenerate inline. Display a reminder at the end: "N files queued for sync -- run `/unslop:sync` to regenerate."

**Quit** stops remediation but keeps the report visible. Unanswered findings are simply skipped.

### Post-Remediation Summary

```
Remediation complete:
  2 specs updated (src/auth/handler.py.spec.md, src/auth/tokens.py.spec.md)
  1 file queued for sync (src/auth/tokens.py)
  1 skipped

Run /unslop:sync to regenerate queued files.
```

## Part 3: Triage Integration

Add a new routing section to `skills/triage/SKILL.md`:

```markdown
## The Drift Detection Prompt

If the user suspects that code has drifted from spec intent, or wants to
audit whether generated code still matches what the spec describes, route
to weed.

**Pattern:** "What drifted?", "Is the code still matching the spec?",
"Check for drift", "Audit this file against its spec", "Weed out drift"
**Route:** `/unslop:weed` (all modified) or `/unslop:weed <file>` (targeted)

**Key distinction from /unslop:status:** Status tells you *that* something
changed (hash mismatch). Weed tells you *what* drifted and *whether the
spec or the code is wrong*. If the user already knows a file is modified
and wants to understand the drift, route to weed, not status.
```

## What This Does NOT Do

- **No new Python scripts.** Weed is a command (prompt) that uses the model's judgment directly. The analysis happens in the model's context, not in a script.
- **No language-specific analysis.** Works for any language the model can read. Python, Go, Rust, TypeScript -- all the same mechanism.
- **No changes to the hash-based freshness system.** Weed is orthogonal to staleness classification. Staleness answers "did things change?" Weed answers "did intent drift?"
- **No inline regeneration.** Weed edits specs and queues syncs. It does not generate code.

## Design Decisions

**Why per-concern, not per-symbol?** Symbol-level drift detection is what the AST audit already did, and it missed behavioral drift entirely. A concern is a judgment call: "here's something that matters." The model may surface concerns that span multiple symbols or that involve behavior no symbol boundary captures.

**Why direction heuristic?** In a `modified` file, the human edited the code intentionally -- the spec is more likely to be the stale artifact. In a `fresh` file, the generator produced the code -- the code is more likely to be wrong. This heuristic gives the model a sensible default while allowing override.

**Why not auto-remediate?** Drift findings require human judgment about which side is correct. Auto-remediation would either always trust the code (wrong) or always trust the spec (also wrong). The walk-through gives the user control per finding.

**Why edit specs directly instead of routing through `/unslop:change`?** Change requests are for *planned* changes -- "I want X to behave differently." Weed findings are *discovered* discrepancies -- "X already behaves differently, the spec should acknowledge it." Direct spec edits are simpler and more honest for this case.
