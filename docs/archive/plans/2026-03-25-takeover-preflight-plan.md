# Takeover Pre-flight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `protected-regions` frontmatter parsing, `managed-end-line` header support, bounded body hashing, and Step 0 pre-flight documentation to the takeover pipeline.

**Architecture:** The plan splits into two layers. Layer 1 is Python infrastructure (parser, hashing, checker) -- all TDD with exact code. Layer 2 is skill/command documentation (takeover Step 0, generation protected-region handling, concrete-spec field docs). Layer 1 ships first so the mechanical pieces are testable; Layer 2 builds on them.

**Tech Stack:** Python 3.8+, pytest, strict string parsing (no YAML library)

---

## File Structure

| File | Responsibility |
|---|---|
| `unslop/scripts/core/frontmatter.py` | Parse `protected-regions` in `parse_concrete_frontmatter` |
| `unslop/scripts/core/hashing.py` | Parse `managed-end-line` in `parse_header`; add `end_line` param to `get_body_below_header` |
| `unslop/scripts/freshness/checker.py` | Wire `managed_end_line` through `classify_file` |
| `tests/test_orchestrator.py` | Tests for all three Python changes |
| `unslop/skills/takeover/SKILL.md` | Step 0 (0a, 0b, 0c) pre-flight phase |
| `unslop/skills/generation/SKILL.md` | Protected region handling in Builder instructions |
| `unslop/skills/concrete-spec/SKILL.md` | Document `protected-regions` frontmatter field |
| `unslop/.claude-plugin/plugin.json` | Version bump 0.24.0 -> 0.25.0 |

---

### Task 1: Parse `protected-regions` in concrete spec frontmatter (TDD)

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `unslop/scripts/core/frontmatter.py:55-179`

- [ ] **Step 1: Write failing tests for `protected-regions` parsing**

Add these tests to the END of `tests/test_orchestrator.py`:

```python
# --- protected-regions parsing tests ---


def test_parse_concrete_frontmatter_protected_regions_single():
    content = """---
source-spec: src/foo.rs.spec.md
target-language: Rust
ephemeral: false
protected-regions:
  - marker: "compile-time test conditional"
    position: tail
    semantics: test-suite
    starts-at: "line 847"
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["protected_regions"]) == 1
    entry = result["protected_regions"][0]
    assert entry["marker"] == "compile-time test conditional"
    assert entry["position"] == "tail"
    assert entry["semantics"] == "test-suite"
    assert entry["starts_at"] == "line 847"


def test_parse_concrete_frontmatter_protected_regions_missing_field(capsys):
    content = """---
source-spec: src/foo.rs.spec.md
ephemeral: false
protected-regions:
  - marker: "test block"
    position: tail
---
"""
    result = parse_concrete_frontmatter(content)
    assert "protected_regions" not in result
    captured = capsys.readouterr()
    assert "missing" in captured.err.lower()


def test_parse_concrete_frontmatter_protected_regions_unknown_semantics(capsys):
    content = """---
source-spec: src/foo.rs.spec.md
ephemeral: false
protected-regions:
  - marker: "custom block"
    position: tail
    semantics: unknown-type
    starts-at: "line 100"
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["protected_regions"]) == 1
    assert result["protected_regions"][0]["semantics"] == "unknown-type"
    captured = capsys.readouterr()
    assert "unknown-type" in captured.err


def test_parse_concrete_frontmatter_protected_regions_with_blocked_by():
    """protected-regions coexists with blocked-by."""
    content = """---
source-spec: src/foo.rs.spec.md
ephemeral: false
blocked-by:
  - symbol: "bar::Baz"
    reason: "r"
    resolution: "res"
    affects: "aff"
protected-regions:
  - marker: "test block"
    position: tail
    semantics: test-suite
    starts-at: "line 500"
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["blocked_by"]) == 1
    assert len(result["protected_regions"]) == 1


def test_parse_concrete_frontmatter_no_protected_regions():
    content = """---
source-spec: src/foo.rs.spec.md
ephemeral: false
---
"""
    result = parse_concrete_frontmatter(content)
    assert "protected_regions" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "protected_regions" -v`
Expected: FAIL -- `protected_regions` key not in result

