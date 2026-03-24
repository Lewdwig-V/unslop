"""Concrete spec graph: extends chains, inheritance resolution, build ordering."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..core.frontmatter import parse_concrete_frontmatter
from ..core.hashing import compute_hash
from .graph import topo_sort


MAX_EXTENDS_DEPTH = 3


def resolve_extends_chain(impl_path: str, project_root: str) -> list[str]:
    """Resolve the extends chain for a concrete spec.

    Returns list of impl paths starting from the input (most specific)
    and walking up to the root parent (most general). The input impl_path
    is always the FIRST element.

    Raises ValueError on:
    - Cycle in extends chain
    - Chain depth exceeding MAX_EXTENDS_DEPTH
    - Missing parent file
    """
    root = Path(project_root).resolve()
    chain = []
    visited = set()
    current = impl_path

    while current:
        resolved = str((root / current).resolve())

        if resolved in visited:
            chain_str = " -> ".join(chain + [current])
            raise ValueError(f"Cycle detected in extends chain: {chain_str}")

        chain.append(current)
        visited.add(resolved)

        if len(chain) > MAX_EXTENDS_DEPTH:
            raise ValueError(
                f"Extends chain exceeds maximum depth of {MAX_EXTENDS_DEPTH}: {' -> '.join(chain)}. Flatten the hierarchy."
            )

        full_path = root / current
        if not full_path.exists():
            if len(chain) == 1:
                # The impl itself doesn't exist -- not an error, just no chain
                return chain
            raise ValueError(f"Missing parent concrete spec in extends chain: {current}")

        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Cannot read concrete spec in extends chain: {full_path} ({e})")

        meta = parse_concrete_frontmatter(content)
        current = meta.get("extends")

    return chain


"""Section-specific inheritance policies for resolve_inherited_sections().

- STRICT_CHILD_ONLY: Parent section is purged during resolution. If the child
  omits it, the resolved spec has no such section -- Phase 0a.1 validation fails.
- Additive (Lowering Notes): Parent and child are merged by language heading.
- Overridable (Pattern, unknown sections): Child replaces parent if present;
  parent persists if child omits.
"""
STRICT_CHILD_ONLY = {
    "Strategy",
    "Type Sketch",
    "Representation Invariants",
    "Safety Contracts",
    "Concurrency Model",
    "State Machine",
}


def resolve_inherited_sections(impl_path: str, project_root: str) -> dict[str, str]:
    """Resolve all inherited sections for a concrete spec.

    Returns a dict of section_name -> resolved_content with inheritance applied.

    Uses three inheritance policies:
    - Strict Child-Only (Strategy, Type Sketch): parent is always purged.
    - Additive (Lowering Notes): parent + child merged by language heading.
    - Overridable (Pattern, others): child replaces parent; parent persists if child omits.
    """
    root = Path(project_root).resolve()
    chain = resolve_extends_chain(impl_path, project_root)

    if len(chain) <= 1:
        # No inheritance -- just return the child's own sections
        full = root / impl_path
        if not full.exists():
            return {}
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Cannot read concrete spec: {full} ({e})")
        return _extract_sections(content)

    # Read sections from each level (most general first)
    # chain is [child, parent, grandparent] -- reverse to get [grandparent, parent, child]
    sections_stack = []
    for path in reversed(chain):
        full = root / path
        if not full.exists():
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Cannot read concrete spec in inheritance chain: {full} ({e})")

        sections = _extract_sections(content)
        sections_stack.append(sections)

    if not sections_stack:
        return {}

    # Separate child (last in stack = most specific) from parents
    parent_sections_list = sections_stack[:-1]
    child_sections = sections_stack[-1]

    # Step 1: Build resolved parent sections (merge all parent levels)
    parent_resolved = {}
    for sections in parent_sections_list:
        for name, content in sections.items():
            if name == "Pattern":
                if name not in parent_resolved:
                    parent_resolved[name] = content
                else:
                    parent_resolved[name] = _merge_pattern_sections(parent_resolved[name], content)
            elif name == "Lowering Notes":
                if name not in parent_resolved:
                    parent_resolved[name] = content
                else:
                    parent_resolved[name] = _merge_lowering_notes(parent_resolved[name], content)
            else:
                parent_resolved[name] = content

    # Step 2: Purge strict child-only sections from parent
    for section in STRICT_CHILD_ONLY:
        parent_resolved.pop(section, None)

    # Step 3: Start with purged parent, apply child overrides/additions
    resolved = dict(parent_resolved)
    for name, content in child_sections.items():
        if name == "Lowering Notes" and name in resolved:
            resolved[name] = _merge_lowering_notes(resolved[name], content)
        elif name == "Pattern" and name in resolved:
            resolved[name] = _merge_pattern_sections(resolved[name], content)
        else:
            resolved[name] = content

    return resolved


def _extract_sections(content: str) -> dict[str, str]:
    """Extract ## sections from a markdown file into a dict."""
    sections = {}
    current_name = None
    current_lines = []

    # Strip frontmatter
    lines = content.split("\n")
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break

    for line in lines[body_start:]:
        match = re.match(r"^## (.+)$", line)
        if match:
            if current_name:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = match.group(1).strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections


def _merge_pattern_sections(parent: str, child: str) -> str:
    """Merge Pattern sections. Child entries override parent entries by key."""
    parent_patterns = _parse_pattern_entries(parent)
    child_patterns = _parse_pattern_entries(child)
    # Child overrides parent
    merged = {**parent_patterns, **child_patterns}
    return "\n".join(f"- **{k}**: {v}" for k, v in merged.items())


def _parse_pattern_entries(content: str) -> dict[str, str]:
    """Parse '- **Key**: Value' pattern entries into a dict."""
    entries = {}
    for line in content.split("\n"):
        match = re.match(r"^\s*-\s+\*\*(.+?)\*\*:\s*(.+)$", line)
        if match:
            entries[match.group(1).strip()] = match.group(2).strip()
    return entries


def _merge_lowering_notes(parent: str, child: str) -> str:
    """Merge Lowering Notes by language heading. Child overrides matching headings."""
    parent_langs = _parse_language_blocks(parent)
    child_langs = _parse_language_blocks(child)
    merged = {**parent_langs, **child_langs}
    parts = []
    for lang, content in merged.items():
        parts.append(f"### {lang}")
        parts.append(content)
    return "\n\n".join(parts)


def _parse_language_blocks(content: str) -> dict[str, str]:
    """Parse ### Language blocks from Lowering Notes into a dict."""
    blocks = {}
    current_lang = None
    current_lines = []

    for line in content.split("\n"):
        match = re.match(r"^### (.+)$", line)
        if match:
            if current_lang:
                blocks[current_lang] = "\n".join(current_lines).strip()
            current_lang = match.group(1).strip()
            current_lines = []
        elif current_lang is not None:
            current_lines.append(line)

    if current_lang:
        blocks[current_lang] = "\n".join(current_lines).strip()

    return blocks


def flatten_inheritance_chain(impl_path: str, project_root: str) -> dict:
    """Produce a flattened view of the inheritance chain for a concrete spec.

    Returns a dict with:
      - chain: list of impl paths (most general first)
      - levels: per-level section snapshots with attribution
      - resolved: the final merged sections after inheritance
    """
    root = Path(project_root).resolve()
    chain = resolve_extends_chain(impl_path, project_root)

    # Normalize chain entries to be relative to project root
    normalized = []
    for p in chain:
        pp = Path(p)
        if pp.is_absolute():
            try:
                p = str(pp.relative_to(root))
            except ValueError:
                pass
        normalized.append(p)
    chain = normalized

    levels = []
    for path in reversed(chain):
        full = root / path
        sections = {}
        if full.exists():
            try:
                content = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                content = ""
            sections = _extract_sections(content)
        levels.append({"impl": path, "sections": sections})

    resolved = resolve_inherited_sections(impl_path, project_root)

    # Build attribution: for each resolved section, record which level provided it
    attribution = {}
    for section_name, resolved_content in resolved.items():
        if section_name == "Lowering Notes":
            # Attribute by language block
            lang_sources = {}
            # Walk levels child-first to find the most specific provider
            for level in reversed(levels):
                raw = level["sections"].get("Lowering Notes", "")
                if raw:
                    for lang in _parse_language_blocks(raw):
                        if lang not in lang_sources:
                            lang_sources[lang] = level["impl"]
            attribution[section_name] = lang_sources
        elif section_name == "Pattern":
            pattern_sources = {}
            for level in reversed(levels):
                raw = level["sections"].get("Pattern", "")
                if raw:
                    for key in _parse_pattern_entries(raw):
                        if key not in pattern_sources:
                            pattern_sources[key] = level["impl"]
            attribution[section_name] = pattern_sources
        else:
            # Non-merging sections: find the most specific level that defines it
            for level in reversed(levels):
                if section_name in level["sections"]:
                    attribution[section_name] = level["impl"]
                    break

    return {
        "chain": list(reversed(chain)),
        "levels": levels,
        "resolved": resolved,
        "attribution": attribution,
    }


