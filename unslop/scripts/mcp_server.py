"""MCP server exposing unslop orchestrator tools.

Run as: python3 -m unslop.scripts.mcp_server
Or auto-started by Claude Code via .mcp.json

The tool functions are plain Python functions that can be imported and tested
without the mcp package. The FastMCP wiring only happens at module level if
mcp is available, and at __main__ time for the server entry point.
"""

from __future__ import annotations

import json
import sys

from .freshness.checker import check_freshness, classify_file
from .dependencies.graph import build_order_from_dir, resolve_deps
from .planning.ripple import ripple_check
from .planning.deep_sync import compute_deep_sync_plan
from .planning.bulk_sync import compute_bulk_sync_plan
from .validation.symbol_audit import audit_symbols, check_drift
from .core.spec_discovery import discover_files

# MCP wiring is optional -- tools work as plain functions without it
_HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP

    mcp_app = FastMCP("unslop")
    _HAS_MCP = True
except ImportError:
    mcp_app = None


def _tool(func):
    """Register as MCP tool if mcp is available, otherwise return unchanged."""
    if _HAS_MCP and mcp_app is not None:
        return mcp_app.tool()(func)
    return func


# --- Freshness & Status ---


@_tool
def unslop_check_freshness(
    directory: str = ".",
    exclude_dirs: list[str] | None = None,
) -> str:
    """Check freshness of all managed files.

    Returns staleness state, blocked constraints, pending changes, and ghost-staleness.
    """
    try:
        exclude = exclude_dirs or [".unslop", "node_modules"]
        result = check_freshness(directory, exclude_dirs=exclude)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_classify_file(
    managed_path: str,
    spec_path: str,
    project_root: str = ".",
) -> str:
    """Classify a single managed file's staleness state."""
    try:
        result = classify_file(managed_path, spec_path, project_root=project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Dependency Resolution ---


@_tool
def unslop_build_order(directory: str = ".") -> str:
    """Topologically sorted spec list from depends-on frontmatter."""
    try:
        result = build_order_from_dir(directory)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_resolve_deps(spec_path: str, project_root: str = ".") -> str:
    """Transitive dependency list for a single spec file."""
    try:
        result = resolve_deps(spec_path, project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Planning ---


@_tool
def unslop_ripple_check(spec_paths: list[str], project_root: str = ".") -> str:
    """Analyze the blast radius of spec changes across abstract specs, concrete specs, and managed files."""
    try:
        result = ripple_check(spec_paths, project_root)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_deep_sync_plan(
    file_path: str,
    project_root: str = ".",
    force: bool = False,
) -> str:
    """Compute a sync plan for a single file (spec or managed) with dependency ordering."""
    try:
        result = compute_deep_sync_plan(file_path, project_root, force=force)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_bulk_sync_plan(
    project_root: str = ".",
    force: bool = False,
    max_batch_size: int = 8,
) -> str:
    """Compute a sync plan for all stale files with parallel batch grouping."""
    try:
        result = compute_bulk_sync_plan(project_root, force=force, max_batch_size=max_batch_size)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Validation ---


@_tool
def unslop_symbol_audit(
    original_path: str,
    generated_path: str,
    removed: list[str] | None = None,
) -> str:
    """Compare public symbols between two versions of a file. Returns added, removed, and matched symbols."""
    try:
        result = audit_symbols(original_path, generated_path, removed=removed)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@_tool
def unslop_check_drift(
    old_path: str,
    new_path: str,
    affected_symbols: list[str],
) -> str:
    """Check symbol-level drift between two file versions. Flags changes to symbols NOT in the affected list."""
    try:
        result = check_drift(old_path, new_path, affected_symbols)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Discovery ---


@_tool
def unslop_discover(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> str:
    """Find source files and test files in a directory."""
    try:
        result = discover_files(directory, extensions=extensions, extra_excludes=extra_excludes)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Entry point ---

if __name__ == "__main__":
    if not _HAS_MCP or mcp_app is None:
        print("mcp package not installed. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)
    mcp_app.run(transport="stdio")
