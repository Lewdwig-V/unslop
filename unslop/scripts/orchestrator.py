"""unslop orchestrator — dependency resolution and file discovery for multi-file takeover."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def compute_hash(content: str) -> str:
    """SHA-256 hash of content, truncated to 12 hex chars.

    Content is stripped of leading/trailing whitespace before hashing
    to normalize across platforms.
    """
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:12]


def parse_header(content: str) -> dict | None:
    """Parse @unslop-managed header from a managed file.

    Reads the first 5 lines looking for the header markers.
    Returns dict with spec_path, spec_hash, output_hash, generated, old_format,
    concrete_deps_hash (legacy), and concrete_manifest (new per-dep format).

    concrete_manifest is a dict of {dep_path: hash} parsed from:
      concrete-manifest:dep1.impl.md:a3f8c2e9b7d1,dep2.impl.md:7f2e1b8a9c04
    """
    lines = content.split("\n")[:5]

    spec_path = None
    spec_hash = None
    output_hash = None
    principles_hash = None
    concrete_deps_hash = None
    concrete_manifest = None
    generated = None
    old_format = False

    for line in lines:
        stripped = line.strip()
        for prefix in ["#", "//", "--", "/*", "<!--"]:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].strip()
                break
        for suffix in ["*/", "-->"]:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)].strip()

        if "@unslop-managed" in stripped:
            m = re.search(r"Edit (.+?) instead", stripped)
            if m:
                spec_path = m.group(1)

        hash_match = re.search(r"spec-hash:([0-9a-f]{12})", stripped)
        if hash_match:
            spec_hash = hash_match.group(1)
            out_match = re.search(r"output-hash:([0-9a-f]{12})", stripped)
            if out_match:
                output_hash = out_match.group(1)
            prin_match = re.search(r"principles-hash:([0-9a-f]{12})", stripped)
            if prin_match:
                principles_hash = prin_match.group(1)
            cdeps_match = re.search(r"concrete-deps-hash:([0-9a-f]{12})", stripped)
            if cdeps_match:
                concrete_deps_hash = cdeps_match.group(1)
            gen_match = re.search(r"generated:(\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

        # Parse concrete-manifest (new per-dep format)
        manifest_match = re.search(r"concrete-manifest:(.+?)(?:\s|$)", stripped)
        if manifest_match:
            raw = manifest_match.group(1)
            manifest = {}
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                # Format: path/to/dep.impl.md:a3f8c2e9b7d1
                last_colon = entry.rfind(":")
                if last_colon > 0:
                    dep_path = entry[:last_colon]
                    dep_hash = entry[last_colon + 1:]
                    if re.match(r"^[0-9a-f]{12}$", dep_hash):
                        manifest[dep_path] = dep_hash
            if manifest:
                concrete_manifest = manifest

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
        "principles_hash": principles_hash,
        "concrete_deps_hash": concrete_deps_hash,
        "concrete_manifest": concrete_manifest,
        "generated": generated,
        "old_format": old_format,
    }


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


def parse_concrete_frontmatter(content: str) -> dict:
    """Parse frontmatter from a concrete spec (.impl.md) file.

    Returns dict with: source_spec, target_language, ephemeral, complexity,
    concrete_dependencies (list of paths).
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return {}

    result = {}
    concrete_deps = []
    targets = []
    in_concrete_deps = False
    in_targets = False
    current_target = None

    for line in lines[1:end]:
        stripped = line.strip()

        # Handle nested target parsing first
        if in_targets:
            if re.match(r"^  - path:", line):
                if current_target:
                    targets.append(current_target)
                current_target = {"path": line.split(":", 1)[1].strip()}
                continue
            elif current_target and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_target[key.strip()] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_target:
                    targets.append(current_target)
                    current_target = None
                in_targets = False

        if in_concrete_deps:
            match = re.match(r"^  - (.+)$", line)
            if match:
                concrete_deps.append(match.group(1).strip())
                continue
            else:
                in_concrete_deps = False

        if stripped.startswith("source-spec:"):
            result["source_spec"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("target-language:"):
            result["target_language"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("ephemeral:"):
            val = stripped.split(":", 1)[1].strip().lower()
            result["ephemeral"] = val == "true"
        elif stripped.startswith("complexity:"):
            result["complexity"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("extends:"):
            result["extends"] = stripped.split(":", 1)[1].strip()
        elif stripped == "targets:":
            in_targets = True
        elif stripped == "concrete-dependencies:":
            in_concrete_deps = True

    # Flush final target
    if current_target:
        targets.append(current_target)

    if concrete_deps:
        result["concrete_dependencies"] = concrete_deps
    if targets:
        result["targets"] = targets

    return result


MAX_EXTENDS_DEPTH = 3


def resolve_extends_chain(impl_path: str, project_root: str) -> list[str]:
    """Resolve the extends chain for a concrete spec.

    Returns list of impl paths in resolution order (most general first,
    most specific last). The input impl_path is always the last element.

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
            chain_str = " → ".join(chain + [current])
            raise ValueError(f"Cycle detected in extends chain: {chain_str}")

        chain.append(current)
        visited.add(resolved)

        if len(chain) > MAX_EXTENDS_DEPTH:
            raise ValueError(
                f"Extends chain exceeds maximum depth of {MAX_EXTENDS_DEPTH}: {' → '.join(chain)}. Flatten the hierarchy."
            )

        full_path = root / current
        if not full_path.exists():
            if len(chain) == 1:
                # The impl itself doesn't exist — not an error, just no chain
                return chain
            raise ValueError(f"Missing parent concrete spec in extends chain: {current}")

        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            break

        meta = parse_concrete_frontmatter(content)
        current = meta.get("extends")

    return chain


"""Section-specific inheritance policies for resolve_inherited_sections().

- STRICT_CHILD_ONLY: Parent section is purged during resolution. If the child
  omits it, the resolved spec has no such section — Phase 0a.1 validation fails.
- Additive (Lowering Notes): Parent and child are merged by language heading.
- Overridable (Pattern, unknown sections): Child replaces parent if present;
  parent persists if child omits.
"""
STRICT_CHILD_ONLY = {"Strategy", "Type Sketch"}


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
        # No inheritance — just return the child's own sections
        full = root / impl_path
        if not full.exists():
            return {}
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}
        return _extract_sections(content)

    # Read sections from each level (most general first)
    # chain is [child, parent, grandparent] — reverse to get [grandparent, parent, child]
    sections_stack = []
    for path in reversed(chain):
        full = root / path
        if not full.exists():
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

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
        # extends is an implicit dependency — parent must be processed before child
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
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

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
                    source_full.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    pass

    if not stale_deps:
        return None

    return {
        "impl_path": impl_path,
        "stale_dependencies": stale_deps,
    }


def get_all_strategy_providers(meta: dict) -> list[str]:
    """Combine explicit concrete_dependencies and extends parents.

    Both are "strategy providers" for hashing purposes — a change
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


def get_registry_key_for_spec(source_spec: str) -> str:
    """Map an impl.md's source-spec to the managed-file registry key.

    Unit specs (*.unit.spec.md) use the parent directory as the registry key,
    matching how check_freshness() registers them.  Per-file specs strip
    .spec.md to get the managed filename.
    """
    if source_spec.endswith(".unit.spec.md"):
        parent = str(Path(source_spec).parent)
        # Top-level unit spec: parent is ".", registry key is "."
        return parent
    return re.sub(r"\.spec\.md$", "", source_spec)


def _gather_recursive_providers(
    root: Path,
    meta: dict,
    seen: set | None = None,
) -> list[str]:
    """Recursively gather all strategy provider content from the full DAG.

    Walks concrete-dependencies and extends transitively, returning a
    sorted list of ``path:hash`` entries for every node in the tree.
    The ``seen`` set prevents infinite loops on circular references.
    """
    if seen is None:
        seen = set()

    entries = []
    providers = get_all_strategy_providers(meta)

    for dep_path in sorted(providers):
        if dep_path in seen:
            continue
        seen.add(dep_path)

        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                entries.append(f"{dep_path}:{compute_hash(dep_content)}")
                # Recurse into this provider's own upstream
                dep_meta = parse_concrete_frontmatter(dep_content)
                entries.extend(_gather_recursive_providers(root, dep_meta, seen))
            except (OSError, UnicodeDecodeError):
                entries.append(f"{dep_path}:unreadable")
        else:
            entries.append(f"{dep_path}:missing")

    return entries


def compute_concrete_deps_hash(impl_path: str, project_root: str) -> str | None:
    """Compute a deep hash of all transitive strategy providers.

    Recursively walks concrete-dependencies and extends chains so that
    a change to a grandparent spec correctly invalidates all descendants.
    Returns a 12-char hex hash, or None if no strategy providers exist.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    meta = parse_concrete_frontmatter(content)
    providers = get_all_strategy_providers(meta)
    if not providers:
        return None

    root = Path(project_root).resolve()
    combined = _gather_recursive_providers(root, meta)
    return compute_hash("\n".join(combined))


def compute_concrete_manifest(impl_path: str, project_root: str) -> dict[str, str] | None:
    """Compute a per-dependency manifest for surgical ghost-staleness detection.

    Returns a dict of {dep_path: 12-char-hex-hash} for all direct strategy
    providers (concrete-dependencies + extends parent). Returns None if no
    strategy providers exist.

    Unlike compute_concrete_deps_hash (which produces a single opaque hash
    of all transitive deps), the manifest stores each direct dependency
    individually so check_freshness() can pinpoint exactly which dep changed.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    meta = parse_concrete_frontmatter(content)
    providers = get_all_strategy_providers(meta)
    if not providers:
        return None

    root = Path(project_root).resolve()
    manifest = {}
    for dep_path in sorted(providers):
        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                manifest[dep_path] = compute_hash(dep_content)
            except (OSError, UnicodeDecodeError):
                manifest[dep_path] = "unreadable000"
        else:
            manifest[dep_path] = "missing000000"[:12]

    return manifest if manifest else None


def format_manifest_header(manifest: dict[str, str]) -> str:
    """Format a concrete manifest dict as a header-safe string.

    Output: dep1.impl.md:a3f8c2e9b7d1,dep2.impl.md:7f2e1b8a9c04
    """
    return ",".join(f"{path}:{h}" for path, h in sorted(manifest.items()))


def diagnose_ghost_staleness(
    manifest: dict[str, str],
    project_root: str,
) -> list[dict]:
    """Compare stored manifest against current state, returning surgical diagnostics.

    For each changed dependency, walks its own upstream chain to find the
    root cause. Returns a list of diagnostic dicts:
      {dep: "path", stored_hash: "...", current_hash: "...", chain: ["path -> changed_upstream"]}
    """
    root = Path(project_root).resolve()
    diagnostics = []

    for dep_path, stored_hash in sorted(manifest.items()):
        dep_full = root / dep_path
        if not dep_full.exists():
            diagnostics.append({
                "dep": dep_path,
                "stored_hash": stored_hash,
                "current_hash": None,
                "reason": "not found",
                "chain": [dep_path],
            })
            continue

        try:
            dep_content = dep_full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            diagnostics.append({
                "dep": dep_path,
                "stored_hash": stored_hash,
                "current_hash": None,
                "reason": "unreadable",
                "chain": [dep_path],
            })
            continue

        current_hash = compute_hash(dep_content)
        if current_hash == stored_hash:
            continue  # This dep is fresh

        # This dep changed — walk its upstream to find root cause
        chain = _trace_change_chain(dep_path, root)
        diagnostics.append({
            "dep": dep_path,
            "stored_hash": stored_hash,
            "current_hash": current_hash,
            "reason": "changed",
            "chain": chain,
        })

    return diagnostics


def _trace_change_chain(dep_path: str, root: Path) -> list[str]:
    """Walk upstream from a changed dep to find the deepest changed node.

    Returns a chain like ["service.impl.md", "utils.impl.md"] meaning
    "service.impl.md changed because utils.impl.md changed."
    """
    chain = [dep_path]
    visited = {dep_path}
    current = dep_path

    while True:
        full = root / current
        if not full.exists():
            break

        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            break

        meta = parse_concrete_frontmatter(content)
        upstream = get_all_strategy_providers(meta)

        # Find which upstream deps exist and could be the root cause
        # We report the chain, not just the leaf — the user needs the path
        found_deeper = False
        for up in sorted(upstream):
            if up in visited:
                continue
            visited.add(up)
            chain.append(up)
            current = up
            found_deeper = True
            break  # Follow one chain (depth-first)

        if not found_deeper:
            break

    return chain


def format_ghost_diagnostic(diagnostics: list[dict]) -> list[str]:
    """Format diagnostics into human-readable strings for status output.

    Returns list of strings like:
      "upstream `service.impl.md` changed (via utils.impl.md)"
    """
    reasons = []
    for d in diagnostics:
        chain = d["chain"]
        if d["reason"] == "not found":
            reasons.append(f"upstream `{d['dep']}` not found")
        elif d["reason"] == "unreadable":
            reasons.append(f"upstream `{d['dep']}` unreadable")
        elif len(chain) == 1:
            reasons.append(f"upstream `{chain[0]}` changed")
        else:
            # chain[0] is the direct dep, chain[1:] is the upstream path
            via = " → ".join(chain[1:])
            reasons.append(f"upstream `{chain[0]}` changed (via {via})")
    return reasons


def _identify_changed_deps(
    dep_paths: list[str],
    stored_combined_hash: str,
    project_root: str,
) -> list[str]:
    """Identify which concrete deps changed by hashing each individually.

    Returns a list of human-readable reasons for ghost-staleness.
    Legacy fallback for files with concrete-deps-hash instead of concrete-manifest.
    """
    root = Path(project_root).resolve()
    changed = []
    for dep_path in sorted(dep_paths):
        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                dep_hash = compute_hash(dep_content)
                changed.append(f"upstream `{dep_path}` changed ({dep_hash[:8]})")
            except (OSError, UnicodeDecodeError):
                changed.append(f"upstream `{dep_path}` unreadable")
        else:
            changed.append(f"upstream `{dep_path}` not found")

    # We know the combined hash differs but can't pinpoint which single dep
    # changed without stored per-dep hashes. Return all deps as suspects.
    return changed


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
    "__pycache__",
    "node_modules",
    "target",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    "vendor",
    ".mypy_cache",
    ".pytest_cache",
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


def get_body_below_header(content: str) -> str:
    """Extract managed file content below the @unslop-managed header.

    Scans the first 5 lines for header markers, skipping blank lines.
    Returns everything after the last header line.
    """
    lines = content.split("\n")
    header_markers = ("@unslop-managed", "spec-hash:", "output-hash:", "Generated from spec at", "concrete-manifest:")
    body_start = 0
    for i in range(min(5, len(lines))):
        stripped = lines[i].strip()
        if any(m in stripped for m in header_markers) or stripped == "":
            body_start = i + 1
        else:
            break
    return "\n".join(lines[body_start:])


def classify_file(managed_path: str, spec_path: str, project_root: str | None = None) -> dict:
    """Classify a managed file's staleness using content hashing.

    4-state: fresh, stale, modified, conflict.
    Plus edge cases: unmanaged, old_format, error.
    """
    managed = Path(managed_path)
    spec = Path(spec_path)

    try:
        managed_content = managed.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "error",
            "hint": f"Cannot read managed file: {e}",
        }

    if not spec.exists():
        return {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "error",
            "hint": "Spec file not found — the managed file references a spec that no longer exists.",
        }

    spec_content = spec.read_text(encoding="utf-8")
    header = parse_header(managed_content)

    if header is None:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "unmanaged"}

    if header.get("old_format"):
        return {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "old_format",
            "warning": "Old header format (no hashes). Regenerate to update.",
        }

    if header["spec_hash"] is None or header["output_hash"] is None:
        return {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "old_format",
            "warning": "Header is missing hash fields. Regenerate to update.",
        }

    current_spec_hash = compute_hash(spec_content)
    body = get_body_below_header(managed_content)
    current_output_hash = compute_hash(body)

    spec_match = current_spec_hash == header["spec_hash"]
    output_match = current_output_hash == header["output_hash"]

    if spec_match and output_match:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "fresh"}
    elif spec_match and not output_match:
        result = {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "modified",
            "hint": "Code was edited directly while spec is unchanged.",
        }
    elif not spec_match and output_match:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "stale"}
    else:
        result = {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "conflict",
            "hint": "Spec and code have both diverged. Resolve manually or use --force to overwrite edits.",
        }

    # Principles check (only when project_root is provided)
    if project_root is not None and header.get("principles_hash") is not None:
        principles_path = Path(project_root) / ".unslop" / "principles.md"
        prin_changed = False
        message = ""
        if principles_path.exists():
            try:
                principles_content = principles_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                prin_changed = True
                message = f"Cannot read principles.md: {e}"
            else:
                current_prin_hash = compute_hash(principles_content)
                if current_prin_hash != header["principles_hash"]:
                    prin_changed = True
                    message = "Principles changed."
        else:
            prin_changed = True
            message = "Principles removed."

        if prin_changed:
            existing_hint = result.get("hint", "")
            result["hint"] = (existing_hint + f" {message}").strip()
            if result["state"] == "fresh":
                result["state"] = "stale"

    return result


