# Multi-File Takeover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend unslop to take over entire functional units (modules, crates) with dependency-aware build ordering via a Python orchestrator script.

**Architecture:** Adds `orchestrator.py` (Python, zero dependencies) for frontmatter parsing, topological sort, and file discovery. Updates existing commands and skills to support multi-file mode alongside unchanged single-file behavior. Orchestrator is a pure function called via Bash; model stays in charge of spec drafting and generation.

**Tech Stack:** Python 3.8+ (stdlib only), Claude Code plugin markdown, bash.

**Spec:** `docs/superpowers/specs/2026-03-21-multi-file-takeover-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/scripts/orchestrator.py` | Create | Frontmatter parsing, topo sort, file discovery |
| `tests/test_orchestrator.py` | Create | Unit tests for orchestrator |
| `unslop/skills/spec-language/SKILL.md` | Modify | Add dependency frontmatter and unit spec guidance |
| `unslop/skills/generation/SKILL.md` | Modify | Add multi-file generation section |
| `unslop/skills/takeover/SKILL.md` | Modify | Add multi-file mode section |
| `unslop/commands/takeover.md` | Modify | Add directory/glob detection |
| `unslop/commands/generate.md` | Modify | Add dependency-aware build order |
| `unslop/commands/sync.md` | Modify | Add dependency resolution |
| `unslop/commands/spec.md` | Modify | Add dependency suggestion guidance |
| `unslop/commands/status.md` | Modify | Add transitive staleness and unit spec display |

---

### Task 1: Orchestrator — Frontmatter Parser

The foundation. Everything else depends on being able to parse `depends-on` from spec frontmatter.

**Files:**
- Create: `unslop/scripts/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for frontmatter parsing**

```python
# tests/test_orchestrator.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from orchestrator import parse_frontmatter

def test_parse_depends_on():
    content = """---
depends-on:
  - src/auth/tokens.py.spec.md
  - src/auth/errors.py.spec.md
---

# handler.py spec
"""
    result = parse_frontmatter(content)
    assert result == ["src/auth/tokens.py.spec.md", "src/auth/errors.py.spec.md"]