- [ ] **Step 3: Implement `protected-regions` parsing in `parse_concrete_frontmatter`**

In `unslop/scripts/core/frontmatter.py`, modify `parse_concrete_frontmatter`:

1. Update the docstring (line 57-60) to add `protected_regions`:
```python
    """Parse frontmatter from a concrete spec (.impl.md) file.

    Returns dict with: source_spec, target_language, ephemeral, complexity,
    concrete_dependencies (list of paths), targets (list of dicts),
    blocked_by (list of dicts with symbol, reason, resolution, affects),
    protected_regions (list of dicts with marker, position, semantics, starts_at).
    """
```

2. Add state variables after line 82 (`current_blocker = None`):
```python
    protected_regions = []
    in_protected_regions = False
    current_region = None
```

3. Add `in_protected_regions` handler block right AFTER the `in_blocked_by` block (after line 120) and BEFORE the `if in_concrete_deps:` block. Structurally identical to the others:
```python
        if in_protected_regions:
            if re.match(r"^  - marker:", line):
                if current_region:
                    protected_regions.append(current_region)
                current_region = {"marker": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_region and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    parsed_key = key.strip().replace("-", "_")
                    current_region[parsed_key] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_region:
                    protected_regions.append(current_region)
                    current_region = None
                in_protected_regions = False
```

Note: the `starts-at` key has a hyphen, so we normalize it to `starts_at` via `.replace("-", "_")`.

4. Add `protected-regions:` detection in the elif chain (after `elif stripped == "blocked-by:"`):
```python
        elif stripped == "protected-regions:":
            in_protected_regions = True
```

5. Add post-loop flush after `if current_blocker:` block:
```python
    if current_region:
        protected_regions.append(current_region)
```

6. Add validation and result assignment after the `blocked_by` validation block (after line 177):
```python
    _required_region_fields = {"marker", "position", "semantics", "starts_at"}
    _valid_semantics = {"test-suite", "entry-point", "examples", "benchmarks"}
    validated_regions = []
    for entry in protected_regions:
        missing = _required_region_fields - set(entry.keys())
        if missing:
            print(
                json.dumps({"warning": f"protected-regions entry missing required field(s) {sorted(missing)}, skipping: {entry}"}),
                file=sys.stderr,
            )
        else:
            if entry["semantics"] not in _valid_semantics:
                print(
                    json.dumps({"warning": f"protected-regions entry has unknown semantics {entry['semantics']!r} -- keeping entry"}),
                    file=sys.stderr,
                )
            validated_regions.append(entry)
    if validated_regions:
        result["protected_regions"] = validated_regions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "protected_regions" -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/core/frontmatter.py tests/test_orchestrator.py
git commit -m "feat: parse protected-regions in concrete spec frontmatter"
```

---

### Task 2: Add `managed-end-line` to `parse_header` and bounded `get_body_below_header` (TDD)

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `unslop/scripts/core/hashing.py:25-132`

- [ ] **Step 1: Write failing tests**

Add to the END of `tests/test_orchestrator.py`:

```python
# --- managed-end-line tests ---


def test_parse_header_with_managed_end_line():
    lines = [
        "// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.",
        "// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 managed-end-line:847 generated:2026-03-25T12:00:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result is not None
    assert result["managed_end_line"] == 847
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"


def test_parse_header_without_managed_end_line():
    lines = [
        "// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.",
        "// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-25T12:00:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result is not None
    assert result["managed_end_line"] is None


def test_get_body_below_header_with_end_line():
    content = "\n".join([
        "// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.",
        "// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 managed-end-line:5 generated:2026-03-25T12:00:00Z",
        "fn implementation() {}",
        "fn more_impl() {}",
        "#[cfg(test)]",
        "mod tests {",
        "    #[test]",
        "    fn it_works() {}",
        "}",
    ])
    # managed-end-line:5 means line 5 is the first protected line (#[cfg(test)])
    # Body starts at line 3 (after 2 header lines)
    # Should return lines 3-4 only (implementation), not lines 5+ (protected region)
    body = get_body_below_header(content, end_line=5)
    assert "fn implementation() {}" in body
    assert "fn more_impl() {}" in body
    assert "#[cfg(test)]" not in body
    assert "mod tests" not in body


def test_get_body_below_header_without_end_line():
    content = "\n".join([
        "// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.",
        "// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-25T12:00:00Z",
        "fn implementation() {}",
        "fn more_impl() {}",
    ])
    # No end_line -- returns full body (backward compat)
    body = get_body_below_header(content)
    assert "fn implementation() {}" in body
    assert "fn more_impl() {}" in body


def test_protected_region_edit_does_not_change_hash():
    """Editing a protected region should not change the output hash."""
    header = "\n".join([
        "// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.",
        "// spec-hash:a3f8c2e9b7d1 output-hash:placeholder managed-end-line:5 generated:2026-03-25T12:00:00Z",
    ])
    impl_lines = "fn implementation() {}\nfn more_impl() {}"
    protected_v1 = "#[cfg(test)]\nmod tests { fn v1() {} }"
    protected_v2 = "#[cfg(test)]\nmod tests { fn v2_edited() {} }"

    content_v1 = f"{header}\n{impl_lines}\n{protected_v1}"
    content_v2 = f"{header}\n{impl_lines}\n{protected_v2}"

    body_v1 = get_body_below_header(content_v1, end_line=5)
    body_v2 = get_body_below_header(content_v2, end_line=5)

    hash_v1 = compute_hash(body_v1)
    hash_v2 = compute_hash(body_v2)

    # Hashes should be identical -- protected region edits are invisible
    assert hash_v1 == hash_v2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "managed_end_line or end_line or protected_region_edit" -v`
Expected: FAIL -- `managed_end_line` key not in result / `end_line` parameter not accepted

- [ ] **Step 3: Implement `managed-end-line` in `parse_header`**

In `unslop/scripts/core/hashing.py`:

0. Add `from __future__ import annotations` at the top of the file (after the module docstring, before existing imports). This enables `int | None` type syntax on Python 3.8+. The file currently lacks this import.

1. Add a `managed_end_line` variable after line 43 (`old_format = False`):
```python
    managed_end_line = None
```

2. Add extraction logic inside the `for line in lines:` loop, after the `gen_match` block (after line 75). Add it within the `if hash_match:` block:
```python
            mel_match = re.search(r"managed-end-line:(\d+)", stripped)
            if mel_match:
                managed_end_line = int(mel_match.group(1))
```

3. Add `managed_end_line` to the return dict (line 105-114):
```python
    return {
        "spec_path": spec_path,
        "spec_hash": spec_hash,
        "output_hash": output_hash,
        "principles_hash": principles_hash,
        "concrete_deps_hash": concrete_deps_hash,
        "concrete_manifest": concrete_manifest,
        "managed_end_line": managed_end_line,
        "generated": generated,
        "old_format": old_format,
    }
```

- [ ] **Step 4: Implement `end_line` parameter in `get_body_below_header`**

In `unslop/scripts/core/hashing.py`, modify `get_body_below_header` (line 117-132):

Change the signature to:
```python
def get_body_below_header(content: str, end_line: int | None = None) -> str:
```

Update the docstring:
```python
    """Extract managed file content below the @unslop-managed header.

    Scans the first 5 lines for header markers, skipping blank lines.
    Returns everything after the last header line.

    If end_line is provided (1-indexed line number), returns only lines
    from below the header up to but not including end_line. This supports
    protected regions where the managed content ends before the file does.
    """
```

Change the return line (line 132) from:
```python
    return "\n".join(lines[body_start:])
```
to:
```python
    if end_line is not None:
        return "\n".join(lines[body_start : end_line - 1])
    return "\n".join(lines[body_start:])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "managed_end_line or end_line or protected_region_edit" -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/core/hashing.py tests/test_orchestrator.py
git commit -m "feat: managed-end-line header support and bounded body hashing"
```

---

### Task 3: Wire `managed_end_line` through freshness checker

**Files:**
- Modify: `unslop/scripts/freshness/checker.py:79-81`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to the END of `tests/test_orchestrator.py`:

