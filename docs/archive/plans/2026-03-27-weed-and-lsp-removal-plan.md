# Weed Command + LSP/AST Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove mechanical drift detection (LSP + AST symbol audit) and add `/unslop:weed` as the LLM-native replacement for intent drift detection.

**Architecture:** Part 1 removes dead code (lsp_queries.py, symbol audit functions, MCP tools, CLI subcommands, skill references). Part 2 adds a new command (`weed.md`) and triage routing. No new Python code -- weed is a prompt-only command that uses the model's judgment.

**Tech Stack:** Python 3.8+, pytest, markdown commands/skills

---

## File Structure

| File | Change |
|---|---|
| `unslop/scripts/validation/lsp_queries.py` | Delete entirely |
| `tests/test_lsp_queries.py` | Delete entirely |
| `unslop/scripts/validation/symbol_audit.py` | Rename to `spec_diff.py`, keep only `compute_spec_diff` + `_parse_md_sections` |
| `tests/test_symbol_audit.py` | Rename to `test_spec_diff.py`, keep only 4 `test_spec_diff_*` tests |
| `unslop/scripts/orchestrator.py` | Remove symbol audit imports/re-exports/CLI subcommands |
| `unslop/scripts/mcp_server.py` | Remove `unslop_symbol_audit` + `unslop_check_drift` tools |
| `tests/test_mcp_server.py` | Remove symbol_audit + check_drift tests |
| `unslop/skills/generation/SKILL.md` | Replace LSP/symbol audit refs with weed note |
| `unslop/skills/takeover/SKILL.md` | Remove `get_symbol_manifest()` references |
| `unslop/commands/init.md` | Remove validation/ placeholder reference |
| `unslop/commands/weed.md` | New -- the `/unslop:weed` command |
| `unslop/skills/triage/SKILL.md` | Add weed routing section |
| `unslop/.claude-plugin/plugin.json` | Version bump |
| `docs/superpowers/specs/2026-03-24-lsp-semantic-layer-design.md` | Mark as superseded |
| `docs/superpowers/plans/2026-03-24-lsp-semantic-layer-plan.md` | Mark as superseded |

---

### Task 1: Delete LSP queries module

**Files:**
- Delete: `unslop/scripts/validation/lsp_queries.py`
- Delete: `tests/test_lsp_queries.py`
- Modify: `unslop/scripts/orchestrator.py`

- [ ] **Step 1: Remove LSP imports and re-exports from orchestrator**

In `unslop/scripts/orchestrator.py`, remove the import line:
```python
from .validation.lsp_queries import SymbolInfo, SymbolManifest, get_symbol_manifest
```

And remove these from the `__all__`-style list:
```python
    "SymbolInfo",
    "SymbolManifest",
    "get_symbol_manifest",
```

- [ ] **Step 2: Delete the files**

```bash
cd /home/lewdwig/git/unslop
git rm unslop/scripts/validation/lsp_queries.py tests/test_lsp_queries.py
```

- [ ] **Step 3: Run tests to verify nothing breaks**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass (lsp_queries was not imported by any other test or module besides orchestrator)

- [ ] **Step 4: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/orchestrator.py
git commit -m "feat: remove LSP semantic query layer (lsp_queries.py)"
```

---

### Task 2: Reduce symbol_audit.py to spec_diff.py

**Files:**
- Rename: `unslop/scripts/validation/symbol_audit.py` -> `unslop/scripts/validation/spec_diff.py`
- Rename: `tests/test_symbol_audit.py` -> `tests/test_spec_diff.py`
- Modify: `unslop/scripts/orchestrator.py`

- [ ] **Step 1: Create the reduced spec_diff.py**

Read `unslop/scripts/validation/symbol_audit.py`. Create `unslop/scripts/validation/spec_diff.py` containing ONLY these two functions (copy verbatim from the original):
- `_parse_md_sections(content: str) -> dict[str, str]`
- `compute_spec_diff(old_spec: str, new_spec: str) -> dict`

Include the necessary imports at the top:
```python
"""Spec section diffing for surgical mode."""

from __future__ import annotations


def _parse_md_sections(content: str) -> dict[str, str]:
    # ... copy from original ...


def compute_spec_diff(old_spec: str, new_spec: str) -> dict:
    # ... copy from original ...
```

- [ ] **Step 2: Create reduced test_spec_diff.py**

Read `tests/test_symbol_audit.py`. Create `tests/test_spec_diff.py` containing ONLY the 4 spec_diff tests:
- `test_spec_diff_changed_section`
- `test_spec_diff_no_change`
- `test_spec_diff_new_section`
- `test_spec_diff_removed_section`

Update the import at the top of the test file from:
```python
from unslop.scripts.orchestrator import audit_symbols, check_drift, compute_spec_diff
```
to:
```python
from unslop.scripts.orchestrator import compute_spec_diff
```

- [ ] **Step 3: Update orchestrator imports**

In `unslop/scripts/orchestrator.py`, change:
```python
from .validation.symbol_audit import audit_symbols, check_drift, compute_spec_diff
```
to:
```python
from .validation.spec_diff import compute_spec_diff
```

Remove from the `__all__`-style list:
```python
    "audit_symbols",
    "check_drift",
