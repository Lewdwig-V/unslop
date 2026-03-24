"""LSP semantic query layer -- data model and language server recommendation registry."""

from __future__ import annotations

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
