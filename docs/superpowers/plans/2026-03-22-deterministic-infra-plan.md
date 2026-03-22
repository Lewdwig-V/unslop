# Deterministic Infrastructure Implementation Plan (Milestone B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mtime-based staleness with content hashing (dual-hash header), consolidate config into `config.json`, and add a `check-freshness` subcommand to the orchestrator for CI/pre-push enforcement.

**Architecture:** Three tightly coupled changes: (1) new dual-hash header format written by the generation skill, (2) `config.json` replacing `config.md` as single source of truth, (3) `check-freshness` subcommand in orchestrator.py using shared header parsing and hash computation. Commands and hooks updated to use the new format.

**Tech Stack:** Python 3.8+ (stdlib only — `hashlib`, `json`, `re`, `pathlib`), Claude Code plugin markdown, bash.

**Spec:** `docs/superpowers/specs/2026-03-22-deterministic-infra-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/scripts/orchestrator.py` | Modify | Add `compute_hash`, `parse_header`, `classify_file`, `check_freshness` + CLI subcommand |
| `tests/test_orchestrator.py` | Modify | Add tests for hash, header parsing, classification, check-freshness |
| `unslop/skills/generation/SKILL.md` | Modify | Update Section 2 (new header format + write order), config.md→config.json refs |
| `unslop/commands/init.md` | Modify | Write config.json, migration from config.md |
| `unslop/commands/generate.md` | Modify | Hash-based staleness, --force flag, config.json refs |
| `unslop/commands/sync.md` | Modify | Hash-based staleness, --force flag, config.json refs |
| `unslop/commands/status.md` | Modify | 4-state classification with conflict state |
| `unslop/hooks/scripts/load-context.sh` | Modify | Read config.json instead of config.md |

---

### Task 1: Orchestrator — `compute_hash` and `parse_header`

Foundation functions that everything else builds on.

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for compute_hash**

Add to `tests/test_orchestrator.py`:

```python
import hashlib
from orchestrator import compute_hash

def test_compute_hash_deterministic():
    result = compute_hash("hello world")
    assert len(result) == 12
    assert result == hashlib.sha256("hello world".encode()).hexdigest()[:12]

def test_compute_hash_strips_whitespace():
    result1 = compute_hash("hello world")
    result2 = compute_hash("  hello world  \n\n")
    assert result1 == result2

def test_compute_hash_empty_string():
    result = compute_hash("")
    assert len(result) == 12
```

- [ ] **Step 2: Implement compute_hash**

Add to `unslop/scripts/orchestrator.py`:

```python
import hashlib

def compute_hash(content: str) -> str:
    """SHA-256 hash of content, truncated to 12 hex chars.

    Content is stripped of leading/trailing whitespace before hashing
    to normalize across platforms.
    """
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:12]
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_orchestrator.py::test_compute_hash_deterministic tests/test_orchestrator.py::test_compute_hash_strips_whitespace tests/test_orchestrator.py::test_compute_hash_empty_string -v`
Expected: 3 PASS

- [ ] **Step 4: Write failing tests for parse_header**

Add to `tests/test_orchestrator.py`:

```python
from orchestrator import parse_header

def test_parse_header_python():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z",
        "",
        "def retry():",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/retry.py.spec.md"
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"
    assert result["generated"] == "2026-03-22T14:32:00Z"

def test_parse_header_typescript():
    lines = [
        "// @unslop-managed — do not edit directly. Edit src/api.ts.spec.md instead.",
        "// spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".ts")
    assert result["spec_path"] == "src/api.ts.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_html():
    lines = [
        "<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->",
        "<!-- spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z -->",
    ]
    result = parse_header("\n".join(lines), ".html")
    assert result["spec_path"] == "src/index.html.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_with_shebang():
    lines = [
        "#!/usr/bin/env python3",
        "# @unslop-managed — do not edit directly. Edit src/cli.py.spec.md instead.",
        "# spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/cli.py.spec.md"

def test_parse_header_missing():
    result = parse_header("def hello():\n    pass\n", ".py")
    assert result is None

def test_parse_header_old_format():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# Generated from spec at 2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/retry.py.spec.md"
    assert result["spec_hash"] is None
    assert result["output_hash"] is None
    assert result["old_format"] is True
```

- [ ] **Step 5: Implement parse_header**

Add to `unslop/scripts/orchestrator.py`:

```python
# Comment syntax by extension (matches generation skill table)
COMMENT_PREFIXES = {
    ".py": "#", ".rb": "#", ".sh": "#", ".yaml": "#", ".yml": "#",
    ".js": "//", ".ts": "//", ".jsx": "//", ".tsx": "//",
    ".java": "//", ".c": "//", ".cpp": "//", ".go": "//",
    ".rs": "//", ".swift": "//", ".kt": "//",
    ".lua": "--", ".sql": "--", ".hs": "--",
}
# HTML/CSS use multi-char delimiters handled separately


def parse_header(content: str, extension: str) -> dict | None:
    """Parse @unslop-managed header from a managed file.

    Reads the first 5 lines looking for the header markers.
    Returns dict with spec_path, spec_hash, output_hash, generated, old_format
    or None if no header found.
    """
    lines = content.split("\n")[:5]

    spec_path = None
    spec_hash = None
    output_hash = None
    generated = None
    old_format = False

    for line in lines:
        # Strip comment syntax
        stripped = line.strip()
        for prefix in ["#", "//", "--", "/*", "<!--"]:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
                break
        # Remove trailing comment closers
        for suffix in ["*/", "-->"]:
            if stripped.endswith(suffix):
                stripped = stripped[:-len(suffix)].strip()

        # Check for @unslop-managed line
        if "@unslop-managed" in stripped:
            # Extract spec path: between "Edit " and " instead"
            m = re.search(r"Edit (.+?) instead", stripped)
            if m:
                spec_path = m.group(1).strip(".")  # strip trailing period if any

        # Check for hash line
        hash_match = re.search(r"spec-hash:(\w{12})", stripped)
        if hash_match:
            spec_hash = hash_match.group(1)
            out_match = re.search(r"output-hash:(\w{12})", stripped)
            if out_match:
                output_hash = out_match.group(1)
            gen_match = re.search(r"generated:(\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

        # Check for old format
        if "Generated from spec at" in stripped and spec_hash is None:
            old_format = True
            gen_match = re.search(r"Generated from spec at (\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

    if spec_path is None:
        return None

    return {
        "spec_path": spec_path,
        "spec_hash": spec_hash,
        "output_hash": output_hash,
        "generated": generated,
        "old_format": old_format,
    }
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all existing tests PASS + 9 new tests PASS

- [ ] **Step 7: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add compute_hash and parse_header to orchestrator"
```

---

### Task 2: Orchestrator — `classify_file` and `check-freshness` Subcommand

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for classify_file**

```python
from orchestrator import classify_file, compute_hash

def test_classify_fresh(tmp_path):
    spec_content = "# retry spec\n\n## Behavior\nRetries stuff.\nWith backoff.\n"
    body = "def retry(): pass\n"
    spec_hash = compute_hash(spec_content)
    output_hash = compute_hash(body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-22T14:32:00Z\n"

    (tmp_path / "retry.py.spec.md").write_text(spec_content)
    (tmp_path / "retry.py").write_text(header + body)

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "fresh"

def test_classify_stale(tmp_path):
    old_spec = "# old spec\n\n## Behavior\nOld behavior.\nMore detail.\n"
    body = "def retry(): pass\n"
    spec_hash = compute_hash(old_spec)
    output_hash = compute_hash(body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-22T14:32:00Z\n"

    new_spec = "# new spec\n\n## Behavior\nNew behavior.\nDifferent detail.\n"
    (tmp_path / "retry.py.spec.md").write_text(new_spec)
    (tmp_path / "retry.py").write_text(header + body)

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "stale"

def test_classify_modified(tmp_path):
    spec_content = "# retry spec\n\n## Behavior\nRetries stuff.\nWith backoff.\n"
    original_body = "def retry(): pass\n"
    spec_hash = compute_hash(spec_content)
    output_hash = compute_hash(original_body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-22T14:32:00Z\n"

    modified_body = "def retry(): return True  # hotfix\n"
    (tmp_path / "retry.py.spec.md").write_text(spec_content)
    (tmp_path / "retry.py").write_text(header + modified_body)

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "modified"

def test_classify_conflict(tmp_path):
    old_spec = "# old spec\n\n## Behavior\nOld behavior.\nMore detail.\n"
    original_body = "def retry(): pass\n"
    spec_hash = compute_hash(old_spec)
    output_hash = compute_hash(original_body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-22T14:32:00Z\n"

    new_spec = "# new spec\n\n## Behavior\nNew behavior.\nDifferent detail.\n"
    modified_body = "def retry(): return True  # hotfix\n"
    (tmp_path / "retry.py.spec.md").write_text(new_spec)
    (tmp_path / "retry.py").write_text(header + modified_body)

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "conflict"

def test_classify_no_header(tmp_path):
    (tmp_path / "retry.py.spec.md").write_text("# spec\n\n## Behavior\nStuff.\nMore.\n")
    (tmp_path / "retry.py").write_text("def retry(): pass\n")

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "unmanaged"

def test_classify_old_header_format(tmp_path):
    spec_content = "# spec\n\n## Behavior\nStuff.\nMore.\n"
    (tmp_path / "retry.py.spec.md").write_text(spec_content)
    (tmp_path / "retry.py").write_text(
        "# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n"
        "# Generated from spec at 2026-03-22T14:32:00Z\n"
        "def retry(): pass\n"
    )

    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "old_format"
    assert "warning" in result
```

