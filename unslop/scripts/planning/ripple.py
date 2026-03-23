"""Ripple-check: compute blast radius of spec changes across all layers."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from core.frontmatter import parse_concrete_frontmatter, parse_frontmatter
from core.spec_discovery import parse_unit_spec_files
from dependencies.graph import topo_sort
from freshness.checker import classify_file


def ripple_check(spec_paths: list[str], project_root: str) -> dict:
    """Compute the ripple effect of changing one or more spec files.

    For each input spec, traces downstream through:
    1. Abstract layer: which specs depend on this one (via depends-on)?
    2. Concrete layer: which impl.md files are affected (via source-spec, concrete-dependencies, extends)?
    3. Code layer: which managed files would need regeneration?

    Returns a structured report suitable for --dry-run display.
    """
    root = Path(project_root).resolve()

    # Build the full abstract spec dependency graph (reverse edges = dependents)
    all_specs = {}
    for s in sorted(root.rglob("*.spec.md")):
        rel = str(s.relative_to(root))
        try:
            content = s.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        all_specs[rel] = parse_frontmatter(content)

    # Build reverse dependency map: spec -> list of specs that depend on it
    reverse_deps: dict[str, list[str]] = {s: [] for s in all_specs}
    for spec, deps in all_specs.items():
        for dep in deps:
            if dep not in reverse_deps:
                reverse_deps[dep] = []
            reverse_deps[dep].append(spec)

    # Build the concrete spec graph
    all_impls: dict[str, dict] = {}
    for impl_path in sorted(root.rglob("*.impl.md")):
        rel = str(impl_path.relative_to(root))
        try:
            content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta = parse_concrete_frontmatter(content)
        # Normalise source_spec to a canonical root-relative path so that
        # downstream maps (spec_to_impls, scope filters, etc.) work even
        # when the impl lives in a different directory and source-spec is
        # written as a relative path (e.g. ../src/api.spec.md).
        src = meta.get("source_spec")
        if src:
            resolved = (impl_path.parent / src).resolve()
            if resolved.exists():
                meta["source_spec"] = str(resolved.relative_to(root))
            elif (root / src).exists():
                meta["source_spec"] = src  # already root-relative
        all_impls[rel] = meta

    # Build reverse concrete dep map: impl -> list of impls that depend on it
    reverse_concrete: dict[str, list[str]] = {i: [] for i in all_impls}
    for impl, meta in all_impls.items():
        for dep in meta.get("concrete_dependencies", []):
            if dep not in reverse_concrete:
                reverse_concrete[dep] = []
            reverse_concrete[dep].append(impl)
        extends = meta.get("extends")
        if extends:
            if extends not in reverse_concrete:
                reverse_concrete[extends] = []
            reverse_concrete[extends].append(impl)

    # Map source-spec -> impl paths (source_spec already normalised above)
    spec_to_impls: dict[str, list[str]] = {}
    for impl, meta in all_impls.items():
        src = meta.get("source_spec")
        if src:
            spec_to_impls.setdefault(src, []).append(impl)

    # For each input spec, compute the full ripple
    affected_specs: set[str] = set()
    directly_changed: set[str] = set()

    # Normalize input paths
    normalized_inputs = []
    for sp in spec_paths:
        p = Path(sp)
        if p.is_absolute():
            try:
                sp = str(p.relative_to(root))
            except ValueError:
                pass
        normalized_inputs.append(sp)

    # BFS to find all transitively affected specs
    queue = list(normalized_inputs)
    directly_changed.update(normalized_inputs)
    visited: set[str] = set()

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        affected_specs.add(current)
        for dependent in reverse_deps.get(current, []):
            queue.append(dependent)

    # Find affected concrete specs (from source-spec links + concrete deps)
    affected_impls: set[str] = set()
    impl_queue: list[str] = []

    # Seed: impls whose source-spec is an affected abstract spec
    for spec in affected_specs:
        for impl in spec_to_impls.get(spec, []):
            impl_queue.append(impl)

    # BFS through concrete dependency graph
    impl_visited: set[str] = set()
    while impl_queue:
        current = impl_queue.pop(0)
        if current in impl_visited:
            continue
        impl_visited.add(current)
        affected_impls.add(current)
        for dependent in reverse_concrete.get(current, []):
            impl_queue.append(dependent)

    # Find affected managed files
    affected_managed: list[dict] = []

    for spec in sorted(affected_specs):
        spec_path_obj = root / spec
        if not spec_path_obj.exists():
            continue

        # Check for multi-target impl (any impl whose source-spec is this
        # spec, not just a co-located companion).
        targets_handled = False
        for _impl_rel in spec_to_impls.get(spec, []):
            _impl_meta = all_impls.get(_impl_rel, {})
            _targets = _impl_meta.get("targets", [])
            if _targets:
                targets_handled = True
                for target in _targets:
                    managed_rel = target.get("path", "")
                    managed_full = root / managed_rel
                    entry = {
                        "managed": managed_rel,
                        "spec": spec,
                        "concrete": _impl_rel,
                        "exists": managed_full.exists(),
                        "language": target.get("language", "unknown"),
                        "cause": "direct" if spec in directly_changed else "transitive",
                    }
                    if managed_full.exists():
                        result = classify_file(str(managed_full), str(spec_path_obj), project_root=str(root))
                        entry["current_state"] = result["state"]
                    else:
                        entry["current_state"] = "new"
                    affected_managed.append(entry)

        if not targets_handled:
            # Unit spec
            if spec.endswith(".unit.spec.md"):
                try:
                    content = spec_path_obj.read_text(encoding="utf-8")
                    for uf in parse_unit_spec_files(content):
                        managed_rel = str((spec_path_obj.parent / uf).relative_to(root))
                        managed_full = root / managed_rel
                        entry = {
                            "managed": managed_rel,
                            "spec": spec,
                            "exists": managed_full.exists(),
                            "cause": "direct" if spec in directly_changed else "transitive",
                        }
                        if managed_full.exists():
                            result = classify_file(str(managed_full), str(spec_path_obj), project_root=str(root))
                            entry["current_state"] = result["state"]
                        else:
                            entry["current_state"] = "new"
                        affected_managed.append(entry)
                except (OSError, UnicodeDecodeError):
                    pass
            else:
                # Per-file spec
                managed_name = re.sub(r"\.spec\.md$", "", spec_path_obj.name)
                managed_full = spec_path_obj.parent / managed_name
                managed_rel = (
                    str(managed_full.relative_to(root))
                    if managed_full.exists()
                    else str((spec_path_obj.parent / managed_name).relative_to(root))
                )
                entry = {
                    "managed": managed_rel,
                    "spec": spec,
                    "exists": managed_full.exists(),
                    "cause": "direct" if spec in directly_changed else "transitive",
                }
                if managed_full.exists():
                    result = classify_file(str(managed_full), str(spec_path_obj), project_root=str(root))
                    entry["current_state"] = result["state"]
                else:
                    entry["current_state"] = "new"
                affected_managed.append(entry)

    # Add concrete-only affected files (ghost staleness via concrete deps, not abstract deps)
    concrete_only_impls = affected_impls - {
        str((root / impl).relative_to(root)) for spec in affected_specs for impl in spec_to_impls.get(spec, [])
    }
    ghost_stale_managed: list[dict] = []
    for impl in sorted(concrete_only_impls):
        meta = all_impls.get(impl, {})
        src = meta.get("source_spec")
        if not src:
            continue
        # This impl's abstract spec wasn't directly affected -- ghost staleness
        spec_path_obj = root / src
        targets = meta.get("targets", [])
        if targets:
            for target in targets:
                managed_rel = target.get("path", "")
                managed_full = root / managed_rel
                ghost_stale_managed.append(
                    {
                        "managed": managed_rel,
                        "spec": src,
                        "concrete": impl,
                        "exists": managed_full.exists(),
                        "cause": "ghost-stale",
                        "ghost_source": impl,
                        "current_state": "ghost-stale",
                    }
                )
        elif src.endswith(".unit.spec.md"):
            # Unit spec: emit an entry for each file listed in ## Files
            spec_path_obj = root / src
            if spec_path_obj.exists():
                try:
                    spec_content = spec_path_obj.read_text(encoding="utf-8")
                    unit_files = parse_unit_spec_files(spec_content)
                    for uf in unit_files:
                        managed_rel = str((spec_path_obj.parent / uf).relative_to(root))
                        managed_full = root / managed_rel
                        ghost_stale_managed.append(
                            {
                                "managed": managed_rel,
                                "spec": src,
                                "concrete": impl,
                                "exists": managed_full.exists(),
                                "cause": "ghost-stale",
                                "ghost_source": impl,
                                "current_state": "ghost-stale",
                            }
                        )
                except (OSError, UnicodeDecodeError):
                    pass
        else:
            # Per-file spec: derive managed path by stripping .spec.md
            managed_name = re.sub(r"\.spec\.md$", "", Path(src).name)
            managed_full = root / Path(src).parent / managed_name
            managed_rel = (
                str(managed_full.relative_to(root)) if managed_full.exists() else str((Path(src).parent / managed_name))
            )
            ghost_stale_managed.append(
                {
                    "managed": managed_rel,
                    "spec": src,
                    "concrete": impl,
                    "exists": managed_full.exists(),
                    "cause": "ghost-stale",
                    "ghost_source": impl,
                    "current_state": "ghost-stale",
                }
            )

    # Collect specs reachable only through concrete-dependency chains so they
    # appear in build_order alongside the abstract-layer specs.
    ghost_stale_specs: set[str] = set()
    for impl in concrete_only_impls:
        src = all_impls.get(impl, {}).get("source_spec")
        if src:
            ghost_stale_specs.add(src)

    # Translate concrete impl->impl edges into spec->spec ordering edges.
    # For every concrete dep edge (depender_impl -> dependency_impl) where both
    # impls have a source-spec, the dependency's spec must precede the
    # depender's spec in build order.
    concrete_spec_edges: dict[str, set[str]] = {}
    for impl, meta in all_impls.items():
        impl_spec = meta.get("source_spec")
        if not impl_spec:
            continue
        for dep_impl in meta.get("concrete_dependencies", []):
            dep_spec = all_impls.get(dep_impl, {}).get("source_spec")
            if dep_spec and dep_spec != impl_spec:
                concrete_spec_edges.setdefault(impl_spec, set()).add(dep_spec)
        ext = meta.get("extends")
        if ext:
            ext_spec = all_impls.get(ext, {}).get("source_spec")
            if ext_spec and ext_spec != impl_spec:
                concrete_spec_edges.setdefault(impl_spec, set()).add(ext_spec)

    # Build the summary
    return {
        "input_specs": normalized_inputs,
        "layers": {
            "abstract": {
                "directly_changed": sorted(directly_changed),
                "transitively_affected": sorted(affected_specs - directly_changed),
                "total": len(affected_specs),
            },
            "concrete": {
                "affected_impls": sorted(affected_impls),
                "ghost_stale_impls": sorted(concrete_only_impls),
                "total": len(affected_impls),
            },
            "code": {
                "regenerate": affected_managed,
                "ghost_stale": ghost_stale_managed,
                "total_files": len(affected_managed) + len(ghost_stale_managed),
            },
        },
        "build_order": _compute_ripple_build_order(
            affected_specs | ghost_stale_specs,
            all_specs,
            concrete_spec_edges,
        ),
    }


def _compute_ripple_build_order(
    affected_specs: set[str],
    all_specs: dict[str, list[str]],
    concrete_spec_edges: dict[str, set[str]] | None = None,
) -> list[str]:
    """Compute build order for just the affected specs.

    *concrete_spec_edges* carries spec->set[spec] ordering edges derived from
    concrete-dependency / extends relationships so that specs reachable only
    through the concrete layer are sequenced correctly.
    """
    # Build subgraph of only affected specs
    subgraph: dict[str, list[str]] = {}
    for spec in affected_specs:
        deps = [d for d in all_specs.get(spec, []) if d in affected_specs]
        # Merge concrete-layer edges (dep spec must precede this spec)
        if concrete_spec_edges:
            for cdep in concrete_spec_edges.get(spec, set()):
                if cdep in affected_specs and cdep not in deps:
                    deps.append(cdep)
        subgraph[spec] = deps

    # Add missing nodes
    all_nodes = set(subgraph.keys())
    for deps_list in list(subgraph.values()):
        for dep in deps_list:
            if dep not in all_nodes:
                subgraph[dep] = []

    try:
        return topo_sort(subgraph)
    except ValueError:
        # Cycle detected -- fall back to alphabetical but warn via stderr
        print(
            json.dumps({"warning": "Cycle detected in dependency graph, falling back to alphabetical order"}),
            file=sys.stderr,
        )
        return sorted(affected_specs)
