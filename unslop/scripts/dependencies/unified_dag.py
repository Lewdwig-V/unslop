"""Unified abstract+concrete dependency DAG for sync planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.frontmatter import parse_concrete_frontmatter, parse_frontmatter
from dependencies.graph import topo_sort


def _build_unified_dag(
    project_root: Path,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Build a single dependency graph from both abstract and concrete edges.

    An edge (u, v) exists if spec v depends on spec u at either layer:
      - Abstract: v's spec has ``depends-on: [u]``
      - Concrete: v's impl has ``extends: u_impl`` or
        ``concrete-dependencies: [u_impl]``

    Returns:
        (graph, impl_to_spec) where graph maps spec -> set of dependency
        specs (edges point to deps, same convention as topo_sort).
    """
    root = project_root

    # Build impl -> source-spec mapping
    impl_to_spec: dict[str, str] = {}
    impl_meta: dict[str, dict] = {}
    for impl_path in root.rglob("*.impl.md"):
        try:
            content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta = parse_concrete_frontmatter(content)
        rel = str(impl_path.relative_to(root))
        impl_meta[rel] = meta
        src = meta.get("source_spec")
        if src:
            impl_to_spec[rel] = src

    # Collect all specs
    all_specs: set[str] = set()
    spec_abstract_deps: dict[str, list[str]] = {}
    for spec_path in root.rglob("*.spec.md"):
        try:
            content = spec_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(spec_path.relative_to(root))
        all_specs.add(rel)
        spec_abstract_deps[rel] = parse_frontmatter(content)

    # Also add specs referenced by impls but maybe not on disk
    for src_spec in impl_to_spec.values():
        all_specs.add(src_spec)

    # Build unified adjacency list: spec -> set of specs it depends on
    graph: dict[str, set[str]] = {s: set() for s in all_specs}

    # Abstract edges: depends-on
    for spec, deps in spec_abstract_deps.items():
        for dep in deps:
            if dep in all_specs:
                graph.setdefault(spec, set()).add(dep)

    # Concrete edges: extends + concrete-dependencies, projected to spec space
    for impl_name, meta in impl_meta.items():
        src_spec = impl_to_spec.get(impl_name)
        if not src_spec:
            continue

        upstream_impls = list(meta.get("concrete_dependencies", []))
        extends = meta.get("extends")
        if extends:
            upstream_impls.append(extends)

        for dep_impl in upstream_impls:
            dep_spec = impl_to_spec.get(dep_impl)
            if dep_spec and dep_spec in all_specs:
                graph.setdefault(src_spec, set()).add(dep_spec)

    return graph, impl_to_spec


def _unified_topo_sort(
    project_root: Path,
    filter_specs: set[str] | None = None,
) -> tuple[list[str], dict[str, set[str]], dict[str, str]]:
    """Topological sort over the unified abstract+concrete DAG.

    Args:
        project_root: Project root directory.
        filter_specs: If provided, only include these specs in the sort
                      (plus their transitive deps that are also in the set).

    Returns:
        (sorted_specs, graph, impl_to_spec) where sorted_specs is in
        dependency order (leaves first).
    """
    full_graph, impl_to_spec = _build_unified_dag(project_root)

    if filter_specs is not None:
        # Restrict graph to only the specs in the filter set
        graph = {s: deps & filter_specs for s, deps in full_graph.items() if s in filter_specs}
    else:
        graph = full_graph

    # Convert set-valued graph to list-valued for topo_sort
    list_graph = {s: sorted(deps) for s, deps in graph.items()}

    try:
        sorted_specs = topo_sort(list_graph)
    except ValueError:
        # Cycle detected -- fall back to sorted order but warn via stderr
        print(json.dumps({"warning": "Cycle detected in unified DAG, falling back to alphabetical order"}), file=sys.stderr)
        sorted_specs = sorted(graph.keys())

    return sorted_specs, graph, impl_to_spec


def _compute_parallel_batches(
    sorted_entries: list[dict],
    graph: dict[str, set[str]],
    max_batch_size: int = 8,
) -> list[list[dict]]:
    """Partition sorted plan entries into parallel-safe batches via Kahn's.

    Two entries are in the same batch iff neither's spec is an ancestor of
    the other's in the unified DAG.  This is computed by running Kahn's
    algorithm and grouping nodes by topological depth.

    Args:
        sorted_entries: Plan entries already sorted in topo order.
        graph: spec -> set of dependency specs (edges point to deps).
        max_batch_size: Maximum files per batch.

    Returns:
        List of batches (each batch is a list of plan entry dicts).
    """
    if not sorted_entries:
        return []

    # Build the subgraph restricted to specs in the plan
    plan_specs = {e["spec"] for e in sorted_entries}
    sub_graph: dict[str, set[str]] = {}
    for spec in plan_specs:
        sub_graph[spec] = graph.get(spec, set()) & plan_specs

    # Compute in-degrees
    in_degree: dict[str, int] = {s: 0 for s in plan_specs}
    # Build forward edges (successors) for Kahn's
    successors: dict[str, set[str]] = {s: set() for s in plan_specs}
    for spec, deps in sub_graph.items():
        in_degree[spec] = len(deps)
        for dep in deps:
            successors.setdefault(dep, set()).add(spec)

    # Kahn's with depth tracking: each "wave" of zero-in-degree nodes
    # forms one parallel batch
    spec_to_entry: dict[str, list[dict]] = {}
    for entry in sorted_entries:
        spec_to_entry.setdefault(entry["spec"], []).append(entry)

    batches: list[list[dict]] = []
    queue = sorted(s for s in plan_specs if in_degree[s] == 0)

    while queue:
        # All nodes in queue can run in parallel
        wave_entries: list[dict] = []
        for spec in queue:
            wave_entries.extend(spec_to_entry.get(spec, []))

        # Split wave into max_batch_size chunks
        for i in range(0, len(wave_entries), max_batch_size):
            batches.append(wave_entries[i : i + max_batch_size])

        # Decrement in-degrees for successors
        next_queue = []
        for spec in queue:
            for succ in successors.get(spec, set()):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    next_queue.append(succ)
        queue = sorted(next_queue)

    # If a cycle left unvisited nodes, emit them so callers always get
    # actionable batches for every entry in sorted_entries.
    visited = {s for batch in batches for e in batch for s in [e["spec"]]}
    remaining = sorted(plan_specs - visited)
    if remaining:
        wave_entries = []
        for spec in remaining:
            wave_entries.extend(spec_to_entry.get(spec, []))
        for i in range(0, len(wave_entries), max_batch_size):
            batches.append(wave_entries[i : i + max_batch_size])

    return batches
