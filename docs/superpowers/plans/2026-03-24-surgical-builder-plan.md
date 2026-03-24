# Surgical Builder (Lite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Builder produce minimal diffs by giving it its prior output as a structural template, a spec diff, and an explicit list of authorized symbols -- with a soft post-hoc drift check for Python files.

**Architecture:** Three new context blocks in the Builder prompt (Existing Code, Spec Diff, Affected Symbols) make surgical mode the default for existing files. A `check_drift()` function in `symbol_audit.py` warns (not rejects) when protected symbols change. `--refactor` bypasses surgical mode for full regeneration. `--incremental` is deprecated.

**Tech Stack:** Python 3.8+ (ast module for drift check), Markdown (skill/command files)

**Spec:** `docs/superpowers/specs/2026-03-23-surgical-builder-design.md`

---

## File Structure

### Modified files
- `unslop/scripts/validation/symbol_audit.py` -- add `check_drift()` and `compute_spec_diff()` functions
- `tests/test_symbol_audit.py` -- add tests for drift check and spec diff
- `unslop/scripts/orchestrator.py` -- add `check_drift` and `compute_spec_diff` re-exports, add `spec-diff` CLI subcommand
- `unslop/skills/generation/SKILL.md` -- add Surgical Context blocks, update mode dispatch, deprecate Mode B
- `unslop/commands/sync.md` -- surgical default, `--refactor` flag, `--incremental` deprecation, modified-file pre-flight
- `unslop/commands/generate.md` -- surgical default, `--refactor` flag, `--incremental` deprecation
- `unslop/.claude-plugin/plugin.json` -- version bump to 0.16.0

---

## Task 1: Add `check_drift()` to Symbol Audit + Tests

The core Python code. TDD.

**Files:**
- Modify: `unslop/scripts/validation/symbol_audit.py`
- Modify: `tests/test_symbol_audit.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_symbol_audit.py`:

```python
from unslop.scripts.validation.symbol_audit import check_drift


def test_drift_clean():
    """No protected symbols changed -> clean report."""
    old_code = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    new_code = "def foo():\n    return 99\n\ndef bar():\n    return 2\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["foo"])
        assert result["status"] == "clean"
        assert result["drifted"] == []
        assert "foo" in result["modified"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_detected():
    """Protected symbol changed -> drift warning."""
    old_code = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    new_code = "def foo():\n    return 99\n\ndef bar():\n    return 99\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["foo"])
        assert result["status"] == "drift"
        assert "bar" in result["drifted"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_new_symbol():
    """New symbol tagged (new) -> no drift warning."""
    old_code = "def foo():\n    return 1\n"
    new_code = "def foo():\n    return 1\n\ndef helper():\n    return 2\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["foo", "helper (new)"])
        assert result["status"] == "clean"
        assert result["drifted"] == []
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_deleted_symbol():
    """Deleted symbol tagged (deleted) -> verify removed."""
    old_code = "def foo():\n    return 1\n\ndef legacy():\n    pass\n"
    new_code = "def foo():\n    return 1\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["legacy (deleted)"])
        assert result["status"] == "clean"
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_deleted_but_still_present():
    """Symbol tagged (deleted) but still in output -> drift warning."""
    old_code = "def foo():\n    return 1\n\ndef legacy():\n    pass\n"
    new_code = "def foo():\n    return 1\n\ndef legacy():\n    pass\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["legacy (deleted)"])
        assert result["status"] == "drift"
        assert any("legacy" in d for d in result["drifted"])
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_nonpython_skips():
    """Non-Python files skip drift check."""
    orig = _write_tmp("export function foo() {}", suffix=".ts")
    gen = _write_tmp("export function bar() {}", suffix=".ts")
    try:
        result = check_drift(orig, gen, affected_symbols=["foo"])
        assert result["skipped"] is True
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_class_body_change():
    """Class method changed in protected class -> drift warning."""
    old_code = "class Cfg:\n    x: int = 1\n\ndef run():\n    pass\n"
    new_code = "class Cfg:\n    x: int = 99\n\ndef run():\n    pass\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["run"])
        assert result["status"] == "drift"
        assert "Cfg" in result["drifted"]
    finally:
        os.unlink(orig)
        os.unlink(gen)
```

- [ ] **Step 2: Run tests -- verify ImportError**