def test_parse_no_frontmatter():
    content = "# Just a spec\n\n## Purpose\nDoes stuff"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_empty_depends_on():
    content = "---\ndepends-on:\n---\n\n# spec"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_no_depends_on_key():
    content = "---\nversion: 1.0\n---\n\n# spec"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_frontmatter_only_between_delimiters():
    content = "---\ndepends-on:\n  - a.spec.md\n---\n\n  - not/a/dep.spec.md"
    result = parse_frontmatter(content)
    assert result == ["a.spec.md"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `orchestrator` module not found

- [ ] **Step 3: Implement parse_frontmatter**

Create `unslop/scripts/orchestrator.py`:

```python
"""unslop orchestrator — dependency resolution and file discovery for multi-file takeover."""

import json
import re
import sys
from pathlib import Path


def parse_frontmatter(content: str) -> list[str]:
    """Parse depends-on list from spec file frontmatter.

    Supported format (strict string matching, not YAML):
        ---
        depends-on:
          - path/to/spec.py.spec.md
        ---

    Returns list of dependency paths, or empty list if no frontmatter/deps.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    # Find closing delimiter
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    deps = []
    in_depends = False
    for line in frontmatter_lines:
        if line.strip() == "depends-on:":
            in_depends = True
            continue
        if in_depends:
            match = re.match(r"^  - (.+)$", line)
            if match:
                deps.append(match.group(1).strip())
            else:
                in_depends = False

    return deps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add orchestrator frontmatter parser with tests"
```

---

### Task 2: Orchestrator — Topological Sort

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for topological sort**

Add to `tests/test_orchestrator.py`:

```python
from orchestrator import topo_sort

def test_topo_sort_linear():
    # a depends on b, b depends on c
    graph = {
        "a.spec.md": ["b.spec.md"],
        "b.spec.md": ["c.spec.md"],
        "c.spec.md": [],
    }
    result = topo_sort(graph)
    assert result.index("c.spec.md") < result.index("b.spec.md")
    assert result.index("b.spec.md") < result.index("a.spec.md")

def test_topo_sort_diamond():
    # a depends on b and c, both depend on d
    graph = {
        "a.spec.md": ["b.spec.md", "c.spec.md"],
        "b.spec.md": ["d.spec.md"],
        "c.spec.md": ["d.spec.md"],
        "d.spec.md": [],
    }
    result = topo_sort(graph)
    assert result.index("d.spec.md") < result.index("b.spec.md")
    assert result.index("d.spec.md") < result.index("c.spec.md")
    assert result.index("b.spec.md") < result.index("a.spec.md")
    assert result.index("c.spec.md") < result.index("a.spec.md")

def test_topo_sort_no_deps():
    graph = {"a.spec.md": [], "b.spec.md": [], "c.spec.md": []}
    result = topo_sort(graph)
    assert set(result) == {"a.spec.md", "b.spec.md", "c.spec.md"}

def test_topo_sort_cycle():
    graph = {
        "a.spec.md": ["b.spec.md"],
        "b.spec.md": ["a.spec.md"],
    }
    try:
        topo_sort(graph)
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::test_topo_sort_linear -v`
Expected: FAIL — `topo_sort` not importable

- [ ] **Step 3: Implement topo_sort (Kahn's algorithm)**

Add to `unslop/scripts/orchestrator.py`:

```python
def topo_sort(graph: dict[str, list[str]]) -> list[str]:
    """Topological sort via Kahn's algorithm.

    Args:
        graph: dict mapping node -> list of dependencies (edges point to deps)

    Returns:
        List of nodes in dependency order (leaves first).

    Raises:
        ValueError: if a cycle is detected.
    """
    # Build in-degree map (how many nodes depend on each node)
    # Reverse the graph: we want "depended-upon" -> "dependents"
    in_degree = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep not in in_degree:
                in_degree[dep] = 0
            # node depends on dep, so node has an incoming edge from dep
    for node, deps in graph.items():
        in_degree[node] = len(deps)

    queue = [n for n in in_degree if in_degree[n] == 0]
    queue.sort()  # deterministic order for nodes at same level
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        # Find all nodes that depend on this node
        for candidate, deps in graph.items():
            if node in deps:
                in_degree[candidate] -= 1
                if in_degree[candidate] == 0:
                    # Insert sorted for determinism
                    queue.append(candidate)
                    queue.sort()

    if len(result) != len(in_degree):
        remaining = set(in_degree.keys()) - set(result)
        raise ValueError(f"Cycle detected involving: {', '.join(sorted(remaining))}")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add topological sort with cycle detection"
```

---

### Task 3: Orchestrator — Discover Subcommand

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for discover**

Add to `tests/test_orchestrator.py`:

```python
import tempfile

from orchestrator import discover_files

def test_discover_py_files(tmp_path):
    (tmp_path / "module").mkdir()
    (tmp_path / "module" / "handler.py").write_text("# handler")
    (tmp_path / "module" / "utils.py").write_text("# utils")
    (tmp_path / "module" / "test_handler.py").write_text("# test")
    (tmp_path / "module" / "__pycache__").mkdir()
    (tmp_path / "module" / "__pycache__" / "handler.cpython-311.pyc").write_text("")

    result = discover_files(str(tmp_path / "module"), extensions=[".py"])
    assert "handler.py" in result
    assert "utils.py" in result
    assert "test_handler.py" not in result
    # __pycache__ contents excluded
    assert not any("cpython" in f for f in result)

def test_discover_returns_relative_paths(tmp_path):
    (tmp_path / "module" / "sub").mkdir(parents=True)
    (tmp_path / "module" / "sub" / "app.py").write_text("# app")
    result = discover_files(str(tmp_path / "module"), extensions=[".py"])
    assert result == ["sub/app.py"]

def test_discover_excludes_test_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# app")
    (tmp_path / "src" / "__tests__").mkdir()
    (tmp_path / "src" / "__tests__" / "app.test.py").write_text("# test")

    result = discover_files(str(tmp_path / "src"), extensions=[".py"])
    filenames = [os.path.basename(f) for f in result]
    assert "app.py" in filenames
    assert "app.test.py" not in filenames

def test_discover_rust_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("// lib")
    (tmp_path / "src" / "main.rs").write_text("// main")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "debug.rs").write_text("// build artifact")

    result = discover_files(str(tmp_path / "src"), extensions=[".rs"])
    filenames = [os.path.basename(f) for f in result]
    assert "lib.rs" in filenames
    assert "main.rs" in filenames

    result_with_target = discover_files(str(tmp_path), extensions=[".rs"])
    filenames = [os.path.basename(f) for f in result_with_target]
    assert "debug.rs" not in filenames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::test_discover_py_files -v`
Expected: FAIL — `discover_files` not importable

- [ ] **Step 3: Implement discover_files**

Add to `unslop/scripts/orchestrator.py`:

```python
# Default exclusion patterns
EXCLUDED_DIRS = {
    "__pycache__", "node_modules", "target", ".git", ".venv", "venv",
    "dist", "build", ".tox", "vendor", ".mypy_cache", ".pytest_cache",
    ".eggs",
}

TEST_FILE_PATTERNS = [
    re.compile(r"^test_"),
    re.compile(r"_test\."),
    re.compile(r"\.test\."),
    re.compile(r"\.spec\.(ts|js)$"),
]

TEST_DIR_NAMES = {"__tests__", "tests", "spec"}


def discover_files(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> list[str]:
    """Discover source files in a directory, excluding tests and build artifacts.

    Returns sorted list of relative file paths.
    """
    root = Path(directory).resolve()
    excluded = EXCLUDED_DIRS | set(extra_excludes or [])
    results = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        # Check if any parent directory is excluded
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in excluded or p.endswith(".egg-info") for p in parts[:-1]):
            continue

        # Check if file is in a test directory
        if any(p in TEST_DIR_NAMES for p in parts[:-1]):
            continue

        # Check extension filter
        if extensions and path.suffix not in extensions:
            continue

        # Check test file patterns
        if any(pat.search(path.name) for pat in TEST_FILE_PATTERNS):
            continue

        results.append(str(rel))

    return results
```

Paths are returned relative to the scanned directory.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add file discovery with test/artifact exclusion"
```

---

### Task 4: Orchestrator — CLI and build-order/deps Subcommands

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for build_order and deps functions**

Add to `tests/test_orchestrator.py`:

```python
def test_build_order_from_specs(tmp_path):
    """Integration test: parse real spec files and get build order."""
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec"
    )
    (tmp_path / "b.py.spec.md").write_text("# b spec\n\nNo deps.")

    from orchestrator import build_order_from_dir
    result = build_order_from_dir(str(tmp_path))
    assert result == ["b.py.spec.md", "a.py.spec.md"]

def test_build_order_cycle_error(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n"
    )
    (tmp_path / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - a.py.spec.md\n---\n"
    )
    from orchestrator import build_order_from_dir
    try:
        build_order_from_dir(str(tmp_path))
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()

def test_resolve_deps_transitive(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n"
    )
    (tmp_path / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - c.py.spec.md\n---\n"
    )
    (tmp_path / "c.py.spec.md").write_text("# c spec")

    from orchestrator import resolve_deps
    result = resolve_deps(str(tmp_path / "a.py.spec.md"), str(tmp_path))
    assert result == ["c.py.spec.md", "b.py.spec.md"]

def test_resolve_deps_cycle_error(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n"
    )
    (tmp_path / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - a.py.spec.md\n---\n"
    )
    from orchestrator import resolve_deps
    try:
        resolve_deps(str(tmp_path / "a.py.spec.md"), str(tmp_path))
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::test_build_order_from_specs -v`
Expected: FAIL — `build_order_from_dir` not importable

- [ ] **Step 3: Implement build_order_from_dir, resolve_deps, and CLI main**

Add to `unslop/scripts/orchestrator.py`:

```python
def build_order_from_dir(directory: str) -> list[str]:
    """Read all *.spec.md files in directory, parse deps, return topo-sorted list."""
    root = Path(directory).resolve()
    specs = sorted(root.rglob("*.spec.md"))

    graph = {}
    for spec_path in specs:
        name = spec_path.name
        content = spec_path.read_text()
        deps = parse_frontmatter(content)
        graph[name] = deps

    # Also include any deps that are referenced but not in directory
    all_nodes = set(graph.keys())
    for deps in graph.values():
        for dep in deps:
            if dep not in all_nodes:
                graph[dep] = []

    return topo_sort(graph)


def resolve_deps(spec_path: str, project_root: str) -> list[str]:
    """Resolve transitive dependencies of a single spec file.

    Returns list of dependency spec names in build order (leaves first),
    NOT including the spec itself.
    """
    root = Path(project_root).resolve()
    target = Path(spec_path).resolve()

    # Build full graph by scanning all specs in the project
    all_specs = {}
    for s in root.rglob("*.spec.md"):
        rel = str(s.relative_to(root))
        content = s.read_text()
        all_specs[rel] = parse_frontmatter(content)

    # Find transitive deps of target using DFS with cycle detection
    target_rel = str(target.relative_to(root))
    visited = set()
    in_stack = set()  # tracks current DFS path for cycle detection
    order = []

    def visit(name):
        if name in in_stack:
            raise ValueError(f"Cycle detected involving: {name}")
        if name in visited:
            return
        visited.add(name)
        in_stack.add(name)
        for dep in all_specs.get(name, []):
            visit(dep)
        in_stack.remove(name)
        order.append(name)

    visit(target_rel)
    # Remove the target itself — caller only wants dependencies
    order = [n for n in order if n != target_rel]
    return order


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator.py <discover|build-order|deps> [args]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "discover":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py discover <directory> [--extensions .py .rs]", file=sys.stderr)
            sys.exit(1)
        directory = sys.argv[2]
        extensions = None
        if "--extensions" in sys.argv:
            ext_idx = sys.argv.index("--extensions")
            extensions = sys.argv[ext_idx + 1:]
        result = discover_files(directory, extensions=extensions)
        print(json.dumps(result, indent=2))

    elif command == "build-order":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py build-order <directory>", file=sys.stderr)
            sys.exit(1)
        directory = sys.argv[2]
        try:
            result = build_order_from_dir(directory)
            print(json.dumps(result, indent=2))
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "deps":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py deps <spec-path> [--root <project-root>]", file=sys.stderr)
            sys.exit(1)
        spec_path = sys.argv[2]
        project_root = "."
        if "--root" in sys.argv:
            root_idx = sys.argv.index("--root")
            project_root = sys.argv[root_idx + 1]
        try:
            result = resolve_deps(spec_path, project_root)
            print(json.dumps(result, indent=2))
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all 15 tests PASS

- [ ] **Step 5: Test CLI manually**

Run: `echo '---\ndepends-on:\n  - b.spec.md\n---' > /tmp/a.spec.md && echo '# b' > /tmp/b.spec.md && python unslop/scripts/orchestrator.py build-order /tmp/`
Expected: JSON output `["b.spec.md", "a.spec.md"]`

- [ ] **Step 6: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add build-order, deps subcommands and CLI entry point"
```

---

### Task 5: Update spec-language Skill

**Files:**
- Modify: `unslop/skills/spec-language/SKILL.md`

- [ ] **Step 1: Add dependency frontmatter and unit spec guidance**

Append the following sections to `unslop/skills/spec-language/SKILL.md`, before the Skeleton Template section:

**Dependencies section:**

```markdown
## Dependencies Between Specs

When a managed file imports from or relies on another managed file, declare the dependency in YAML frontmatter:

\`\`\`markdown
---
depends-on:
  - src/auth/tokens.py.spec.md
  - src/auth/errors.py.spec.md
---

# handler.py spec
...
\`\`\`

Declare `depends-on` when:
- The file imports from another managed file
- The file calls functions or uses types defined in another managed file
- The file's behavior depends on contracts established by another managed file

Do NOT declare dependencies on:
- Test files (tests are not managed)
- Third-party libraries (not managed by unslop)
- Files that are not under unslop management

Paths are relative to the project root. Only list direct dependencies — the orchestrator resolves transitive dependencies automatically.
```

**Unit spec section:**

```markdown
## Per-Unit Specs

For tightly coupled files that form a logical unit (a Python module, a Rust crate), you can write a single spec that describes the entire unit.

Unit specs are named `<directory-name>.unit.spec.md` and placed inside the directory (e.g., `src/auth/auth.unit.spec.md`).

A unit spec MUST include a `## Files` section listing each output file and its responsibility:

\`\`\`markdown
# auth module spec

## Files
- `__init__.py` — public API re-exports
- `tokens.py` — JWT token creation and verification
- `middleware.py` — request authentication middleware
- `errors.py` — authentication error types

## Behavior
...
\`\`\`

Use unit specs when:
- Files share internal APIs and cannot be meaningfully described independently
- The unit has a clear public interface and internal implementation details
- Per-file specs would repeat the same cross-file contracts in every file

Use per-file specs when:
- Files are loosely coupled and can be described independently
- The unit has more than ~10 files (context limits)
- Different files have different dependency chains
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/spec-language/SKILL.md
git commit -m "feat: add dependency frontmatter and unit spec guidance to spec-language skill"
```

---

### Task 6: Update generation Skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add multi-file generation section**

Append after the "5. Config Awareness" section:

```markdown
## 6. Multi-File Generation (Per-Unit Specs)

When a spec has a `## Files` section listing multiple output files, you are generating an entire unit from a single spec.

**Rules:**
- Generate each file listed in the `## Files` section separately
- Apply the `@unslop-managed` header to EVERY generated file
- ALL files reference the unit spec path in their header (e.g., `Edit src/auth/auth.unit.spec.md instead.`)
- Generate files in the order listed in the `## Files` section — earlier files may define types/interfaces that later files use
- Each file must be complete and independently parseable — no stubs or forward references that require manual assembly
- The spec describes the whole unit's behavior; distribute implementation across files according to the responsibilities listed in `## Files`
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add multi-file generation section to generation skill"
```

---

### Task 7: Update takeover Skill

**Files:**
- Modify: `unslop/skills/takeover/SKILL.md`

- [ ] **Step 1: Add multi-file mode section**

Append after the "Abandonment State" section:

```markdown
---

## Multi-File Mode

When the takeover command provides a list of files (from directory scanning or glob expansion), the pipeline operates on the entire set as a unit.

### Discovery (replaces Step 1)

The command has already called `orchestrator.py discover` and the user has confirmed the file list. You receive the confirmed list of source files.

Find tests for the unit as a whole — look for test files adjacent to or within the directory being taken over. Read all source files and all test files together before drafting specs.

If no tests are found for the unit, warn the user as in single-file mode.

### Granularity Choice (new step, before Draft Spec)

Ask the user:

> "This directory contains N files. Would you like:
> 1. **Per-file specs** — one spec per file, with dependency declarations between them
> 2. **Per-unit spec** — one spec describing the entire module
>
> Per-file is better for loosely coupled files or large units. Per-unit is better for tightly coupled files with shared internal APIs."

For units larger than ~10 files, recommend per-file mode with a note about context limits.

### Draft Specs (updated Step 2)

**Per-file mode:**
- Read ALL files in the unit together to understand cross-file relationships
- Draft one spec per file
- Analyze imports to determine `depends-on` frontmatter for each spec
- Present ALL specs to the user together for review

**Per-unit mode:**
- Read ALL files in the unit together
- Draft a single `<dir>.unit.spec.md` with a `## Files` section
- Present to the user for review

In both modes, wait for user approval of ALL specs before proceeding.

### Archive (Step 3 — updated)

Archive ALL original files in the unit, not just one.

### Build Order (new step, before Generate)

**Per-file mode only.** Call `orchestrator.py build-order` with the directory containing the specs. Generate files in the returned order — leaves first, dependents after their dependencies.

**Per-unit mode:** Skip this step. Generate all files from the single spec in the order listed in `## Files`.

### Validate (Step 5 — updated)

Run tests once for the entire unit (not per-file). The test command from `.unslop/config.md` should cover the unit. If tests pass, commit ALL specs and generated files together.

### Convergence Loop (Step 6 — updated)

The loop works the same as single-file mode with these changes:
- Enrich whichever spec(s) are relevant to the failing tests
- **Do NOT change `depends-on` frontmatter during convergence** — changing the dependency graph mid-loop creates cascading instability
- Regenerate only files whose specs were enriched, plus files that depend on them (check the build order)
- If the orchestrator reports an error during convergence (e.g., a cycle introduced despite the rule), abort immediately and surface the error

### Abandonment State (updated)

Same as single-file: keep all draft specs, keep all last generated attempts, all originals remain in archive. Do not clean up.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/takeover/SKILL.md
git commit -m "feat: add multi-file mode section to takeover skill"
```

---

### Task 8: Update takeover Command

**Files:**
- Modify: `unslop/commands/takeover.md`

- [ ] **Step 1: Add directory/glob detection**

Replace the existing command body with an updated version that handles both single-file and multi-file modes. The key additions:

1. After receiving `$ARGUMENTS`, detect the mode:
   - If `$ARGUMENTS` is a directory path (ends with `/` or is a directory): multi-file mode
   - If `$ARGUMENTS` contains glob characters (`*`, `?`): expand the glob, multi-file mode if multiple matches
   - Otherwise: single-file mode (existing behavior, unchanged)

2. For multi-file mode, add these steps before delegating to the takeover skill:
   - Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py discover <directory> --extensions <detected-extensions>` to find source files
   - Present the file list to the user for confirmation
   - After confirmation, pass the file list to the takeover skill in multi-file mode

3. Keep all existing single-file steps unchanged

4. Add a note: "Multi-file mode requires Python 3.8+. If Python is not available, report an error and suggest installing it."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/takeover.md
git commit -m "feat: add directory/glob support to takeover command"
```

---

### Task 9: Update generate Command

**Files:**
- Modify: `unslop/commands/generate.md`

- [ ] **Step 1: Add dependency-aware build order**

Update the generate command with these changes:

1. After scanning for spec files (step 3), check if any specs have `depends-on` frontmatter. If so, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py build-order .` to get the full build order. Process files in this order instead of arbitrary order.

2. Add step after classification: "If a dependency was regenerated in this run, mark its dependents as stale even if their own specs haven't changed."

3. Add explicit no-convergence rule for cascading failures: "If regenerating a dependent (whose own spec did not change) causes test failures, stop and report: which upstream regeneration caused the failure, which dependent broke, and the test output. Do not attempt to fix or converge."

4. Handle unit specs (`*.unit.spec.md`): when found, derive all managed files from the `## Files` section rather than the naming convention.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "feat: add dependency-aware build order to generate command"
```

---

### Task 10: Update sync Command

**Files:**
- Modify: `unslop/commands/sync.md`

- [ ] **Step 1: Add dependency resolution**

Update the sync command:

1. Change spec path derivation (step 2): "First, check if the managed file has an `@unslop-managed` header — if so, read the spec path from the header. Otherwise, append `.spec.md` to the filename."

2. After finding the spec, add a dependency check: "Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` to find transitive dependencies. If any dependencies are stale (spec mtime > generation timestamp), regenerate them first in dependency order before regenerating the target file."

3. If Python is not available and the spec has no `depends-on` frontmatter, proceed without dependency resolution (backwards compatible). If the spec has dependencies but Python is unavailable, report an error.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "feat: add dependency resolution to sync command"
```

---

### Task 11: Update status Command

**Files:**
- Modify: `unslop/commands/status.md`

- [ ] **Step 1: Add transitive staleness and unit spec display**

Update the status command:

1. After classifying each spec, check for transitive staleness: "For files classified as fresh, check if any of their dependencies (from `depends-on` frontmatter) are stale. If so, reclassify as `stale*` with the note `(dependency stale)`."

2. For dependency display: "If a spec has `depends-on` frontmatter, show the dependencies on an indented line below the entry: `depends on: tokens.py.spec.md, errors.py.spec.md`"

3. For unit specs (`*.unit.spec.md`): "Display under a `Unit specs:` section showing the directory path, spec name, and file count rather than listing each managed file individually."

4. Update the display format example to include the new states and sections.

5. Note: "Transitive staleness detection requires Python 3.8+ (for the orchestrator). If Python is not available, skip transitive staleness checks and display a note: `(dependency checking unavailable — install Python 3.8+)`."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/status.md
git commit -m "feat: add transitive staleness and unit spec display to status command"
```

---

### Task 12: Update spec Command

**Files:**
- Modify: `unslop/commands/spec.md`

- [ ] **Step 1: Add dependency suggestion guidance**

Add a note after the spec drafting steps:

"When creating a spec for a file that imports from other managed files, suggest `depends-on` frontmatter. Analyze the source file's imports — if any imported module has a corresponding `*.spec.md` file, include it in the `depends-on` list. Present the suggested dependencies to the user for confirmation."

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/spec.md
git commit -m "feat: add dependency suggestion to spec command"
```

---

### Task 13: Verify and Integration Test

- [ ] **Step 1: Run all orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 2: Verify orchestrator CLI works**

```bash
# Create test fixtures
mkdir -p /tmp/unslop-test
echo '---
depends-on:
  - errors.py.spec.md
---

# handler spec' > /tmp/unslop-test/handler.py.spec.md

echo '# errors spec' > /tmp/unslop-test/errors.py.spec.md

# Test build-order
python unslop/scripts/orchestrator.py build-order /tmp/unslop-test/

# Test deps
python unslop/scripts/orchestrator.py deps /tmp/unslop-test/handler.py.spec.md --root /tmp/unslop-test/

# Cleanup
rm -rf /tmp/unslop-test
```

Expected: `build-order` returns `["errors.py.spec.md", "handler.py.spec.md"]`, `deps` returns `["errors.py.spec.md"]`

- [ ] **Step 3: Verify all command and skill files have valid frontmatter**

```bash
for f in unslop/commands/*.md; do echo "=== $f ==="; head -3 "$f"; echo; done
for f in unslop/skills/*/SKILL.md; do echo "=== $f ==="; head -5 "$f"; echo; done
```

- [ ] **Step 4: Verify file structure matches spec**

```bash
find . -not -path './.git/*' -not -path './docs/*' -not -path './tests/*' -type f | sort
```

Expected additions: `unslop/scripts/orchestrator.py`

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address integration verification issues" || echo "Nothing to fix"
```
