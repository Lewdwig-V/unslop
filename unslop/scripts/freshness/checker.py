"""Freshness checker: classify managed files and detect staleness."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from ..core.frontmatter import (
    parse_absorbed_from,
    parse_concrete_frontmatter,
    parse_distilled_from,
    parse_exuded_from,
    parse_managed_file,
    parse_needs_review,
)
from ..core.hashing import compute_hash, get_body_below_header, parse_header
from ..core.spec_discovery import get_registry_key_for_spec, parse_unit_spec_files
from ..dependencies.concrete_graph import (
    build_concrete_order,
    get_all_strategy_providers,
)
from .manifest import compute_concrete_deps_hash


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
            "hint": "Spec file not found -- the managed file references a spec that no longer exists.",
        }

    try:
        spec_content = spec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {
            "managed": str(managed_path),
            "spec": str(spec_path),
            "state": "error",
            "hint": f"Cannot read spec file: {e}",
        }

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
    body = get_body_below_header(managed_content, end_line=header.get("managed_end_line"))
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


def diagnose_ghost_staleness(
    manifest: dict[str, str],
    project_root: str,
) -> list[dict]:
    """Compare stored manifest against current state, returning surgical diagnostics.

    The manifest is expected to contain **transitive** deps (since v0.11.6).
    Each entry is compared directly against the current file on disk.  For each
    changed dependency, walks its upstream chain to find the root cause.

    Returns a list of diagnostic dicts:
      {dep: "path", stored_hash: "...", current_hash: "...",
       reason: "changed"|"not found"|"unreadable",
       chain: ["path -> changed_upstream"]}
    """
    root = Path(project_root).resolve()
    diagnostics = []

    for dep_path, stored_hash in sorted(manifest.items()):
        dep_full = root / dep_path
        if not dep_full.exists():
            diagnostics.append(
                {
                    "dep": dep_path,
                    "stored_hash": stored_hash,
                    "current_hash": None,
                    "reason": "not found",
                    "chain": [dep_path],
                }
            )
            continue

        try:
            dep_content = dep_full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            diagnostics.append(
                {
                    "dep": dep_path,
                    "stored_hash": stored_hash,
                    "current_hash": None,
                    "reason": "unreadable",
                    "chain": [dep_path],
                }
            )
            continue

        current_hash = compute_hash(dep_content)
        if current_hash == stored_hash:
            continue  # This dep is fresh

        # This dep changed -- walk its upstream to find root cause
        chain = _trace_change_chain(dep_path, root)
        diagnostics.append(
            {
                "dep": dep_path,
                "stored_hash": stored_hash,
                "current_hash": current_hash,
                "reason": "changed",
                "chain": chain,
            }
        )

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
        # We report the chain, not just the leaf -- the user needs the path
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
            via = " -> ".join(chain[1:])
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


def check_freshness(directory: str, exclude_dirs: list[str] | None = None) -> dict:
    """Check freshness of all managed files in directory."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    _exclude = {(root / e).resolve() for e in (exclude_dirs or [])}

    def _is_excluded(p: Path) -> bool:
        resolved = p.resolve()
        return any(resolved == ex or ex in resolved.parents for ex in _exclude)

    specs = sorted(s for s in root.rglob("*.spec.md") if not _is_excluded(s))
    files = []

    # Pre-scan: build set of spec paths that have a target-driven impl
    # anywhere in the tree (not just co-located).  This prevents the
    # default basename fallback from creating ghost entries when the impl
    # lives in a different directory (e.g. .plans/api_multi.impl.md with
    # source-spec: src/api.spec.md).
    _target_owned_specs: set[str] = set()
    for _impl_path in (p for p in root.rglob("*.impl.md") if not _is_excluded(p)):
        try:
            _ic = _impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _rel = str(_impl_path.relative_to(root))
            print(json.dumps({"warning": f"Skipping unreadable impl: {_rel} ({e})"}), file=sys.stderr)
            continue
        _ic_meta = parse_concrete_frontmatter(_ic)
        if _ic_meta.get("targets"):
            _src = _ic_meta.get("source_spec", "")
            if _src:
                # Resolve relative to impl directory, then fall back to root-relative
                _resolved = (_impl_path.parent / _src).resolve()
                if _resolved.exists():
                    _target_owned_specs.add(str(_resolved.relative_to(root)))
                elif (root / _src).exists():
                    _target_owned_specs.add(_src)

    for spec_path in specs:
        rel_spec = str(spec_path.relative_to(root))

        # Handle unit specs
        if spec_path.name.endswith(".unit.spec.md"):
            content = spec_path.read_text(encoding="utf-8")
            unit_files = parse_unit_spec_files(content)

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
            priority = {
                "fresh": 0,
                "old_format": 1,
                "pending": 2,
                "stale": 3,
                "structural": 4,
                "modified": 5,
                "conflict": 6,
                "unmanaged": 7,
                "error": 8,
            }
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
                    # Check unit spec provenance to decide structural vs pending.
                    # For unit specs, the provenance is on the unit spec itself
                    # (not on per-file specs, which don't exist in this model).
                    has_prov = bool(
                        parse_distilled_from(content) or parse_absorbed_from(content) or parse_exuded_from(content)
                    )
                    new_state = "structural" if has_prov else "pending"
                    if priority.get(new_state, 0) > priority.get(worst_state, 0):
                        worst_state = new_state

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
            needs_review = parse_needs_review(content)
            if needs_review:
                entry["needs_review"] = needs_review
            files.append(entry)
            continue

        # Per-file spec
        # If any .impl.md with explicit targets[] claims this spec
        # (co-located or not), skip the default basename deduction --
        # the target-driven pass will handle it.  This prevents ghost
        # entries for files that don't exist (e.g. "auth_logic" when
        # targets point elsewhere like .plans/api_multi.impl.md).
        if rel_spec in _target_owned_specs:
            continue  # target-driven pass owns this spec's mappings

        # Check for managed-file frontmatter override (directory modules)
        try:
            spec_content = spec_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(json.dumps({"warning": f"Cannot read spec for managed-file check: {rel_spec} ({e})"}), file=sys.stderr)
            spec_content = ""
        managed_file_override = parse_managed_file(spec_content)
        if managed_file_override:
            managed_path = root / managed_file_override
        else:
            managed_name = re.sub(r"\.spec\.md$", "", spec_path.name)
            managed_path = spec_path.parent / managed_name
        if not managed_path.exists():
            # Classify missing managed file as pending or structural based on provenance
            has_provenance = bool(
                parse_distilled_from(spec_content) or parse_absorbed_from(spec_content) or parse_exuded_from(spec_content)
            )
            state = "structural" if has_provenance else "pending"
            entry = {"managed": str(managed_path.relative_to(root)), "spec": rel_spec, "state": state}
            needs_review = parse_needs_review(spec_content)
            if needs_review:
                entry["needs_review"] = needs_review
            files.append(entry)
            continue

        result = classify_file(str(managed_path), str(spec_path), project_root=str(root))
        result["managed"] = str(managed_path.relative_to(root))
        result["spec"] = rel_spec
        needs_review = parse_needs_review(spec_content)
        if needs_review:
            result["needs_review"] = needs_review
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
        except (OSError, UnicodeDecodeError) as e:
            print(json.dumps({"warning": f"Skipping unreadable impl: {rel_impl} ({e})"}), file=sys.stderr)
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
                    try:
                        spec_content_target = spec_full.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as e:
                        print(
                            json.dumps({"warning": f"Cannot read spec for provenance check: {source_spec} ({e})"}),
                            file=sys.stderr,
                        )
                        spec_content_target = ""
                    has_provenance_target = bool(
                        parse_distilled_from(spec_content_target)
                        or parse_absorbed_from(spec_content_target)
                        or parse_exuded_from(spec_content_target)
                    )
                    target_state = "structural" if has_provenance_target else "pending"
                    files.append(
                        {
                            "managed": target_rel,
                            "spec": source_spec,
                            "state": target_state,
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
                    # Surface needs-review from spec frontmatter
                    try:
                        _spec_content = spec_full.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as e:
                        print(
                            json.dumps({"warning": f"Cannot read spec for needs-review check: {source_spec} ({e})"}),
                            file=sys.stderr,
                        )
                        _spec_content = ""
                    _nr = parse_needs_review(_spec_content)
                    if _nr:
                        result["needs_review"] = _nr
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
    impl_meta_cache: dict[Path, dict] = {}  # cache parsed metadata to avoid double I/O
    for impl_path in impl_files:
        rel_impl = str(impl_path.relative_to(root))
        try:
            impl_content = impl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(json.dumps({"warning": f"Skipping unreadable impl: {rel_impl} ({e})"}), file=sys.stderr)
            continue

        meta = parse_concrete_frontmatter(impl_content)
        impl_meta_cache[impl_path] = meta
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
                target_paths_for_hash = [get_registry_key_for_spec(source_spec, project_root=str(root))]

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
                            except (OSError, UnicodeDecodeError) as e:
                                msg = f"Cannot read spec for unit file list: {source_spec} ({e})"
                                print(json.dumps({"warning": msg}), file=sys.stderr)
                                spec_content = ""
                            for uf in parse_unit_spec_files(spec_content):
                                candidates.append(managed_full / uf)
                elif managed_full.is_file():
                    candidates = [managed_full]
                else:
                    continue

                for candidate in candidates:
                    if not candidate.exists():
                        continue
                    try:
                        managed_content = candidate.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as e:
                        msg = f"Cannot read managed file for ghost check: {candidate} ({e})"
                        print(json.dumps({"warning": msg}), file=sys.stderr)
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
                    target_paths = [get_registry_key_for_spec(source_spec, project_root=str(root))]

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

    # Scan for blocked constraints (deferred constraints from blocked-by frontmatter)
    # Uses impl_meta_cache from the ghost-staleness scan to avoid double I/O and duplicate warnings
    for impl_path in impl_files:
        meta = impl_meta_cache.get(impl_path)
        if meta is None:
            continue  # file was unreadable during ghost-staleness scan
        if meta.get("ephemeral", True):
            continue  # blocked-by on ephemeral specs is ignored

        blocked_by = meta.get("blocked_by", [])
        if not blocked_by:
            continue

        # Determine which managed files this impl affects
        target_paths = []
        targets_list = meta.get("targets", [])
        if targets_list:
            target_paths = [t["path"] for t in targets_list if "path" in t]
        else:
            source_spec = meta.get("source_spec", "")
            if source_spec:
                target_paths = [get_registry_key_for_spec(source_spec, project_root=str(root))]

        constraints = [
            {
                "symbol": entry["symbol"],
                "affects": entry["affects"],
                "reason": entry["reason"],
                "resolution": entry["resolution"],
            }
            for entry in blocked_by
        ]

        for managed_rel in target_paths:
            for f in files:
                if f["managed"] == managed_rel:
                    if "blocked_constraints" in f:
                        f["blocked_constraints"].extend(constraints)
                    else:
                        f["blocked_constraints"] = list(constraints)
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

    # Collect files with pending changes for CI messaging
    pending_intent_files = [
        {"managed": f["managed"], "count": f["pending_changes"]["count"]} for f in files if "pending_changes" in f
    ]

    result = {"status": "pass" if all_fresh else "fail", "files": files, "summary": summary}
    if pending_intent_files:
        result["pending_intent_files"] = pending_intent_files
    return result
