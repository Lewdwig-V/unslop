"""unslop orchestrator -- dependency resolution and file discovery for multi-file takeover.

This module is the CLI entry point and backward-compatible re-export facade.
All logic lives in submodules: core/, dependencies/, freshness/, planning/.

Can be invoked three ways:
  1. python -m unslop.scripts.orchestrator <cmd>  (package import)
  2. python orchestrator.py <cmd>                  (direct execution, vendored CI)
  3. from unslop.scripts.orchestrator import ...    (library import)
"""

from __future__ import annotations

# When run directly (python orchestrator.py), __package__ is None and relative
# imports fail. Bootstrap the package context so the rest of the module works.
if __name__ == "__main__" and not __package__:
    import os
    import sys

    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_scripts_dir)
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    __package__ = "scripts"

import json
import sys
from pathlib import Path

# === Re-exports for backward compatibility ===
# Tests and vendored CI scripts import directly from this module.

# core
from .core.frontmatter import (
    compute_intent_hash,
    parse_concrete_frontmatter,
    parse_frontmatter,
    parse_intent,
    parse_managed_file,
    validate_intent_hash,
)
from .core.hashing import (
    MISSING_SENTINEL,
    UNREADABLE_SENTINEL,
    compute_hash,
    get_body_below_header,
    parse_header,
)
from .core.spec_discovery import (
    EXCLUDED_DIRS,
    TEST_DIR_NAMES,
    TEST_FILE_PATTERNS,
    discover_files,
    file_tree,
    get_registry_key_for_spec,
    parse_unit_spec_files,
)

# dependencies
from .dependencies.concrete_graph import (
    MAX_EXTENDS_DEPTH,
    STRICT_CHILD_ONLY,
    build_concrete_order,
    check_concrete_staleness,
    flatten_inheritance_chain,
    get_all_strategy_providers,
    resolve_extends_chain,
    resolve_inherited_sections,
)
from .dependencies.graph import build_order_from_dir, resolve_deps, topo_sort
from .dependencies.unified_dag import (
    _build_unified_dag,
    _compute_parallel_batches,
    _unified_topo_sort,
)

# freshness
from .freshness.checker import (
    check_freshness,
    classify_file,
    diagnose_ghost_staleness,
    format_ghost_diagnostic,
    parse_change_file,
)
from .freshness.manifest import (
    compute_concrete_deps_hash,
    compute_concrete_manifest,
    format_manifest_header,
)

# validation
from .validation.lsp_queries import SymbolInfo, SymbolManifest, get_symbol_manifest
from .validation.symbol_audit import audit_symbols, check_drift, compute_spec_diff

# planning
from .planning.bulk_sync import compute_bulk_sync_plan
from .planning.deep_sync import compute_deep_sync_plan
from .planning.graph_renderer import render_dependency_graph
from .planning.resume import compute_resume_plan
from .planning.ripple import ripple_check

# _sentinel_hashes is used internally but re-exported for completeness
_SENTINEL_HASHES = {MISSING_SENTINEL, UNREADABLE_SENTINEL}