- [ ] **Step 2: Implement classify_file**

Add to `orchestrator.py`:

```python
def get_body_below_header(content: str) -> str:
    """Extract managed file content below the @unslop-managed header.

    Skips the first N lines that contain header markers, returns the rest.
    """
    lines = content.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        if "@unslop-managed" in line or "spec-hash:" in line or "output-hash:" in line or "Generated from spec at" in line:
            body_start = i + 1
        else:
            if body_start > 0:
                break
    return "\n".join(lines[body_start:])


def classify_file(managed_path: str, spec_path: str) -> dict:
    """Classify a managed file's staleness state using content hashing.

    Returns dict with: managed, spec, state, and optionally hint/warning.
    """
    managed = Path(managed_path)
    spec = Path(spec_path)
    ext = managed.suffix

    managed_content = managed.read_text(encoding="utf-8")
    spec_content = spec.read_text(encoding="utf-8")

    header = parse_header(managed_content, ext)

    if header is None:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "unmanaged"}

    if header.get("old_format"):
        return {
            "managed": str(managed_path), "spec": str(spec_path), "state": "old_format",
            "warning": "Old header format (no hashes). Regenerate to update."
        }

    current_spec_hash = compute_hash(spec_content)
    body = get_body_below_header(managed_content)
    current_output_hash = compute_hash(body)

    spec_match = (current_spec_hash == header["spec_hash"])
    output_match = (current_output_hash == header["output_hash"])

    if spec_match and output_match:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "fresh"}
    elif spec_match and not output_match:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "modified",
                "hint": "Code was edited directly while spec is unchanged."}
    elif not spec_match and output_match:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "stale"}
    else:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "conflict",
                "hint": "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."}
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 4: Write failing tests for check-freshness CLI**

```python
def test_check_freshness_all_fresh(tmp_path):
    from orchestrator import check_freshness
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
        + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "pass"
    assert all(f["state"] == "fresh" for f in result["files"])

def test_check_freshness_has_stale(tmp_path):
    from orchestrator import check_freshness
    old_spec = "# old\n\n## Behavior\nOld.\nMore.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(old_spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text("# new spec\n\n## Behavior\nNew.\nDifferent.\n")
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
        + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"

def test_cli_check_freshness(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
        + body
    )
    r = subprocess.run(
        [sys.executable, "unslop/scripts/orchestrator.py", "check-freshness", str(tmp_path)],
        capture_output=True, text=True
    )
    assert r.returncode == 0
    output = json.loads(r.stdout)
    assert output["status"] == "pass"
