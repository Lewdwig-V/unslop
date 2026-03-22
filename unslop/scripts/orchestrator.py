"""unslop orchestrator — dependency resolution and file discovery for multi-file takeover."""
from __future__ import annotations

import hashlib
import json
import re
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


def classify_file(managed_path: str, spec_path: str) -> dict:
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
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "fresh"}
    elif spec_match and not output_match:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "modified",
                "hint": "Code was edited directly while spec is unchanged."}
    elif not spec_match and output_match:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "stale"}
    else:
        return {"managed": str(managed_path), "spec": str(spec_path), "state": "conflict",
                "hint": "Spec and code have both diverged. Resolve manually or use --force to overwrite edits."}


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
            for uf in unit_files:
                mp = spec_path.parent / uf
                if mp.exists():
                    r = classify_file(str(mp), str(spec_path))
                    if priority.get(r["state"], 0) > priority.get(worst_state, 0):
                        worst_state = r["state"]
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
            files.append(entry)
            continue

        # Per-file spec
        managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
        managed_path = spec_path.parent / managed_name
        if not managed_path.exists():
            files.append({"managed": str(managed_path.relative_to(root)), "spec": rel_spec, "state": "stale"})
            continue

        result = classify_file(str(managed_path), str(spec_path))
        result["managed"] = str(managed_path.relative_to(root))
        result["spec"] = rel_spec
        files.append(result)

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
        f["state"] == "fresh" and "pending_changes" not in f
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


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator.py <discover|build-order|deps|check-freshness> [args]", file=sys.stderr)
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

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