def check_freshness(directory: str) -> dict:
    """Check freshness of all managed files in directory."""
    from collections import Counter

    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    specs = sorted(root.rglob("*.spec.md"))
    files = []

    for spec_path in specs:
        rel_spec = str(spec_path.relative_to(root))

        # Handle unit specs
        if spec_path.name.endswith(".unit.spec.md"):
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

            if not unit_files:
                files.append(
                    {
                        "managed": str(spec_path.parent.relative_to(root)),
                        "spec": rel_spec,
                        "state": "error",
                        "hint": "Unit spec has no files listed in ## Files section.",
                    }
                )
                continue

            worst_state = "fresh"
            priority = {"fresh": 0, "old_format": 1, "stale": 2, "modified": 3, "conflict": 4, "unmanaged": 5, "error": 6}
            missing_files = []
            principles_hints = []
            for uf in unit_files:
                mp = spec_path.parent / uf
                if mp.exists():
                    r = classify_file(str(mp), str(spec_path), project_root=str(root))
                    if priority.get(r["state"], 0) > priority.get(worst_state, 0):
                        worst_state = r["state"]
                    r_hint = r.get("hint", "")
                    if "principles" in r_hint.lower() or "cannot read principles" in r_hint.lower():
                        principles_hints.append(r_hint)
                else:
                    missing_files.append(uf)
                    if priority.get("stale", 0) > priority.get(worst_state, 0):
                        worst_state = "stale"

            entry = {"managed": str(spec_path.parent.relative_to(root)), "spec": rel_spec, "state": worst_state}
            if missing_files:
                entry["missing"] = missing_files
            if worst_state == "conflict":
                entry["hint"] = "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."
            elif worst_state == "modified":
                entry["hint"] = "Code was edited directly while spec is unchanged."
            if principles_hints:
                prin_msg = principles_hints[0]
                existing = entry.get("hint", "")
                entry["hint"] = (existing + f" {prin_msg}").strip()
            files.append(entry)
            continue

        # Per-file spec
        # If a corresponding .impl.md exists with explicit targets[],
        # skip the default basename deduction — the target-driven pass
        # will handle it.  This prevents ghost entries for files that
        # don't exist (e.g. "auth_logic" when targets point elsewhere).
        impl_companion = spec_path.parent / re.sub(r"\.spec\.md$", ".impl.md", spec_path.name)
        if impl_companion.exists():
            try:
                _ic = impl_companion.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                _ic = ""
            _ic_meta = parse_concrete_frontmatter(_ic)
            if _ic_meta.get("targets"):
                continue  # target-driven pass owns this spec's mappings

        managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
        managed_path = spec_path.parent / managed_name
        if not managed_path.exists():
            files.append({"managed": str(managed_path.relative_to(root)), "spec": rel_spec, "state": "stale"})
            continue

        result = classify_file(str(managed_path), str(spec_path), project_root=str(root))
        result["managed"] = str(managed_path.relative_to(root))
        result["spec"] = rel_spec
        files.append(result)

    # Target-driven discovery: scan .impl.md files with targets[] to find
    # managed files that live outside their spec's directory tree.
    seen_managed = {f["managed"] for f in files}
    target_owners = {}  # managed_rel -> impl_rel (for collision detection)

    # Record ownership from spec-driven pass (single-target defaults)
    for f in files:
        managed_rel = f["managed"]
        if managed_rel not in target_owners:
            target_owners[managed_rel] = f.get("spec", "")

    impl_files_for_targets = sorted(root.rglob("*.impl.md"))
    for impl_path in impl_files_for_targets:
        rel_impl = str(impl_path.relative_to(root))
        try:
            impl_content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta = parse_concrete_frontmatter(impl_content)
        targets_list = meta.get("targets", [])
        if not targets_list:
            continue

        source_spec = meta.get("source_spec", "")
        # Resolve spec path relative to the impl file's directory
        if source_spec:
            spec_full = (impl_path.parent / source_spec).resolve()
            if not spec_full.exists():
                spec_full = root / source_spec
        else:
            spec_full = None

        for target in targets_list:
            target_rel = target.get("path", "")
            if not target_rel:
                continue

            # Collision detection: two impl specs claiming the same target
            if target_rel in target_owners and target_owners[target_rel] != rel_impl:
                prev_owner = target_owners[target_rel]
                files.append(
                    {
                        "managed": target_rel,
                        "spec": source_spec,
                        "state": "error",
                        "hint": (
                            f"Target collision: `{target_rel}` claimed by both "
                            f"`{prev_owner}` and `{rel_impl}`. "
                            "Remove the duplicate target from one concrete spec."
                        ),
                        "impl_path": rel_impl,
                    }
                )
                continue
            target_owners[target_rel] = rel_impl

            # Skip if already tracked from the spec-driven pass
            if target_rel in seen_managed:
                continue
            seen_managed.add(target_rel)

            target_full = root / target_rel
            if spec_full and spec_full.exists():
                if not target_full.exists():
                    files.append(
                        {
                            "managed": target_rel,
                            "spec": source_spec,
                            "state": "stale",
                            "impl_path": rel_impl,
                        }
                    )
                else:
                    result = classify_file(
                        str(target_full),
                        str(spec_full),
                        project_root=str(root),
                    )
                    result["managed"] = target_rel
                    result["spec"] = source_spec
                    result["impl_path"] = rel_impl
                    files.append(result)
            elif not target_full.exists():
                files.append(
                    {
                        "managed": target_rel,
                        "spec": source_spec,
                        "state": "stale",
                        "hint": "Target file does not exist and spec not found.",
                        "impl_path": rel_impl,
                    }
                )
            else:
                files.append(
                    {
                        "managed": target_rel,
                        "spec": source_spec,
                        "state": "error",
                        "hint": f"Spec `{source_spec}` not found for target.",
                        "impl_path": rel_impl,
                    }
                )

    # Check for circular concrete dependencies before scanning
    try:
        build_concrete_order(str(root))
    except ValueError as e:
        if "Cycle detected" in str(e):
            # Add a warning entry for the cycle
            files.append(
                {
                    "managed": "(concrete dependency cycle)",
                    "spec": None,
                    "state": "error",
                    "hint": f"Circular concrete-dependencies detected: {e}. "
                    "Break the cycle before concrete coherence can be checked.",
                }
            )

    # Scan for concrete spec ghost staleness
    impl_files = sorted(root.rglob("*.impl.md"))
    for impl_path in impl_files:
        rel_impl = str(impl_path.relative_to(root))
        try:
            impl_content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta = parse_concrete_frontmatter(impl_content)
        if meta.get("ephemeral", True):
            continue  # Skip ephemeral concrete specs

        all_providers = get_all_strategy_providers(meta)
        if not all_providers:
            continue

        # Check each upstream strategy provider (deps + parents) for changes
        stale_reasons = []
        for dep_path in all_providers:
            dep_full = root / dep_path
            if not dep_full.exists():
                stale_reasons.append(f"upstream `{dep_path}` not found")
                continue

        # Determine which managed files this impl affects
        target_paths_for_hash = []
        targets_list = meta.get("targets", [])
        if targets_list:
            target_paths_for_hash = [t["path"] for t in targets_list if "path" in t]
        else:
            source_spec = meta.get("source_spec", "")
            if source_spec:
                target_paths_for_hash = [get_registry_key_for_spec(source_spec)]

        # Compare against stored manifest or hash in managed file headers
        if not stale_reasons:
            for managed_rel in target_paths_for_hash:
                managed_full = root / managed_rel

                # Collect candidate files to check for concrete-manifest/concrete-deps-hash.
                # For unit specs the registry key is a directory; we need to
                # check the headers of the individual managed files inside it.
                candidates = []
                if managed_full.is_dir():
                    # Unit spec: find managed files inside the directory
                    source_spec = meta.get("source_spec", "")
                    if source_spec:
                        spec_full = root / source_spec
                        if spec_full.exists():
                            try:
                                spec_content = spec_full.read_text(encoding="utf-8")
                            except (OSError, UnicodeDecodeError):
                                spec_content = ""
                            in_files = False
                            for sline in spec_content.split("\n"):
                                if re.match(r"^## Files", sline):
                                    in_files = True
                                    continue
                                if in_files:
                                    if re.match(r"^## ", sline):
                                        break
                                    fm = re.match(r"^\s*-\s+`([^`]+)`", sline)
                                    if fm:
                                        candidates.append(managed_full / fm.group(1))
                elif managed_full.is_file():
                    candidates = [managed_full]
                else:
                    continue

                for candidate in candidates:
                    if not candidate.exists():
                        continue
                    try:
                        managed_content = candidate.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    header = parse_header(managed_content)
                    if header is None:
                        continue

                    # Prefer concrete-manifest (surgical per-dep check)
                    stored_manifest = header.get("concrete_manifest")
                    if stored_manifest is not None:
                        diagnostics = diagnose_ghost_staleness(stored_manifest, str(root))
                        if diagnostics:
                            stale_reasons.extend(format_ghost_diagnostic(diagnostics))
                            break
                    else:
                        # Fall back to legacy concrete-deps-hash (coarse check)
                        stored_cdeps = header.get("concrete_deps_hash")
                        current_cdeps_hash = compute_concrete_deps_hash(str(impl_path), str(root))
                        if stored_cdeps is not None and current_cdeps_hash is not None and stored_cdeps != current_cdeps_hash:
                            changed = _identify_changed_deps(
                                all_providers,
                                stored_cdeps,
                                str(root),
                            )
                            for reason in changed:
                                stale_reasons.append(reason)
                            break

        if stale_reasons:
            # Determine which managed files this impl.md affects
            target_paths = []
            targets = meta.get("targets", [])
            if targets:
                # Multi-target: mark all targets as ghost-stale
                target_paths = [t["path"] for t in targets if "path" in t]
            else:
                # Single-target: derive from source-spec
                source_spec = meta.get("source_spec", "")
                if source_spec:
                    target_paths = [get_registry_key_for_spec(source_spec)]

            for managed_rel in target_paths:
                for f in files:
                    if f["managed"] == managed_rel:
                        if f["state"] == "fresh":
                            f["state"] = "ghost-stale"
                        reason_str = "; ".join(stale_reasons)
                        ghost_hint = f"Upstream concrete spec changed: {reason_str}"
                        existing = f.get("hint", "")
                        f["hint"] = (existing + f" {ghost_hint}").strip()
                        f["concrete_staleness"] = {
                            "impl_path": rel_impl,
                            "stale_deps": stale_reasons,
                        }
                        if targets:
                            total = len(targets)
                            idx = target_paths.index(managed_rel) + 1
                            f["multi_target"] = f"[target {idx}/{total}]"
                        break

    # Scan for pending change requests
    change_files = sorted(root.rglob("*.change.md"))
    for change_path in change_files:
        try:
            content = change_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(json.dumps({"warning": f"Cannot read change file: {exc}"}), file=sys.stderr)
            continue
        entries = parse_change_file(content)
        if not entries:
            continue

        # Derive managed file path: strip .change.md
        managed_name = re.sub(r"\.change\.md$", "", change_path.name)
        managed_rel = str((change_path.parent / managed_name).relative_to(root))

        status_counts = Counter(e["status"] for e in entries)
        counts = {
            "count": len(entries),
            "pending": status_counts.get("pending", 0),
            "tactical": status_counts.get("tactical", 0),
        }

        # Find and update the matching file entry
        # Check both exact match (per-file specs) and parent directory match (unit specs)
        change_dir = str(change_path.parent.relative_to(root))
        matched = False
        for f in files:
            if f["managed"] == managed_rel or f["managed"] == change_dir:
                if "pending_changes" in f:
                    # Accumulate counts for unit specs with multiple change files
                    f["pending_changes"]["count"] += counts["count"]
                    f["pending_changes"]["pending"] += counts["pending"]
                    f["pending_changes"]["tactical"] += counts["tactical"]
                else:
                    f["pending_changes"] = counts
                change_hint = f"{f['pending_changes']['count']} change request(s) awaiting processing."
                if "hint" in f and "change request" not in f["hint"]:
                    f["hint"] = f"{f['hint']} Additionally: {change_hint}"
                else:
                    f["hint"] = change_hint
                matched = True
                break
        if not matched:
            # Orphan change file -- no matching managed file
            print(json.dumps({"warning": f"Orphan change file: no managed file found for {managed_rel}"}), file=sys.stderr)
            files.append(
                {
                    "managed": managed_rel,
                    "spec": None,
                    "state": "error",
                    "hint": f"Change file exists but no matching spec found for {managed_rel}",
                    "pending_changes": counts,
                }
            )

    all_fresh = all(f["state"] == "fresh" and "pending_changes" not in f and "concrete_staleness" not in f for f in files)
    counts = Counter(f["state"] for f in files)
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))

    return {"status": "pass" if all_fresh else "fail", "files": files, "summary": summary}


