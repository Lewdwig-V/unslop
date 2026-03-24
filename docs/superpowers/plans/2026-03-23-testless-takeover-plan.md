# Testless Takeover (Milestone N) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable `/unslop:takeover` to bring files without tests under spec management by chaining the existing takeover pipeline into the adversarial quality pipeline.

**Architecture:** The takeover skill gains a "testless path" that automatically routes through the adversarial pipeline when no tests are found. The Architect performs a Double-Lift (Code -> impl.md -> spec.md + behaviour.yaml) with legacy smell detection, the Builder generates with `test_policy: "skip"`, a Symbol Audit validates structural integrity, then the Mason/Saboteur pipeline generates and validates tests. Convergence crosses three stages (Architect/Builder/Mason) with an entropy threshold to prevent oscillation.

**Tech Stack:** Python 3.8+ (symbol audit script), Markdown (skill/command files), YAML (behaviour DSL)

**Spec:** `docs/superpowers/specs/2026-03-23-testless-takeover-design.md`

**Note:** The spec's Scope of Changes section (line 284) references `test_policy: "snapshot"` -- this is stale from before the snapshot lockdown was killed during red-teaming. This plan uses `test_policy: "skip"` as described in the spec's Phase 2 body (line 100-102), which is the correct post-red-team design.

---

## File Structure

### New files
- `unslop/scripts/validation/symbol_audit.py` -- AST-level public symbol comparison (original vs generated)
- `tests/test_symbol_audit.py` -- Tests for symbol audit

### Modified files
- `unslop/scripts/orchestrator.py` -- Re-export symbol_audit, add `symbol-audit` CLI subcommand
- `unslop/scripts/validation/__init__.py` -- Package docstring update
- `unslop/skills/takeover/SKILL.md` -- Major: Double-Lift, legacy smells, behaviour.yaml, testless routing, adversarial wiring, convergence rewrite
- `unslop/commands/takeover.md` -- Detect testless, add `--skip-adversarial` flag
- `unslop/skills/generation/SKILL.md` -- Add `test_policy: "skip"` to policy table
- `unslop/skills/adversarial/SKILL.md` -- Add takeover mode, entropy threshold, radical hardening
- `unslop/commands/init.md` -- Add `entropy_threshold` to config template
- `unslop/.claude-plugin/plugin.json` -- Version bump to 0.14.0

---

## Task 1: Symbol Audit Script + Tests

The only new Python code. Must be implemented TDD-style and pass independently before any skill changes.

**Files:**
- Create: `unslop/scripts/validation/symbol_audit.py`
- Create: `tests/test_symbol_audit.py`
- Modify: `unslop/scripts/validation/__init__.py`
- Modify: `unslop/scripts/orchestrator.py`

### Step 1: Write the test file

- [ ] **Step 1a: Create test_symbol_audit.py with core tests**

