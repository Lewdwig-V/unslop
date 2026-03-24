"""Tests for symbol_audit -- AST-level public symbol verification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from unslop.scripts.validation.symbol_audit import audit_symbols, check_drift, compute_spec_diff

AUDIT_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts", "orchestrator.py")


def _write_tmp(content: str, suffix: str = ".py") -> str:
    """Write content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


def test_identical_files_pass():
    src = "def foo():\n    pass\n\ndef bar():\n    pass\n"
    orig = _write_tmp(src)
    gen = _write_tmp(src)
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert result["missing"] == []
        assert result["unexpected"] == []
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_missing_symbol_fails():
    orig = _write_tmp("def foo():\n    pass\n\ndef bar():\n    pass\n")
    gen = _write_tmp("def foo():\n    pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "bar" in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_removed_symbols_excluded():
    orig = _write_tmp("def foo():\n    pass\n\ndef legacy():\n    pass\n")
    gen = _write_tmp("def foo():\n    pass\n")
    try:
        result = audit_symbols(orig, gen, removed=["legacy"])
        assert result["status"] == "pass"
        assert "legacy" not in result["missing"]
        assert result["removed"] == ["legacy"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_unexpected_symbol_warns():
    orig = _write_tmp("def foo():\n    pass\n")
    gen = _write_tmp("def foo():\n    pass\n\ndef extra():\n    pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert "extra" in result["unexpected"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_private_symbols_ignored():
    orig = _write_tmp("def _internal():\n    pass\n\ndef public():\n    pass\n")
    gen = _write_tmp("def public():\n    pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert "_internal" not in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_class_symbols_tracked():
    orig = _write_tmp("class MyClass:\n    pass\n")
    gen = _write_tmp("pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "MyClass" in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_constants_tracked():
    orig = _write_tmp("MAX_RETRIES = 3\n\ndef run():\n    pass\n")
    gen = _write_tmp("def run():\n    pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "MAX_RETRIES" in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_nonpython_passthrough():
    orig = _write_tmp("export function foo() {}", suffix=".ts")
    gen = _write_tmp("export function foo() {}", suffix=".ts")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert result["skipped"] is True
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_syntax_error_in_original():
    orig = _write_tmp("def broken(\n")
    gen = _write_tmp("def foo():\n    pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "error"
        assert "hint" in result
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_cli_symbol_audit():
    orig = _write_tmp("def foo():\n    pass\n\ndef bar():\n    pass\n")
    gen = _write_tmp("def foo():\n    pass\n")
    try:
        proc = subprocess.run(
            [sys.executable, AUDIT_SCRIPT, "symbol-audit", orig, gen],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1
        data = json.loads(proc.stdout)
        assert data["status"] == "fail"
        assert "bar" in data["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_empty_files_pass():
    """Both files empty -> pass with no symbols."""
    orig = _write_tmp("")
    gen = _write_tmp("")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert result["missing"] == []
        assert result["original_symbols"] == []
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_empty_generated_fails():
    """Original has symbols, generated is empty -> fail."""
    orig = _write_tmp("def foo(): pass\n")
    gen = _write_tmp("")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "foo" in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_async_function_tracked():
    """Async functions are public symbols."""
    orig = _write_tmp("async def fetch(): pass\n")
    gen = _write_tmp("def other(): pass\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "fetch" in result["missing"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_syntax_error_in_generated():
    """Unparseable generated file -> error with 'generated' hint."""
    orig = _write_tmp("def foo(): pass\n")
    gen = _write_tmp("def broken(")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "error"
        assert "generated" in result["hint"].lower()
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_file_not_found():
    """Nonexistent file -> error result, not crash."""
    result = audit_symbols("/nonexistent/file.py", "/also/nonexistent.py")
    assert result["status"] == "error"


def test_private_constant_ignored():
    """Constants starting with _ are private and not tracked."""
    orig = _write_tmp("MAX_RETRIES = 3\n_INTERNAL_LIMIT = 10\n")
    gen = _write_tmp("MAX_RETRIES = 3\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert "_INTERNAL_LIMIT" not in result["original_symbols"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_annotated_constants_tracked():
    """Annotated assignments (AnnAssign) like MAX_RETRIES: int = 3 are public symbols."""
    orig = _write_tmp("MAX_RETRIES: int = 3\nTIMEOUT: float = 30.0\n")
    gen = _write_tmp("MAX_RETRIES: int = 3\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "TIMEOUT" in result["missing"]
        assert "MAX_RETRIES" in result["original_symbols"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_reexports_tracked():
    """ImportFrom re-exports (from .core import Foo) are public symbols."""
    orig = _write_tmp("from .core import Foo, Bar\nfrom .utils import Helper\n")
    gen = _write_tmp("from .core import Foo\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "fail"
        assert "Bar" in result["missing"]
        assert "Helper" in result["missing"]
        assert "Foo" in result["original_symbols"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_private_reexports_ignored():
    """Private re-exports (from .core import _internal) are not tracked."""
    orig = _write_tmp("from .core import Foo, _internal\n")
    gen = _write_tmp("from .core import Foo\n")
    try:
        result = audit_symbols(orig, gen)
        assert result["status"] == "pass"
        assert "_internal" not in result["original_symbols"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


# ---- check_drift tests ----


def test_drift_clean():
    """Only affected symbols changed -> clean."""
    old = _write_tmp("def foo():\n    pass\n\ndef bar():\n    pass\n")
    new = _write_tmp("def foo():\n    return 1\n\ndef bar():\n    pass\n")
    try:
        result = check_drift(old, new, ["foo"])
        assert result["status"] == "clean"
        assert result["drifted"] == []
        assert "foo" in result["modified"]
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_detected():
    """Protected symbol changed -> drift."""
    old = _write_tmp("def foo():\n    pass\n\ndef bar():\n    pass\n")
    new = _write_tmp("def foo():\n    pass\n\ndef bar():\n    return 99\n")
    try:
        result = check_drift(old, new, ["foo"])
        assert result["status"] == "drift"
        assert "bar" in result["drifted"]
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_new_symbol():
    """(new) tag exempts new symbols from drift detection."""
    old = _write_tmp("def foo():\n    pass\n")
    new = _write_tmp("def foo():\n    pass\n\ndef helper():\n    return 1\n")
    try:
        result = check_drift(old, new, ["helper (new)"])
        assert result["status"] == "clean"
        assert result["drifted"] == []
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_deleted_symbol():
    """(deleted) tag, symbol removed -> clean."""
    old = _write_tmp("def foo():\n    pass\n\ndef legacy():\n    pass\n")
    new = _write_tmp("def foo():\n    pass\n")
    try:
        result = check_drift(old, new, ["legacy (deleted)"])
        assert result["status"] == "clean"
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_deleted_but_still_present():
    """Tagged deleted but still in output -> drift."""
    old = _write_tmp("def foo():\n    pass\n\ndef legacy():\n    pass\n")
    new = _write_tmp("def foo():\n    pass\n\ndef legacy():\n    pass\n")
    try:
        result = check_drift(old, new, ["legacy (deleted)"])
        assert result["status"] == "drift"
        assert "legacy" in result["drifted"]
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_nonpython_skips():
    """.ts files skip drift checking."""
    old = _write_tmp("export function foo() {}", suffix=".ts")
    new = _write_tmp("export function bar() {}", suffix=".ts")
    try:
        result = check_drift(old, new, [])
        assert result["status"] == "clean"
        assert result["skipped"] is True
    finally:
        os.unlink(old)
        os.unlink(new)


def test_drift_class_body_change():
    """Class method changed in protected class -> drift."""
    old_src = "def unrelated():\n    pass\n\nclass MyClass:\n    def method(self):\n        return 1\n"
    new_src = "def unrelated():\n    pass\n\nclass MyClass:\n    def method(self):\n        return 999\n"
    old = _write_tmp(old_src)
    new = _write_tmp(new_src)
    try:
        result = check_drift(old, new, ["unrelated"])
        assert result["status"] == "drift"
        assert "MyClass" in result["drifted"]
    finally:
        os.unlink(old)
        os.unlink(new)


# ---- compute_spec_diff tests ----


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


def test_drift_unauthorized_new_symbol():
    """New symbol appears without (new) tag -> drift warning."""
    old_code = "def foo():\n    return 1\n"
    new_code = "def foo():\n    return 1\n\ndef sneaked_in():\n    return 2\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["foo"])
        assert result["status"] == "drift"
        assert any("sneaked_in" in d for d in result["drifted"])
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_empty_new_file():
    """Old file has symbols, new file is empty -> all protected symbols drifted."""
    old_code = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    new_code = ""
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=[])
        assert result["status"] == "drift"
        assert "foo" in result["drifted"]
        assert "bar" in result["drifted"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_drift_adjacent_classes():
    """Two adjacent classes -- verify line-range slicing is correct."""
    old_code = "class A:\n    x = 1\n\nclass B:\n    y = 2\n"
    new_code = "class A:\n    x = 1\n\nclass B:\n    y = 99\n"
    orig = _write_tmp(old_code)
    gen = _write_tmp(new_code)
    try:
        result = check_drift(orig, gen, affected_symbols=["B"])
        assert result["status"] == "clean"
        assert result["drifted"] == []
        assert "B" in result["modified"]
    finally:
        os.unlink(orig)
        os.unlink(gen)


def test_manifest_to_source_map_matches_extract():
    """Bridge function produces same output as _extract_symbol_sources for Python files."""
    code = "def foo():\n    return 1\n\nclass Bar:\n    x = 1\n\nMAX = 10\n"
    orig = _write_tmp(code)
    try:
        from unslop.scripts.validation.symbol_audit import _manifest_to_source_map, _extract_symbol_sources
        from unslop.scripts.validation.lsp_queries import get_symbol_manifest

        # Old path
        old_result = _extract_symbol_sources(open(orig).read())
        # New path via manifest
        manifest = get_symbol_manifest(orig)
        with open(orig) as f:
            source_lines = f.readlines()
        new_result = _manifest_to_source_map(manifest, source_lines)
        # Same keys, same values
        assert set(old_result.keys()) == set(new_result.keys())
        for key in old_result:
            assert old_result[key] == new_result[key], f"Mismatch for {key}"
    finally:
        os.unlink(orig)
