"""Mermaid dependency graph renderer for spec/concrete/code layers."""

from __future__ import annotations

import re
from pathlib import Path

from core.frontmatter import parse_concrete_frontmatter, parse_frontmatter
from core.spec_discovery import parse_unit_spec_files
from freshness.checker import check_freshness


def render_dependency_graph(
    directory: str,
    scope: list[str] | None = None,
    include_code: bool = True,
    stale_only: bool = False,
) -> dict:
    """Render a Mermaid dependency graph of the spec/concrete/code layers.

    Args:
        directory: Project root directory.
        scope: Optional list of spec paths to focus on (with their transitive
               dependents). If None, renders the full project graph.
        include_code: Whether to include managed code file nodes.
        stale_only: If True, only include nodes on paths that lead to
                    stale/ghost-stale managed files. Helps prioritize syncs.

    Returns:
        dict with:
          - mermaid: The Mermaid graph source string
          - stats: Summary counts
          - nodes: List of node dicts for programmatic use
    """
    root = Path(directory).resolve()

    # Gather all specs and their deps
    all_specs: dict[str, list[str]] = {}
    for s in sorted(root.rglob("*.spec.md")):
        rel = str(s.relative_to(root))
        try:
            content = s.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        all_specs[rel] = parse_frontmatter(content)

    # Gather all impl files
    all_impls: dict[str, dict] = {}
    for impl_path in sorted(root.rglob("*.impl.md")):
        rel = str(impl_path.relative_to(root))
        try:
            content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta = parse_concrete_frontmatter(content)
        # Normalise source_spec to canonical root-relative path (impl may
        # live elsewhere and use a relative source-spec like ../src/api.spec.md).
        src = meta.get("source_spec")
        if src:
            resolved = (impl_path.parent / src).resolve()
            if resolved.exists():
                meta["source_spec"] = str(resolved.relative_to(root))
            elif (root / src).exists():
                meta["source_spec"] = src
        all_impls[rel] = meta

    # If scope is set, compute the affected subgraph (dual-layer aware)
    if scope:
        # Build reverse dep map for abstract specs
        reverse_deps: dict[str, list[str]] = {s: [] for s in all_specs}
        for spec, deps in all_specs.items():
            for dep in deps:
                reverse_deps.setdefault(dep, []).append(spec)

        # BFS from scope to find all transitively affected abstract specs
        in_scope_specs: set[str] = set()
        queue = list(scope)
        while queue:
            current = queue.pop(0)
            if current in in_scope_specs:
                continue
            in_scope_specs.add(current)
            for dep in all_specs.get(current, []):
                queue.append(dep)
            for dependent in reverse_deps.get(current, []):
                queue.append(dependent)

        # Dual-layer expansion: map each in-scope spec to its impl partner
        in_scope_impls: set[str] = set()
        spec_to_impl_map: dict[str, str] = {}
        for impl_path_str, meta in all_impls.items():
            src = meta.get("source_spec")
            if src:
                spec_to_impl_map[src] = impl_path_str

        # Seed concrete scope with impls whose source-spec is in scope
        for spec in in_scope_specs:
            impl = spec_to_impl_map.get(spec)
            if impl:
                in_scope_impls.add(impl)

        # Also seed with any impl.md paths directly in the scope input
        for s in scope:
            if s in all_impls:
                in_scope_impls.add(s)

        # BFS through concrete dep graph (both directions) to find
        # all transitively affected impls
        reverse_concrete: dict[str, list[str]] = {i: [] for i in all_impls}
        for impl_path_str, meta in all_impls.items():
            for dep in meta.get("concrete_dependencies", []):
                reverse_concrete.setdefault(dep, []).append(impl_path_str)
            extends = meta.get("extends")
            if extends:
                reverse_concrete.setdefault(extends, []).append(impl_path_str)

        impl_queue = list(in_scope_impls)
        impl_visited: set[str] = set()
        while impl_queue:
            current = impl_queue.pop(0)
            if current in impl_visited:
                continue
            impl_visited.add(current)
            in_scope_impls.add(current)
            # Downstream: impls that depend on this one
            for dependent in reverse_concrete.get(current, []):
                impl_queue.append(dependent)
            # Upstream: impls this one depends on
            meta = all_impls.get(current, {})
            for dep in meta.get("concrete_dependencies", []):
                impl_queue.append(dep)
            extends = meta.get("extends")
            if extends:
                impl_queue.append(extends)

        # Also pull in specs for any impls we discovered through concrete deps
        for impl_path_str in in_scope_impls:
            meta = all_impls.get(impl_path_str, {})
            src = meta.get("source_spec")
            if src and src in all_specs:
                in_scope_specs.add(src)

        # Filter specs and impls to scope
        all_specs = {k: v for k, v in all_specs.items() if k in in_scope_specs}
        all_impls = {k: v for k, v in all_impls.items() if k in in_scope_impls}

    # Get freshness data for staleness coloring
    try:
        freshness = check_freshness(str(root))
        state_map = {f["managed"]: f["state"] for f in freshness.get("files", [])}
    except (ValueError, OSError):
        state_map = {}

    # stale-only filter: causality-aware pruning.
    context_provider_impls: set[str] = set()

    if stale_only:
        stale_managed = {path for path, state in state_map.items() if state not in ("fresh",)}
        if not stale_managed:
            # Nothing stale -- return empty graph
            return {
                "mermaid": 'graph TD\n    empty["All files are fresh"]',
                "stats": {"abstract_specs": 0, "concrete_specs": 0, "managed_files": 0, "total_nodes": 0},
                "nodes": [],
            }

        # Pass 1: Walk backward from stale managed files to find seed specs/impls
        stale_specs: set[str] = set()
        stale_impls: set[str] = set()
        for managed in stale_managed:
            # Find the spec that generates this managed file
            spec = managed + ".spec.md"
            if spec in all_specs:
                stale_specs.add(spec)
            # Check freshness entries for spec info
            for f in freshness.get("files", []):
                if f["managed"] == managed and f.get("spec"):
                    if f["spec"] in all_specs:
                        stale_specs.add(f["spec"])

        # Include upstream abstract deps of stale specs
        stale_spec_closure: set[str] = set()
        sq = list(stale_specs)
        while sq:
            current = sq.pop(0)
            if current in stale_spec_closure:
                continue
            stale_spec_closure.add(current)
            for dep in all_specs.get(current, []):
                sq.append(dep)
        stale_specs = stale_spec_closure

        # Find impls whose source-spec is stale
        for impl_path_str, meta in all_impls.items():
            src = meta.get("source_spec")
            if src in stale_specs:
                stale_impls.add(impl_path_str)

        # Pass 2: For every seed impl, recursively trace upstream concrete
        # providers (extends + concrete-dependencies).
        impl_queue = list(stale_impls)
        visited_impls: set[str] = set(stale_impls)
        while impl_queue:
            current = impl_queue.pop(0)
            meta = all_impls.get(current, {})
            upstream = list(meta.get("concrete_dependencies", []))
            extends = meta.get("extends")
            if extends:
                upstream.append(extends)
            for dep_impl in upstream:
                if dep_impl not in visited_impls and dep_impl in all_impls:
                    visited_impls.add(dep_impl)
                    impl_queue.append(dep_impl)
                    if dep_impl not in stale_impls:
                        context_provider_impls.add(dep_impl)

        stale_impls = visited_impls

        # Also pull in specs for context-provider impls so their abstract
        # nodes show up in the graph
        for impl_path_str in context_provider_impls:
            meta = all_impls.get(impl_path_str, {})
            src = meta.get("source_spec")
            if src and src in all_specs:
                stale_specs.add(src)

        all_specs = {k: v for k, v in all_specs.items() if k in stale_specs}
        all_impls = {k: v for k, v in all_impls.items() if k in stale_impls}

    # Build Mermaid graph
    lines = ["graph TD"]
    node_ids: dict[str, str] = {}  # path -> sanitized node ID
    node_counter = [0]
    nodes_info = []

    def _node_id(path: str) -> str:
        if path not in node_ids:
            node_ids[path] = f"n{node_counter[0]}"
            node_counter[0] += 1
        return node_ids[path]

    def _short(path: str) -> str:
        """Shorten path for display."""
        parts = path.rsplit("/", 1)
        return parts[-1] if len(parts) > 1 else path

    # Style definitions
    lines.append("")
    lines.append("    %% Staleness colors")
    lines.append("    classDef fresh fill:#2d5a2d,stroke:#4a4,color:#fff")
    lines.append("    classDef stale fill:#8b4513,stroke:#d90,color:#fff")
    lines.append("    classDef ghostStale fill:#4a3060,stroke:#a6f,color:#fff")
    lines.append("    classDef modified fill:#8b6914,stroke:#da0,color:#fff")
    lines.append("    classDef conflict fill:#8b1a1a,stroke:#f44,color:#fff")
    lines.append("    classDef new fill:#1a4a6b,stroke:#4af,color:#fff")
    lines.append("    classDef spec fill:#1a3a5a,stroke:#58f,color:#fff")
    lines.append("    classDef impl fill:#3a2a5a,stroke:#a8f,color:#fff")
    lines.append("    classDef base fill:#2a3a3a,stroke:#8aa,color:#fff")
    lines.append("    classDef contextProvider fill:#3a3a3a,stroke:#888,color:#aaa,stroke-dasharray:5 5")

    # Abstract spec nodes
    if all_specs:
        lines.append("")
        lines.append("    %% Abstract Specs")
        for spec in sorted(all_specs):
            nid = _node_id(spec)
            label = _short(spec).replace(".spec.md", "")
            lines.append(f'    {nid}["{label}\\n<small>.spec.md</small>"]')
            lines.append(f"    class {nid} spec")
            nodes_info.append({"id": nid, "path": spec, "layer": "abstract", "type": "spec"})

    # Abstract spec dependency edges
    for spec, deps in sorted(all_specs.items()):
        for dep in deps:
            if dep in node_ids:
                lines.append(f"    {_node_id(dep)} --> {_node_id(spec)}")

    # Concrete spec nodes
    if all_impls:
        lines.append("")
        lines.append("    %% Concrete Specs")
        for impl, meta in sorted(all_impls.items()):
            nid = _node_id(impl)
            label = _short(impl).replace(".impl.md", "")
            is_context = impl in context_provider_impls
            is_base = not meta.get("source_spec")
            if is_base:
                lines.append(f'    {nid}{{"{label}\\n<small>base .impl.md</small>"}}')
                css_class = "contextProvider" if is_context else "base"
                lines.append(f"    class {nid} {css_class}")
                node_type = "context_provider" if is_context else "base"
                nodes_info.append({"id": nid, "path": impl, "layer": "concrete", "type": node_type})
            else:
                lines.append(f'    {nid}[/"{label}\\n<small>.impl.md</small>"/]')
                css_class = "contextProvider" if is_context else "impl"
                lines.append(f"    class {nid} {css_class}")
                node_type = "context_provider" if is_context else "impl"
                nodes_info.append({"id": nid, "path": impl, "layer": "concrete", "type": node_type})

    # Concrete spec edges: source-spec link, extends, concrete-dependencies
    for impl, meta in sorted(all_impls.items()):
        source = meta.get("source_spec")
        if source and source in node_ids:
            lines.append(f"    {_node_id(source)} -.->|lowers to| {_node_id(impl)}")

        extends = meta.get("extends")
        if extends and extends in node_ids:
            lines.append(f"    {_node_id(extends)} ==>|extends| {_node_id(impl)}")
        elif extends:
            # Parent might be out of scope -- add it as a reference node
            pnid = _node_id(extends)
            plabel = _short(extends).replace(".impl.md", "")
            lines.append(f'    {pnid}{{"{plabel}\\n<small>base</small>"}}')
            lines.append(f"    class {pnid} base")
            lines.append(f"    {pnid} ==>|extends| {_node_id(impl)}")

        for dep in meta.get("concrete_dependencies", []):
            if dep in node_ids:
                lines.append(f"    {_node_id(dep)} -->|concrete dep| {_node_id(impl)}")

    # Managed code file nodes
    if include_code:
        code_nodes = set()
        lines.append("")
        lines.append("    %% Managed Code Files")

        # Build reverse map: spec -> impls that claim it via source_spec
        _spec_to_target_impls: dict[str, list[str]] = {}
        for _impl_path, _meta in all_impls.items():
            _src = _meta.get("source_spec")
            if _src and _meta.get("targets"):
                _spec_to_target_impls.setdefault(_src, []).append(_impl_path)

        for spec in sorted(all_specs):
            # Multi-target check: find any impl (co-located or not)
            # whose source-spec is this spec and that has targets[].
            target_impls = _spec_to_target_impls.get(spec, [])
            if target_impls:
                for _impl_path in target_impls:
                    targets = all_impls[_impl_path].get("targets", [])
                    for target in targets:
                        managed = target.get("path", "")
                        if managed and managed not in code_nodes:
                            code_nodes.add(managed)
                            nid = _node_id(managed)
                            label = _short(managed)
                            state = state_map.get(managed, "new")
                            lines.append(f'    {nid}(["{label}"])')
                            css = _state_to_class(state)
                            lines.append(f"    class {nid} {css}")
                            lines.append(f"    {_node_id(spec)} -->|generates| {nid}")
                            nodes_info.append({"id": nid, "path": managed, "layer": "code", "state": state})
                continue

            # Unit specs list their managed files in a ## Files section
            if spec.endswith(".unit.spec.md"):
                try:
                    spec_content = (root / spec).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                spec_dir = str(Path(spec).parent)
                for uf in parse_unit_spec_files(spec_content):
                    managed = str(Path(spec_dir) / uf)
                    if managed not in code_nodes:
                        code_nodes.add(managed)
                        nid = _node_id(managed)
                        label = _short(managed)
                        state = state_map.get(managed, "new")
                        lines.append(f'    {nid}(["{label}"])')
                        css = _state_to_class(state)
                        lines.append(f"    class {nid} {css}")
                        lines.append(f"    {_node_id(spec)} -->|generates| {nid}")
                        nodes_info.append({"id": nid, "path": managed, "layer": "code", "state": state})
                continue

            # Single target
            managed = re.sub(r"\.spec\.md$", "", spec)
            if managed not in code_nodes:
                code_nodes.add(managed)
                nid = _node_id(managed)
                label = _short(managed)
                state = state_map.get(managed, "new")
                lines.append(f'    {nid}(["{label}"])')
                css = _state_to_class(state)
                lines.append(f"    class {nid} {css}")
                lines.append(f"    {_node_id(spec)} -->|generates| {nid}")
                nodes_info.append({"id": nid, "path": managed, "layer": "code", "state": state})

    mermaid = "\n".join(lines)
    spec_count = len(all_specs)
    impl_count = len(all_impls)
    code_count = sum(1 for n in nodes_info if n["layer"] == "code")

    return {
        "mermaid": mermaid,
        "stats": {
            "abstract_specs": spec_count,
            "concrete_specs": impl_count,
            "managed_files": code_count,
            "total_nodes": len(nodes_info),
        },
        "nodes": nodes_info,
    }


def _state_to_class(state: str) -> str:
    """Map a staleness state to a Mermaid CSS class name."""
    return {
        "fresh": "fresh",
        "stale": "stale",
        "ghost-stale": "ghostStale",
        "modified": "modified",
        "conflict": "conflict",
        "new": "new",
        "old_format": "stale",
    }.get(state, "new")
