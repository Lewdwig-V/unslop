"""Tests for symbol_audit -- AST-level public symbol verification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from unslop.scripts.validation.symbol_audit import audit_symbols

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