```python
# tests/test_symbol_audit.py
import os
import sys
import tempfile

from unslop.scripts.validation.symbol_audit import audit_symbols


def test_identical_files_pass():
    """Same public symbols -> PASS."""
    code = "def foo(): pass\ndef bar(): pass\nclass Baz: pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(code)
        gen.write(code)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "pass"
    assert result["missing"] == []
    assert result["unexpected"] == []
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_missing_symbol_fails():
    """Generated code drops a public function -> FAIL."""
    original = "def foo(): pass\ndef bar(): pass\n"
    generated = "def foo(): pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "fail"
    assert "bar" in result["missing"]
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_removed_symbols_excluded():
    """Symbols listed as removed are not expected."""
    original = "def foo(): pass\ndef deprecated(): pass\n"
    generated = "def foo(): pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name, removed=["deprecated"])
    assert result["status"] == "pass"
    assert result["missing"] == []
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_unexpected_symbol_warns():
    """Generated code adds a symbol not in original or spec -> WARN."""
    original = "def foo(): pass\n"
    generated = "def foo(): pass\ndef helper(): pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "pass"  # unexpected is a warning, not failure
    assert "helper" in result["unexpected"]
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_private_symbols_ignored():
    """Symbols starting with _ are not tracked."""
    original = "def foo(): pass\ndef _internal(): pass\n"
    generated = "def foo(): pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "pass"
    assert result["missing"] == []
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_class_symbols_tracked():
    """Classes are public symbols."""
    original = "class Foo: pass\nclass Bar: pass\n"
    generated = "class Foo: pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "fail"
    assert "Bar" in result["missing"]
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_constants_tracked():
    """Module-level UPPER_CASE assignments are public symbols."""
    original = "MAX_RETRIES = 3\ndef foo(): pass\n"
    generated = "def foo(): pass\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write(original)
        gen.write(generated)
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "fail"
    assert "MAX_RETRIES" in result["missing"]
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_nonpython_passthrough():
    """Non-Python files always pass (audit is Python-only for now)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as gen:
        orig.write("export function foo() {}")
        gen.write("export function foo() {}")
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "pass"
    assert result["skipped"] is True
    os.unlink(orig.name)
    os.unlink(gen.name)


def test_syntax_error_in_original():
    """Unparseable original -> error result, not crash."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write("def broken(")
        gen.write("def foo(): pass\n")
        orig.flush()
        gen.flush()
        result = audit_symbols(orig.name, gen.name)
    assert result["status"] == "error"
    assert "original" in result["hint"].lower()
    os.unlink(orig.name)
    os.unlink(gen.name)
```

- [ ] **Step 1b: Run tests to verify they fail**

Run: `pytest tests/test_symbol_audit.py -v`
Expected: ImportError -- `symbol_audit` module doesn't exist yet

### Step 2: Implement symbol_audit.py

- [ ] **Step 2a: Create the symbol audit module**

