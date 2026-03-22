# Project Principles Implementation Plan (Milestone D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `.unslop/principles.md` as a project-wide generation constraint document, tracked via `principles-hash` in managed file headers, with global staleness when principles change.

**Architecture:** `principles.md` is a freeform markdown file read by the generation skill as context. The `@unslop-managed` header gains an optional `principles-hash` field on line 2. `classify_file` gains an optional `project_root` parameter for principles checking. Init creates the file, commands enforce it.

**Tech Stack:** Python 3.8+ (stdlib only), Claude Code plugin markdown.

**Spec:** `docs/superpowers/specs/2026-03-22-project-principles-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/scripts/orchestrator.py` | Modify | `parse_header` extracts `principles_hash`; `classify_file` gains `project_root` param; `check_freshness` passes root |
| `tests/test_orchestrator.py` | Modify | Tests for principles-hash parsing, classification, check-freshness |
| `unslop/skills/generation/SKILL.md` | Modify | Read principles, inject as context, write principles-hash in header |
| `unslop/commands/init.md` | Modify | Create starter principles.md |
| `unslop/commands/change.md` | Modify | Load principles in tactical flow |
| `unslop/commands/status.md` | Modify | Show `(principles changed)` annotation |

---

### Task 1: Orchestrator -- parse_header + classify_file Principles Support

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for principles-hash parsing**

```python
def test_parse_header_with_principles_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7f2e1b8a9c04 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"
    assert result["principles_hash"] == "7f2e1b8a9c04"

def test_parse_header_without_principles_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["principles_hash"] is None
```

- [ ] **Step 2: Update parse_header to extract principles_hash**

In `parse_header`, after the `output-hash` extraction, add:

```python
        prin_match = re.search(r"principles-hash:([0-9a-f]{12})", stripped)
        if prin_match:
            principles_hash = prin_match.group(1)
```

Add `principles_hash` to the return dict (default `None`).

- [ ] **Step 3: Write failing tests for classify_file with principles**

```python
def test_classify_principles_stale(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    principles = "# Principles\n\n## Style\n- Use typed errors\n"
    old_prin_hash = compute_hash("old principles content")
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{old_prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_text(principles)

    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "stale"
    assert "principles" in result.get("hint", "").lower()

def test_classify_principles_fresh(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    principles = "# Principles\n\n## Style\n- Use typed errors\n"
    prin_hash = compute_hash(principles)
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_text(principles)

    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "fresh"

def test_classify_principles_deleted(tmp_path):
    """Files with principles-hash but no principles.md should be stale."""
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:abc123def456 generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    # No principles.md exists

    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "stale"
    assert "principles" in result.get("hint", "").lower()

def test_classify_no_project_root_skips_principles(tmp_path):
    """Without project_root, principles check is skipped (backwards compat)."""
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    old_prin_hash = compute_hash("old principles")
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{old_prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)

    # No project_root passed -- principles check skipped
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"))
    assert result["state"] == "fresh"  # would be stale if principles were checked
```

- [ ] **Step 4: Update classify_file**

Add `project_root: str | None = None` parameter. After the existing spec/output hash comparison, add:

```python
    # Principles check (only when project_root is provided)
    if project_root is not None and header.get("principles_hash") is not None:
        principles_path = Path(project_root) / ".unslop" / "principles.md"
        if principles_path.exists():
            current_prin_hash = compute_hash(principles_path.read_text(encoding="utf-8"))
            if current_prin_hash != header["principles_hash"]:
                result["hint"] = (result.get("hint", "") + " Principles changed.").strip()
                if result["state"] == "fresh":
                    result["state"] = "stale"
                return result
        else:
            # principles.md was deleted -- file is stale
            result["hint"] = (result.get("hint", "") + " Principles removed.").strip()
            if result["state"] == "fresh":
                result["state"] = "stale"
            return result
```

