"""LSP semantic query layer -- data model and language server recommendation registry."""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field


@dataclass
class SymbolInfo:
    """A single symbol extracted from LSP documentSymbol or workspace/symbol responses."""

    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    container: str | None = None


@dataclass
class SymbolManifest:
    """Aggregated symbol data for a single file, with provenance tracking."""

    file_path: str
    language: str
    symbols: list[SymbolInfo] = field(default_factory=list)
    source: str = "unavailable"
    error: str | None = None


# LSP SymbolKind enum (from the LSP spec) mapped to unslop-internal kind strings.
_LSP_KIND_MAP: dict[int, str] = {
    1: "module",  # File
    2: "module",  # Module
    3: "module",  # Namespace
    4: "module",  # Package
    5: "class",  # Class
    6: "function",  # Method
    7: "symbol",  # Property
    8: "symbol",  # Field
    9: "function",  # Constructor
    10: "enum",  # Enum
    11: "interface",  # Interface
    12: "function",  # Function
    13: "symbol",  # Variable
    14: "constant",  # Constant
    15: "symbol",  # String
    16: "symbol",  # Number
    17: "symbol",  # Boolean
    18: "symbol",  # Array
    19: "symbol",  # Object
    20: "symbol",  # Key
    21: "symbol",  # Null
    22: "symbol",  # EnumMember
    23: "symbol",  # Struct (mapped to class)
    24: "symbol",  # Event
    25: "symbol",  # Operator
    26: "symbol",  # TypeParameter
}


def _lsp_kind_to_unslop(kind_num: int) -> str:
    """Map an LSP SymbolKind integer to an unslop kind string."""
    return _LSP_KIND_MAP.get(kind_num, "symbol")


# Extension -> (language_name, plugin/server_name) for LSP install guidance.
_LSP_RECOMMENDATIONS: dict[str, tuple[str, str]] = {
    ".rs": ("Rust", "rust-analyzer"),
    ".go": ("Go", "gopls"),
    ".ts": ("TypeScript", "typescript-language-server"),
    ".tsx": ("TypeScript (React)", "typescript-language-server"),
    ".js": ("JavaScript", "typescript-language-server"),
    ".jsx": ("JavaScript (React)", "typescript-language-server"),
    ".py": ("Python", "pyright"),
    ".java": ("Java", "jdtls (Eclipse JDT Language Server)"),
    ".c": ("C", "clangd"),
    ".cpp": ("C++", "clangd"),
    ".h": ("C/C++ Header", "clangd"),
}


def get_lsp_recommendation(extension: str) -> str:
    """Return install guidance for the LSP server matching *extension*.

    If the extension is not in the known registry, returns generic VS Code
    marketplace guidance.
    """
    entry = _LSP_RECOMMENDATIONS.get(extension)
    if entry is None:
        return (
            f"No built-in LSP recommendation for '{extension}'. "
            "Search the VS Code extension marketplace for a language server that supports this file type."
        )
    language, server = entry
    return f"For {language} files, install the '{server}' language server."


# ---------------------------------------------------------------------------
# Extension -> canonical language name (used for dedup of warnings)
# ---------------------------------------------------------------------------
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".rs": "Rust",
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".py": "Python",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
}

# Tracks which languages have already emitted a "no LSP" warning to stderr.
_warned_languages: set[str] = set()


def _try_lsp_document_symbols(file_path: str) -> list[SymbolInfo] | None:  # noqa: ARG001
    """Attempt to retrieve symbols via an LSP documentSymbol request.

    This is a placeholder -- the LSP tool is a Claude Code built-in and is not
    callable from standalone Python scripts.  Always returns None so callers
    fall through to the AST-based or unavailable path.
    """
    return None


def _python_ast_manifest(file_path: str, language: str) -> SymbolManifest:
    """Extract public symbols from a Python file using the ``ast`` module."""
    try:
        with open(file_path, encoding="utf-8") as fh:
            source = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"get_symbol_manifest: cannot read {file_path}: {exc}", file=sys.stderr)
        return SymbolManifest(file_path=file_path, language=language, source="ast", error=str(exc))

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        print(f"get_symbol_manifest: syntax error in {file_path}: {exc}", file=sys.stderr)
        return SymbolManifest(file_path=file_path, language=language, source="ast", error=str(exc))

    symbols: list[SymbolInfo] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind="function",
                    file_path=file_path,
                    start_line=start,
                    end_line=node.end_lineno or node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind="class",
                    file_path=file_path,
                    start_line=start,
                    end_line=node.end_lineno or node.lineno,
                )
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                    symbols.append(
                        SymbolInfo(
                            name=target.id,
                            kind="constant",
                            file_path=file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                        )
                    )
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.isupper() and not node.target.id.startswith("_"):
                symbols.append(
                    SymbolInfo(
                        name=node.target.id,
                        kind="constant",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            if node.names:
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name == "*" or name.startswith("_"):
                        continue
                    symbols.append(
                        SymbolInfo(
                            name=name,
                            kind="symbol",
                            file_path=file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                        )
                    )

    return SymbolManifest(file_path=file_path, language=language, symbols=symbols, source="ast")


def get_symbol_manifest(file_path: str) -> SymbolManifest:
    """Return a symbol manifest for *file_path*, trying LSP first then falling back.

    Falls back to AST extraction for Python files, or returns an unavailable
    manifest with an actionable recommendation for other languages.
    """
    ext = os.path.splitext(file_path)[1].lower()
    language = _EXT_TO_LANGUAGE.get(ext, ext)

    # 1. Try LSP
    lsp_symbols = _try_lsp_document_symbols(file_path)
    if lsp_symbols is not None:
        return SymbolManifest(
            file_path=file_path,
            language=language,
            symbols=lsp_symbols,
            source="lsp",
        )

    # 2. Fallback for Python
    if ext == ".py":
        return _python_ast_manifest(file_path, language)

    # 3. Unavailable for other languages
    recommendation = get_lsp_recommendation(ext)
    if language not in _warned_languages:
        _warned_languages.add(language)
        print(f"[unslop] No LSP available for {language}: {recommendation}", file=sys.stderr)

    return SymbolManifest(
        file_path=file_path,
        language=language,
        source="unavailable",
        error=recommendation,
    )
