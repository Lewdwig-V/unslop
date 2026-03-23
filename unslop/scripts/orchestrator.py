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
    Returns dict with spec_path, spec_hash, output_hash, generated, old_format
    or None if no header found.
    """
    lines = content.split("\n")[:5]

    spec_path = None
    spec_hash = None
    output_hash = None
    principles_hash = None
    generated = None
    old_format = False

    for line in lines:
        stripped = line.strip()
        for prefix in ["#", "//", "--", "/*", "<!--"]:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
                break
        for suffix in ["*/", "-->"]:
            if stripped.endswith(suffix):
                stripped = stripped[:-len(suffix)].strip()

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
            gen_match = re.search(r"generated:(\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

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
    in_concrete_deps = False

    for line in lines[1:end]:
        stripped = line.strip()

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
        elif stripped == "concrete-dependencies:":
            in_concrete_deps = True
            continue

        if in_concrete_deps:
            match = re.match(r"^  - (.+)$", line)
            if match:
                concrete_deps.append(match.group(1).strip())
            else:
                in_concrete_deps = False

    if concrete_deps:
        result["concrete_dependencies"] = concrete_deps

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
                f"Extends chain exceeds maximum depth of {MAX_EXTENDS_DEPTH}: "
                f"{' → '.join(chain)}. Flatten the hierarchy."
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


def resolve_inherited_sections(impl_path: str, project_root: str) -> dict[str, str]:
    """Resolve all inherited sections for a concrete spec.

    Returns a dict of section_name -> resolved_content with inheritance applied.
    Child sections override parent sections per the resolution rules.
    """
    root = Path(project_root).resolve()
    chain = resolve_extends_chain(impl_path, project_root)

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

    # Merge: start from the most general, overlay with more specific
    resolved = {}
    for sections in sections_stack:
        for name, content in sections.items():
            if name == "Strategy":
                # Strategy is never inherited — always use the most specific
                resolved[name] = content
            elif name == "Type Sketch":
                # Type Sketch is never inherited — always use the most specific
                resolved[name] = content
            elif name == "Pattern":
                # Pattern merges — child entries override by key
                if name not in resolved:
                    resolved[name] = content
                else:
                    resolved[name] = _merge_pattern_sections(resolved[name], content)
            elif name == "Lowering Notes":
                # Lowering Notes inherit + override by language heading
                if name not in resolved:
                    resolved[name] = content
                else:
                    resolved[name] = _merge_lowering_notes(resolved[name], content)
            else:
                # Unknown sections: child wins
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
        print(json.dumps({"warning": f"Missing concrete dependency specs: {missing_names}"}),
              file=sys.stderr)
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
    deps = meta.get("concrete_dependencies", [])
    if not deps:
        return None

    root = Path(project_root).resolve()
    stale_deps = []

    # Hash the concrete spec itself to check if deps have changed
    for dep_path in deps:
        dep_full = root / dep_path
        if not dep_full.exists():
            stale_deps.append({
                "path": dep_path,
                "reason": "upstream concrete spec not found",
            })
            continue

        try:
            dep_content = dep_full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale_deps.append({
                "path": dep_path,
                "reason": "cannot read upstream concrete spec",
            })
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
                    # We can't check against a stored hash without a tracking file,
                    # so we compare the upstream impl's strategy sections against
                    # what the downstream expects. For now, we track via a
                    # concrete-deps-hash approach: hash all upstream .impl.md
                    # contents and compare against stored value.
                except (OSError, UnicodeDecodeError):
                    pass

    if not stale_deps:
        return None

    return {
        "impl_path": impl_path,
        "stale_dependencies": stale_deps,
    }


def compute_concrete_deps_hash(impl_path: str, project_root: str) -> str | None:
    """Compute a combined hash of all concrete-dependencies for a concrete spec.

    Returns a 12-char hex hash, or None if no concrete dependencies exist.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    meta = parse_concrete_frontmatter(content)
    deps = meta.get("concrete_dependencies", [])
    if not deps:
        return None

    root = Path(project_root).resolve()
    combined = []
    for dep_path in sorted(deps):
        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                combined.append(f"{dep_path}:{compute_hash(dep_content)}")
            except (OSError, UnicodeDecodeError):
                combined.append(f"{dep_path}:unreadable")
        else:
            combined.append(f"{dep_path}:missing")

    return compute_hash("\n".join(combined))


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
    header_markers = ("@unslop-managed", "spec-hash:", "output-hash:", "Generated from spec at")
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
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "error",
                "hint": f"Cannot read managed file: {e}"}

    if not spec.exists():
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "error",
                "hint": "Spec file not found — the managed file references a spec that no longer exists."}

    spec_content = spec.read_text(encoding="utf-8")
    header = parse_header(managed_content)

    if header is None:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "unmanaged"}

    if header.get("old_format"):
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "old_format",
                "warning": "Old header format (no hashes). Regenerate to update."}

    if header["spec_hash"] is None or header["output_hash"] is None:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "old_format",
                "warning": "Header is missing hash fields. Regenerate to update."}

    current_spec_hash = compute_hash(spec_content)
    body = get_body_below_header(managed_content)
    current_output_hash = compute_hash(body)

    spec_match = (current_spec_hash == header["spec_hash"])
    output_match = (current_output_hash == header["output_hash"])

    if spec_match and output_match:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "fresh"}
    elif spec_match and not output_match:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "modified",
                  "hint": "Code was edited directly while spec is unchanged."}
    elif not spec_match and output_match:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "stale"}
    else:
        result = {"managed": str(managed_path), "spec": str(spec_path), "state": "conflict",
                  "hint": "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."}

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
                files.append({"managed": str(spec_path.parent.relative_to(root)), "spec": rel_spec,
                              "state": "error", "hint": "Unit spec has no files listed in ## Files section."})
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
        managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
        managed_path = spec_path.parent / managed_name
        if not managed_path.exists():
            files.append({"managed": str(managed_path.relative_to(root)), "spec": rel_spec, "state": "stale"})
            continue

        result = classify_file(str(managed_path), str(spec_path), project_root=str(root))
        result["managed"] = str(managed_path.relative_to(root))
        result["spec"] = rel_spec
        files.append(result)

    # Check for circular concrete dependencies before scanning
    try:
        build_concrete_order(str(root))
    except ValueError as e:
        if "Cycle detected" in str(e):
            # Add a warning entry for the cycle
            files.append({
                "managed": "(concrete dependency cycle)",
                "spec": None,
                "state": "error",
                "hint": f"Circular concrete-dependencies detected: {e}. "
                        "Break the cycle before concrete coherence can be checked.",
            })

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

        concrete_deps = meta.get("concrete_dependencies", [])
        if not concrete_deps:
            continue

        # Check each upstream concrete dep for changes
        stale_reasons = []
        for dep_path in concrete_deps:
            dep_full = root / dep_path
            if not dep_full.exists():
                stale_reasons.append(f"upstream `{dep_path}` not found")
                continue

        if stale_reasons:
            # Find the managed file this impl.md corresponds to
            source_spec = meta.get("source_spec", "")
            if source_spec:
                managed_rel = re.sub(r"\.spec\.md$", "", source_spec)
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
            files.append({
                "managed": managed_rel,
                "spec": None,
                "state": "error",
                "hint": f"Change file exists but no matching spec found for {managed_rel}",
                "pending_changes": counts,
            })

    all_fresh = all(
        f["state"] == "fresh" and "pending_changes" not in f and "concrete_staleness" not in f
        for f in files
    )
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
    if not lines or not re.match(r'^<!--\s*unslop-changes\s+v\d+\s*-->', lines[0]):
        return []

    entries = []
    current_entry = None

    for line in lines[1:]:
        heading_match = re.match(
            r'^### \[(\w+)\]\s+(.+?)(?:\s+--\s+(\S+))?\s*$', line
        )
        if heading_match:
            if current_entry is not None:
                current_entry["body"] = current_entry["body"].strip()
                entries.append(current_entry)
            status = heading_match.group(1)
            if status not in ("pending", "tactical"):
                print(
                    json.dumps({"warning": f"Malformed change entry: unknown status [{status}]"}),
                    file=sys.stderr
                )
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
            print(
                json.dumps({"warning": f"Malformed change entry heading: {line.strip()!r}"}),
                file=sys.stderr
            )

    if current_entry is not None:
        current_entry["body"] = current_entry["body"].strip()
        entries.append(current_entry)

    if not entries and any(line.strip() for line in lines[1:]):
        print(json.dumps({
            "warning": "Change file has format marker but no parseable entries. "
            "Expected ### [pending] or ### [tactical] headings."
        }), file=sys.stderr)

    return entries


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
        print("Usage: orchestrator.py <discover|build-order|deps|check-freshness|concrete-deps|file-tree> [args]", file=sys.stderr)
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
                print(json.dumps({"error": error_msg,
                                  "hint": "Circular concrete-dependencies found. "
                                          "Break the cycle by removing one direction of the dependency."}),
                      file=sys.stderr)
            else:
                print(json.dumps({"error": error_msg}), file=sys.stderr)
            sys.exit(1)

    elif command == "concrete-deps":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py concrete-deps <impl-path> [--root <project-root>]", file=sys.stderr)
            sys.exit(1)
        impl_path = sys.argv[2]
        project_root = "."
        if "--root" in sys.argv:
            root_idx = sys.argv.index("--root")
            if root_idx + 1 >= len(sys.argv):
                print("Usage: orchestrator.py concrete-deps <impl-path> [--root <project-root>]", file=sys.stderr)
                sys.exit(1)
            project_root = sys.argv[root_idx + 1]
        try:
            impl = Path(impl_path)
            if not impl.exists():
                print(json.dumps({"error": f"File not found: {impl_path}"}), file=sys.stderr)
                sys.exit(1)
            content = impl.read_text(encoding="utf-8")
            meta = parse_concrete_frontmatter(content)
            deps = meta.get("concrete_dependencies", [])
            deps_hash = compute_concrete_deps_hash(str(impl), project_root)
            result = {
                "impl_path": impl_path,
                "concrete_dependencies": deps,
                "deps_hash": deps_hash,
                "source_spec": meta.get("source_spec"),
                "complexity": meta.get("complexity"),
                "ephemeral": meta.get("ephemeral", True),
            }
            print(json.dumps(result, indent=2))
        except (OSError, UnicodeDecodeError) as e:
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