```python
def test_classify_file_with_managed_end_line(tmp_path):
    """managed-end-line causes checker to hash only the bounded body."""
    spec = tmp_path / "src" / "foo.rs.spec.md"
    spec.parent.mkdir(parents=True)
    spec_content = "# foo spec\n"
    spec.write_text(spec_content)

    spec_hash = compute_hash(spec_content)

    impl_body = "fn implementation() {}"
    output_hash = compute_hash(impl_body)

    # managed-end-line:4 means protected region starts at line 4
    # Header is lines 1-2, implementation is line 3, protected is line 4+
    managed = tmp_path / "src" / "foo.rs"
    managed.write_text(
        f"// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.\n"
        f"// spec-hash:{spec_hash} output-hash:{output_hash} managed-end-line:4 generated:2026-03-25T12:00:00Z\n"
        f"{impl_body}\n"
        f"#[cfg(test)]\n"
        f"mod tests {{ }}\n"
    )

    result = classify_file(str(managed), str(spec))
    assert result["state"] == "fresh"

    # Now edit the protected region -- should still be fresh
    managed.write_text(
        f"// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.\n"
        f"// spec-hash:{spec_hash} output-hash:{output_hash} managed-end-line:4 generated:2026-03-25T12:00:00Z\n"
        f"{impl_body}\n"
        f"#[cfg(test)]\n"
        f"mod tests {{ fn edited() {{}} }}\n"
    )

    result2 = classify_file(str(managed), str(spec))
    assert result2["state"] == "fresh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py::test_classify_file_with_managed_end_line -v`
Expected: FAIL -- `managed_end_line` not in header dict or not wired through

- [ ] **Step 3: Wire `managed_end_line` in `classify_file`**

In `unslop/scripts/freshness/checker.py`, modify `classify_file` around line 79-81. Change:

```python
    current_spec_hash = compute_hash(spec_content)
    body = get_body_below_header(managed_content)
    current_output_hash = compute_hash(body)
```

to:

```python
    current_spec_hash = compute_hash(spec_content)
    body = get_body_below_header(managed_content, end_line=header.get("managed_end_line"))
    current_output_hash = compute_hash(body)
```

That's it -- `get_body_below_header` already handles `None` (full body, backward compat).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py::test_classify_file_with_managed_end_line -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/freshness/checker.py tests/test_orchestrator.py
git commit -m "feat: wire managed-end-line through freshness checker"
```

---

### Task 4: Add Step 0 pre-flight to takeover skill

**Files:**
- Modify: `unslop/skills/takeover/SKILL.md`

- [ ] **Step 1: Add Step 0 before current Step 1**

In `unslop/skills/takeover/SKILL.md`, find the `## Step 1: Discover` heading. Before it, insert the new Step 0 section. The content should cover:

**Step 0: Pre-flight Analysis**

Three sub-steps:

**Step 0a: Measure and Detect**
- Read the target file
- Compute line count, public symbol count (via `get_symbol_manifest()` if available), estimated token weight (`file_size_bytes / 4`)
- Scan for protected regions: tail blocks that serve a different purpose than the implementation above them (e.g., compile-time test conditionals, main entry guards, example/benchmark blocks)
- Compare against thresholds (configurable in `.unslop/config.json` under `preflight` key):
  - Suggest split: >1000 lines OR >30 public symbols OR >8000 tokens
  - Require split: >2000 lines OR >60 public symbols OR >16000 tokens
- If below all thresholds and no protected regions: Step 0 is a no-op, proceed to Step 1
- If protected regions detected but no split needed: record them for the concrete spec, proceed to Step 1
- Present the analysis to the user

**Step 0b: Split Planning** (only if thresholds exceeded)
- Present the split plan: submodule names, approximate sizes, symbol assignments, protected region placement
- User approves (y), rejects (n), or edits the plan
- API preservation is the prime directive: all public symbols remain accessible at the original path via re-exports
- The `--force` flag overrides "require" thresholds with a warning

**Step 0c: Split Execution** (only if user approved)
- Create submodule files, write facade with re-exports, update internal references
- Verify compilation via build check command
- Verify tests pass (if they exist)
- On failure: rollback (delete created files, restore original from git), offer options (fix/retry, proceed unsplit if below require threshold, abort)
- On success: atomic commit (`refactor: split <file> into submodules (pre-takeover)`), then queue submodules for individual takeover with facade last
- Facade spec SHOULD declare `depends-on` entries for each submodule spec

