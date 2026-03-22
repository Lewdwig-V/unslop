# Change Requests Implementation Plan (Milestone C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured change request workflow — `*.change.md` sidecars, `/unslop:change` command, Phase 0c in the generation skill, and check-freshness/status integration — enabling surgical fixes that reconcile back to the spec.

**Architecture:** New `parse_change_file()` in orchestrator handles deterministic parsing. The `/unslop:change` command creates entries. The generation skill's Phase 0c consumes them during generation. `check-freshness` overlays `pending_changes` on the existing 4-state classification. Delete-on-promotion lifecycle keeps the workspace clean.

**Tech Stack:** Python 3.8+ (stdlib only), Claude Code plugin markdown, existing orchestrator infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-22-change-requests-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/scripts/orchestrator.py` | Modify | Add `parse_change_file()`, update `check_freshness()` for pending_changes overlay |
| `tests/test_orchestrator.py` | Modify | Tests for parse_change_file and check-freshness integration |
| `unslop/commands/change.md` | Create | `/unslop:change` command |
| `unslop/skills/generation/SKILL.md` | Modify | Add Phase 0c (change request consumption) |
| `unslop/commands/status.md` | Modify | Add pending changes display |
| `unslop/commands/takeover.md` | Modify | Add change.md guard |
| `unslop/commands/generate.md` | Modify | Note about Phase 0c consumption |
| `unslop/commands/sync.md` | Modify | Note about Phase 0c consumption |

---

### Task 1: Orchestrator — `parse_change_file`

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_orchestrator.py`:

```python
from orchestrator import parse_change_file

def test_parse_change_file_single_pending():
    content = """<!-- unslop-changes v1 -->
### [pending] Add jitter to backoff — 2026-03-22T15:00:00Z

Backoff should include random jitter.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["status"] == "pending"
    assert result[0]["description"] == "Add jitter to backoff"
    assert result[0]["timestamp"] == "2026-03-22T15:00:00Z"
    assert "jitter" in result[0]["body"]

def test_parse_change_file_multiple_entries():
    content = """<!-- unslop-changes v1 -->
### [pending] Add jitter — 2026-03-22T15:00:00Z

Add jitter to backoff.

---

### [tactical] Fix API endpoint — 2026-03-22T16:30:00Z

Update base URL.

---
"""
    result = parse_change_file(content)
    assert len(result) == 2
    assert result[0]["status"] == "pending"
    assert result[1]["status"] == "tactical"

def test_parse_change_file_empty():
    content = "<!-- unslop-changes v1 -->\n"
    result = parse_change_file(content)
    assert result == []

def test_parse_change_file_no_marker():
    content = "### [pending] Something — 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
    result = parse_change_file(content)
    assert result == []

def test_parse_change_file_malformed_entry(capsys):
    content = """<!-- unslop-changes v1 -->
### Missing status marker — 2026-03-22T15:00:00Z

Body here.

---

### [pending] Valid entry — 2026-03-22T16:00:00Z

Valid body.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["status"] == "pending"
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "malformed" in captured.err.lower()

def test_parse_change_file_no_timestamp():
    content = """<!-- unslop-changes v1 -->
### [pending] No timestamp entry

Body without timestamp.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["timestamp"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::test_parse_change_file_single_pending -v`
Expected: FAIL — `parse_change_file` not importable

- [ ] **Step 3: Implement parse_change_file**

Add to `unslop/scripts/orchestrator.py`:

```python
def parse_change_file(content: str) -> list[str]:
    """Parse stacked change entries from a *.change.md file.

    Returns list of dicts with: status, description, timestamp, body.
    Requires <!-- unslop-changes v1 --> format marker on first line.
    Malformed entries are skipped with a stderr warning.
    """
    lines = content.split("\n")
    if not lines or "unslop-changes" not in lines[0]:
        return []

    entries = []
    current_entry = None

    for line in lines[1:]:  # skip format marker
        # Check for entry heading
        heading_match = re.match(
            r'^### \[(\w+)\]\s+(.+?)(?:\s+—\s+(\S+))?\s*$', line
        )
        if heading_match:
            if current_entry is not None:
                current_entry["body"] = current_entry["body"].strip()
                entries.append(current_entry)
            status = heading_match.group(1)
            if status not in ("pending", "tactical"):
                print(
                    f'{{"warning": "Malformed change entry: unknown status [{status}]"}}',
                    file=sys.stderr
                )
                current_entry = None
                continue
            current_entry = {
                "status": status,
                "description": heading_match.group(2).strip(),
                "timestamp": heading_match.group(3),
                "body": "",
            }
        elif line.strip() == "---":
            if current_entry is not None:
                current_entry["body"] = current_entry["body"].strip()
                entries.append(current_entry)
                current_entry = None
        elif current_entry is not None:
            current_entry["body"] += line + "\n"
        elif line.strip().startswith("### ") and current_entry is None:
            # Heading that didn't match the expected format
            print(
                f'{{"warning": "Malformed change entry heading: {line!r}"}}',
                file=sys.stderr
            )

    # Handle last entry without trailing ---
    if current_entry is not None:
        current_entry["body"] = current_entry["body"].strip()
        entries.append(current_entry)

    return entries
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add parse_change_file to orchestrator"
```