def parse_change_file(content: str) -> list[dict]:
    """Parse stacked change entries from a *.change.md file.

    Returns list of dicts with: status, description, timestamp, body.
    Requires <!-- unslop-changes v1 --> format marker on first line.
    Malformed entries are skipped with a stderr warning.
    """
    lines = content.split("\n")
    if not lines or not re.match(r"^<!--\s*unslop-changes\s+v\d+\s*-->", lines[0]):
        return []

    entries = []
    current_entry = None

    for line in lines[1:]:
        heading_match = re.match(r"^### \[(\w+)\]\s+(.+?)(?:\s+--\s+(\S+))?\s*$", line)
        if heading_match:
            if current_entry is not None:
                current_entry["body"] = current_entry["body"].strip()
                entries.append(current_entry)
            status = heading_match.group(1)
            if status not in ("pending", "tactical"):
                print(json.dumps({"warning": f"Malformed change entry: unknown status [{status}]"}), file=sys.stderr)
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
            print(json.dumps({"warning": f"Malformed change entry heading: {line.strip()!r}"}), file=sys.stderr)

    if current_entry is not None:
        current_entry["body"] = current_entry["body"].strip()
        entries.append(current_entry)

    if not entries and any(line.strip() for line in lines[1:]):
        print(
            json.dumps(
                {
                    "warning": "Change file has format marker but no parseable entries. "
                    "Expected ### [pending] or ### [tactical] headings."
                }
            ),
            file=sys.stderr,
        )

    return entries


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
        all_impls[rel] = parse_concrete_frontmatter(content)

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

    # Map source-spec -> impl paths
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
        spec_path = root / spec
        if not spec_path.exists():
            continue

        # Check for multi-target impl
        impl_companion = spec_path.parent / re.sub(r"\.spec\.md$", ".impl.md", spec_path.name)
        targets_handled = False

        if impl_companion.exists():
            try:
                ic_content = impl_companion.read_text(encoding="utf-8")
                ic_meta = parse_concrete_frontmatter(ic_content)
                if ic_meta.get("targets"):
                    targets_handled = True
                    for target in ic_meta["targets"]:
                        managed_rel = target.get("path", "")
                        managed_full = root / managed_rel
                        entry = {
                            "managed": managed_rel,
                            "spec": spec,
                            "concrete": str(impl_companion.relative_to(root)),
                            "exists": managed_full.exists(),
                            "language": target.get("language", "unknown"),
                            "cause": "direct" if spec in directly_changed else "transitive",
                        }
                        if managed_full.exists():
                            result = classify_file(str(managed_full), str(spec_path), project_root=str(root))
                            entry["current_state"] = result["state"]
                        else:
                            entry["current_state"] = "new"
                        affected_managed.append(entry)
            except (OSError, UnicodeDecodeError):
                pass

        if not targets_handled:
            # Unit spec
            if spec.endswith(".unit.spec.md"):
                try:
                    content = spec_path.read_text(encoding="utf-8")
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
                                managed_rel = str((spec_path.parent / m.group(1)).relative_to(root))
                                managed_full = root / managed_rel
                                entry = {
                                    "managed": managed_rel,
                                    "spec": spec,
                                    "exists": managed_full.exists(),
                                    "cause": "direct" if spec in directly_changed else "transitive",
                                }
                                if managed_full.exists():
                                    result = classify_file(str(managed_full), str(spec_path), project_root=str(root))
                                    entry["current_state"] = result["state"]
                                else:
                                    entry["current_state"] = "new"
                                affected_managed.append(entry)
                except (OSError, UnicodeDecodeError):
                    pass
            else:
                # Per-file spec
                managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
                managed_full = spec_path.parent / managed_name
                managed_rel = str(managed_full.relative_to(root)) if managed_full.exists() else str(
                    (spec_path.parent / managed_name).relative_to(root)
                )
                entry = {
                    "managed": managed_rel,
                    "spec": spec,
                    "exists": managed_full.exists(),
                    "cause": "direct" if spec in directly_changed else "transitive",
                }
                if managed_full.exists():
                    result = classify_file(str(managed_full), str(spec_path), project_root=str(root))
                    entry["current_state"] = result["state"]
                else:
                    entry["current_state"] = "new"
                affected_managed.append(entry)

    # Add concrete-only affected files (ghost staleness via concrete deps, not abstract deps)
    concrete_only_impls = affected_impls - {
        str((root / impl).relative_to(root))
        for spec in affected_specs
        for impl in spec_to_impls.get(spec, [])
    }
    ghost_stale_managed: list[dict] = []
    for impl in sorted(concrete_only_impls):
        meta = all_impls.get(impl, {})
        src = meta.get("source_spec")
        if not src:
            continue
        # This impl's abstract spec wasn't directly affected — ghost staleness
        spec_path = root / src
        targets = meta.get("targets", [])
        if targets:
            for target in targets:
                managed_rel = target.get("path", "")
                managed_full = root / managed_rel
                ghost_stale_managed.append({
                    "managed": managed_rel,
                    "spec": src,
                    "concrete": impl,
                    "exists": managed_full.exists(),
                    "cause": "ghost-stale",
                    "ghost_source": impl,
                    "current_state": "ghost-stale",
                })
        else:
            managed_name = re.sub(r"\.spec\.md$", "", Path(src).name)
            managed_full = root / Path(src).parent / managed_name
            managed_rel = str(managed_full.relative_to(root)) if managed_full.exists() else str(
                (Path(src).parent / managed_name)
            )
            ghost_stale_managed.append({
                "managed": managed_rel,
                "spec": src,
                "concrete": impl,
                "exists": managed_full.exists(),
                "cause": "ghost-stale",
                "ghost_source": impl,
                "current_state": "ghost-stale",
            })

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
        "build_order": _compute_ripple_build_order(affected_specs, all_specs),
    }