```python
# unslop/scripts/validation/symbol_audit.py
"""Symbol audit: AST-level check that public symbols survive generation."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _extract_public_symbols(source: str) -> set[str]:
    """Extract public symbol names from Python source.

    Tracks: top-level functions, classes, and UPPER_CASE assignments.
    Ignores: names starting with _ (private by convention).
    """
    tree = ast.parse(source)
    symbols = set()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.add(target.id)

    return symbols


def audit_symbols(
    original_path: str,
    generated_path: str,
    removed: list[str] | None = None,
) -> dict:
    """Compare public symbols between original and generated files.

    Args:
        original_path: Path to the archived original file.
        generated_path: Path to the Builder's generated file.
        removed: Symbols explicitly removed (e.g., legacy smells).

    Returns:
        dict with: status ("pass"|"fail"|"error"), missing, unexpected,
        original_symbols, generated_symbols, skipped.
    """
    orig = Path(original_path)
    gen = Path(generated_path)

    # Non-Python files: skip audit (Python-only for now)
    if orig.suffix != ".py":
        return {"status": "pass", "skipped": True, "missing": [], "unexpected": []}

    removed_set = set(removed or [])

    # Parse original
    try:
        orig_source = orig.read_text(encoding="utf-8")
        orig_symbols = _extract_public_symbols(orig_source)
    except SyntaxError as e:
        return {
            "status": "error",
            "hint": f"Cannot parse original file: {e}",
            "missing": [],
            "unexpected": [],
        }
    except (OSError, UnicodeDecodeError) as e:
        return {
            "status": "error",
            "hint": f"Cannot read original file: {e}",
            "missing": [],
            "unexpected": [],
        }

    # Parse generated
    try:
        gen_source = gen.read_text(encoding="utf-8")
        gen_symbols = _extract_public_symbols(gen_source)
    except SyntaxError as e:
        return {
            "status": "error",
            "hint": f"Cannot parse generated file: {e}",
            "missing": [],
            "unexpected": [],
        }
    except (OSError, UnicodeDecodeError) as e:
        return {
            "status": "error",
            "hint": f"Cannot read generated file: {e}",
            "missing": [],
            "unexpected": [],
        }

    expected = orig_symbols - removed_set
    missing = sorted(expected - gen_symbols)
    unexpected = sorted(gen_symbols - orig_symbols - removed_set)

    status = "fail" if missing else "pass"

    return {
        "status": status,
        "missing": missing,
        "unexpected": unexpected,
        "original_symbols": sorted(orig_symbols),
        "generated_symbols": sorted(gen_symbols),
        "removed": sorted(removed_set),
        "skipped": False,
    }


def main():
    """CLI entry point: symbol-audit <original> <generated> [--removed s1,s2]."""
    if len(sys.argv) < 3:
        print("Usage: symbol_audit.py <original-path> <generated-path> [--removed s1,s2]", file=sys.stderr)
        sys.exit(1)

    original = sys.argv[1]
    generated = sys.argv[2]
    removed = []
    if "--removed" in sys.argv:
        idx = sys.argv.index("--removed")
        if idx + 1 < len(sys.argv):
            removed = sys.argv[idx + 1].split(",")

    result = audit_symbols(original, generated, removed=removed)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("pass",) else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2b: Update validation/__init__.py**

Replace the placeholder docstring:

```python
"""Validation modules: symbol audit for Milestone N testless takeover."""
```

- [ ] **Step 2c: Run tests**

Run: `pytest tests/test_symbol_audit.py -v`
Expected: All 9 tests PASS

### Step 3: Wire into orchestrator CLI

- [ ] **Step 3a: Add re-export and CLI subcommand to orchestrator.py**

In the re-exports section, add:

```python
from .validation.symbol_audit import audit_symbols
```

Add `"audit_symbols"` to `__all__`.

In `main()`, add a new `elif` branch after the `file-tree` command:

```python
elif command == "symbol-audit":
    if len(sys.argv) < 4:
        print("Usage: orchestrator.py symbol-audit <original> <generated> [--removed s1,s2]", file=sys.stderr)
        sys.exit(1)
    original = sys.argv[2]
    generated = sys.argv[3]
    removed = []
    if "--removed" in sys.argv:
        idx = sys.argv.index("--removed")
        if idx + 1 < len(sys.argv):
            removed = sys.argv[idx + 1].split(",")
    result = audit_symbols(original, generated, removed=removed)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("pass",) else 1)
```

Update the usage string to include `symbol-audit`.

- [ ] **Step 3b: Add CLI integration test**

Add to `tests/test_symbol_audit.py`:

```python
import subprocess

AUDIT_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts", "orchestrator.py")

