# Concrete Spec Enhancements v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `blocked-by` frontmatter parsing, freshness surfacing, and two new `STRICT_CHILD_ONLY` sections (Error Taxonomy, Test Seams) to the concrete spec layer.

**Architecture:** Parser extension follows the existing `targets` pattern (independent state variables, 4-space indent sub-fields). Freshness checker injects `blocked_constraints` into file result dicts alongside existing `concrete_staleness` and `pending_changes`. Skill/command files get documentation updates. All Python changes are TDD.

**Tech Stack:** Python 3.8+, pytest, strict string parsing (no YAML library)

---

## File Structure

| File | Responsibility |
|---|---|
| `unslop/scripts/core/frontmatter.py` | Parse `blocked-by` entries in `parse_concrete_frontmatter` |
| `unslop/scripts/freshness/checker.py` | Surface `blocked_constraints` in `check_freshness` file results |
| `unslop/scripts/dependencies/concrete_graph.py` | Add two new sections to `STRICT_CHILD_ONLY` set |
| `tests/test_orchestrator.py` | Tests for parser, checker, and STRICT_CHILD_ONLY |
| `unslop/commands/status.md` | Display `⊘` annotation for blocked constraints |
| `unslop/commands/coherence.md` | Known-blocker annotation in concrete spec coherence |
| `unslop/skills/generation/SKILL.md` | Builder deviation permit instructions |
| `unslop/skills/concrete-spec/SKILL.md` | Document all three additions |
| `unslop/skills/spec-language/SKILL.md` | Document `blocked-by` syntax |
| `unslop/.claude-plugin/plugin.json` | Version bump 0.23.0 -> 0.24.0 |

---

### Task 1: Parse `blocked-by` in concrete spec frontmatter (TDD)

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `unslop/scripts/core/frontmatter.py:54-133`

- [ ] **Step 1: Write failing tests for `blocked-by` parsing**

Add these tests to `tests/test_orchestrator.py`:

```python
# --- blocked-by parsing tests ---

def test_parse_concrete_frontmatter_blocked_by_single():
    content = """---
source-spec: src/roots.rs.spec.md
target-language: Rust
ephemeral: false
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs"
    affects: "Scanning<RustVM> impl"
---
"""
    result = parse_concrete_frontmatter(content)
    assert result["source_spec"] == "src/roots.rs.spec.md"
    assert result["ephemeral"] is False
    assert len(result["blocked_by"]) == 1
    entry = result["blocked_by"][0]
    assert entry["symbol"] == "binding::vm_impl::RustVM::VMScanning"
    assert entry["reason"] == "unconditionally aliases RustScanning"
    assert entry["resolution"] == "cfg-gate VMScanning alias in binding/vm_impl.rs"
    assert entry["affects"] == "Scanning<RustVM> impl"


def test_parse_concrete_frontmatter_blocked_by_multiple():
    content = """---
source-spec: src/roots.rs.spec.md
ephemeral: false
blocked-by:
  - symbol: "mod_a::TypeA"
    reason: "reason A"
    resolution: "fix A"
    affects: "part A"
  - symbol: "mod_b::TypeB"
    reason: "reason B"
    resolution: "fix B"
    affects: "part B"
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["blocked_by"]) == 2
    assert result["blocked_by"][0]["symbol"] == "mod_a::TypeA"
    assert result["blocked_by"][1]["symbol"] == "mod_b::TypeB"


def test_parse_concrete_frontmatter_blocked_by_missing_field_skipped(capsys):
    content = """---
source-spec: src/foo.spec.md
ephemeral: false
blocked-by:
  - symbol: "some::Symbol"
    reason: "missing resolution and affects"
---
"""
    result = parse_concrete_frontmatter(content)
    assert "blocked_by" not in result or len(result.get("blocked_by", [])) == 0
    captured = capsys.readouterr()
    assert "Warning" in captured.err or "missing" in captured.err.lower()


def test_parse_concrete_frontmatter_blocked_by_with_other_fields():
    """blocked-by coexists with targets and concrete-dependencies."""
    content = """---
source-spec: src/foo.spec.md
ephemeral: false
targets:
  - path: src/foo.py
    language: python
blocked-by:
  - symbol: "bar::Baz"
    reason: "needs migration"
    resolution: "migrate bar module"
    affects: "Baz usage"
concrete-dependencies:
  - src/bar.py.impl.md
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["targets"]) == 1
    assert result["targets"][0]["path"] == "src/foo.py"
    assert len(result["blocked_by"]) == 1
    assert result["blocked_by"][0]["symbol"] == "bar::Baz"
    assert result["concrete_dependencies"] == ["src/bar.py.impl.md"]


def test_parse_concrete_frontmatter_no_blocked_by():
    """No blocked-by field means no blocked_by key in result."""
    content = """---
source-spec: src/foo.spec.md
ephemeral: false
---
"""
    result = parse_concrete_frontmatter(content)
    assert "blocked_by" not in result


def test_parse_concrete_frontmatter_blocked_by_ephemeral_warning(capsys):
    """blocked-by on ephemeral spec emits warning but still parses."""
    content = """---
source-spec: src/foo.spec.md
ephemeral: true
blocked-by:
  - symbol: "bar::Baz"
    reason: "r"
    resolution: "res"
    affects: "aff"
---
"""
    result = parse_concrete_frontmatter(content)
    # Entries are still parsed (so promotion doesn't lose data)
    assert len(result["blocked_by"]) == 1
    assert result["blocked_by"][0]["symbol"] == "bar::Baz"
    # But a warning is emitted
    captured = capsys.readouterr()
    assert "ephemeral" in captured.err.lower()
    assert "promote" in captured.err.lower()


def test_parse_concrete_frontmatter_blocked_by_before_targets():
    """blocked-by appearing before targets parses both correctly."""
    content = """---
source-spec: src/foo.spec.md
ephemeral: false
blocked-by:
  - symbol: "a::B"
    reason: "r"
    resolution: "res"
    affects: "aff"
targets:
  - path: src/foo.py
    language: python
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["blocked_by"]) == 1
    assert len(result["targets"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "blocked_by" -v`
