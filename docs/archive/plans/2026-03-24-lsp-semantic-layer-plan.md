> **SUPERSEDED** by `2026-03-27-weed-and-lsp-removal-design.md`. The LSP semantic query layer and AST-based symbol audit have been removed. Drift detection is now LLM-native via `/unslop:weed`.

# LSP Semantic Query Layer -- PR 1: Wrapper + Drift Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `lsp_queries.py` wrapper with `get_symbol_manifest()` and migrate `check_drift()` to use it -- proving that the LSP abstraction works and giving drift detection to all languages with a configured language server.

**Architecture:** A thin wrapper module (`lsp_queries.py`) calls the Claude Code LSP tool for `documentSymbol`, falling back to Python `ast` for `.py` files when no LSP is available. `check_drift()` delegates symbol extraction to the wrapper instead of calling `_extract_symbol_sources()` directly. The drift comparison logic is unchanged -- only the data source changes.

**Tech Stack:** Python 3.8+, Claude Code LSP tool (runtime dependency -- mocked in tests)

**Spec:** `docs/superpowers/specs/2026-03-24-lsp-semantic-layer-design.md` (PR 1 scope only)

---

## File Structure

### New files
- `unslop/scripts/validation/lsp_queries.py` -- LSP wrapper with `get_symbol_manifest()`, data model, fallback logic, LSP recommendation registry
- `tests/test_lsp_queries.py` -- tests with mocked LSP responses

### Modified files
- `unslop/scripts/validation/symbol_audit.py` -- `check_drift()` delegates to `get_symbol_manifest()`
- `unslop/scripts/orchestrator.py` -- re-export `get_symbol_manifest`, `SymbolInfo`, `SymbolManifest`
- `unslop/.claude-plugin/plugin.json` -- version bump

---

## Task 1: Data Model + LSP Recommendation Registry

The foundation types that everything else depends on.

**Files:**
- Create: `unslop/scripts/validation/lsp_queries.py`
- Create: `tests/test_lsp_queries.py`

- [ ] **Step 1: Write the test file with data model tests**

```python
# tests/test_lsp_queries.py
import os
import sys

from unslop.scripts.validation.lsp_queries import (
    SymbolInfo,
    SymbolManifest,
    get_lsp_recommendation,
)


def test_symbol_info_creation():
    """SymbolInfo holds name, kind, file, lines, container."""
    sym = SymbolInfo(
        name="allocate",
        kind="function",
        file_path="/src/alloc.rs",
        start_line=10,
        end_line=25,
    )
    assert sym.name == "allocate"
    assert sym.kind == "function"
    assert sym.container is None


def test_symbol_info_with_container():
    """SymbolInfo can have a container (parent symbol)."""
    sym = SymbolInfo(
        name="new",
        kind="function",
        file_path="/src/alloc.rs",
        start_line=15,
        end_line=20,
        container="impl Allocator",
    )
    assert sym.container == "impl Allocator"


def test_symbol_manifest_lsp_source():
    """SymbolManifest records its data source."""
    manifest = SymbolManifest(
        file_path="/src/alloc.rs",
        language="rust",
        symbols=[],
        source="lsp",
    )
    assert manifest.source == "lsp"
    assert manifest.error is None


def test_symbol_manifest_unavailable():
    """Unavailable manifest has actionable error."""
    manifest = SymbolManifest(
        file_path="/src/alloc.rs",
        language="rust",
        symbols=[],
        source="unavailable",
        error="No language server for .rs files.",
    )
    assert manifest.source == "unavailable"
    assert ".rs" in manifest.error


def test_lsp_recommendation_rust():
    """Rust files get rust-analyzer recommendation."""
    rec = get_lsp_recommendation(".rs")
    assert "rust-analyzer" in rec


def test_lsp_recommendation_go():
    """Go files get gopls recommendation."""
    rec = get_lsp_recommendation(".go")
    assert "gopls" in rec


def test_lsp_recommendation_typescript():
    """TypeScript files get typescript-language-server recommendation."""
    rec = get_lsp_recommendation(".ts")
    assert "typescript" in rec.lower()


def test_lsp_recommendation_python():
    """Python files get pyright recommendation with fallback note."""
    rec = get_lsp_recommendation(".py")
    assert "pyright" in rec.lower() or "optional" in rec.lower()


def test_lsp_recommendation_unknown():
    """Unknown extensions get generic marketplace guidance."""
    rec = get_lsp_recommendation(".zig")
    assert "marketplace" in rec.lower()
```

