"""unslop orchestrator — dependency resolution and file discovery for multi-file takeover."""
from __future__ import annotations

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
            elif re.match(r"^\s+- ", line):
                print(f"Warning: possible malformed dependency (wrong indentation): {line!r}", file=sys.stderr)
                in_depends = False
            else:
                in_depends = False

    return deps


def topo_sort(graph: dict[str, list[str]]) -> list[str]:
    """Topological sort via Kahn's algorithm.

    Args:
        graph: dict mapping node -> list of dependencies (edges point to deps)

    Returns:
        List of nodes in dependency order (leaves first).

    Raises:
        ValueError: if a cycle is detected.
    """
    in_degree = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep not in in_degree:
                in_degree[dep] = 0
    for node, deps in graph.items():
        in_degree[node] = len(deps)

    queue = [n for n in in_degree if in_degree[n] == 0]
    queue.sort()
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for candidate, deps in graph.items():
            if node in deps:
                in_degree[candidate] -= 1
                if in_degree[candidate] == 0:
                    queue.append(candidate)
                    queue.sort()

    if len(result) != len(in_degree):
        remaining = set(in_degree.keys()) - set(result)
        raise ValueError(f"Cycle detected involving: {', '.join(sorted(remaining))}")

    return result


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


def build_order_from_dir(directory: str) -> list[str]:
    """Read all *.spec.md files in directory (recursively), parse deps, return topo-sorted list."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")
    specs = sorted(root.rglob("*.spec.md"))

    graph: dict[str, list[str]] = {}
    for spec_path in specs:
        name = str(spec_path.relative_to(root))
        content = spec_path.read_text()
        deps = parse_frontmatter(content)
        graph[name] = deps

    all_nodes = set(graph.keys())
    missing: dict[str, list[str]] = {}
    for deps_list in graph.values():
        for dep in deps_list:
            if dep not in all_nodes and dep not in missing:
                missing[dep] = []
    if missing:
        missing_names = ", ".join(sorted(missing.keys()))
        print(f'{{"warning": "Missing dependency specs: {missing_names}"}}', file=sys.stderr)
    graph.update(missing)

    return topo_sort(graph)


def resolve_deps(spec_path: str, project_root: str) -> list[str]:
    """Resolve transitive dependencies of a single spec file.

    Returns list of dependency spec names in build order (leaves first),
    NOT including the spec itself.

    Raises ValueError if a cycle is detected.
    """
    root = Path(project_root).resolve()
    target = Path(spec_path).resolve()

    all_specs = {}
    for s in root.rglob("*.spec.md"):
        rel = str(s.relative_to(root))
        content = s.read_text()
        all_specs[rel] = parse_frontmatter(content)

    target_rel = str(target.relative_to(root))
    visited: set[str] = set()
    in_stack: set[str] = set()
    order: list[str] = []

    # Iterative DFS to avoid recursion limit on deep chains
    stack: list[tuple[str, bool]] = [(target_rel, False)]
    while stack:
        name, processed = stack.pop()
        if processed:
            in_stack.discard(name)
            order.append(name)
            continue
        if name in in_stack:
            raise ValueError(f"Cycle detected involving: {name}")
        if name in visited:
            continue
        visited.add(name)
        in_stack.add(name)
        stack.append((name, True))  # post-order marker
        for dep in reversed(all_specs.get(name, [])):
            stack.append((dep, False))

    order = [n for n in order if n != target_rel]
    return order


def discover_files(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> list[str]:
    """Discover source files in a directory, excluding tests and build artifacts.

    Returns sorted list of file paths relative to the scanned directory.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")
    excluded = EXCLUDED_DIRS | set(extra_excludes or [])
    results = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in excluded or p.endswith(".egg-info") for p in parts[:-1]):
            continue

        if any(p in TEST_DIR_NAMES for p in parts[:-1]):
            continue

        if extensions and path.suffix not in extensions:
            continue

        if any(pat.search(path.name) for pat in TEST_FILE_PATTERNS):
            continue

        results.append(str(rel))

    return results


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
            if not extensions:
                print("Usage: orchestrator.py discover <directory> [--extensions .py .rs]", file=sys.stderr)
                sys.exit(1)
        try:
            result = discover_files(directory, extensions=extensions)
            print(json.dumps(result, indent=2))
        except (OSError, ValueError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "build-order":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py build-order <directory>", file=sys.stderr)
            sys.exit(1)
        directory = sys.argv[2]
        try:
            result = build_order_from_dir(directory)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError, RecursionError) as e:
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
            if root_idx + 1 >= len(sys.argv):
                print("Usage: orchestrator.py deps <spec-path> [--root <project-root>]", file=sys.stderr)
                sys.exit(1)
            project_root = sys.argv[root_idx + 1]
        try:
            result = resolve_deps(spec_path, project_root)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError, RecursionError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
