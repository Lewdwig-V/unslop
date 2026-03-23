"""Abstract spec dependency graph: topological sort, build order, dep resolution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..core.frontmatter import parse_frontmatter


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


def build_order_from_dir(directory: str) -> list[str]:
    """Read all *.spec.md files in directory (recursively), parse deps, return topo-sorted list."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")
    specs = sorted(root.rglob("*.spec.md"))

    graph: dict[str, list[str]] = {}
    for spec_path in specs:
        name = str(spec_path.relative_to(root))
        try:
            content = spec_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Cannot read spec file: {spec_path} ({e})")
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
        print(json.dumps({"warning": f"Missing dependency specs: {missing_names}"}), file=sys.stderr)
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
        try:
            content = s.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Cannot read spec file: {s} ({e})")
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
