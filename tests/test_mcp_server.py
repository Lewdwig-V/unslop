"""Tests for MCP server tool dispatch.

These tests call the tool functions directly (not via MCP protocol)
to verify they correctly wrap the orchestrator functions.
"""

import json

from unslop.scripts.mcp_server import (
    unslop_build_order,
    unslop_bulk_sync_plan,
    unslop_check_drift,
    unslop_check_freshness,
    unslop_classify_file,
    unslop_deep_sync_plan,
    unslop_discover,
    unslop_resolve_deps,
    unslop_ripple_check,
    unslop_symbol_audit,
)
from unslop.scripts.orchestrator import compute_hash


def test_check_freshness_empty_dir(tmp_path):
    """check_freshness on a dir with no specs returns pass."""
    (tmp_path / ".unslop").mkdir()
    result = json.loads(unslop_check_freshness(directory=str(tmp_path)))
    assert result["status"] == "pass"
    assert result["files"] == []


def test_check_freshness_error_on_missing_dir():
    """check_freshness on a nonexistent dir returns error."""
    result = json.loads(unslop_check_freshness(directory="/nonexistent/path"))
    assert "error" in result


def test_classify_file_fresh(tmp_path):
    """classify_file returns fresh for matching hashes."""
    spec = tmp_path / "foo.py.spec.md"
    spec_content = "# foo spec\n"
    spec.write_text(spec_content)

    spec_hash = compute_hash(spec_content)
    managed_body = "# managed code"
    output_hash = compute_hash(managed_body)

    managed = tmp_path / "foo.py"
    managed.write_text(
        f"# @unslop-managed -- do not edit directly. Edit foo.py.spec.md instead.\n"
        f"# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-26T12:00:00Z\n"
        f"{managed_body}\n"
    )

    result = json.loads(
        unslop_classify_file(
            managed_path=str(managed),
            spec_path=str(spec),
        )
    )
    assert result["state"] == "fresh"


def test_classify_file_missing_managed():
    """classify_file returns error for missing managed file."""
    result = json.loads(
        unslop_classify_file(
            managed_path="/nonexistent",
            spec_path="/also/nonexistent",
        )
    )
    assert result["state"] == "error"


def test_build_order_empty_dir(tmp_path):
    """build_order on empty dir returns empty list."""
    result = json.loads(unslop_build_order(directory=str(tmp_path)))
    assert result == []


def test_build_order_error_on_missing_dir():
    result = json.loads(unslop_build_order(directory="/nonexistent"))
    assert "error" in result


def test_resolve_deps_no_deps(tmp_path):
    """resolve_deps for a spec with no depends-on returns empty list."""
    spec = tmp_path / "foo.py.spec.md"
    spec.write_text("# foo spec\n")
    result = json.loads(
        unslop_resolve_deps(
            spec_path=str(spec),
            project_root=str(tmp_path),
        )
    )
    assert result == []


def test_ripple_check_single_spec(tmp_path):
    """ripple_check on a single spec with no deps."""
    spec = tmp_path / "foo.py.spec.md"
    spec.write_text("# foo spec\n")
    result = json.loads(
        unslop_ripple_check(
            spec_paths=[str(spec.relative_to(tmp_path))],
            project_root=str(tmp_path),
        )
    )
    assert "error" not in result
    assert isinstance(result, dict)


def test_deep_sync_plan_error_on_missing():
    result = json.loads(
        unslop_deep_sync_plan(
            file_path="nonexistent.spec.md",
            project_root="/nonexistent",
        )
    )
    assert "error" in result


def test_bulk_sync_plan_empty_project(tmp_path):
    (tmp_path / ".unslop").mkdir()
    result = json.loads(unslop_bulk_sync_plan(project_root=str(tmp_path)))
    assert "error" not in result


def test_symbol_audit_error_on_missing():
    result = json.loads(
        unslop_symbol_audit(
            original_path="/nonexistent/a.py",
            generated_path="/nonexistent/b.py",
        )
    )
    # On missing files, symbol_audit returns a hint indicating the error
    assert "hint" in result or "error" in result


def test_check_drift_error_on_missing():
    result = json.loads(
        unslop_check_drift(
            old_path="/nonexistent/a.py",
            new_path="/nonexistent/b.py",
            affected_symbols=["foo"],
        )
    )
    # On missing files, check_drift returns status: "error"
    assert result.get("status") == "error" or "error" in result


def test_discover_finds_files(tmp_path):
    """discover finds Python files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# main\n")
    result = json.loads(unslop_discover(directory=str(tmp_path), extensions=[".py"]))
    assert any("main.py" in f for f in result)


def test_discover_error_on_missing():
    result = json.loads(unslop_discover(directory="/nonexistent"))
    assert "error" in result