```
Keep:
```python
    "compute_spec_diff",
```

- [ ] **Step 4: Remove CLI subcommands for symbol-audit and check-drift**

In `unslop/scripts/orchestrator.py`, in the `main()` function:
- Remove the `elif command == "symbol-audit":` block (including all its contents)
- Remove the `elif command == "check-drift":` block (including all its contents)
- Keep the `elif command == "spec-diff":` block
- Update the usage string at the top of `main()` to remove `symbol-audit` and `check-drift`

- [ ] **Step 5: Delete the old files**

```bash
cd /home/lewdwig/git/unslop
git rm unslop/scripts/validation/symbol_audit.py tests/test_symbol_audit.py
```

- [ ] **Step 6: Run tests**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_spec_diff.py -v`
Expected: 4 tests pass

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass (count will drop -- the 34 removed audit/drift tests are gone)

- [ ] **Step 7: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/validation/spec_diff.py tests/test_spec_diff.py unslop/scripts/orchestrator.py
git commit -m "feat: reduce symbol_audit.py to spec_diff.py (keep only compute_spec_diff)"
```

---

### Task 3: Remove symbol audit + drift from MCP server

**Files:**
- Modify: `unslop/scripts/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Remove tools from MCP server**

In `unslop/scripts/mcp_server.py`:
- Remove the import: `from .validation.symbol_audit import audit_symbols, check_drift`
- Remove the entire `unslop_symbol_audit` function and its `@_tool` decorator
- Remove the entire `unslop_check_drift` function and its `@_tool` decorator
- This reduces the server from 10 tools to 8 tools

- [ ] **Step 2: Remove tests**

In `tests/test_mcp_server.py`:
- Remove the imports: `unslop_symbol_audit`, `unslop_check_drift`
- Remove `test_symbol_audit_error_on_missing`
- Remove `test_check_drift_error_on_missing`

- [ ] **Step 3: Run tests**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_mcp_server.py -v`
Expected: 12 tests pass (down from 14)

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: remove symbol_audit + check_drift from MCP server (8 tools remain)"
```

---

### Task 4: Update skills and commands (remove LSP/audit references)

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`
- Modify: `unslop/skills/takeover/SKILL.md`
- Modify: `unslop/commands/init.md`

- [ ] **Step 1: Update generation skill**

In `unslop/skills/generation/SKILL.md`:
- Find all references to LSP, symbol audit, drift check, `get_symbol_manifest()`. Replace with a note that `/unslop:weed` is the mechanism for drift detection.
- Specifically look for references around: "symbol audit (testless path)", "using `get_symbol_manifest()` from `lsp_queries.py`", "Run symbol audit (Step 4b)" and replace or remove them.
- Where the skill describes post-generation validation with symbol audit, replace with: "For intent drift detection after generation, use `/unslop:weed` to compare spec intent against generated code."

- [ ] **Step 2: Update takeover skill**

In `unslop/skills/takeover/SKILL.md`:
- Find references to `get_symbol_manifest()` for public symbol counting in the pre-flight analysis (Step 0a).
- Replace with: "Public symbol count -- count by reading the file (grep for exported functions, public types, module-level constants)."
- Find and remove any references to LSP semantic query layer or drift check.

- [ ] **Step 3: Update init command**

In `unslop/commands/init.md`:
- Find the reference to `validation/` directory as a placeholder for symbol_audit
- Update to reflect that `validation/` contains `spec_diff.py` (spec section comparison for surgical mode)

- [ ] **Step 4: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/generation/SKILL.md unslop/skills/takeover/SKILL.md unslop/commands/init.md
git commit -m "docs: remove LSP/symbol audit references from skills and commands"
```

---

### Task 5: Mark old design docs as superseded

**Files:**
- Modify: `docs/superpowers/specs/2026-03-24-lsp-semantic-layer-design.md`
- Modify: `docs/superpowers/plans/2026-03-24-lsp-semantic-layer-plan.md`

- [ ] **Step 1: Add superseded notice to both files**

At the top of each file, add:

```markdown
> **SUPERSEDED** by `2026-03-27-weed-and-lsp-removal-design.md`. The LSP semantic query layer and AST-based symbol audit have been removed. Drift detection is now LLM-native via `/unslop:weed`.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add docs/superpowers/specs/2026-03-24-lsp-semantic-layer-design.md docs/superpowers/plans/2026-03-24-lsp-semantic-layer-plan.md
git commit -m "docs: mark LSP semantic layer design/plan as superseded"
```

---