def _compute_ripple_build_order(affected_specs: set[str], all_specs: dict[str, list[str]]) -> list[str]:
    """Compute build order for just the affected specs."""
    # Build subgraph of only affected specs
    subgraph: dict[str, list[str]] = {}
    for spec in affected_specs:
        deps = [d for d in all_specs.get(spec, []) if d in affected_specs]
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
        return sorted(affected_specs)


def render_dependency_graph(
    directory: str,
    scope: list[str] | None = None,
    include_code: bool = True,
) -> dict:
    """Render a Mermaid dependency graph of the spec/concrete/code layers.

    Args:
        directory: Project root directory.
        scope: Optional list of spec paths to focus on (with their transitive
               dependents). If None, renders the full project graph.
        include_code: Whether to include managed code file nodes.

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
        all_impls[rel] = parse_concrete_frontmatter(content)

    # If scope is set, compute the affected subgraph
    if scope:
        # Build reverse dep map
        reverse_deps: dict[str, list[str]] = {s: [] for s in all_specs}
        for spec, deps in all_specs.items():
            for dep in deps:
                reverse_deps.setdefault(dep, []).append(spec)

        # BFS from scope to find all transitively affected specs
        in_scope: set[str] = set()
        queue = list(scope)
        while queue:
            current = queue.pop(0)
            if current in in_scope:
                continue
            in_scope.add(current)
            # Include upstream deps
            for dep in all_specs.get(current, []):
                queue.append(dep)
            # Include downstream dependents
            for dependent in reverse_deps.get(current, []):
                queue.append(dependent)

        # Filter specs to scope
        all_specs = {k: v for k, v in all_specs.items() if k in in_scope}
        # Filter impls to those whose source-spec is in scope
        all_impls = {
            k: v for k, v in all_impls.items()
            if v.get("source_spec") in in_scope
            or any(d in in_scope for d in v.get("concrete_dependencies", []))
        }

    # Get freshness data for staleness coloring
    try:
        freshness = check_freshness(str(root))
        state_map = {f["managed"]: f["state"] for f in freshness.get("files", [])}
    except (ValueError, OSError):
        state_map = {}

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
            is_base = not meta.get("source_spec")
            if is_base:
                lines.append(f'    {nid}{{"{label}\\n<small>base .impl.md</small>"}}')
                lines.append(f"    class {nid} base")
                nodes_info.append({"id": nid, "path": impl, "layer": "concrete", "type": "base"})
            else:
                lines.append(f'    {nid}[/"{label}\\n<small>.impl.md</small>"/]')
                lines.append(f"    class {nid} impl")
                nodes_info.append({"id": nid, "path": impl, "layer": "concrete", "type": "impl"})

    # Concrete spec edges: source-spec link, extends, concrete-dependencies
    for impl, meta in sorted(all_impls.items()):
        source = meta.get("source_spec")
        if source and source in node_ids:
            lines.append(f"    {_node_id(source)} -.->|lowers to| {_node_id(impl)}")

        extends = meta.get("extends")
        if extends and extends in node_ids:
            lines.append(f"    {_node_id(extends)} ==>|extends| {_node_id(impl)}")
        elif extends:
            # Parent might be out of scope — add it as a reference node
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

        for spec in sorted(all_specs):
            # Multi-target check
            impl_companion = re.sub(r"\.spec\.md$", ".impl.md", spec)
            if impl_companion in all_impls:
                targets = all_impls[impl_companion].get("targets", [])
                if targets:
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

            # Single target
            if spec.endswith(".unit.spec.md"):
                continue  # Unit specs handled separately

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


def file_tree(directory: str) -> list[str]:
    """List git-tracked files in directory.

    Returns sorted list of tracked filenames relative to the directory.
    Used by the Architect stage to see file names without file contents.

    An empty repo (no tracked files) returns [].
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise ValueError("git executable not found on PATH. Install git and ensure it is available.")
    except subprocess.CalledProcessError as exc:
        stderr_detail = exc.stderr.strip() if exc.stderr else ""
        detail = f" ({stderr_detail})" if stderr_detail else ""
        raise ValueError(f"Not a git repository: {directory}{detail}") from exc

    files = [f for f in result.stdout.strip().split("\n") if f]
    return sorted(files)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        cmds = "discover|build-order|deps|check-freshness|concrete-order|concrete-deps|ripple-check|graph|file-tree"
        print(f"Usage: orchestrator.py <{cmds}> [args]", file=sys.stderr)
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
            extensions = sys.argv[ext_idx + 1 :]
            if not extensions:
                print("Usage: orchestrator.py discover <directory> [--extensions .py .rs]", file=sys.stderr)
                sys.exit(1)
        # Read exclude_patterns from config.json — search upward from scan dir to find project root
        extra_excludes = None
        search = Path(directory).resolve()
        config_path = None
        while search != search.parent:
            candidate = search / ".unslop" / "config.json"
            if candidate.exists():
                config_path = candidate
                break
            search = search.parent
        if config_path is not None:
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                extra_excludes = config.get("exclude_patterns", [])
            except json.JSONDecodeError as e:
                print(json.dumps({"warning": f"Ignoring malformed .unslop/config.json: {e}"}), file=sys.stderr)
            except OSError as e:
                print(json.dumps({"warning": f"Could not read .unslop/config.json: {e}"}), file=sys.stderr)
        try:
            result = discover_files(directory, extensions=extensions, extra_excludes=extra_excludes)
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

    elif command == "check-freshness":
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        try:
            result = check_freshness(directory)
            print(json.dumps(result, indent=2))
            sys.exit(0 if result["status"] == "pass" else 1)
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(2)

    elif command == "concrete-order":
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        try:
            result = build_concrete_order(directory)
            print(json.dumps(result, indent=2))
        except ValueError as e:
            error_msg = str(e)
            if "Cycle detected" in error_msg:
                print(
                    json.dumps(
                        {
                            "error": error_msg,
                            "hint": "Circular concrete-dependencies found. "
                            "Break the cycle by removing one direction of the dependency.",
                        }
                    ),
                    file=sys.stderr,
                )
            else:
                print(json.dumps({"error": error_msg}), file=sys.stderr)
            sys.exit(1)

    elif command == "concrete-deps":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py concrete-deps <impl-path> [--root <project-root>] [--flatten]", file=sys.stderr)
            sys.exit(1)
        impl_path = sys.argv[2]
        project_root = "."
        if "--root" in sys.argv:
            root_idx = sys.argv.index("--root")
            if root_idx + 1 >= len(sys.argv):
                print("Usage: orchestrator.py concrete-deps <impl-path> [--root <project-root>] [--flatten]", file=sys.stderr)
                sys.exit(1)
            project_root = sys.argv[root_idx + 1]
        flatten = "--flatten" in sys.argv
        try:
            impl = Path(impl_path)
            if not impl.exists():
                print(json.dumps({"error": f"File not found: {impl_path}"}), file=sys.stderr)
                sys.exit(1)
            content = impl.read_text(encoding="utf-8")
            meta = parse_concrete_frontmatter(content)
            deps = meta.get("concrete_dependencies", [])
            deps_hash = compute_concrete_deps_hash(str(impl), project_root)
            manifest = compute_concrete_manifest(str(impl), project_root)
            result = {
                "impl_path": impl_path,
                "concrete_dependencies": deps,
                "deps_hash": deps_hash,
                "manifest": manifest,
                "manifest_header": format_manifest_header(manifest) if manifest else None,
                "source_spec": meta.get("source_spec"),
                "complexity": meta.get("complexity"),
                "ephemeral": meta.get("ephemeral", True),
            }
            if flatten:
                result["flattened"] = flatten_inheritance_chain(str(impl), project_root)
            print(json.dumps(result, indent=2))
        except (OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "ripple-check":
        if len(sys.argv) < 3:
            print(
                "Usage: orchestrator.py ripple-check <spec-path> [<spec-path>...] [--root <project-root>]",
                file=sys.stderr,
            )
            sys.exit(1)
        project_root = "."
        spec_paths = []
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--root":
                if i + 1 >= len(sys.argv):
                    print("--root requires a value", file=sys.stderr)
                    sys.exit(1)
                project_root = sys.argv[i + 1]
                i += 2
            else:
                spec_paths.append(sys.argv[i])
                i += 1
        try:
            result = ripple_check(spec_paths, project_root)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "graph":
        directory = "."
        scope = []
        no_code = False
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--root":
                if i + 1 < len(sys.argv):
                    directory = sys.argv[i + 1]
                    i += 2
                else:
                    print("--root requires a value", file=sys.stderr)
                    sys.exit(1)
            elif sys.argv[i] == "--no-code":
                no_code = True
                i += 1
            elif sys.argv[i] == "--scope":
                # Collect all following non-flag args as scope specs
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    scope.append(sys.argv[i])
                    i += 1
            else:
                # Positional: treat as directory or scope spec
                if not scope:
                    directory = sys.argv[i]
                else:
                    scope.append(sys.argv[i])
                i += 1
        try:
            result = render_dependency_graph(
                directory,
                scope=scope if scope else None,
                include_code=not no_code,
            )
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "file-tree":
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        try:
            result = file_tree(directory)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