---

### Task 2: Orchestrator — `check-freshness` Pending Changes Overlay

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
def test_check_freshness_pending_changes(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n"
        "### [pending] Add feature — 2026-03-22T15:00:00Z\n\nAdd a feature.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"  # pending changes = non-fresh
    file_entry = result["files"][0]
    assert file_entry["state"] == "fresh"  # hash state is fresh
    assert "pending_changes" in file_entry
    assert file_entry["pending_changes"]["count"] == 1
    assert file_entry["pending_changes"]["pending"] == 1

def test_check_freshness_no_changes(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "pass"
    assert "pending_changes" not in result["files"][0]
```

- [ ] **Step 2: Implement pending changes overlay in check_freshness**

In `check_freshness()`, after the existing spec classification loop, add a scan for `*.change.md` files:

```python
    # Scan for pending change requests
    change_files = sorted(root.rglob("*.change.md"))
    for change_path in change_files:
        content = change_path.read_text(encoding="utf-8")
        entries = parse_change_file(content)
        if not entries:
            continue

        # Find the corresponding file entry
        # Derive managed file path: strip .change.md
        managed_name = re.sub(r"\.change\.md$", "", change_path.name)
        managed_rel = str((change_path.parent / managed_name).relative_to(root))

        counts = {"count": len(entries), "pending": 0, "tactical": 0}
        for e in entries:
            if e["status"] in counts:
                counts[e["status"]] += 1

        # Find and update the matching file entry
        for f in files:
            if f["managed"] == managed_rel:
                f["pending_changes"] = counts
                f["hint"] = f"{counts['count']} change request(s) awaiting processing."
                break

    # Update all_fresh check to account for pending changes
    all_fresh = all(
        f["state"] == "fresh" and "pending_changes" not in f
        for f in files
    )
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add pending_changes overlay to check-freshness"
```

---

### Task 3: `/unslop:change` Command

**Files:**
- Create: `unslop/commands/change.md`

- [ ] **Step 1: Write the command**

```yaml
---
description: Record a change request for a managed file
argument-hint: <file-path> "description" [--tactical]
---
```

Command body:

```markdown
**Parse arguments:** `$ARGUMENTS` contains the file path, an optional description in quotes, and an optional `--tactical` flag. Extract the file path (first argument not starting with `--` and not in quotes), the description (quoted string), and the flag.

**1. Verify prerequisites**

Check that `.unslop/` exists. If not: "unslop is not initialized. Run `/unslop:init` first."

Check that the target file exists and has an `@unslop-managed` header. If not managed: "File is not managed by unslop. Run `/unslop:takeover` or `/unslop:spec` first."

Read the `@unslop-managed` header to get the spec path. Check that the spec file exists. If not: "Spec not found. The managed file references a spec that no longer exists."

If the file is in `conflict` state (both spec-hash and output-hash don't match): "File has unresolved conflicts. Resolve with `/unslop:sync --force` before adding changes."

**2. Check for existing changes**

If a `*.change.md` sidecar already exists with 5 or more entries, warn: "This file has N pending changes. Consider running `/unslop:generate` to process them before adding more."

**3. Get the description**

If a description was provided in the arguments, use it. If not, ask the user to describe the change intent.

**4. Write the entry**

Determine the status: `[tactical]` if `--tactical` was passed, `[pending]` otherwise.

If the `*.change.md` sidecar doesn't exist, create it with the format marker:
```
<!-- unslop-changes v1 -->
```

Append the new entry:
```
### [status] description — ISO8601-UTC-timestamp

[description or elaborated body]

---
```

**5. Execute or defer**

If `--tactical`: Execute the tactical flow immediately:
1. Read the current spec and current managed file
2. Use the **unslop/generation** skill in incremental mode (Mode B) to patch the managed file based on the change intent
3. Run tests from `.unslop/config.json`
4. If tests pass: draft a spec update that captures the change, present to user for approval
5. On approval: delete the entry from change.md (delete the file if empty), update hashes, commit
6. On rejection: revert the code change, inform user the entry stays in change.md for manual resolution

If `[pending]` (default): Inform the user:
> "Change recorded in `<file>.change.md`. Run `/unslop:generate` or `/unslop:sync <file>` to apply."
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/change.md
git commit -m "feat: add /unslop:change command"
```

---

### Task 4: Generation Skill — Phase 0c

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add Phase 0c after Phase 0b**

Read the file. Insert the following after Phase 0b (Ambiguity Detection) and before Section 1:

```markdown
### Phase 0c: Change Request Consumption

After validation passes, check for a `*.change.md` sidecar file for the target managed file (same directory, same base name with `.change.md` extension).

If no change file exists, skip to Section 1.

If change entries exist:

**1. Conflict detection (model-driven):** Before processing, review each entry's intent against the current spec. If any entry contradicts the spec (e.g., spec says "backoff base is 2", entry says "change to 1.5"), surface the conflict to the user:

> "Change request conflicts with current spec: [quote entry] vs [quote spec]. Resolve by editing the spec or the change entry before proceeding."

Stop generation until the conflict is resolved.

**2. Classify and order entries:**
- Process `[pending]` entries first (they update the spec)
- Then `[tactical]` entries (they patch code and propose spec updates)

**3. For each `[pending]` entry:**
- Propose a spec update that captures the entry's intent
- Present to the user: "This change request suggests updating the spec as follows: [diff]. Approve?"
- On approval: apply the spec update, then generate code from the updated spec
- On rejection: skip this entry, leave it in change.md

**4. For each `[tactical]` entry:**
- Patch the managed file via incremental mode (Mode B) based on the entry's intent
- Run tests
- If green: propose a spec update reflecting the code change
- Present to user: "I've patched the code and updated the spec to match. Review?"
- On approval: entry is promoted
- On rejection: revert code change, entry stays

**5. After processing:**
- Delete each successfully promoted entry from the change.md file
- If the file is now empty (no remaining entries), delete it entirely
- Compute final output-hash from the managed file body
- Each promoted entry is committed individually (sequential, not atomic)
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Phase 0c change request consumption to generation skill"
```

---

### Task 5: Update Status Command — Pending Changes Display

**Files:**
- Modify: `unslop/commands/status.md`

- [ ] **Step 1: Add change.md awareness**

Read the file. Add after the existing classification logic:

"After classifying each managed file, check for a corresponding `*.change.md` sidecar (same directory, same base name with `.change.md` extension). If present, read it and count entries by status. Display a summary line indented below the file entry:

```
           Δ N pending changes [X pending, Y tactical]
```

The `Δ` indicator appears regardless of the file's staleness state."

Update the display example to include the change indicator.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/status.md
git commit -m "feat: add pending changes display to status command"
```

---

### Task 6: Update Takeover Command — Change.md Guard

**Files:**
- Modify: `unslop/commands/takeover.md`

- [ ] **Step 1: Add guard**

Read the file. After the prerequisites check (file exists, .unslop/ initialized), add:

"Check for a `*.change.md` sidecar for the target file. If one exists with pending entries, warn: 'This file has N pending changes that will be lost during takeover. Process them first with `/unslop:sync` or use `--force` to proceed.' Require `--force` to continue."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/takeover.md
git commit -m "feat: add change.md guard to takeover command"
```

---

### Task 7: Update Generate and Sync Commands — Change.md Notes

**Files:**
- Modify: `unslop/commands/generate.md`
- Modify: `unslop/commands/sync.md`

- [ ] **Step 1: Add Phase 0c notes**

In both files, add a note after the generation skill reference:

For generate.md: "The generation skill's Phase 0c automatically processes any pending `*.change.md` entries for each file being regenerated. No additional command-level logic is needed — the skill handles change request consumption, conflict detection, and promotion."

For sync.md: Same note, scoped to "the target file."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md unslop/commands/sync.md
git commit -m "feat: add Phase 0c change consumption notes to generate and sync commands"
```

---

### Task 8: Bump Plugin Version

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.5.0**

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.5.0"
```

---

### Task 9: Verify and Integration Test

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (orchestrator + validate_spec, no regressions)

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check unslop/scripts/ tests/`
Expected: no errors

- [ ] **Step 3: Test parse_change_file CLI-style**

```bash
python -c "
import sys; sys.path.insert(0, 'unslop/scripts')
from orchestrator import parse_change_file
content = '''<!-- unslop-changes v1 -->
### [pending] Test change — 2026-03-22T15:00:00Z

Test body.

---
'''
result = parse_change_file(content)
print(f'Entries: {len(result)}, Status: {result[0][\"status\"]}')
assert len(result) == 1
assert result[0]['status'] == 'pending'
print('OK')
"
```

- [ ] **Step 4: Verify command exists with valid frontmatter**

```bash
head -4 unslop/commands/change.md
```
Expected: YAML frontmatter with `description` field

- [ ] **Step 5: Verify Phase 0c exists in generation skill**

```bash
grep 'Phase 0c' unslop/skills/generation/SKILL.md
```
Expected: at least one match

- [ ] **Step 6: Verify no config.md references remain**

```bash
grep -r 'config\.md' unslop/commands/ unslop/skills/ | grep -v 'fallback\|legacy\|migration\|config\.md.*exists' || echo "Clean"
```

- [ ] **Step 7: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address verification issues" || echo "Nothing to fix"
```