### Task 6: Create `/unslop:weed` command

**Files:**
- Create: `unslop/commands/weed.md`

- [ ] **Step 1: Create the weed command**

Create `unslop/commands/weed.md` with the full content from the design spec's Part 2 (sections Phase 1-4 and Post-Remediation Summary). The command is prompt-only -- no Python scripts, no subagents. It reads files and uses the model's judgment.

```markdown
---
description: Detect intent drift between specs and code. Surfaces meaningful discrepancies and offers per-finding remediation.
argument-hint: "[file-path] [--all]"
---

**Parse arguments:** `$ARGUMENTS` may contain a file path and optional flags.

- If a file path is provided: target that single file
- If `--all` is provided: target all managed files regardless of classification
- If no arguments: target files classified as `modified` (code edited directly, spec unchanged)

**0. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

**1. Target Selection**

If a file path argument is provided, validate it is a managed file (has `@unslop-managed` header and a corresponding `*.spec.md`). If not:

> "This file is not under spec management. Use `/unslop:takeover` first."

If no argument:
- Scan for all managed files using the same mechanism as `/unslop:status`.
- Default: select files classified as `modified` (code edited directly, spec unchanged).
- With `--all`: select all managed files regardless of classification.

If no targets found:

> "No files to weed."

**2. Analysis**

For each target file:

1. Read the spec file (abstract spec `*.spec.md`).
2. Read the concrete spec (`*.impl.md`) if it exists.
3. Read the managed file (the generated/edited code).
4. Compare spec intent against code behavior and identify **concerns**.

A concern is a meaningful discrepancy between what the spec says and what the code does. Not a style issue. Not a naming preference. A place where behavior has drifted from intent.

Each concern has:

| Field | Description |
|-------|-------------|
| **title** | Short description, e.g., "Unbounded retry loop" |
| **direction** | `spec-behind` (code is right, spec incomplete) or `code-drifted` (spec is right, code diverged) |
| **spec-reference** | Which section(s) of the spec are relevant |
| **code-reference** | File path + line range |
| **rationale** | Why this is a meaningful discrepancy |

**Direction heuristic:** If the file is `modified` (code edited directly), lean toward `spec-behind` -- the human edit was probably intentional. If the file is `fresh` (generated), lean toward `code-drifted` -- the generator probably missed something. Override with your own judgment if the heuristic doesn't fit.

**3. Report**

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

If no concerns: "No drift detected across N files."

**4. Remediation**

Walk through each finding one at a time.

**If `spec-behind`:**
> Concern N: "<title>" -- spec should document <what>.
> (u) Update spec to match code  |  (s) Skip  |  (q) Quit remediation

If the user chooses "update spec": edit the spec file directly. Add or modify the relevant section to reflect what the code actually does. The file will show as `stale` in `/unslop:status` (spec changed, code unchanged) -- but since the spec now matches the code, the next sync will be a no-op or trivially confirmed.

**If `code-drifted`:**
> Concern N: "<title>" -- code should <what> per spec.
> (r) Regenerate to match spec  |  (s) Skip  |  (q) Quit remediation

If the user chooses "regenerate": mark the file for sync. Do NOT regenerate inline. Display a reminder at the end: "N files queued for sync -- run `/unslop:sync` to regenerate."

**Quit** stops remediation but keeps the report visible. Unanswered findings are simply skipped.

**5. Post-Remediation Summary**

```
Remediation complete:
  2 specs updated (src/auth/handler.py.spec.md, src/auth/tokens.py.spec.md)
  1 file queued for sync (src/auth/tokens.py)
  1 skipped

Run /unslop:sync to regenerate queued files.
```
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/commands/weed.md
git commit -m "feat: add /unslop:weed command for LLM-native drift detection"
```

---

### Task 7: Add weed routing to triage skill

**Files:**
- Modify: `unslop/skills/triage/SKILL.md`

- [ ] **Step 1: Add weed routing section**

In `unslop/skills/triage/SKILL.md`, find an appropriate location (near the staleness/status routing) and add:

```markdown
## The Drift Detection Prompt

If the user suspects that code has drifted from spec intent, or wants to audit whether generated code still matches what the spec describes, route to weed.

**Pattern:** "What drifted?", "Is the code still matching the spec?", "Check for drift", "Audit this file against its spec", "Weed out drift"
**Route:** `/unslop:weed` (all modified) or `/unslop:weed <file>` (targeted)

**Key distinction from /unslop:status:** Status tells you *that* something changed (hash mismatch). Weed tells you *what* drifted and *whether the spec or the code is wrong*. If the user already knows a file is modified and wants to understand the drift, route to weed, not status.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/triage/SKILL.md
git commit -m "feat: add weed routing to triage skill"
```

---

### Task 8: Version bump

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version**

Change version from `0.32.0` to `0.33.0`.

- [ ] **Step 2: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.33.0"
```
