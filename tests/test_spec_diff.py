"""Tests for compute_spec_diff -- section-level markdown diffing."""

from __future__ import annotations

from unslop.scripts.orchestrator import compute_spec_diff


def test_spec_diff_changed_section():
    """Changed section detected."""
    old = "## Overview\nOld content\n\n## API\nSame\n"
    new = "## Overview\nNew content\n\n## API\nSame\n"
    result = compute_spec_diff(old, new)
    assert "Overview" in result["changed_sections"]
    assert "API" in result["unchanged_sections"]


def test_spec_diff_no_change():
    """Identical specs -> no changed sections."""
    spec = "## Overview\nContent\n\n## API\nEndpoints\n"
    result = compute_spec_diff(spec, spec)
    assert result["changed_sections"] == []
    assert len(result["unchanged_sections"]) == 2


def test_spec_diff_new_section():
    """New section in new spec -> changed."""
    old = "## Overview\nContent\n"
    new = "## Overview\nContent\n\n## API\nNew stuff\n"
    result = compute_spec_diff(old, new)
    assert "API" in result["changed_sections"]
    assert "Overview" in result["unchanged_sections"]


def test_spec_diff_removed_section():
    """Section removed from new spec -> changed."""
    old = "## Overview\nContent\n\n## Legacy\nOld stuff\n"
    new = "## Overview\nContent\n"
    result = compute_spec_diff(old, new)
    assert "Legacy" in result["changed_sections"]
    assert "Overview" in result["unchanged_sections"]