- [ ] **Step 2: Run tests -- verify ImportError**

Run: `pytest tests/test_lsp_queries.py -v`
Expected: ImportError (`lsp_queries` doesn't exist)

- [ ] **Step 3: Implement data model and registry**

```python
# unslop/scripts/validation/lsp_queries.py
"""LSP semantic query layer -- language-agnostic symbol extraction via Claude Code LSP tool."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass
class SymbolInfo:
    """A single public symbol extracted from a source file."""

    name: str
    kind: str  # "function", "class", "enum", "interface", "constant", "module", "symbol"
    file_path: str
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed, inclusive
    container: str | None = None  # parent symbol for reporting


@dataclass
class SymbolManifest:
    """A file's complete public API surface."""

    file_path: str
    language: str
    symbols: list[SymbolInfo] = field(default_factory=list)
    source: str = "unavailable"  # "lsp", "ast", "unavailable"
    error: str | None = None


# LSP SymbolKind (from LSP spec) -> unslop kind
_LSP_KIND_MAP: dict[int, str] = {
    1: "module",     # File
    2: "module",     # Module
    3: "module",     # Namespace
    4: "module",     # Package
    5: "class",      # Class
    6: "function",   # Method
    8: "function",   # Constructor
    9: "enum",       # Enum
    10: "interface",  # Interface
    12: "function",   # Function
    13: "constant",   # Variable (filtered to UPPER_CASE later)
    14: "constant",   # Constant
    22: "class",      # Struct
    23: "enum",       # Event
    25: "interface",  # TypeParameter
    26: "interface",  # TypeAlias (added for Rust/TS type aliases)
}


def _lsp_kind_to_unslop(kind_num: int) -> str:
    """Map LSP SymbolKind integer to unslop kind string."""
    return _LSP_KIND_MAP.get(kind_num, "symbol")


# Recommendation registry: file extension -> (language name, install guidance)
_LSP_RECOMMENDATIONS: dict[str, tuple[str, str]] = {
    ".rs": ("Rust", "rust-analyzer@superpowers-marketplace"),
    ".go": ("Go", "gopls@superpowers-marketplace"),
    ".ts": ("TypeScript", "typescript-language-server@superpowers-marketplace"),
    ".tsx": ("TypeScript", "typescript-language-server@superpowers-marketplace"),
    ".js": ("JavaScript", "typescript-language-server@superpowers-marketplace"),
    ".jsx": ("JavaScript", "typescript-language-server@superpowers-marketplace"),
    ".py": ("Python", "pyright@superpowers-marketplace (optional -- ast fallback available)"),
    ".java": ("Java", "jdtls@superpowers-marketplace"),
    ".c": ("C", "clangd@superpowers-marketplace"),
    ".cpp": ("C++", "clangd@superpowers-marketplace"),
    ".h": ("C/C++", "clangd@superpowers-marketplace"),
}


def get_lsp_recommendation(extension: str) -> str:
    """Get install guidance for a language server by file extension."""
    if extension in _LSP_RECOMMENDATIONS:
        lang, plugin = _LSP_RECOMMENDATIONS[extension]
        return f"Install {lang} language server: /plugin install {plugin}"
    return "Check the superpowers marketplace for available language server plugins."
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_lsp_queries.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```
feat: add LSP semantic query layer data model and recommendation registry
```

---

## Task 2: `get_symbol_manifest()` with ast Fallback

The core wrapper function. LSP path is tested with mocks; ast fallback uses real files.

**Files:**
- Modify: `unslop/scripts/validation/lsp_queries.py`
- Modify: `tests/test_lsp_queries.py`

- [ ] **Step 1: Write tests for ast fallback (no mocking needed)**

```python
import tempfile

from unslop.scripts.validation.lsp_queries import get_symbol_manifest


def test_manifest_python_ast_fallback():
    """Python files use ast fallback when LSP unavailable."""
    code = "def foo():\n    pass\n\nclass Bar:\n    x = 1\n\nMAX = 10\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        manifest = get_symbol_manifest(f.name)
    assert manifest.source in ("lsp", "ast")
    names = {s.name for s in manifest.symbols}
    assert "foo" in names
    assert "Bar" in names
    assert "MAX" in names
    assert manifest.language == "python"
    os.unlink(f.name)


def test_manifest_nonpython_no_lsp():
    """Non-Python files without LSP return unavailable with guidance."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write("fn main() {}\n")
        f.flush()
        manifest = get_symbol_manifest(f.name)
    # In test environment, LSP is likely unavailable
    # Either LSP works (source="lsp") or we get guidance (source="unavailable")
    assert manifest.source in ("lsp", "unavailable")
    if manifest.source == "unavailable":
        assert manifest.error is not None
        assert "rust-analyzer" in manifest.error.lower() or "language server" in manifest.error.lower()
    assert manifest.language == "rust"
    os.unlink(f.name)


def test_manifest_empty_python_file():
    """Empty Python file -> empty symbol list, not error."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("")
        f.flush()
        manifest = get_symbol_manifest(f.name)
    assert manifest.source in ("lsp", "ast")
    assert manifest.symbols == []
    os.unlink(f.name)


def test_manifest_syntax_error_python():
    """Python file with syntax error -> error in manifest."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def broken(\n")
        f.flush()
        manifest = get_symbol_manifest(f.name)
    assert manifest.error is not None
    os.unlink(f.name)


def test_manifest_lsp_path(monkeypatch):
    """When LSP returns symbols, manifest has source='lsp'."""
    from unslop.scripts.validation import lsp_queries

    fake_symbols = [
        SymbolInfo(name="main", kind="function", file_path="/test.rs", start_line=1, end_line=3),
        SymbolInfo(name="Config", kind="class", file_path="/test.rs", start_line=5, end_line=15),
    ]
    monkeypatch.setattr(lsp_queries, "_try_lsp_document_symbols", lambda _: fake_symbols)
    manifest = get_symbol_manifest("/test.rs")
    assert manifest.source == "lsp"
    assert len(manifest.symbols) == 2
    assert manifest.symbols[0].name == "main"
    assert manifest.language == "rust"


def test_manifest_warning_dedup(monkeypatch, capsys):
    """LSP unavailable warning appears once per language, not per call."""
    from unslop.scripts.validation import lsp_queries

    lsp_queries._warned_languages.clear()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write("fn main() {}\n")
        f.flush()
        get_symbol_manifest(f.name)
        get_symbol_manifest(f.name)  # second call, same language
    captured = capsys.readouterr()
    # Should warn at most once for .rs
    assert captured.err.count("rust-analyzer") <= 1
    os.unlink(f.name)
    lsp_queries._warned_languages.clear()
```

- [ ] **Step 2: Implement `get_symbol_manifest()`**

Add to `lsp_queries.py`:

```python
from pathlib import Path


# Extension -> language name mapping
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".rs": "rust", ".go": "go",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
}

# Track which languages we've warned about (once per session)
_warned_languages: set[str] = set()


def get_symbol_manifest(file_path: str) -> SymbolManifest:
    """Extract all public top-level symbols from a file.

    Tries LSP documentSymbol first. Falls back to Python ast for .py files.
    Returns unavailable with actionable guidance for other languages without LSP.
    """
    path = Path(file_path)
    ext = path.suffix
    language = _EXT_TO_LANGUAGE.get(ext, ext.lstrip("."))

    # Try LSP first
    lsp_result = _try_lsp_document_symbols(file_path)
    if lsp_result is not None:
        return SymbolManifest(
            file_path=file_path,
            language=language,
            symbols=lsp_result,
            source="lsp",
        )

    # Fallback: Python ast
    if ext == ".py":
        return _python_ast_manifest(file_path, language)

    # No LSP, not Python -> unavailable
    guidance = get_lsp_recommendation(ext)
    if language not in _warned_languages:
        print(
            f"Semantic analysis requires a language server for {ext} files. {guidance}",
            file=sys.stderr,
        )
        _warned_languages.add(language)

    return SymbolManifest(
        file_path=file_path,
        language=language,
        symbols=[],
        source="unavailable",
        error=f"No language server for {ext} files. {guidance}",
    )


def _try_lsp_document_symbols(file_path: str) -> list[SymbolInfo] | None:
    """Attempt LSP documentSymbol. Returns None if LSP unavailable."""
    # The LSP tool is a Claude Code built-in -- it's called by the
    # controlling session (Architect/skill), not by this Python script.
    # This function is a placeholder that returns None in script context.
    # In practice, the skill/command that calls get_symbol_manifest()
    # will invoke the LSP tool directly and pass results here.
    #
    # For the ast-based drift check (called from orchestrator CLI),
    # LSP is not available -- the fallback path handles it.
    return None


def _python_ast_manifest(file_path: str, language: str) -> SymbolManifest:
    """Extract symbols from a Python file using the ast module."""
    import ast

    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"get_symbol_manifest: cannot read {file_path}: {e}", file=sys.stderr)
        return SymbolManifest(
            file_path=file_path, language=language,
            source="ast", error=str(e),
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"get_symbol_manifest: cannot parse {file_path}: {e}", file=sys.stderr)
        return SymbolManifest(
            file_path=file_path, language=language,
            source="ast", error=str(e),
        )

    symbols: list[SymbolInfo] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                symbols.append(SymbolInfo(
                    name=node.name,
                    kind="function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class",
                    file_path=file_path,
                    start_line=start,
                    end_line=node.end_lineno or start,
                ))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if not name.startswith("_") and name == name.upper() and any(c.isalpha() for c in name):
                        symbols.append(SymbolInfo(
                            name=name, kind="constant", file_path=file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                        ))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if not name.startswith("_") and name == name.upper() and any(c.isalpha() for c in name):
                    symbols.append(SymbolInfo(
                        name=name, kind="constant", file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.names:
                for alias in node.names:
                    imp_name = alias.asname if alias.asname else alias.name
                    if imp_name != "*" and not imp_name.startswith("_"):
                        symbols.append(SymbolInfo(
                            name=imp_name, kind="symbol", file_path=file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                        ))

    return SymbolManifest(
        file_path=file_path, language=language,
        symbols=symbols, source="ast",
    )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_lsp_queries.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```
feat: implement get_symbol_manifest() with ast fallback for Python
```

---

## Task 3: Migrate `check_drift()` to Use the Wrapper

Replace `_extract_symbol_sources()` calls with `get_symbol_manifest()`.

**Files:**
- Modify: `unslop/scripts/validation/symbol_audit.py`
- Modify: `unslop/skills/generation/SKILL.md` (update drift check documentation to note LSP-aware path)
- Modify: `tests/test_symbol_audit.py` (verify existing tests still pass, add bridge function test)

- [ ] **Step 1: Update `check_drift()` to use `get_symbol_manifest()`**

In `symbol_audit.py`, change `check_drift()` to call the wrapper:

```python
from .lsp_queries import get_symbol_manifest
```

Replace the two `_extract_symbol_sources()` calls with:
```python
old_manifest = get_symbol_manifest(old_path)
new_manifest = get_symbol_manifest(new_path)
```

Build the symbol name -> normalized source mapping from the manifest's symbols + the source file lines (read once). The comparison logic stays identical -- only the symbol discovery changes.

Key change: the `_extract_symbol_sources()` function returned `{name: normalized_source_text}`. The manifest returns `SymbolInfo` objects with line ranges. To bridge: extract source text using the line ranges from the manifest, then normalize. This preserves the exact same comparison semantics.

```python
def _manifest_to_source_map(manifest, source_lines):
    """Convert a SymbolManifest to {name: normalized_source_text} for comparison."""
    result = {}
    for sym in manifest.symbols:
        raw = "".join(source_lines[sym.start_line - 1 : sym.end_line])
        result[sym.name] = _normalize_source(raw)
    return result
```

- [ ] **Step 2: Handle the unavailable case**

If either manifest has `source="unavailable"`, `check_drift()` returns `{"status": "clean", "skipped": True}` with the manifest's error as guidance. This matches current behavior for non-Python files.

If either manifest has an `error` (e.g., syntax error), return `{"status": "error"}` as before.

- [ ] **Step 3: Add bridge function test**

Add to `tests/test_symbol_audit.py`:

```python
def test_manifest_to_source_map_matches_extract():
    """Bridge function produces same output as _extract_symbol_sources for Python files."""
    from unslop.scripts.validation.symbol_audit import _manifest_to_source_map, _extract_symbol_sources, _normalize_source

    code = "def foo():\n    return 1\n\nclass Bar:\n    x = 1\n\nMAX = 10\n"
    orig = _write_tmp(code)
    try:
        # Old path
        old_result = _extract_symbol_sources(open(orig).read())
        # New path via manifest
        manifest = get_symbol_manifest(orig)
        source_lines = open(orig).readlines()
        new_result = _manifest_to_source_map(manifest, source_lines)
        # Same keys, same values
        assert set(old_result.keys()) == set(new_result.keys())
        for key in old_result:
            assert old_result[key] == new_result[key], f"Mismatch for {key}"
    finally:
        os.unlink(orig)
```

- [ ] **Step 4: Update generation SKILL.md drift check docs**

In the "Optional Drift Check" section of `unslop/skills/generation/SKILL.md`, update the description to note the LSP-aware path:

Replace "This is currently Python-only (uses `ast` for symbol extraction)" with:

"Uses the LSP semantic query layer for symbol extraction when a language server is available, falling back to Python `ast` for `.py` files. Non-Python files without an LSP server skip the drift check with actionable guidance on installing the appropriate language server plugin."

- [ ] **Step 5: Run ALL existing drift tests**

Run: `pytest tests/test_symbol_audit.py -v -k drift`
Expected: All 10+ drift tests PASS (behavior unchanged)

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q`
Expected: All 446+ tests PASS

- [ ] **Step 7: Commit**

```
refactor: migrate check_drift to use LSP semantic query layer
```

---

## Task 4: Wire into Orchestrator + Version Bump

**Files:**
- Modify: `unslop/scripts/orchestrator.py`
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Add re-exports**

In the validation re-exports section of `orchestrator.py`, add:

```python
from .validation.lsp_queries import SymbolInfo, SymbolManifest, get_symbol_manifest
```

Add `"SymbolInfo"`, `"SymbolManifest"`, and `"get_symbol_manifest"` to `__all__`.

- [ ] **Step 2: Bump version**

Change `plugin.json` version to the next number.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```
feat: wire LSP semantic query layer into orchestrator, bump version
```

---

## Execution Order

```
[1: Data Model + Registry] -> [2: get_symbol_manifest()] -> [3: Migrate check_drift()] -> [4: Orchestrator + Version]
```

Strictly sequential. Each task builds on the prior.

---

## What This PR Validates

If all drift tests pass after the migration (Task 3), the LSP wrapper abstraction is correct: same inputs, same outputs, different data source. PR 2 (symbol conflicts via `workspaceSymbol`) and PR 3 (consumer validation) can build on this foundation with confidence.

The wrapper's `_try_lsp_document_symbols()` returns `None` in script context (no LSP tool available to Python scripts). In practice, the Architect/controlling session has LSP access and can populate the manifest directly. The ast fallback ensures the CLI tools (`orchestrator.py check-drift`) continue working without LSP. This dual-path is the design's key property: LSP enhances, ast preserves.