Update `check_freshness` to pass `project_root=str(root)` to `classify_file`.

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add principles-hash to parse_header and classify_file"
```

---

### Task 2: Update Generation Skill -- Principles Context + Header

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add principles to permitted reads**

In both Mode A and Mode B permitted reads lists, add:
```
- `.unslop/principles.md` (project-wide generation constraints, if it exists)
```

- [ ] **Step 2: Add principles context injection to Phase 0b**

Before the ambiguity detection prompt in Phase 0b, add:

```markdown
**Before running ambiguity detection**, check if `.unslop/principles.md` exists. If it does, read it and use it as additional context. Check whether the spec's constraints conflict with any principle. Include principles context when evaluating ambiguity -- a spec phrase that would be ambiguous without principles may be unambiguous with them (e.g., "handle errors" is ambiguous alone, but if principles say "errors must be typed", the ambiguity is resolved).
```

- [ ] **Step 3: Update header format in Section 2**

Update the header format description and examples to include the optional `principles-hash` field:

Line 2 format: `spec-hash:<12hex> output-hash:<12hex> [principles-hash:<12hex>] generated:<ISO8601>`

Add to the Write Order section:
```
3b. If `.unslop/principles.md` exists, hash its content -> `principles-hash`
5. Write header line 2: `spec-hash:<hash> output-hash:<hash> principles-hash:<hash> generated:<timestamp>`
```

Update the Python example to show the principles-hash field.

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add principles context and principles-hash to generation skill"
```

---

### Task 3: Update Init Command -- Create Starter Principles

**Files:**
- Modify: `unslop/commands/init.md`

- [ ] **Step 1: Add principles creation step**

After the config.json writing step and before the alignment-summary step, add:

```markdown
**5. Create `.unslop/principles.md` (optional)**

Ask the user: "Would you like to define project principles? These are non-negotiable constraints that apply to all generated code (e.g., error handling style, architecture patterns)."

If yes, create `.unslop/principles.md` with a starter template:

```markdown
# Project Principles

<!-- Define non-negotiable constraints for all generated code. -->
<!-- These are enforced during every generation cycle. -->

## Architecture
- [Add architectural constraints here]

## Error Handling
- [Add error handling rules here]

## Style
- [Add style requirements here]
```

Present the template to the user for editing.

If no, skip. Principles are optional.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat: add principles.md creation to init command"
```

---

### Task 4: Update Change Command -- Load Principles in Tactical Flow

**Files:**
- Modify: `unslop/commands/change.md`

- [ ] **Step 1: Add principles loading**

In the tactical flow (step 5), after "Read the current spec file and the current managed file", add:

"Read `.unslop/principles.md` if it exists. Apply principles as constraints alongside the spec when patching the managed file. The tactical change must not violate any project principle."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/change.md
git commit -m "feat: load principles in tactical change flow"
```

---

### Task 5: Update Status Command -- Principles Annotation

**Files:**
- Modify: `unslop/commands/status.md`

- [ ] **Step 1: Add principles-stale display**

After the existing classification logic, add:

"If a file's `principles-hash` in the header does not match the current `.unslop/principles.md` hash, add `(principles changed)` to the status annotation. This is additive -- a file can show `modified (principles changed)` or `conflict (principles changed)`. If `principles.md` has been deleted but files still have `principles-hash`, annotate as `(principles removed)`."

Update the display example to include a principles-stale entry.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/status.md
git commit -m "feat: add principles-stale annotation to status command"
```

---

### Task 6: Bump Version + Verify

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.6.0**

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check unslop/scripts/ tests/`
Expected: clean

- [ ] **Step 4: Verify principles-hash in parse_header**

```bash
grep 'principles.hash' unslop/scripts/orchestrator.py | head -5
```

- [ ] **Step 5: Verify generation skill references principles**

```bash
grep -i 'principles' unslop/skills/generation/SKILL.md | head -5
```

- [ ] **Step 6: Commit and finalize**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.6.0"
```