Also update the Pipeline Overview steps list at the top to include Step 0.

**Important:** All language used in this step must be language-agnostic. Describe patterns ("compile-time test conditional", "main entry guard") not syntax (`#[cfg(test)]`, `if __name__`). The Architect identifies these by reading the file.

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/takeover/SKILL.md
git commit -m "feat: add Step 0 pre-flight to takeover skill"
```

---

### Task 5: Add protected region handling to generation skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add protected region instructions**

In `unslop/skills/generation/SKILL.md`, two changes:

**Change 1:** In the `## 2. Write the @unslop-managed Header` section (around line 949), add `managed-end-line` to the header format documentation:

After the existing `**Line 3 (optional):**` for concrete-manifest, add:
```markdown
**Line N (optional):** `managed-end-line:<line-number>` -- 1-indexed line number where the protected region starts. Present only when the concrete spec declares `protected-regions`. The freshness checker hashes only lines from below the header up to but not including this line.
```

Add an example showing the field in a Rust header.

**Change 2:** After the `**Deferred Constraints (blocked-by):**` paragraph (added in the previous PR), add a new paragraph:

```markdown
**Protected Regions:** If the concrete spec's frontmatter contains `protected-regions` entries, the Builder MUST preserve these regions verbatim during generation. Before writing any output, the Builder reads the existing managed file and extracts the protected region into memory (everything from `starts-at` to EOF for `tail` position). After generating the implementation, the Builder appends the protected region verbatim. The Builder then: (1) verifies the protected region is present in the output -- if missing, report BLOCKED; (2) counts the 1-indexed line number where the protected region starts and writes it as `managed-end-line` in the header; (3) updates the `starts-at` field in the concrete spec frontmatter to match; (4) computes `output-hash` over the implementation portion only (excluding the protected region). The Builder MUST NOT modify, reformat, or reorder the protected region content.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/generation/SKILL.md
git commit -m "feat: protected region handling in generation skill"
```

---

### Task 6: Document `protected-regions` in concrete-spec skill

**Files:**
- Modify: `unslop/skills/concrete-spec/SKILL.md`

- [ ] **Step 1: Add `protected-regions` to frontmatter documentation**

In `unslop/skills/concrete-spec/SKILL.md`:

**Change 1:** Add `protected-regions` to the first frontmatter example (after the `blocked-by` block added in the previous PR):
```yaml
protected-regions:
  - marker: "compile-time test conditional"
    position: tail
    semantics: test-suite
    starts-at: "line 847"
```

**Change 2:** Add a new row to the field table (after `blocked-by`):
```markdown
| `protected-regions` | no | List of contiguous tail blocks the Builder preserves verbatim. Each entry has `marker`, `position` (always `tail`), `semantics` (`test-suite`, `entry-point`, `examples`, `benchmarks`), `starts-at` (1-indexed line reference, updated each generation). No mid-file regions -- split the file first |
```

**Change 3:** After the `## Test Seams` section (added in the previous PR) and before `## Lifecycle: Ephemeral by Default`, add a brief section:

```markdown
#### `## Protected Regions` (frontmatter, not a body section)

Protected regions are declared in the frontmatter, not as body sections. They represent contiguous tail blocks (inline test suites, main entry guards, example blocks) that the spec does not describe and the Builder does not touch. See the `protected-regions` frontmatter field above.

Protected regions are discovered during the takeover pre-flight phase (Step 0a) and recorded in the frontmatter. The Builder preserves them verbatim during generation and writes `managed-end-line` to the managed file header so the freshness checker can exclude them from hash comparison.
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/skills/concrete-spec/SKILL.md
git commit -m "feat: document protected-regions in concrete-spec skill"
```

---

### Task 7: Version bump and final verification

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Verify current version and bump**

Run: `grep '"version"' /home/lewdwig/git/unslop/unslop/.claude-plugin/plugin.json`
Expected: `"version": "0.24.0",`

If the version is already 0.25.0 or higher, skip this step. Otherwise, change to:
```json
  "version": "0.25.0",
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.25.0"
```
