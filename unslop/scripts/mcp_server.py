"""MCP server exposing unslop orchestrator tools.

Run as: python3 -m unslop.scripts.mcp_server
Or auto-started by Claude Code via .mcp.json

The tool functions are plain Python functions that can be imported and tested
without the mcp package. The FastMCP wiring only happens at module level if
mcp is available, and at __main__ time for the server entry point.
"""

from __future__ import annotations

import functools
import json
import sys
import traceback

from .freshness.checker import check_freshness, classify_file
from .dependencies.graph import build_order_from_dir, resolve_deps
from .planning.ripple import ripple_check
from .planning.deep_sync import compute_deep_sync_plan
from .planning.bulk_sync import compute_bulk_sync_plan
from .core.spec_discovery import discover_files

# MCP wiring is optional -- tools work as plain functions without it
_HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

if FastMCP is not None:
    try:
        mcp_app = FastMCP("unslop")
        _HAS_MCP = True
    except Exception as e:
        print(
            f"Warning: mcp package found but FastMCP init failed: {e}",
            file=sys.stderr,
        )
        mcp_app = None
else:
    mcp_app = None


# Expected domain errors -- these get clean JSON responses
_DOMAIN_ERRORS = (ValueError, FileNotFoundError, OSError, UnicodeDecodeError)


def _tool(func):
    """Register as MCP tool if mcp is available, otherwise return unchanged.

    Also wraps the function with two-tier error handling:
    - Domain errors (ValueError, FileNotFoundError, OSError): clean JSON error
    - Unexpected errors: full traceback to stderr + JSON error with "internal" type
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except _DOMAIN_ERRORS as e:
            return json.dumps(
                {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "tool": func.__name__,
                }
            )
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return json.dumps(
                {
                    "error": f"Internal error: {type(e).__name__}: {e}",
                    "error_type": "internal",
                    "tool": func.__name__,
                }
            )

    if _HAS_MCP and mcp_app is not None:
        return mcp_app.tool()(wrapper)
    return wrapper


def _serialize(result, tool_name: str):
    """Serialize orchestrator result to JSON, handling non-serializable types.

    If the result is a dict with an "error" key (domain-level error from the
    orchestrator), enrich it with tool name and error_type for consistency.
    """
    if isinstance(result, dict) and "error" in result and "tool" not in result:
        result["error_type"] = result.get("error_type", "domain")
        result["tool"] = tool_name
    return json.dumps(result, indent=2, default=str)


# --- Freshness & Status ---


@_tool
def unslop_check_freshness(
    directory: str = ".",
    exclude_dirs: list[str] | None = None,
) -> str:
    """Check freshness of all managed files.

    Returns staleness state, blocked constraints, pending changes,
    and ghost-staleness.
    """
    exclude = exclude_dirs or [".unslop", "node_modules"]
    result = check_freshness(directory, exclude_dirs=exclude)
    return _serialize(result, "unslop_check_freshness")


@_tool
def unslop_classify_file(
    managed_path: str,
    spec_path: str,
    project_root: str = ".",
) -> str:
    """Classify a single managed file's staleness state."""
    result = classify_file(managed_path, spec_path, project_root=project_root)
    return _serialize(result, "unslop_classify_file")


# --- Dependency Resolution ---


@_tool
def unslop_build_order(directory: str = ".") -> str:
    """Topologically sorted spec list from depends-on frontmatter."""
    result = build_order_from_dir(directory)
    return _serialize(result, "unslop_build_order")


@_tool
def unslop_resolve_deps(spec_path: str, project_root: str = ".") -> str:
    """Transitive dependency list for a single spec file."""
    result = resolve_deps(spec_path, project_root)
    return _serialize(result, "unslop_resolve_deps")


# --- Planning ---


@_tool
def unslop_ripple_check(spec_paths: list[str], project_root: str = ".") -> str:
    """Analyze the blast radius of spec changes across abstract specs,
    concrete specs, and managed files."""
    result = ripple_check(spec_paths, project_root)
    return _serialize(result, "unslop_ripple_check")


@_tool
def unslop_deep_sync_plan(
    file_path: str,
    project_root: str = ".",
    force: bool = False,
) -> str:
    """Compute a sync plan for a single file with dependency ordering."""
    result = compute_deep_sync_plan(file_path, project_root, force=force)
    return _serialize(result, "unslop_deep_sync_plan")


@_tool
def unslop_bulk_sync_plan(
    project_root: str = ".",
    force: bool = False,
    max_batch_size: int = 8,
) -> str:
    """Compute a sync plan for all stale files with parallel batch grouping."""
    result = compute_bulk_sync_plan(project_root, force=force, max_batch_size=max_batch_size)
    return _serialize(result, "unslop_bulk_sync_plan")


# --- Discovery ---


@_tool
def unslop_discover(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> str:
    """Find source files and test files in a directory."""
    # Load exclude_patterns from .unslop/config.json if caller didn't provide
    if extra_excludes is None:
        from pathlib import Path

        search = Path(directory).resolve()
        while search != search.parent:
            config_path = search / ".unslop" / "config.json"
            if config_path.exists():
                try:
                    import json as _json

                    config = _json.loads(config_path.read_text(encoding="utf-8"))
                    extra_excludes = config.get("exclude_patterns", [])
                except (json.JSONDecodeError, OSError):
                    pass
                break
            search = search.parent
    result = discover_files(directory, extensions=extensions, extra_excludes=extra_excludes)
    return _serialize(result, "unslop_discover")


# --- Entry point ---

if __name__ == "__main__":
    if not _HAS_MCP or mcp_app is None:
        print(
            "mcp package not installed. Install with: pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)
    mcp_app.run(transport="stdio")
