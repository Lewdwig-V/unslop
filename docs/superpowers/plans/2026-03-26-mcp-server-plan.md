# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose 10 orchestrator functions as MCP tools with typed schemas via a plugin-bundled stdio server.

**Architecture:** Single `mcp_server.py` file using the `FastMCP` pattern from the official MCP Python SDK. Each tool is a decorated function that calls existing orchestrator code and returns JSON. The server is declared in `.mcp.json` and auto-starts on session. Graceful degradation if `mcp` package is not installed.

**Tech Stack:** Python 3.8+, `mcp` (MCP Python SDK), `FastMCP`, pytest

---

## File Structure

| File | Responsibility |
|---|---|
| `unslop/scripts/mcp_server.py` | MCP server with 10 tools wrapping orchestrator functions |
| `unslop/.claude-plugin/.mcp.json` | Plugin MCP server declaration |
| `tests/test_mcp_server.py` | Tool dispatch and error handling tests |
| `unslop/commands/init.md` | Add `mcp` dependency check |
| `unslop/.claude-plugin/plugin.json` | Version bump |

---

### Task 1: Create the MCP server with first 2 tools (freshness) -- TDD

**Files:**
- Create: `unslop/scripts/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for the two freshness tools**

Add `tests/test_mcp_server.py`:

```python
"""Tests for MCP server tool dispatch.

These tests call the tool functions directly (not via MCP protocol)
to verify they correctly wrap the orchestrator functions.
"""

import json

from unslop.scripts.mcp_server import (
    unslop_check_freshness,
    unslop_classify_file,
)
from unslop.scripts.orchestrator import compute_hash


def test_check_freshness_empty_dir(tmp_path):
    """check_freshness on a dir with no specs returns pass."""
    (tmp_path / ".unslop").mkdir()
    result = json.loads(unslop_check_freshness(directory=str(tmp_path)))
    assert result["status"] == "pass"
    assert result["files"] == []


def test_check_freshness_error_on_missing_dir():
    """check_freshness on a nonexistent dir returns error."""
    result = json.loads(unslop_check_freshness(directory="/nonexistent/path"))
    assert "error" in result


def test_classify_file_fresh(tmp_path):
    """classify_file returns fresh for matching hashes."""
    spec = tmp_path / "foo.py.spec.md"
    spec_content = "# foo spec\n"
    spec.write_text(spec_content)

    spec_hash = compute_hash(spec_content)
    managed_body = "# managed code"
    output_hash = compute_hash(managed_body)

    managed = tmp_path / "foo.py"
    managed.write_text(
        f"# @unslop-managed -- do not edit directly. Edit foo.py.spec.md instead.\n"
        f"# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-26T12:00:00Z\n"
        f"{managed_body}\n"
    )

    result = json.loads(unslop_classify_file(
        managed_path=str(managed),
        spec_path=str(spec),
    ))
    assert result["state"] == "fresh"


