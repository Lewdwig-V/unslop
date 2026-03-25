"""Tests for lsp_queries -- LSP semantic query layer data model and recommendations."""

from __future__ import annotations

import os
import tempfile

from unslop.scripts.validation.lsp_queries import (
    SymbolInfo,
    SymbolManifest,
    _warned_languages,
    get_lsp_recommendation,
    get_symbol_manifest,
)


def test_symbol_info_creation():
    info = SymbolInfo(name="main", kind="function", file_path="src/main.rs", start_line=1, end_line=10)
    assert info.name == "main"
    assert info.kind == "function"
    assert info.file_path == "src/main.rs"
    assert info.start_line == 1
    assert info.end_line == 10
    assert info.container is None


def test_symbol_info_with_container():
    info = SymbolInfo(name="process", kind="function", file_path="src/lib.rs", start_line=5, end_line=20, container="Engine")
    assert info.container == "Engine"


def test_symbol_manifest_lsp_source():
    sym = SymbolInfo(name="Foo", kind="class", file_path="foo.py", start_line=1, end_line=5)
    manifest = SymbolManifest(file_path="foo.py", language="python", symbols=[sym], source="lsp")
    assert manifest.source == "lsp"
    assert manifest.error is None
    assert len(manifest.symbols) == 1


def test_symbol_manifest_unavailable():
    manifest = SymbolManifest(file_path="bar.py", language="python", source="unavailable", error="No LSP server running")
    assert manifest.source == "unavailable"
    assert manifest.error == "No LSP server running"
    assert manifest.symbols == []


def test_lsp_recommendation_rust():
    rec = get_lsp_recommendation(".rs")
    assert "rust-analyzer" in rec


def test_lsp_recommendation_go():
    rec = get_lsp_recommendation(".go")
    assert "gopls" in rec


def test_lsp_recommendation_typescript():
    rec = get_lsp_recommendation(".ts")
    assert "typescript-language-server" in rec


def test_lsp_recommendation_python():
    rec = get_lsp_recommendation(".py")
    assert "pyright" in rec


def test_lsp_recommendation_unknown():
    rec = get_lsp_recommendation(".zig")
    assert "marketplace" in rec.lower() or "extension" in rec.lower()


# ---------------------------------------------------------------------------
# get_symbol_manifest tests
# ---------------------------------------------------------------------------


def test_manifest_python_ast_fallback():
    """Python file with functions, classes, constants produces ast manifest."""
    src = "MAX = 100\n\ndef foo():\n    pass\n\nclass Bar:\n    pass\n"
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        os.write(fd, src.encode())
        os.close(fd)
        m = get_symbol_manifest(path)
        assert m.source in ("lsp", "ast")
        names = {s.name for s in m.symbols}
        assert "foo" in names
        assert "Bar" in names
        assert "MAX" in names
        assert m.error is None
    finally:
        os.unlink(path)


def test_manifest_nonpython_no_lsp():
    """.rs file without LSP -> unavailable with rust-analyzer mention."""
    _warned_languages.discard("Rust")  # reset dedup state
    fd, path = tempfile.mkstemp(suffix=".rs")
    try:
        os.write(fd, b"fn main() {}\n")
        os.close(fd)
        m = get_symbol_manifest(path)
        assert m.source in ("unavailable", "lsp")
        if m.source == "unavailable":
            assert m.error is not None
            assert "rust-analyzer" in m.error
    finally:
        os.unlink(path)
        _warned_languages.discard("Rust")


def test_manifest_empty_python_file():
    """Empty .py file -> empty symbols, no error."""
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        os.close(fd)
        m = get_symbol_manifest(path)
        assert m.symbols == []
        assert m.error is None
    finally:
        os.unlink(path)


def test_manifest_syntax_error_python():
    """Broken Python -> error is not None."""
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        os.write(fd, b"def broken(\n")
        os.close(fd)
        m = get_symbol_manifest(path)
        assert m.error is not None
    finally:
        os.unlink(path)


def test_manifest_lsp_path(monkeypatch):
    """When LSP returns symbols, source is 'lsp'."""
    fake = [SymbolInfo(name="hello", kind="function", file_path="x.py", start_line=1, end_line=5)]
    monkeypatch.setattr("unslop.scripts.validation.lsp_queries._try_lsp_document_symbols", lambda _path: fake)
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        os.close(fd)
        m = get_symbol_manifest(path)
        assert m.source == "lsp"
        assert m.symbols[0].name == "hello"
    finally:
        os.unlink(path)


def test_manifest_warning_dedup(capsys):
    """Calling twice for .rs emits warning at most once."""
    _warned_languages.discard("Rust")
    fd1, path1 = tempfile.mkstemp(suffix=".rs")
    fd2, path2 = tempfile.mkstemp(suffix=".rs")
    try:
        os.close(fd1)
        os.close(fd2)
        get_symbol_manifest(path1)
        get_symbol_manifest(path2)
        captured = capsys.readouterr()
        assert captured.err.count("[unslop] No LSP available for Rust") == 1
    finally:
        os.unlink(path1)
        os.unlink(path2)
        _warned_languages.discard("Rust")
