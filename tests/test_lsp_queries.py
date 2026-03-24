"""Tests for lsp_queries -- LSP semantic query layer data model and recommendations."""

from __future__ import annotations

from unslop.scripts.validation.lsp_queries import (
    SymbolInfo,
    SymbolManifest,
    get_lsp_recommendation,
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