__all__ = [
    # core
    "EXCLUDED_DIRS",
    "MISSING_SENTINEL",
    "TEST_DIR_NAMES",
    "TEST_FILE_PATTERNS",
    "UNREADABLE_SENTINEL",
    "compute_hash",
    "discover_files",
    "file_tree",
    "get_body_below_header",
    "get_registry_key_for_spec",
    "parse_concrete_frontmatter",
    "parse_frontmatter",
    "parse_managed_file",
    "parse_intent",
    "compute_intent_hash",
    "validate_intent_hash",
    "parse_header",
    "parse_unit_spec_files",
    # dependencies
    "MAX_EXTENDS_DEPTH",
    "STRICT_CHILD_ONLY",
    "_build_unified_dag",
    "_compute_parallel_batches",
    "_unified_topo_sort",
    "build_concrete_order",
    "build_order_from_dir",
    "check_concrete_staleness",
    "flatten_inheritance_chain",
    "get_all_strategy_providers",
    "resolve_deps",
    "resolve_extends_chain",
    "resolve_inherited_sections",
    "topo_sort",
    # freshness
    "check_freshness",
    "classify_file",
    "compute_concrete_deps_hash",
    "compute_concrete_manifest",
    "diagnose_ghost_staleness",
    "format_ghost_diagnostic",
    "format_manifest_header",
    "parse_change_file",
    # planning
    "compute_bulk_sync_plan",
    "compute_deep_sync_plan",
    "compute_resume_plan",
    "render_dependency_graph",
    "ripple_check",
    # validation
    "SymbolInfo",
    "SymbolManifest",
    "audit_symbols",
    "check_drift",
    "compute_spec_diff",
    "get_symbol_manifest",
]


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        cmds = (
            "discover|build-order|deps|check-freshness|concrete-order"
            "|concrete-deps|ripple-check|deep-sync-plan|bulk-sync-plan"
            "|resume-sync-plan|graph|file-tree|symbol-audit|check-drift|spec-diff"
        )
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
        # Read exclude_patterns from config.json
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
        exclude_dirs: list[str] = []
        if "--exclude" in sys.argv:
            eidx = sys.argv.index("--exclude")
            if eidx + 1 < len(sys.argv):
                exclude_dirs = [sys.argv[eidx + 1]]
        try:
            result = check_freshness(directory, exclude_dirs=exclude_dirs)
            print(json.dumps(result, indent=2))
            for pif in result.get("pending_intent_files", []):
                print(
                    f"FAIL: {pif['managed']} has {pif['count']} pending change(s) requiring interactive approval.\n"
                    f"  Run 'unslop:sync {pif['managed']}' locally to approve the spec update.\n"
                    f"  CI cannot perform architectural lowering (Phase 0a.0 requires human approval).",
                    file=sys.stderr,
                )
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

    elif command == "deep-sync-plan":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py deep-sync-plan <file-path> [--root <dir>] [--force]", file=sys.stderr)
            sys.exit(1)
        file_path = sys.argv[2]
        project_root = "."
        force = False
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--root" and i + 1 < len(sys.argv):
                project_root = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--force":
                force = True
                i += 1
            else:
                i += 1
        try:
            result = compute_deep_sync_plan(file_path, project_root, force=force)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "bulk-sync-plan":
        project_root = "."
        force = False
        max_batch_size = 8
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--root" and i + 1 < len(sys.argv):
                project_root = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--force":
                force = True
                i += 1
            elif sys.argv[i] == "--max-batch" and i + 1 < len(sys.argv):
                try:
                    max_batch_size = int(sys.argv[i + 1])
                except ValueError:
                    print("--max-batch requires an integer", file=sys.stderr)
                    sys.exit(1)
                i += 2
            else:
                i += 1
        try:
            result = compute_bulk_sync_plan(project_root, force=force, max_batch_size=max_batch_size)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "resume-sync-plan":
        project_root = "."
        force = False
        max_batch_size = 8
        failed: list[str] = []
        succeeded: list[str] = []
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--root" and i + 1 < len(sys.argv):
                project_root = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--force":
                force = True
                i += 1
            elif sys.argv[i] == "--max-batch" and i + 1 < len(sys.argv):
                try:
                    max_batch_size = int(sys.argv[i + 1])
                except ValueError:
                    print("--max-batch requires an integer", file=sys.stderr)
                    sys.exit(1)
                i += 2
            elif sys.argv[i] == "--failed" and i + 1 < len(sys.argv):
                failed = sys.argv[i + 1].split(",")
                i += 2
            elif sys.argv[i] == "--succeeded" and i + 1 < len(sys.argv):
                succeeded = sys.argv[i + 1].split(",")
                i += 2
            else:
                i += 1
        if not failed:
            print(
                "Usage: orchestrator.py resume-sync-plan --failed f1,f2 --succeeded s1,s2 [--root <dir>]",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            result = compute_resume_plan(
                project_root,
                failed_files=failed,
                succeeded_files=succeeded,
                force=force,
                max_batch_size=max_batch_size,
            )
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif command == "graph":
        directory = "."
        scope = []
        no_code = False
        stale_only = False
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
            elif sys.argv[i] == "--stale-only":
                stale_only = True
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
                stale_only=stale_only,
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

    elif command == "symbol-audit":
        if len(sys.argv) < 4:
            print(
                "Usage: orchestrator.py symbol-audit <original> <generated> [--removed s1,s2]",
                file=sys.stderr,
            )
            sys.exit(1)
        original = sys.argv[2]
        generated = sys.argv[3]
        removed: list[str] = []
        if "--removed" in sys.argv:
            ridx = sys.argv.index("--removed")
            if ridx + 1 >= len(sys.argv):
                print("symbol-audit: --removed requires a comma-separated value", file=sys.stderr)
                sys.exit(1)
            removed = [s for s in sys.argv[ridx + 1].split(",") if s]
        try:
            result = audit_symbols(original, generated, removed=removed)
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2))
        if result["status"] == "error":
            sys.exit(2)
        sys.exit(0 if result["status"] == "pass" else 1)

    elif command == "check-drift":
        if len(sys.argv) < 4:
            print(
                "Usage: orchestrator.py check-drift <old> <new> --affected s1,s2",
                file=sys.stderr,
            )
            sys.exit(1)
        old_file = sys.argv[2]
        new_file = sys.argv[3]
        affected: list[str] = []
        if "--affected" in sys.argv:
            aidx = sys.argv.index("--affected")
            if aidx + 1 >= len(sys.argv):
                print("check-drift: --affected requires a comma-separated value", file=sys.stderr)
                sys.exit(1)
            affected = [s for s in sys.argv[aidx + 1].split(",") if s]
        try:
            result = check_drift(old_file, new_file, affected)
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2))
        if result["status"] == "error":
            sys.exit(2)
        sys.exit(0 if result["status"] != "drift" else 1)

    elif command == "spec-diff":
        if len(sys.argv) < 4:
            print(
                "Usage: orchestrator.py spec-diff <old-spec> <new-spec>",
                file=sys.stderr,
            )
            sys.exit(1)
        old_spec_path = sys.argv[2]
        new_spec_path = sys.argv[3]
        try:
            old_text = Path(old_spec_path).read_text(encoding="utf-8")
            new_text = Path(new_spec_path).read_text(encoding="utf-8")
            result = compute_spec_diff(old_text, new_text)
        except (OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2))
        sys.exit(0 if not result["changed_sections"] else 1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