Expected: FAIL -- `blocked_by` key not in result

- [ ] **Step 3: Implement `blocked-by` parsing in `parse_concrete_frontmatter`**

In `unslop/scripts/core/frontmatter.py`, modify `parse_concrete_frontmatter`:

1. Update the docstring (line 55-58) to:
```python
    """Parse frontmatter from a concrete spec (.impl.md) file.

    Returns dict with: source_spec, target_language, ephemeral, complexity,
    concrete_dependencies (list of paths), targets (list of dicts),
    blocked_by (list of dicts with symbol, reason, resolution, affects).
    """
```

2. Add state variables after line 77 (`current_target = None`):
```python
    blocked_by = []
    in_blocked_by = False
    current_blocker = None
```

3. Add the `in_blocked_by` handler block. Insert it right after the `in_targets` block (after line 98, before the `if in_concrete_deps:` block). The block is structurally identical to `in_targets` but uses `- symbol:` as the entry delimiter:

```python
        if in_blocked_by:
            if re.match(r"^  - symbol:", line):
                if current_blocker:
                    blocked_by.append(current_blocker)
                current_blocker = {"symbol": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_blocker and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_blocker[key.strip()] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_blocker:
                    blocked_by.append(current_blocker)
                    current_blocker = None
                in_blocked_by = False
```

4. Add the `blocked-by:` key detection in the elif chain (after `elif stripped == "concrete-dependencies:"` on line 121-122):
```python
        elif stripped == "blocked-by:":
            in_blocked_by = True
```

5. Add post-loop flush (after the `if current_target:` block, around line 125):
```python
    if current_blocker:
        blocked_by.append(current_blocker)
```