```

- [ ] **Step 5: Implement check_freshness and CLI**

Add to `orchestrator.py`:

```python
def check_freshness(directory: str) -> dict:
    """Check freshness of all managed files in directory.

    Returns dict with status (pass/fail), files list, and summary.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    specs = sorted(root.rglob("*.spec.md"))
    files = []

    for spec_path in specs:
        rel_spec = str(spec_path.relative_to(root))

        # Handle unit specs
        if spec_path.name.endswith(".unit.spec.md"):
            # Read ## Files section to get managed paths
            content = spec_path.read_text(encoding="utf-8")
            unit_files = []
            in_files = False
            for line in content.split("\n"):
                if re.match(r"^## Files", line):
                    in_files = True
                    continue
                if in_files:
                    if re.match(r"^## ", line):
                        break
                    m = re.match(r"^\s*-\s+`([^`]+)`", line)
                    if m:
                        unit_files.append(m.group(1))

            worst_state = "fresh"
            state_priority = {"fresh": 0, "old_format": 1, "stale": 2, "modified": 3, "conflict": 4, "unmanaged": 5}
            for uf in unit_files:
                managed_path = spec_path.parent / uf
                if managed_path.exists():
                    result = classify_file(str(managed_path), str(spec_path))
                    if state_priority.get(result["state"], 0) > state_priority.get(worst_state, 0):
                        worst_state = result["state"]
                else:
                    worst_state = "stale"  # file doesn't exist yet

            entry = {"managed": str(spec_path.parent.relative_to(root)), "spec": rel_spec, "state": worst_state}
            if worst_state == "conflict":
                entry["hint"] = "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."
            elif worst_state == "modified":
                entry["hint"] = "Code was edited directly while spec is unchanged."
            files.append(entry)
            continue

        # Per-file spec: derive managed path by stripping .spec.md
        managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
        managed_path = spec_path.parent / managed_name

        if not managed_path.exists():
            files.append({"managed": str(managed_path.relative_to(root)), "spec": rel_spec, "state": "stale"})
            continue

        result = classify_file(str(managed_path), str(spec_path))
        result["managed"] = str(managed_path.relative_to(root))
        result["spec"] = rel_spec
        files.append(result)

    all_fresh = all(f["state"] == "fresh" for f in files)

    # Build summary
    from collections import Counter
    counts = Counter(f["state"] for f in files)
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))

    return {"status": "pass" if all_fresh else "fail", "files": files, "summary": summary}
```

Add to `main()` CLI:

```python
    elif command == "check-freshness":
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        try:
            result = check_freshness(directory)
            print(json.dumps(result, indent=2))
            sys.exit(0 if result["status"] == "pass" else 1)
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add classify_file, check-freshness subcommand to orchestrator"
```

---

### Task 3: Update Generation Skill — New Header Format

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Replace Section 2 header format**

Read the current file. Replace the existing Section 2 ("Write the @unslop-managed Header") content with the new dual-hash format. Key changes:

1. Line 2 changes from `Generated from spec at <timestamp>` to `spec-hash:<12hex> output-hash:<12hex> generated:<timestamp>`
2. Add the write-order instructions after the examples:

```markdown
### Write Order

When generating a file, follow this exact sequence:
1. Generate the file body (everything below the header)
2. Apply `str.strip()` to the body, then compute its SHA-256 hash truncated to 12 hex chars → `output-hash`
3. Read the spec file content and compute its SHA-256 hash truncated to 12 hex chars → `spec-hash`
4. Write header line 1 (spec path — unchanged)
5. Write header line 2: `spec-hash:<hash> output-hash:<hash> generated:<ISO8601 UTC timestamp>`
6. Write the body

This ordering ensures the output-hash is computed before the header is written — the header is NOT included in the hash.
```

3. Update all examples to show the new line 2 format
4. Remove the placeholder comment about "when dual-hash staleness from Gap 2 is implemented" (currently in the incremental mode section)
5. Add to incremental mode section: "After applying targeted edits, re-hash the full body content and update the header with new `output-hash`, `spec-hash`, and timestamp."
6. Replace all references to `.unslop/config.md` with `.unslop/config.json` throughout the file

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: update generation skill with dual-hash header format and config.json refs"
```

---

### Task 4: Update Init Command — config.json

**Files:**
- Modify: `unslop/commands/init.md`

- [ ] **Step 1: Update init to write config.json**

Read the current file. Make these changes:

1. Change "overwrite `.unslop/config.md`" to "overwrite `.unslop/config.json`"
2. Replace the config.md writing step with config.json:

```markdown
**4. Write `.unslop/config.json`**

```json
{
  "test_command": "<detected or user-provided command>",
  "test_command_note": "Detected from <source>",
  "exclude_patterns": [],
  "exclude_patterns_note": "Additional directory patterns to exclude from discovery, beyond defaults"
}
```
```

3. Add migration step: "If `.unslop/config.md` exists, read its test command value, write it into `config.json`, then delete `config.md`. Include the deletion in the commit."

4. Update all other references to `config.md` in the file to `config.json`

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat: update init command to write config.json, migrate from config.md"
```

---

### Task 5: Update Status Command — 4-State Classification

**Files:**
- Modify: `unslop/commands/status.md`

- [ ] **Step 1: Replace mtime classification with hash-based**

Read the current file. Replace the classification logic with:

1. For each managed file, read the `@unslop-managed` header:
   - Extract `spec-hash` and `output-hash`
   - Compute current spec hash and current output hash
   - Classify using the 4-state table: fresh / stale / modified / conflict

2. Replace the three-state display rules with four-state:
   - **fresh** — no annotation needed
   - **stale** — show `(spec changed)`
   - **modified** — show `(edited directly)`
   - **conflict** — show `(spec and code both changed — regenerating will lose manual edits)`
   - **old_format** — show `(old header — regenerate to update)`

3. Add `conflict` to the display example

4. Update any `config.md` references to `config.json`

5. Remove all mtime comparison logic — staleness is now purely hash-based

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/status.md
git commit -m "feat: update status command with 4-state hash-based classification"
```

---

### Task 6: Update Generate and Sync Commands — Hash Staleness + --force

**Files:**
- Modify: `unslop/commands/generate.md`
- Modify: `unslop/commands/sync.md`

- [ ] **Step 1: Update generate.md**

Read the current file. Make these changes:

1. Replace the mtime-based staleness classification with hash-based:
   - Read the `@unslop-managed` header, extract `spec-hash` and `output-hash`
   - Compute current hashes and classify as fresh/stale/modified/conflict
   - Fresh: skip. Stale: regenerate. Modified: warn + require `--force` or confirmation. Conflict: block + require `--force` or confirmation.

2. Add `--force` to the argument-hint: `"[--force] [--force-ambiguous] [--incremental]"`

3. Add flag parsing: "If `$ARGUMENTS` contains `--force`, proceed with regeneration even on modified/conflict files."

4. Replace all `config.md` references with `config.json`

5. Remove all mtime comparison logic

- [ ] **Step 2: Update sync.md**

Same changes as generate.md:

1. Hash-based staleness instead of mtime
2. Add `--force` to argument-hint: `<file-path> [--force] [--force-ambiguous] [--incremental]`
3. Add `--force` flag parsing
4. Replace `config.md` references with `config.json`

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/generate.md unslop/commands/sync.md
git commit -m "feat: update generate and sync with hash-based staleness and --force flag"
```

---

### Task 7: Update load-context.sh Hook

**Files:**
- Modify: `unslop/hooks/scripts/load-context.sh`

- [ ] **Step 1: Update to read config.json**

Read the current file. Replace the config reading section. Change from reading `config.md` via `cat` to reading `config.json` via `jq`:

```bash
# Load config if it exists
config_file="$CLAUDE_PROJECT_DIR/.unslop/config.json"
if [ -f "$config_file" ]; then
  config=$(cat "$config_file")
  has_content=true
  output="$output

---
$config"
fi

# Fallback: check for legacy config.md
if [ ! -f "$config_file" ] && [ -f "$CLAUDE_PROJECT_DIR/.unslop/config.md" ]; then
  config=$(cat "$CLAUDE_PROJECT_DIR/.unslop/config.md")
  has_content=true
  output="$output

---
$config

Note: This project uses the legacy config.md format. Run /unslop:init to migrate to config.json."
fi
```

- [ ] **Step 2: Commit**

```bash
git add unslop/hooks/scripts/load-context.sh
git commit -m "feat: update load-context hook to read config.json with config.md fallback"
```

---

### Task 8: Bump Plugin Version

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.4.0**

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.4.0"
```

---

### Task 9: Verify and Integration Test

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (orchestrator + validate_spec, no regressions)

- [ ] **Step 2: Test check-freshness CLI**

Create test fixtures and verify:
```bash
mkdir -p /tmp/unslop-hash-test
python -c "
from unslop.scripts.orchestrator import compute_hash
spec = '# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n'
body = 'def thing(): pass\n'
sh = compute_hash(spec)
oh = compute_hash(body)
print(f'spec-hash: {sh}')
print(f'output-hash: {oh}')
with open('/tmp/unslop-hash-test/thing.py.spec.md', 'w') as f:
    f.write(spec)
with open('/tmp/unslop-hash-test/thing.py', 'w') as f:
    f.write(f'# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n')
    f.write(f'# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n')
    f.write(body)
"
python unslop/scripts/orchestrator.py check-freshness /tmp/unslop-hash-test/
rm -rf /tmp/unslop-hash-test
```
Expected: `"status": "pass"`, exit 0

- [ ] **Step 3: Verify generation skill has updated header format**

```bash
grep 'spec-hash' unslop/skills/generation/SKILL.md | head -5
```
Expected: new format examples with `spec-hash:` and `output-hash:`

- [ ] **Step 4: Verify no config.md references remain in commands/skills**

```bash
grep -r 'config\.md' unslop/commands/ unslop/skills/ || echo "No config.md references found"
```
Expected: "No config.md references found"

- [ ] **Step 5: Verify config.json references are present**

```bash
grep -r 'config\.json' unslop/commands/ unslop/skills/ unslop/hooks/ | head -10
```
Expected: multiple hits across init, generate, sync, generation skill, load-context

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address verification issues" || echo "Nothing to fix"
```