def test_cli_symbol_audit():
    """CLI invocation returns JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as orig, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as gen:
        orig.write("def foo(): pass\ndef bar(): pass\n")
        gen.write("def foo(): pass\n")
        orig.flush()
        gen.flush()
        result = subprocess.run(
            [sys.executable, AUDIT_SCRIPT, "symbol-audit", orig.name, gen.name],
            capture_output=True, text=True,
        )
    assert result.returncode == 1
    import json
    data = json.loads(result.stdout)
    assert data["status"] == "fail"
    assert "bar" in data["missing"]
    os.unlink(orig.name)
    os.unlink(gen.name)
```

- [ ] **Step 3c: Run full test suite**

Run: `pytest tests/ -q`
Expected: 409 + ~10 new = ~419 tests PASS

- [ ] **Step 3d: Commit**

```
feat: add symbol audit script for testless takeover (Milestone N)
```

---

## Task 2: Add `test_policy: "skip"` to Generation Skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:202-205`

- [ ] **Step 1: Add "skip" to the test_policy table**

At line 205, after the `change (tactical)` entry, add:

```markdown
- **testless takeover:** `"Do NOT create, modify, or run test files. Report DONE based on successful code generation only. The adversarial pipeline will generate and validate tests separately."`
```

- [ ] **Step 2: Document what DONE means in skip mode**

After the test_policy table, add a note:

```markdown
**Note on `test_policy: "skip"` (testless takeover):** The Builder reports DONE after generating code that satisfies the spec. No tests are run. The calling pipeline (takeover) is responsible for running the Symbol Audit and adversarial pipeline as the quality gate. The Builder must NOT attempt to write tests -- the Mason writes them from the behaviour.yaml behind a Chinese Wall.

**Adversarial intensity tagging:** When testless takeover dispatches the Builder, the Architect tags the adversarial intensity based on file complexity:
- `adversarial: "full"` (default): Mason + Saboteur. For multi-function files, complex state, or tangled dependencies.
- `adversarial: "mason-only"`: Mason generates tests, Saboteur skipped. For single-function files with tight specs.
The user can override with `--full-adversarial`.
```

- [ ] **Step 3: Commit**

```
feat(generation): add test_policy "skip" for testless takeover
```

---

## Task 3: Add Config Fields to init.md

**Files:**
- Modify: `unslop/commands/init.md:36-46`

- [ ] **Step 1: Add adversarial config fields to config template**

In the config.json template, add after the `promote-threshold` field:

```json
  "adversarial_max_iterations": 3,
  "adversarial_max_iterations_note": "Maximum convergence iterations before requiring manual review",
  "mutation_tool": "builtin",
  "mutation_tool_note": "Mutation engine: 'mutmut' for full mutation testing, 'builtin' for lightweight AST mutator",
  "entropy_threshold": 0.05,
  "entropy_threshold_note": "Minimum mutation kill rate improvement per convergence iteration. Below this delta, the loop stalls and triggers radical spec hardening. Set to 0 to disable."
```

Note: `adversarial` (bool) and `adversarial_max_iterations` already exist in the adversarial skill docs but are not in the init config template. Add all three fields together.

- [ ] **Step 2: Commit**

```
feat(init): add entropy_threshold to config template
```

---

## Task 4: Rewrite Takeover Skill -- Testless Path

This is the largest task. The takeover skill gains the testless routing, Double-Lift with legacy smell detection, behaviour.yaml generation, Symbol Audit gate, adversarial pipeline wiring, and the three-stage convergence loop with entropy threshold.

**Files:**
- Modify: `unslop/skills/takeover/SKILL.md` (major rewrite of Steps 1, 2b, 4, 5, 6 + new steps)

- [ ] **Step 1: Rewrite Step 1 (Discover) -- testless routing**

Replace the current "stop and warn" block (lines 40-44) with automatic routing:

```markdown
**If no tests are found**, determine the takeover path:

If the project has adversarial mode enabled (`.unslop/config.json` has `"adversarial": true` or the user has not explicitly disabled it):

> "No tests found for this file. Routing to **testless takeover** -- the adversarial pipeline will generate and validate tests automatically.
>
> This adds a behaviour.yaml extraction step and uses the Mason/Saboteur pipeline as the quality gate instead of existing tests.
>
> Proceed? (y/n)"

If adversarial mode is not available, fall back to the existing warning:

> "No tests found. Takeover without tests means the spec is unvalidated. Proceed only with explicit user confirmation."

Track which path was taken: `testless_mode = true/false`. This controls downstream routing.
```

- [ ] **Step 2: Rewrite Step 2b (Raise to Abstract) -- add Double-Lift + behaviour.yaml**

After the existing Step 2b content, add the testless-specific extensions:

```markdown
### Step 2c: Generate Behaviour YAML (testless path only)

Skip this step if `testless_mode = false` (tests exist).

From the Concrete Spec and Abstract Spec, generate a `*.behaviour.yaml` file:

**Requirements:**
- At least one `given`/`when`/`then` constraint per public function
- `error` entries for every exception the code raises
- `invariant` entries for state consistency properties
- Must pass `validate_behaviour.py` structural validation

Use the multi-behaviour format if the file has multiple public functions.

**Legacy Smell Detection:**

Before writing the behaviour.yaml, cross-check every extracted behaviour against `.unslop/principles.md`:

For each constraint:
  If the constraint contradicts a project principle:
    Flag as `legacy_smell` in the behaviour.yaml
    Present to user: "Extracted behaviour '{constraint}' contradicts principle '{principle}'. Preserve or discard?"

Do NOT encode legacy smells as invariants unless the user explicitly overrides.

Example: If principles say "never retry on client errors (4xx)" but the code retries on 404, flag `"retry on 404"` as a legacy smell rather than encoding it as `given: "response.status == 404" then: "retry"`.

**Bias guard:** Present smells neutrally. Say "This behaviour contradicts principle X. Preserve or discard?" -- NOT "This is a bug, discard it?"

**Observable Behaviour Preservation (reinforced for testless path):**

The behaviour.yaml MUST reflect the original observable behaviour. Apply the observable test to every constraint: if two implementations produce different outputs for the same inputs, the choice is observable and must be pinned.

If the Architect wants to change an observable behaviour (e.g., upgrade half-jitter to full-jitter), the constraint must use the new value AND the spec must document the upgrade with rationale as a **Behavioural Upgrade**. Silent substitution is a spec defect. This is especially critical in testless mode because there are no existing tests to catch silent algorithmic changes.

Present the behaviour.yaml to the user alongside the abstract spec for joint approval.
```

- [ ] **Step 3: Rewrite Step 4 (Lower & Generate) -- add test_policy skip + Symbol Audit**

Replace the Builder dispatch section with:

```markdown
## Step 4: Lower & Generate (Stage A.2 + Stage B)

Use the **unslop/generation** skill's multi-stage execution model.

**CRITICAL: Takeover always uses full regeneration mode (Mode A). The Builder does NOT read the archived original.**

**Stage A.2 (Lowering):** The generation skill's Stage A.2 runs to derive a fresh Concrete Spec from the approved Abstract Spec. During takeover, the previously raised Concrete Spec (from Step 2) is available as reference.

**Stage B (Building):** Dispatch a Builder Agent with:
- test_policy: `"Write or extend tests as needed"` (if tests exist)
- test_policy: `"skip"` (if testless_mode = true)
- Mode A (full regeneration) -- always, no incremental for takeover
- The abstract spec path as the primary source of truth
- The concrete spec (from Stage A.2) as strategic guidance

### Step 4b: Symbol Audit (testless path only)

Skip if `testless_mode = false`.

After the Builder reports DONE, run the Symbol Audit before proceeding to the adversarial pipeline:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py symbol-audit <archive-path> <generated-path> [--removed <legacy-smell-symbols>]
```

Parse the JSON result:
- **pass**: Proceed to Step 5 (adversarial validation)
- **fail**: Report missing symbols to user. The Builder dropped public symbols that weren't listed as removed. Re-enter convergence with a diagnostic: "Symbol Audit failed: missing {symbols}. Enrich the spec to include these symbols or explicitly remove them."
- **error**: Report the error. The file may have syntax issues.

The `--removed` flag should include any symbols that were explicitly removed as legacy smells (from Step 2c).
```

- [ ] **Step 4: Add new Step 5 -- Adversarial Validation (testless path)**

Insert before the current Step 5 (Validate):

```markdown
## Step 5: Adversarial Validation (testless path only)

Skip if `testless_mode = false`. If tests exist, go directly to Step 6 (Validate with existing tests).

This step replaces test-run verification for testless files. Use the **unslop/adversarial** skill in takeover mode.

### Step 5a: Mason generates tests

The Mason reads ONLY the `*.behaviour.yaml` from Step 2c. It CANNOT see the generated source code (Chinese Wall enforced by the adversarial skill).

The Mason writes black-box tests that exercise the behaviour constraints.

### Step 5b: Mock Budget Lint

Run `validate_mocks.py` against the Mason's tests. If any test mocks an internal module, it is rejected and the Mason retries.

**Integration Pass:** If an imported internal module is already under unslop management (`@unslop-managed` header present), the Mason may use it directly without mocking.

**Unmanaged dependency cascade:** If the blocking dependency is NOT managed, recommend taking it over first:

> "Cannot test `{target}` in isolation -- it depends on `{dep}` which is not under spec management. Run `/unslop:takeover {dep}` first, then retry."

The user can override by adding the module to `boundaries.json` as an explicit internal boundary.

### Step 5c: Run tests against generated code

Execute the Mason's tests against the Builder's generated code. This is the first time the tests and code meet.

- **All green**: Proceed to Step 5d (mutation testing)
- **Failures**: Route to convergence (Step 7) with diagnostic: "Mason's tests expose a gap between behaviour.yaml and generated code"

### Step 5d: Saboteur runs mutation testing

The Saboteur mutates the generated source code and runs the Mason's tests against each mutant. The Prosecutor classifies surviving mutants.

- **All killed or equivalent**: Tests are strong. Proceed to Step 6 (Commit).
- **weak_test**: Mason retries with surviving mutant guidance. Back to Step 5a.
- **spec_gap**: Architect enriches behaviour.yaml. Back to Step 2c, then re-run from Step 5a.

**Adversarial intensity** (Architect-selected during Step 4):
- `adversarial: "full"` (default): Full Mason + Saboteur pipeline
- `adversarial: "mason-only"`: Mason generates tests, Saboteur skipped. For simple single-function files.

The user can override with `--full-adversarial` to force mutation testing.
```

- [ ] **Step 5: Rewrite Step 5/6 (Validate + Convergence) -- rename and add entropy threshold**

Renumber existing Step 5 to Step 6, Step 6 to Step 7. Update the convergence loop:

```markdown
## Step 6: Validate (tests-exist path)

(Unchanged from current Step 5 -- run existing tests, commit if green, converge if red.)

## Step 7: Convergence Loop (Cross-Stage)

Maximum **3 normal iterations + 1 radical hardening = 4 total**.

### Tests-exist convergence (unchanged)

For each iteration: read failure report -> diagnose with Concrete Spec -> enrich Abstract Spec -> get approval -> re-lower -> re-build. Same as current Step 6.

### Testless convergence (three-stage)

For each iteration:

a. **Diagnose** -- Read the Mason's test failures and/or Saboteur's surviving mutant report.

b. **Route by diagnosis:**
   - `weak_test` (surviving mutants that should be killed): Mason retries with mutant guidance. Skip to (f).
   - `spec_gap` (behaviour.yaml doesn't cover the failing case): Architect enriches behaviour.yaml. User approves. Continue to (c).
   - `test_failure` (Mason's tests fail against generated code): Architect enriches the abstract spec. User approves. Continue to (c).

c. **Re-lower (Stage A.2)** -- Derive fresh Concrete Spec from enriched Abstract Spec.

d. **Re-build (Stage B)** -- Fresh Builder, new worktree, test_policy: "skip".

e. **Symbol Audit** -- Verify public symbols survive.

f. **Re-validate (Steps 5a-5d)** -- Mason generates new tests from enriched behaviour.yaml, run against new code, Saboteur validates.

g. **Measure entropy delta** -- Compare mutation kill rate against previous iteration.

### Entropy Threshold

After each Saboteur run, compute the kill rate delta:

```
delta = current_kill_rate - previous_kill_rate
```

- If `delta >= entropy_threshold` (default 0.05): continue normally
- If `current_kill_rate == 1.0`: success, skip threshold check
- If `delta < entropy_threshold` and `current_kill_rate < 1.0`: **STALL detected**

On stall:

> "Convergence stalled: kill rate improved only {delta}% (threshold: {threshold}%). Triggering radical spec hardening."

**Radical Spec Hardening (one-shot):**
1. Prosecutor summarizes ALL surviving mutants as a batch
2. Architect rewrites behaviour.yaml from scratch using: original abstract spec + Prosecutor's summary + previous behaviour.yaml as reference
3. Mason generates tests from the rewritten behaviour.yaml
4. If this also stalls: DONE_WITH_CONCERNS -- report surviving mutants, commit with partial coverage

### Abandonment State

When iterations are exhausted without convergence:
- Keep all artifacts (spec, behaviour.yaml, generated code, generated tests, archive)
- Report surviving mutants as known gaps
- The file is under spec management with partial mutation coverage
- The user can run `/unslop:cover` later to grow coverage incrementally
```

- [ ] **Step 6: Update the Atomic Commit step**

Add behaviour.yaml and tests to the commit:

```markdown
## Step 8: Atomic Commit

**Testless path commits:**
- `*.spec.md` (abstract spec)
- `*.impl.md` (concrete spec, if promoted)
- `*.behaviour.yaml`
- Generated source code (with `@unslop-managed` header)
- Generated test file(s) from the Mason

After this commit, the file is under full spec management with tests. Subsequent generate/sync cycles use `test_policy: "do NOT modify test files"`.

**Tests-exist path commits:** (unchanged)
- `*.spec.md`
- `*.impl.md` (if promoted)
- Generated source code
```

- [ ] **Step 7: Update version in SKILL.md frontmatter**

Change `version: 0.1.0` to `version: 0.14.0`.

- [ ] **Step 8: Commit**

```
feat(takeover): add testless path with Double-Lift, adversarial validation, and entropy convergence
```

---

## Task 5: Update Takeover Command

**Files:**
- Modify: `unslop/commands/takeover.md`

- [ ] **Step 1: Add --skip-adversarial and --full-adversarial flags**

In the argument parsing section, add:

```markdown
Extract flags:
- `--force-ambiguous` — allow ambiguous specs (existing)
- `--skip-adversarial` — skip the adversarial pipeline even for testless files. The Builder generates with `test_policy: "takeover"` (write tests itself). Use for files where mutation testing is impractical (pure I/O, GUI code).
- `--full-adversarial` — force full mutation testing regardless of the Architect's intensity assessment.
```

- [ ] **Step 2: Add automatic testless detection**

In the "Run Pipeline" section, add before dispatching the skill:

```markdown
**Testless detection:** The takeover skill detects test absence automatically (Step 1). No `--no-tests` flag is needed. If `--skip-adversarial` is set, pass it to the skill so it falls back to the Builder-writes-tests path.
```

- [ ] **Step 3: Commit**

```
feat(takeover-cmd): add --skip-adversarial and --full-adversarial flags
```

---

## Task 6: Update Adversarial Skill -- Takeover Mode

**Files:**
- Modify: `unslop/skills/adversarial/SKILL.md`

- [ ] **Step 1: Add takeover mode section**

After the existing pipeline overview, add:

```markdown
## Takeover Mode

When invoked from the testless takeover pipeline (not directly by the user), the adversarial skill operates with these differences:

1. **The Architect writes the behaviour.yaml, not the Archaeologist.** During testless takeover, the Architect already reads the code and drafts the spec -- it produces the behaviour.yaml in the same pass (takeover Step 2c). The Archaeologist is reserved for post-takeover use (e.g., `/unslop:cover`).

2. **The Mason receives the behaviour.yaml from the takeover pipeline.** It does not extract its own. The Chinese Wall is still enforced -- the Mason sees only the behaviour.yaml, never the source code.

3. **Convergence crosses three stages.** In normal adversarial runs, only the Mason retries. In takeover mode, the Architect may enrich the behaviour.yaml and the Builder may re-generate code, creating a three-way convergence loop managed by the takeover skill.
```

- [ ] **Step 2: Add entropy threshold and radical hardening documentation**

After the convergence section, add:

```markdown
## Entropy Threshold (Takeover Mode)

Each Saboteur iteration tracks the mutation kill rate. If the improvement between iterations drops below the project's `entropy_threshold` (default 0.05 = 5%), convergence has stalled.

**Success exemption:** If kill rate is already 100%, skip the entropy check.

**On stall:** The takeover skill triggers Radical Spec Hardening -- a one-shot rewrite of the behaviour.yaml using the Prosecutor's surviving mutant summary as guidance. If this also stalls, the pipeline accepts partial coverage and reports surviving mutants as DONE_WITH_CONCERNS.

The entropy threshold is configurable in `.unslop/config.json` as `entropy_threshold`. Set to 0 to disable.
```

- [ ] **Step 3: Add Integration Pass documentation**

After the Mock Budget section, add:

```markdown
## Integration Pass (Takeover Mode)

During testless takeover, the Mason may encounter internal dependencies. The mock budget normally rejects these, but:

- **Managed dependencies** (files with `@unslop-managed` header) may be used directly in tests without mocking. Their behaviour is contractual.
- **Unmanaged dependencies** trigger a cascade recommendation: "Take over {dep} first, then retry."
- **User escape hatch:** Add the blocking module to `boundaries.json` as an internal boundary.
```

- [ ] **Step 4: Commit**

```
feat(adversarial): add takeover mode, entropy threshold, integration pass docs
```

---

## Task 7: Version Bump + Plugin Update

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.14.0**

Change `"version": "0.13.0"` to `"version": "0.14.0"`.

- [ ] **Step 2: Update description**

```json
"description": "Spec-driven development harness for Claude Code -- testless takeover, adversarial quality pipeline, worktree-isolated generation, cross-spec coherence, and triage routing"
```

- [ ] **Step 3: Commit**

```
chore: bump plugin version to 0.14.0 for Milestone N
```

---

## Task 8: Integration Validation Against Dirty Scaffold

**Files:**
- No file changes -- validation only
- Reference: `stress-tests/dirty-jitter/`

This task validates the full pipeline end-to-end using the dirty scaffold from the design spec.

- [ ] **Step 1: Verify the dirty scaffold is intact**

Check that `stress-tests/dirty-jitter/` has:
- `src/retry_v1.py` with 3 intentional bugs (404 retry, no cap, BaseException)
- `.unslop/principles.md` contradicting each bug
- `.unslop/boundaries.json` listing external deps
- `tests/test_retry_v1.py` with Mason-generated tests from the design validation

- [ ] **Step 2: Manually simulate the testless takeover flow**

Walk through each phase against the scaffold:

1. **Phase 1 (Double-Lift):** Does the Architect extract all 3 bugs? Does legacy smell detection flag them against principles?
2. **Phase 2 (Symbol Audit):** Run `orchestrator.py symbol-audit` against the archived original and a hypothetical generated version. Does it pass when symbols match? Fail when one is dropped?
3. **Phase 3 (Adversarial):** The existing `tests/test_retry_v1.py` already demonstrates Mason catching all 3 bugs. Verify the tests still fail against the buggy code and pass against a corrected version.
4. **Phase 4 (Convergence):** Document the expected iteration count and entropy deltas.

- [ ] **Step 3: Document validation results**

Add results to the design spec as an appendix or create a validation report.

- [ ] **Step 4: Final commit with all changes**

```
docs: Milestone N integration validation against dirty scaffold
```

---

## Execution Order

Tasks 1-3 are independent and can be parallelized.
Task 4 depends on Tasks 1-3 (references symbol audit, test_policy skip, config fields).
Tasks 5 and 6 both depend on Task 4 and can be parallelized with each other.
Task 7 is independent (can run any time).
Task 8 depends on all previous tasks.

```
  [1: Symbol Audit] ──┐
  [2: test_policy]  ──┼── [4: Takeover Skill] ── [5: Takeover Cmd] ── [8: Validation]
  [3: Config]       ──┘           │
                                  └── [6: Adversarial Skill]
  [7: Version Bump] ────────────────────────────────────────────────── [8: Validation]
```