6. Add validation and result assignment (after the `if targets:` block, around line 131):
```python
    _required_blocker_fields = {"symbol", "reason", "resolution", "affects"}
    validated_blockers = []
    for entry in blocked_by:
        missing = _required_blocker_fields - set(entry.keys())
        if missing:
            print(
                f"Warning: blocked-by entry missing required field(s) {sorted(missing)}, skipping: {entry}",
                file=sys.stderr,
            )
        else:
            validated_blockers.append(entry)
    if validated_blockers:
        result["blocked_by"] = validated_blockers
        if result.get("ephemeral", True):
            print(
                "Warning: blocked-by on ephemeral concrete spec has no effect -- promote to permanent first",
                file=sys.stderr,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "blocked_by" -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/core/frontmatter.py tests/test_orchestrator.py
git commit -m "feat: parse blocked-by in concrete spec frontmatter"
```

---

### Task 2: Add `STRICT_CHILD_ONLY` entries for Error Taxonomy and Test Seams

**Files:**
- Modify: `unslop/scripts/dependencies/concrete_graph.py:76-84`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_strict_child_only_includes_error_taxonomy_and_test_seams():
    assert "Error Taxonomy" in STRICT_CHILD_ONLY
    assert "Test Seams" in STRICT_CHILD_ONLY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py::test_strict_child_only_includes_error_taxonomy_and_test_seams -v`
Expected: FAIL -- `"Error Taxonomy" not in STRICT_CHILD_ONLY`

- [ ] **Step 3: Add entries to `STRICT_CHILD_ONLY`**

In `unslop/scripts/dependencies/concrete_graph.py`, edit the `STRICT_CHILD_ONLY` set (lines 76-84) to add the two new sections:

```python
STRICT_CHILD_ONLY = {
    "Strategy",
    "Type Sketch",
    "Representation Invariants",
    "Safety Contracts",
    "Concurrency Model",
    "State Machine",
    "Migration Notes",
    "Error Taxonomy",
    "Test Seams",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py::test_strict_child_only_includes_error_taxonomy_and_test_seams -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/dependencies/concrete_graph.py tests/test_orchestrator.py
git commit -m "feat: add Error Taxonomy and Test Seams to STRICT_CHILD_ONLY"
```

---

### Task 3: Surface `blocked_constraints` in freshness checker

**Files:**
- Modify: `unslop/scripts/freshness/checker.py:581-709`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_check_freshness_surfaces_blocked_constraints(tmp_path):
    """Permanent impl with blocked-by adds blocked_constraints to file result."""
    spec = tmp_path / "src" / "roots.rs.spec.md"
    spec.parent.mkdir(parents=True)
    spec_content = "# roots.rs spec\n\nBlackwall compliance.\n"
    spec.write_text(spec_content)

    spec_hash = compute_hash(spec_content)

    managed = tmp_path / "src" / "roots.rs"
    managed_body = "// managed code"
    output_hash = compute_hash(managed_body)
    managed.write_text(
        f"// @unslop-managed spec=src/roots.rs.spec.md spec-hash={spec_hash} output-hash={output_hash}\n"
        f"{managed_body}"
    )

    impl_file = tmp_path / "src" / "roots.rs.impl.md"
    impl_file.write_text("""---
source-spec: src/roots.rs.spec.md
target-language: Rust
ephemeral: false
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning"
    resolution: "cfg-gate VMScanning alias"
    affects: "Scanning<RustVM> impl"
---

## Strategy
Some strategy.
""")

    (tmp_path / ".unslop").mkdir()

    result = check_freshness(str(tmp_path))
    roots_entry = next(f for f in result["files"] if "roots" in f["managed"])
    assert "blocked_constraints" in roots_entry
    assert len(roots_entry["blocked_constraints"]) == 1
    assert roots_entry["blocked_constraints"][0]["symbol"] == "binding::vm_impl::RustVM::VMScanning"
    assert roots_entry["blocked_constraints"][0]["affects"] == "Scanning<RustVM> impl"
    assert roots_entry["blocked_constraints"][0]["reason"] == "unconditionally aliases RustScanning"
    assert roots_entry["blocked_constraints"][0]["resolution"] == "cfg-gate VMScanning alias"
    # Blocked constraints do NOT change staleness state
    assert roots_entry["state"] == "fresh"


def test_check_freshness_ignores_blocked_by_on_ephemeral(tmp_path):
    """Ephemeral impl with blocked-by does NOT add blocked_constraints."""
    spec = tmp_path / "src" / "foo.py.spec.md"
    spec.parent.mkdir(parents=True)
    spec_content = "# foo spec\n"
    spec.write_text(spec_content)

    spec_hash = compute_hash(spec_content)
    managed = tmp_path / "src" / "foo.py"
    managed_body = "# managed"
    output_hash = compute_hash(managed_body)
    managed.write_text(
        f"# @unslop-managed spec=src/foo.py.spec.md spec-hash={spec_hash} output-hash={output_hash}\n"
        f"{managed_body}"
    )

    impl_file = tmp_path / "src" / "foo.py.impl.md"
    impl_file.write_text("""---
source-spec: src/foo.py.spec.md
target-language: python
ephemeral: true
blocked-by:
  - symbol: "bar::Baz"
    reason: "r"
    resolution: "res"
    affects: "aff"
---
""")

    (tmp_path / ".unslop").mkdir()

    result = check_freshness(str(tmp_path))
    foo_entry = next(f for f in result["files"] if "foo" in f["managed"])
    assert "blocked_constraints" not in foo_entry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "blocked_constraints" -v`
Expected: FAIL -- `blocked_constraints` key not in result

- [ ] **Step 3: Implement blocked constraints surfacing in `check_freshness`**

In `unslop/scripts/freshness/checker.py`, add a new scan block after the ghost-staleness scan (after line 709, before the `# Scan for pending change requests` comment on line 711). This block iterates over the same `impl_files` list that was already scanned for ghost-staleness:

```python
    # Scan for blocked constraints (deferred constraints from blocked-by frontmatter)
    for impl_path in impl_files:
        rel_impl = str(impl_path.relative_to(root))
        try:
            impl_content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta = parse_concrete_frontmatter(impl_content)
        if meta.get("ephemeral", True):
            continue  # blocked-by on ephemeral specs is ignored

        blocked_by = meta.get("blocked_by", [])
        if not blocked_by:
            continue

        # Determine which managed files this impl affects
        target_paths = []
        targets_list = meta.get("targets", [])
        if targets_list:
            target_paths = [t["path"] for t in targets_list if "path" in t]
        else:
            source_spec = meta.get("source_spec", "")
            if source_spec:
                target_paths = [get_registry_key_for_spec(source_spec)]

        constraints = [
            {
                "symbol": entry["symbol"],
                "affects": entry["affects"],
                "reason": entry["reason"],
                "resolution": entry["resolution"],
            }
            for entry in blocked_by
        ]

        for managed_rel in target_paths:
            for f in files:
                if f["managed"] == managed_rel:
                    if "blocked_constraints" in f:
                        f["blocked_constraints"].extend(constraints)
                    else:
                        f["blocked_constraints"] = list(constraints)
                    break
```

Note: `impl_files` was already computed on line 582. We re-read and re-parse here because the ghost-staleness scan only processes files with `all_providers` (concrete-dependencies or extends). Files with `blocked-by` but no concrete-dependencies would be skipped otherwise. The double-read is acceptable because the files are small and the scan is I/O-bound.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "blocked_constraints" -v`
Expected: Both tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/freshness/checker.py tests/test_orchestrator.py
git commit -m "feat: surface blocked_constraints in freshness checker"
```

---

### Task 4: Update status command to display `⊘` annotation

**Files:**
- Modify: `unslop/commands/status.md:99-125`

- [ ] **Step 1: Add blocked constraint display rules**

In `unslop/commands/status.md`, after the existing `Δ` indicator section (lines 114-120), add:

```markdown
---

After classifying each managed file, check for `blocked_constraints` in the freshness result. If present, display a summary line indented below the file entry:

```
             ⊘ N blocked constraint(s): <affects-1>, <affects-2>
               waiting on <symbol-1>, <symbol-2>
```

The ⊘ indicator is a new annotation type parallel to Δ (pending changes). It appears regardless of the file's staleness state. A file can show both ⊘ and Δ simultaneously. Blocked constraints do NOT change the file's staleness classification -- they are informational only.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/commands/status.md
git commit -m "feat: display blocked constraints in status command"
```

---

### Task 5: Update coherence command for blocked-by awareness

**Files:**
- Modify: `unslop/commands/coherence.md:70-131`

- [ ] **Step 1: Add blocked-by annotation rules**

In `unslop/commands/coherence.md`, after step **5b** (Strategy coherence checks, line 91) and before step **5c** (Cascade detection, line 92), insert a new sub-step:

```markdown
**5b.1 Blocked constraint awareness:**

For each concrete spec pair being checked, read the `blocked-by` frontmatter of both specs. If either spec has `blocked-by` entries:

- Display the blocked constraint with `⊘` (not `✗`):
  ```
    ⊘ blocked constraint: <affects> (known -- tracked in blocked-by)
  ```
- Do NOT count blocked constraints toward the incoherence total
- If the upstream concrete spec in the pair is ghost-stale (already flagged by cascade detection or ghost-staleness logic), append an advisory:
  ```
    ⊘ blocked constraint: <affects> (known -- tracked in blocked-by)
      ℹ upstream <impl-path> is ghost-stale -- blocker may be resolved
  ```

The lookup boundary is the same as step 5a -- only concrete spec pairs derived from abstract spec `depends-on` relationships are checked. Coherence does NOT scan all `.impl.md` files in the project looking for symbol matches, and does NOT use `concrete-dependencies` or `extends` edges for pair discovery. If a `blocked-by` entry's symbol lives in a file with no abstract-level `depends-on` edge, the blocker is invisible to coherence (it still appears in `/unslop:status`). No additional pair discovery or pairing logic changes are needed.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/commands/coherence.md
git commit -m "feat: blocked-by awareness in coherence command"
```

---

### Task 6: Update generation skill with deviation permit instructions

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:66-80`

- [ ] **Step 1: Add deviation permit paragraph**

In `unslop/skills/generation/SKILL.md`, after the **Concrete Spec format** paragraph (line 66-70) and before the **Strategy Inheritance** paragraph (line 72), insert:

```markdown
**Deferred Constraints (blocked-by):** If the concrete spec's frontmatter contains `blocked-by` entries, the Builder treats each entry as an **explicit deviation permit**. The `affects` field names which part of the abstract spec can't be fulfilled yet; the `reason` field explains why. The Builder MUST proceed normally with all unblocked constraints. For the blocked scope, the Builder handles pragmatically -- keeping existing imports, using compatibility shims, or preserving legacy code paths. The Builder MUST NOT silently deviate on constraints not listed in `blocked-by`. The Builder SHOULD add a code comment at each deviation site: `// blocked-by: <symbol> -- <reason>`.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/generation/SKILL.md
git commit -m "feat: deviation permit instructions for blocked-by in generation"
```

---

### Task 7: Update concrete-spec skill documentation

**Files:**
- Modify: `unslop/skills/concrete-spec/SKILL.md:38-81` (frontmatter table)
- Modify: `unslop/skills/concrete-spec/SKILL.md:537-656` (architectural invariant sections)

- [ ] **Step 1: Add `blocked-by` to frontmatter table**

In `unslop/skills/concrete-spec/SKILL.md`, after the frontmatter example (line 49), add `blocked-by` to the example:

After the `concrete-dependencies:` block in the first example, add:
```yaml
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning -- needs cfg-gate"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    affects: "Scanning<RustVM> impl"
```

Add a new row to the field table (after `concrete-dependencies` on line 80):

```markdown
| `blocked-by` | no | List of deferred constraints -- symbol-level blockers that the spec wants to express but can't fulfill yet. Each entry has `symbol`, `reason`, `resolution`, `affects` (all required). Only meaningful on permanent specs (`ephemeral: false`). See Section 1 of the Concrete Spec Enhancements v2 design spec. |
```

- [ ] **Step 2: Add ephemeral restriction note**

After the `blocked-by` row in the table, add a note paragraph:

```markdown
**Ephemeral restriction:** `blocked-by` is only meaningful on permanent concrete specs. If present on an ephemeral spec, entries are parsed but ignored by the freshness checker and coherence command. Promote to permanent first via `/unslop:promote`.
```

- [ ] **Step 3: Add Error Taxonomy and Test Seams sections**

In `unslop/skills/concrete-spec/SKILL.md`, after the `## Migration Notes` section (ends around line 656), add the two new sections:

```markdown
#### `## Error Taxonomy` (optional)

Error classification hierarchy. Prevents the Builder from over-handling (catching everything, swallowing errors) or under-handling (letting panics propagate where recoverable errors are expected).

```markdown
## Error Taxonomy

ERROR AllocationFailure:
  CATEGORY: recoverable
  HANDLE: return GcResult::Err, caller retries after GC cycle
  NEVER: panic, log-and-ignore, retry internally

ERROR CorruptedHeader:
  CATEGORY: fatal
  HANDLE: panic immediately with diagnostic
  NEVER: attempt recovery, return default header

ERROR MutatorNotRegistered:
  CATEGORY: propagated
  HANDLE: return Result::Err to caller, do not log at this layer
  NEVER: register a default mutator, silently succeed
```

Fields per error:
- **`CATEGORY`** -- one of: `recoverable`, `fatal`, `propagated`
- **`HANDLE`** -- what the Builder MUST do
- **`NEVER`** -- what the Builder MUST NOT do

**When to include:** When the file has multiple error paths and the abstract spec's error handling description is ambiguous enough that the Builder might choose wrong.

#### `## Test Seams` (optional)

Testability boundaries and injectable dependencies. Prevents the Builder from generating tightly-coupled code or tests that leak state.

```markdown
## Test Seams

INJECTABLE allocator:
  INTERFACE: trait Allocator
  PRODUCTION: BumpAllocator
  TEST: MockAllocator (tracks allocation count, zero-cost)
  ISOLATION: per-test instance, no shared state

BOUNDARY gc_trigger:
  OBSERVABLE_VIA: callback count on MockAllocator
  NOT_OBSERVABLE_VIA: internal GC state (opaque to tests)
```

Entry types:
- **`INJECTABLE`** -- dependency with a test double (`INTERFACE`, `PRODUCTION`, `TEST`, `ISOLATION`)
- **`BOUNDARY`** -- testability boundary (`OBSERVABLE_VIA`, `NOT_OBSERVABLE_VIA`)

**When to include:** When the file has external dependencies (I/O, time, allocators) that must be injectable for testing.
```

- [ ] **Step 4: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/concrete-spec/SKILL.md
git commit -m "feat: document blocked-by, Error Taxonomy, Test Seams in concrete-spec skill"
```

---

### Task 8: Update spec-language skill documentation

**Files:**
- Modify: `unslop/skills/spec-language/SKILL.md:117-142`

- [ ] **Step 1: Add `blocked-by` documentation**

In `unslop/skills/spec-language/SKILL.md`, after the `depends-on` documentation section (ends at line 142), add a new section:

```markdown
## Deferred Constraints in Concrete Specs

When a concrete spec (`*.impl.md`) needs to track symbol-level blockers -- constraints the abstract spec wants to express but the implementation can't fulfill yet -- use `blocked-by` in the concrete spec frontmatter:

```markdown
---
source-spec: src/roots.rs.spec.md
target-language: Rust
ephemeral: false
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning -- needs cfg-gate"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    affects: "Scanning<RustVM> impl"
---
```

All four fields (`symbol`, `reason`, `resolution`, `affects`) are required. `blocked-by` is only meaningful on permanent concrete specs (`ephemeral: false`).

Unlike `depends-on` (file-level, passive), `blocked-by` is symbol-level and names a specific resolution action. It's a directed action item that can be removed once the upstream change happens.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/spec-language/SKILL.md
git commit -m "feat: document blocked-by syntax in spec-language skill"
```

---

### Task 9: Version bump and final verification

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Verify current version and bump**

Run: `grep '"version"' /home/lewdwig/git/unslop/unslop/.claude-plugin/plugin.json`
Expected: `"version": "0.23.0",`

If the version is already 0.24.0 or higher, skip this step. Otherwise, in `unslop/.claude-plugin/plugin.json`, change line 3:

```json
  "version": "0.24.0",
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.24.0"
```