def build_concrete_order(directory: str) -> list[str]:
    """Read all *.impl.md files in directory, parse concrete-dependencies, return topo-sorted list.

    Raises ValueError if a cycle is detected in the concrete dependency graph.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    impl_files = sorted(root.rglob("*.impl.md"))
    graph: dict[str, list[str]] = {}

    for impl_path in impl_files:
        name = str(impl_path.relative_to(root))
        try:
            content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            graph[name] = []
            continue
        meta = parse_concrete_frontmatter(content)
        deps = list(meta.get("concrete_dependencies", []))
        # extends is an implicit dependency -- parent must be processed before child
        if "extends" in meta:
            deps.append(meta["extends"])
        graph[name] = deps

    # Add missing nodes (deps that don't have their own .impl.md)
    all_nodes = set(graph.keys())
    missing: dict[str, list[str]] = {}
    for deps_list in graph.values():
        for dep in deps_list:
            if dep not in all_nodes and dep not in missing:
                missing[dep] = []
    if missing:
        missing_names = ", ".join(sorted(missing.keys()))
        print(json.dumps({"warning": f"Missing concrete dependency specs: {missing_names}"}), file=sys.stderr)
    graph.update(missing)

    return topo_sort(graph)


def check_concrete_staleness(
    impl_path: str,
    project_root: str,
) -> dict | None:
    """Check if a concrete spec's upstream dependencies have changed.

    Returns a dict describing ghost staleness, or None if fresh/not applicable.
    Raises ValueError if the impl file exists but cannot be read.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"Cannot read concrete spec for staleness check: {impl} ({e})")

    meta = parse_concrete_frontmatter(content)
    providers = get_all_strategy_providers(meta)
    if not providers:
        return None

    root = Path(project_root).resolve()
    stale_deps = []

    # Hash all strategy providers (deps + parents) for changes
    for dep_path in providers:
        dep_full = root / dep_path
        if not dep_full.exists():
            stale_deps.append(
                {
                    "path": dep_path,
                    "reason": "upstream concrete spec not found",
                }
            )
            continue

        try:
            dep_content = dep_full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale_deps.append(
                {
                    "path": dep_path,
                    "reason": "cannot read upstream concrete spec",
                }
            )
            continue

        dep_meta = parse_concrete_frontmatter(dep_content)

        # Check if the upstream concrete spec's source-spec has changed
        upstream_source = dep_meta.get("source_spec")
        if upstream_source:
            source_full = root / upstream_source
            if source_full.exists():
                try:
                    source_content = source_full.read_text(encoding="utf-8")
                    source_hash = compute_hash(source_content)
                    # If upstream source spec changed, flag as stale
                    stale_deps.append(
                        {
                            "path": dep_path,
                            "reason": f"upstream source-spec {upstream_source} changed ({source_hash[:8]})",
                        }
                    )
                except (OSError, UnicodeDecodeError):
                    stale_deps.append(
                        {
                            "path": dep_path,
                            "reason": f"upstream source-spec {upstream_source} unreadable",
                        }
                    )

    if not stale_deps:
        return None

    return {
        "impl_path": impl_path,
        "stale_dependencies": stale_deps,
    }


def get_all_strategy_providers(meta: dict) -> list[str]:
    """Combine explicit concrete_dependencies and extends parents.

    Both are "strategy providers" for hashing purposes -- a change
    to either should trigger ghost-staleness in the child spec.
    """
    deps = set(meta.get("concrete_dependencies", []))
    extends = meta.get("extends")
    if extends:
        if isinstance(extends, list):
            deps.update(extends)
        else:
            deps.add(extends)
    return sorted(deps)
