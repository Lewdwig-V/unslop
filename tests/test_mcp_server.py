"""Tests for MCP server tool dispatch.

These tests call the tool functions directly (not via MCP protocol)
to verify they correctly wrap the orchestrator functions.
"""

import json

from unslop.scripts.mcp_server import (
    unslop_check_freshness,
    unslop_classify_file,
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