def test_classify_file_missing_managed():
    """classify_file returns error for missing managed file."""
    result = json.loads(unslop_classify_file(
        managed_path="/nonexistent",
        spec_path="/also/nonexistent",
    ))
    assert result["state"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_mcp_server.py -v`
Expected: FAIL -- import error (mcp_server.py doesn't exist yet)

- [ ] **Step 3: Create the MCP server with freshness tools**

Create `unslop/scripts/mcp_server.py`:

```python
"""MCP server exposing unslop orchestrator tools.

Run as: python3 -m unslop.scripts.mcp_server
Or auto-started by Claude Code via .mcp.json

The tool functions are plain Python functions that can be imported and tested
without the mcp package. The FastMCP wiring only happens at module level if
mcp is available, and at __main__ time for the server entry point.
"""

from __future__ import annotations

import json
import sys

from .freshness.checker import check_freshness, classify_file
from .dependencies.graph import build_order_from_dir, resolve_deps
from .planning.ripple import ripple_check
from .planning.deep_sync import compute_deep_sync_plan
from .planning.bulk_sync import compute_bulk_sync_plan
from .validation.symbol_audit import audit_symbols, check_drift
from .core.spec_discovery import discover_files

# MCP wiring is optional -- tools work as plain functions without it
_HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP

    mcp_app = FastMCP("unslop")
    _HAS_MCP = True
except ImportError:
    mcp_app = None


def _tool(func):
    """Register as MCP tool if mcp is available, otherwise return unchanged."""
    if _HAS_MCP and mcp_app is not None:
        return mcp_app.tool()(func)
    return func


# --- Freshness & Status ---


@_tool
def unslop_check_freshness(
    directory: str = ".",
    exclude_dirs: list[str] | None = None,
) -> str:
    """Check freshness of all managed files. Returns staleness state, blocked constraints, pending changes, and ghost-staleness."""
    try:
        exclude = exclude_dirs or [".unslop", "node_modules"]
        result = check_freshness(directory, exclude_dirs=exclude)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_classify_file(
    managed_path: str,
    spec_path: str,
    project_root: str = ".",
) -> str:
    """Classify a single managed file's staleness state."""
    try:
        result = classify_file(managed_path, spec_path, project_root=project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Dependency Resolution ---


@_tool
def unslop_build_order(directory: str = ".") -> str:
    """Topologically sorted spec list from depends-on frontmatter."""
    try:
        result = build_order_from_dir(directory)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_resolve_deps(spec_path: str, project_root: str = ".") -> str:
    """Transitive dependency list for a single spec file."""
    try:
        result = resolve_deps(spec_path, project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Planning ---


@_tool
def unslop_ripple_check(spec_paths: list[str], project_root: str = ".") -> str:
    """Analyze the blast radius of spec changes across abstract specs, concrete specs, and managed files."""
    try:
        result = ripple_check(spec_paths, project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_deep_sync_plan(
    file_path: str,
    project_root: str = ".",
    force: bool = False,
) -> str:
    """Compute a sync plan for a single file (spec or managed) with dependency ordering."""
    try:
        result = compute_deep_sync_plan(file_path, project_root, force=force)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_bulk_sync_plan(
    project_root: str = ".",
    force: bool = False,
    max_batch_size: int = 8,
) -> str:
    """Compute a sync plan for all stale files with parallel batch grouping."""
    try:
        result = compute_bulk_sync_plan(project_root, force=force, max_batch_size=max_batch_size)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Validation ---


@_tool
def unslop_symbol_audit(
    original_path: str,
    generated_path: str,
    removed: list[str] | None = None,
) -> str:
    """Compare public symbols between two versions of a file. Returns added, removed, and matched symbols."""
    try:
        result = audit_symbols(original_path, generated_path, removed=removed)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_check_drift(
    old_path: str,
    new_path: str,
    affected_symbols: list[str],
) -> str:
    """Check symbol-level drift between two file versions. Flags changes to symbols NOT in the affected list."""
    try:
        result = check_drift(old_path, new_path, affected_symbols)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Discovery ---


@_tool
def unslop_discover(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> str:
    """Find source files and test files in a directory."""
    try:
        result = discover_files(directory, extensions=extensions, extra_excludes=extra_excludes)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Entry point ---

if __name__ == "__main__":
    if not _HAS_MCP or mcp_app is None:
        print("mcp package not installed. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)
    mcp_app.run(transport="stdio")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_mcp_server.py -v`
Expected: All 4 tests PASS

Note: The tool functions are plain Python functions that work without the `mcp` package. The `_tool` decorator is a no-op when `mcp` is not installed.

- [ ] **Step 5: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/scripts/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: MCP server with 10 orchestrator tools"
```

---

### Task 2: Add .mcp.json plugin declaration

**Files:**
- Create: `unslop/.claude-plugin/.mcp.json`

- [ ] **Step 1: Create the MCP server declaration**

Create `unslop/.claude-plugin/.mcp.json`:

```json
{
  "mcpServers": {
    "unslop": {
      "command": "python3",
      "args": ["-m", "unslop.scripts.mcp_server"],
      "cwd": "${PROJECT_ROOT}"
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/.claude-plugin/.mcp.json
git commit -m "feat: add .mcp.json for plugin MCP server auto-registration"
```

---

### Task 3: Add more tool tests (dependency, planning, validation, discovery)

**Files:**
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Add tests for remaining tools**

Append to `tests/test_mcp_server.py`:

```python
from unslop.scripts.mcp_server import (
    unslop_build_order,
    unslop_resolve_deps,
    unslop_ripple_check,
    unslop_deep_sync_plan,
    unslop_bulk_sync_plan,
    unslop_symbol_audit,
    unslop_check_drift,
    unslop_discover,
)


def test_build_order_empty_dir(tmp_path):
    """build_order on empty dir returns empty list."""
    result = json.loads(unslop_build_order(directory=str(tmp_path)))
    assert result == []


def test_build_order_error_on_missing_dir():
    result = json.loads(unslop_build_order(directory="/nonexistent"))
    assert "error" in result


def test_resolve_deps_no_deps(tmp_path):
    """resolve_deps for a spec with no depends-on returns empty list."""
    spec = tmp_path / "foo.py.spec.md"
    spec.write_text("# foo spec\n")
    result = json.loads(unslop_resolve_deps(
        spec_path=str(spec),
        project_root=str(tmp_path),
    ))
    assert result == []


def test_ripple_check_single_spec(tmp_path):
    """ripple_check on a single spec with no deps."""
    spec = tmp_path / "foo.py.spec.md"
    spec.write_text("# foo spec\n")
    result = json.loads(unslop_ripple_check(
        spec_paths=[str(spec.relative_to(tmp_path))],
        project_root=str(tmp_path),
    ))
    assert "error" not in result
    assert "input_specs" in result or "layers" in result or isinstance(result, dict)


def test_deep_sync_plan_error_on_missing():
    result = json.loads(unslop_deep_sync_plan(
        file_path="nonexistent.spec.md",
        project_root="/nonexistent",
    ))
    assert "error" in result


def test_bulk_sync_plan_empty_project(tmp_path):
    (tmp_path / ".unslop").mkdir()
    result = json.loads(unslop_bulk_sync_plan(project_root=str(tmp_path)))
    assert "error" not in result


def test_symbol_audit_error_on_missing():
    result = json.loads(unslop_symbol_audit(
        original_path="/nonexistent/a.py",
        generated_path="/nonexistent/b.py",
    ))
    assert "error" in result


def test_check_drift_error_on_missing():
    result = json.loads(unslop_check_drift(
        old_path="/nonexistent/a.py",
        new_path="/nonexistent/b.py",
        affected_symbols=["foo"],
    ))
    assert "error" in result


def test_discover_finds_files(tmp_path):
    """discover finds Python files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# main\n")
    result = json.loads(unslop_discover(directory=str(tmp_path), extensions=[".py"]))
    assert any("main.py" in f for f in result)


def test_discover_error_on_missing():
    result = json.loads(unslop_discover(directory="/nonexistent"))
    assert "error" in result
```

- [ ] **Step 2: Update imports at top of test file**

The imports from Step 1 (Task 1) only imported `unslop_check_freshness` and `unslop_classify_file`. Add the remaining imports at the location shown in the test code above.

- [ ] **Step 3: Run all MCP tests**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_mcp_server.py -v`
Expected: All 15 tests PASS

- [ ] **Step 4: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd /home/lewdwig/git/unslop
git add tests/test_mcp_server.py
git commit -m "test: add tests for all 10 MCP tools"
```

---

### Task 4: Update init command + version bump

**Files:**
- Modify: `unslop/commands/init.md`
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Add MCP dependency check to init command**

In `unslop/commands/init.md`, find the section where `.unslop/config.json` is created. After it, add a note about the MCP dependency:

```markdown
**MCP server dependency:** Check if the `mcp` Python package is installed:

```bash
python3 -c "import mcp" 2>/dev/null && echo "MCP available" || echo "MCP not available"
```

If not available, inform the user:

> "Optional: install the `mcp` package (`pip install mcp`) to enable MCP tools. Without it, the orchestrator CLI still works but tools won't auto-register in Claude Code."
```

- [ ] **Step 2: Bump version**

In `unslop/.claude-plugin/plugin.json`, change version from `0.31.0` to `0.32.0`.

- [ ] **Step 3: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/commands/init.md unslop/.claude-plugin/plugin.json
git commit -m "chore: add MCP dependency check to init, bump to v0.32.0"
```

---

### Task 5: Note MCP tools in status and generate commands

**Files:**
- Modify: `unslop/commands/status.md`
- Modify: `unslop/commands/generate.md`

- [ ] **Step 1: Update status command**

In `unslop/commands/status.md`, find the section that describes how to check freshness (the `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py check-freshness` reference). Add a note before or after it:

```markdown
**Preferred:** If the MCP server is running, use the `unslop_check_freshness` tool directly instead of shelling out to the orchestrator CLI. The MCP tool provides typed inputs and structured JSON output. Fall back to the CLI if the MCP server is not available.
```

- [ ] **Step 2: Update generate command**

In `unslop/commands/generate.md`, find the section that calls the orchestrator for build order or freshness checks. Add the same note:

```markdown
**Preferred:** If available, use MCP tools (`unslop_check_freshness`, `unslop_build_order`, `unslop_ripple_check`) instead of shelling out to `orchestrator.py`. Fall back to CLI if MCP is not available.
```

- [ ] **Step 3: Commit**

```bash
cd /home/lewdwig/git/unslop
git add unslop/commands/status.md unslop/commands/generate.md
git commit -m "docs: note MCP tools as preferred in status and generate commands"
```