Run: `pytest tests/test_symbol_audit.py::test_drift_clean -v`
Expected: ImportError (`check_drift` doesn't exist yet)

- [ ] **Step 3: Implement `check_drift()`**

Add to `unslop/scripts/validation/symbol_audit.py`, before `main()`:

```python
def _extract_symbol_source_ranges(source: str) -> dict[str, tuple[int, int]]:
    """Extract line ranges for each top-level symbol.

    Returns {name: (start_line, end_line)} where lines are 0-indexed.
    """
    tree = ast.parse(source)
    symbols: dict[str, tuple[int, int]] = {}
    nodes = [n for n in ast.iter_child_nodes(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    for i, node in enumerate(nodes):
        start = node.lineno - 1  # ast uses 1-indexed lines
        if i + 1 < len(nodes):
            end = nodes[i + 1].lineno - 2  # line before next node
        else:
            end = len(source.split("\n")) - 1
        if not node.name.startswith("_"):
            symbols[node.name] = (start, end)

    return symbols


def _normalize_block(lines: list[str], start: int, end: int) -> str:
    """Extract and normalize a block of source lines for comparison."""
    block = lines[start:end + 1]
    # Strip trailing whitespace, collapse blank lines
    normalized = []
    prev_blank = False
    for line in block:
        stripped = line.rstrip()
        if not stripped:
            if not prev_blank:
                normalized.append("")
            prev_blank = True
        else:
            normalized.append(stripped)
            prev_blank = False
    return "\n".join(normalized).strip()


def check_drift(
    old_path: str,
    new_path: str,
    affected_symbols: list[str],
) -> dict:
    """Check if the Builder modified symbols outside its authorization.

    This is a SOFT check -- it warns, not rejects.

    Args:
        old_path: Path to the existing managed file (compilation target).
        new_path: Path to the Builder's output.
        affected_symbols: List of authorized symbol names. Tags:
            "name (new)" for new symbols, "name (deleted)" for removed ones.

    Returns:
        dict with: status ("clean"|"drift"|"error"), drifted (list of
        symbol names that changed without authorization), modified
        (authorized symbols that changed), skipped (bool).
    """
    old = Path(old_path)
    new = Path(new_path)

    if old.suffix != ".py" or new.suffix != ".py":
        return {"status": "clean", "drifted": [], "modified": [], "skipped": True}

    # Parse affected_symbols tags
    authorized = set()
    new_symbols = set()
    deleted_symbols = set()
    for s in affected_symbols:
        s = s.strip()
        if s.endswith("(new)"):
            new_symbols.add(s.replace("(new)", "").strip())
        elif s.endswith("(deleted)"):
            deleted_symbols.add(s.replace("(deleted)", "").strip())
        else:
            authorized.add(s)

    try:
        old_source = old.read_text(encoding="utf-8")
        new_source = new.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"check-drift: cannot read input: {exc}", file=sys.stderr)
        return {"status": "error", "drifted": [], "modified": [], "skipped": False,
                "hint": str(exc)}

    try:
        old_ranges = _extract_symbol_source_ranges(old_source)
        new_ranges = _extract_symbol_source_ranges(new_source)
    except SyntaxError as exc:
        print(f"check-drift: cannot parse: {exc}", file=sys.stderr)
        return {"status": "error", "drifted": [], "modified": [], "skipped": False,
                "hint": str(exc)}

    old_lines = old_source.split("\n")
    new_lines = new_source.split("\n")

    drifted = []
    modified = []

    # Check protected symbols (in old, not in authorized/new/deleted)
    for name, (start, end) in old_ranges.items():
        if name in authorized or name in new_symbols or name in deleted_symbols:
            continue
        # Protected symbol -- should be unchanged
        if name not in new_ranges:
            drifted.append(name)
            continue
        new_start, new_end = new_ranges[name]
        old_block = _normalize_block(old_lines, start, end)
        new_block = _normalize_block(new_lines, new_start, new_end)
        if old_block != new_block:
            drifted.append(name)

    # Check authorized symbols were actually modified
    for name in authorized:
        if name in old_ranges and name in new_ranges:
            old_start, old_end = old_ranges[name]
            new_start, new_end = new_ranges[name]
            old_block = _normalize_block(old_lines, old_start, old_end)
            new_block = _normalize_block(new_lines, new_start, new_end)
            if old_block != new_block:
                modified.append(name)

    # Check deleted symbols are actually gone
    for name in deleted_symbols:
        if name in new_ranges:
            drifted.append(f"{name} (marked deleted but still present)")

    # Check unauthorized new symbols
    all_known = authorized | new_symbols | deleted_symbols | set(old_ranges.keys())
    for name in new_ranges:
        if name not in all_known:
            drifted.append(f"{name} (unauthorized new symbol)")

    status = "drift" if drifted else "clean"
    return {
        "status": status,
        "drifted": sorted(drifted),
        "modified": sorted(modified),
        "skipped": False,
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_symbol_audit.py -v`
Expected: All tests pass (existing 19 + new 7 = 26)

- [ ] **Step 5: Commit**

```
feat: add check_drift() for surgical builder post-hoc drift detection
```

---

## Task 2: Add `compute_spec_diff()` + Tests

**Files:**
- Modify: `unslop/scripts/validation/symbol_audit.py`
- Modify: `tests/test_symbol_audit.py`

- [ ] **Step 1: Write the failing tests**

```python
from unslop.scripts.validation.symbol_audit import compute_spec_diff


def test_spec_diff_changed_section():
    """Changed section detected."""
    old_spec = "# Spec\n\n## Purpose\nDo stuff\n\n## Behavior\nRetry 3 times\n"
    new_spec = "# Spec\n\n## Purpose\nDo stuff\n\n## Behavior\nRetry 5 times\n"
    result = compute_spec_diff(old_spec, new_spec)
    assert "## Behavior" in result["changed_sections"]
    assert "## Purpose" in result["unchanged_sections"]


def test_spec_diff_no_change():
    """Identical specs -> no changes."""
    spec = "# Spec\n\n## Purpose\nDo stuff\n"
    result = compute_spec_diff(spec, spec)
    assert result["changed_sections"] == []
    assert "## Purpose" in result["unchanged_sections"]


def test_spec_diff_new_section():
    """Added section detected as changed."""
    old_spec = "# Spec\n\n## Purpose\nDo stuff\n"
    new_spec = "# Spec\n\n## Purpose\nDo stuff\n\n## Errors\nRaise on timeout\n"
    result = compute_spec_diff(old_spec, new_spec)
    assert "## Errors" in result["changed_sections"]


def test_spec_diff_removed_section():
    """Removed section detected as changed."""
    old_spec = "# Spec\n\n## Purpose\nDo stuff\n\n## Legacy\nOld stuff\n"
    new_spec = "# Spec\n\n## Purpose\nDo stuff\n"
    result = compute_spec_diff(old_spec, new_spec)
    assert "## Legacy" in result["changed_sections"]
```

- [ ] **Step 2: Run tests -- verify ImportError**

- [ ] **Step 3: Implement `compute_spec_diff()`**

Add to `symbol_audit.py` before `main()`:

```python
def compute_spec_diff(old_spec: str, new_spec: str) -> dict:
    """Compute section-level diff between two spec versions.

    Parses markdown headings (## Level) and compares section content.

    Returns:
        dict with changed_sections and unchanged_sections (lists of heading strings).
    """
    def _parse_sections(text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current = None
        lines: list[str] = []
        for line in text.split("\n"):
            if line.startswith("## "):
                if current is not None:
                    sections[current] = "\n".join(lines).strip()
                current = line.strip()
                lines = []
            elif current is not None:
                lines.append(line)
        if current is not None:
            sections[current] = "\n".join(lines).strip()
        return sections

    old_sections = _parse_sections(old_spec)
    new_sections = _parse_sections(new_spec)
    all_headings = set(old_sections.keys()) | set(new_sections.keys())

    changed = []
    unchanged = []
    for heading in sorted(all_headings):
        old_content = old_sections.get(heading)
        new_content = new_sections.get(heading)
        if old_content == new_content:
            unchanged.append(heading)
        else:
            changed.append(heading)

    return {"changed_sections": changed, "unchanged_sections": unchanged}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_symbol_audit.py -v`
Expected: All pass (26 + 4 = 30)

- [ ] **Step 5: Commit**

```
feat: add compute_spec_diff() for section-level markdown comparison
```

---

## Task 3: Wire into Orchestrator CLI

**Files:**
- Modify: `unslop/scripts/orchestrator.py`

- [ ] **Step 1: Add re-exports**

In the validation re-exports section (line 85), add:

```python
from .validation.symbol_audit import audit_symbols, check_drift, compute_spec_diff
```

Add `"check_drift"` and `"compute_spec_diff"` to `__all__` (after `"audit_symbols"`).

- [ ] **Step 2: Add `spec-diff` and `check-drift` CLI subcommands**

After the `symbol-audit` elif block, add both:

```python
elif command == "spec-diff":
    if len(sys.argv) < 4:
        print("Usage: orchestrator.py spec-diff <old-spec> <new-spec>", file=sys.stderr)
        sys.exit(1)
    old_path = sys.argv[2]
    new_path = sys.argv[3]
    try:
        old_text = Path(old_path).read_text(encoding="utf-8")
        new_text = Path(new_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    result = compute_spec_diff(old_text, new_text)
    print(json.dumps(result, indent=2))

elif command == "check-drift":
    if len(sys.argv) < 4:
        print("Usage: orchestrator.py check-drift <old-file> <new-file> --affected s1,s2", file=sys.stderr)
        sys.exit(1)
    old_file = sys.argv[2]
    new_file = sys.argv[3]
    affected: list[str] = []
    if "--affected" in sys.argv:
        aidx = sys.argv.index("--affected")
        if aidx + 1 >= len(sys.argv):
            print("check-drift: --affected requires a comma-separated value", file=sys.stderr)
            sys.exit(1)
        affected = [s.strip() for s in sys.argv[aidx + 1].split(",") if s.strip()]
    result = check_drift(old_file, new_file, affected_symbols=affected)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "clean" else 1)
```

Update the usage string to include `spec-diff` and `check-drift`.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```
feat: wire check_drift and spec-diff into orchestrator CLI
```

---

## Task 4: Update Generation Skill -- Surgical Context

The big skill rewrite. Adds Surgical Context blocks to the Builder prompt and updates mode dispatch.

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Update mode dispatch logic**

Find the Mode A / Mode B sections (around lines 691-739). Replace the mode selection with:

```markdown
### Generation Modes

**Surgical mode (default for existing files):** The Builder receives three additional context blocks: Existing Code (its prior output), Spec Diff (which sections changed), and Affected Symbols (which symbols it may modify). The Builder produces a complete file where protected symbols are copied verbatim from the Existing Code and only affected symbols are regenerated.

**Mode A -- Full Regeneration:** The Builder generates from scratch with no reference to existing code. Used for first generation (no existing file), `--refactor` flag, or `conflict` state with user choosing "Overwrite."

**Mode B (`--incremental`) is deprecated.** Surgical mode subsumes it. `--incremental` is treated as a no-op and emits: `"--incremental is deprecated. Surgical mode is now the default. Use --refactor for full regeneration."`

**Dispatch logic:**
- New file (no existing code): Mode A
- Existing file, normal sync: Surgical mode
- `--refactor` flag: Mode A (explicit full regen)
```

- [ ] **Step 2: Add Surgical Context blocks to Builder prompt**

In the Builder dispatch section, add the three new context blocks:

```markdown
### Surgical Context (existing files only)

When dispatching the Builder for an existing managed file (not first generation, not `--refactor`), include three additional blocks in the prompt:

**Existing Code block:**

> "## Last Successful Compilation Target
> This is your prior output for this file. Use it as your structural template.
> Copy all protected symbols verbatim -- do not reformat, reorder, or 'improve' them.
> **If the Spec Diff contradicts this code, the Spec Diff wins. Always.**
>
> ```<language>
> <contents of existing managed file>
> ```"

**Spec Diff block:**

> "## Spec Diff
> The following spec sections changed since the last generation:
> Changed: <list of changed section headings>
> Unchanged: <list of unchanged section headings>
>
> Focus your attention on the changed sections."

**Affected Symbols block:**

> "## Affected Symbols
> You are authorized to modify ONLY these symbols: [<symbol_list>]
> All other symbols, including their docstrings, type signatures, and internal
> logic, must remain identical to the Existing Code. Copy them verbatim.
> Do not reformat, reorder, or 'improve' protected symbols.
>
> The Surgicality Drift Check will verify your output after generation."

These blocks are omitted for Mode A (first generation or `--refactor`).
```

- [ ] **Step 3: Add post-hoc drift check documentation**

After the Verification section, add:

```markdown
### Post-Hoc Drift Check (Surgical Mode, Python only)

After the Builder returns DONE in surgical mode, before worktree merge, run:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py check-drift <old-file> <new-file> --affected <symbol1,symbol2>
```

Parse the JSON result:
- **clean**: All protected symbols preserved. Proceed to merge.
- **drift**: One or more protected symbols changed. Include the drift warning in the triage summary but proceed with merge. The warning surfaces as:

```
WARNING: Builder modified protected symbol 'RetryConfig' (not in affected_symbols).
  Affected symbols were: [calculate_delay, retry]
  This may indicate the spec change has broader impact than expected.
```

- **error**: File could not be parsed. Proceed without drift check.

The drift check is a WARNING, not a gate. The worktree merge always proceeds.
```

- [ ] **Step 4: Add Triage Summary templates**

After the drift check section, add:

```markdown
### Triage Summary (Surgical Mode)

After merge, report the surgical sync result. No LLM involved -- pure string formatting.

**Clean surgical sync:**
\```
Surgical sync: src/retry.py
  Modified: calculate_delay, retry (2 symbols)
  Preserved: RetryConfig, MaxRetriesExceeded, T (3 symbols)
\```

**Surgical sync with drift warning:**
\```
Surgical sync: src/retry.py
  Modified: calculate_delay, retry (2 symbols)
  WARNING: RetryConfig was also modified (not in affected_symbols)
  Preserved: MaxRetriesExceeded, T (2 symbols)
\```

**Full regeneration (--refactor):**
\```
Full regeneration: src/retry.py
  Mode: --refactor
  Symbols: 5 written
\```
```

- [ ] **Step 5: Add note about multi-target affected_symbols**

In the Surgical Context section, add a note:

```markdown
**Multi-target specs:** For concrete specs with `targets[]` arrays, each target gets its own `affected_symbols` list. Each parallel Builder receives only its target's symbols. See the spec for the frontmatter format. Single-target specs use top-level `affected_symbols`.
```

- [ ] **Step 6: Commit**

```
feat(generation): add Surgical Context blocks, update mode dispatch for surgical default
```

---

## Task 5: Update sync.md and generate.md Commands

**Files:**
- Modify: `unslop/commands/sync.md`
- Modify: `unslop/commands/generate.md`

- [ ] **Step 1: Update sync.md**

In the argument-hint (line 3), append `--refactor` to the existing flags (preserve all existing flags like `--deep`, `--stale-only`, `--force`, `--incremental`, `--dry-run`, `--resume`, `--max-batch`, etc.).

In the mode dispatch section (around line 242), update:

```markdown
**Mode selection:**
- If the managed file does not exist: Mode A (full generation).
- If `--refactor` was passed: Mode A (full generation, ignore existing structure).
- Otherwise: **Surgical mode** (default). The Builder receives the existing file as a structural template.
- If `--incremental` was passed: emit deprecation warning `"--incremental is deprecated. Surgical mode is now the default. Use --refactor for full regeneration."` and proceed with surgical mode.
```

Add modified-file pre-flight check before dispatch:

```markdown
**Modified file pre-flight (surgical mode only):**

If the managed file has state `modified` (user hand-edited the code) and the spec also changed:

> "src/retry.py has manual edits (modified state). The spec also changed.
>   [a] Overwrite -- discard manual edits, regenerate from spec (Mode A)
>   [b] Absorb -- incorporate manual edits into the spec first, then regenerate
>   [c] Skip -- leave this file alone for now"

Option (a) uses Mode A. Option (b) routes to `/unslop:change`. Option (c) skips.

If state is `modified` but spec has NOT changed: no pre-flight needed (the file is just edited, not stale).
```

- [ ] **Step 2: Update generate.md**

In the argument-hint (line 3), add `--refactor`:
```
argument-hint: [--dry-run] [--force-ambiguous] [--force-pseudocode] [--force-strategy] [--refactor]
```

In the mode dispatch section (around line 120), update to match the same logic as sync.md.

- [ ] **Step 3: Commit**

```
feat(sync,generate): surgical mode as default, --refactor flag, --incremental deprecation
```

---

## Task 6: Version Bump

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.16.0**

- [ ] **Step 2: Update description**

Add "surgical diff minimization" or similar.

- [ ] **Step 3: Commit**

```
chore: bump plugin version to 0.16.0 for Surgical Builder
```

---

## Execution Order

Tasks 1-2 are independent Python code (can parallelize in theory, but sequential is fine since Task 2 modifies the same file).
Task 3 depends on Tasks 1-2 (wires their exports into orchestrator).
Tasks 4-5 depend on Task 3 (reference the CLI commands).
Task 6 is independent.

```
[1: check_drift] -> [2: spec_diff] -> [3: Orchestrator CLI] -> [4: Generation Skill] -> [5: sync/generate commands]
[6: Version Bump] ──────────────────────────────────────────────────────────────────────────────────────────────────
```
