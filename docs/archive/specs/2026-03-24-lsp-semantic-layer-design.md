> **SUPERSEDED** by `2026-03-27-weed-and-lsp-removal-design.md`. The LSP semantic query layer and AST-based symbol audit have been removed. Drift detection is now LLM-native via `/unslop:weed`.

# LSP Semantic Query Layer Design Spec

**Date:** 2026-03-24
**Status:** Design-Locked

## Problem

unslop's semantic awareness is Python-only (`ast` module in `symbol_audit.py`). The drift check, symbol audit, and coherence command can't reason about Rust, TypeScript, Go, or any other language at the symbol level. The field test exposed two concrete gaps:

1. **Symbol-level conflicts across modules** -- two `AllocationSemantics` enums in different Rust files, invisible to file-level `depends-on` checking.
2. **Spec-to-codebase consistency** -- specs promise one signature, consumers call another, discovered only at `cargo check` time.

Claude Code has LSP access (`documentSymbol`, `workspaceSymbol`, `findReferences`, `hover`, etc.) for any language with a configured server. This gives us language-agnostic semantic awareness for free.

## Solution: Thin Wrapper in validation/

A `lsp_queries.py` module that wraps common LSP patterns into standardised query functions. The wrapper fetches data; the existing commands (coherence, drift check) make decisions. Intelligence stays in the commands, data fetching stays in the wrapper.

### Design Principles

1. **LSP-first, not LSP-only.** The wrapper tries LSP first. If no language server is available, it falls back to Python `ast` for `.py` files and returns "unavailable" for other languages with actionable guidance.
2. **The wrapper doesn't decide.** It returns standardised data structures. The coherence command and drift check interpret the data.
3. **Graceful degradation with loud guidance.** No silent fallbacks. If LSP is unavailable, tell the user what they're missing and how to fix it.
4. **No new dependencies.** Uses the Claude Code LSP tool directly. No client libraries.

---

## Data Model

### `SymbolInfo`

The standardised return type for symbol queries. Language-agnostic.

```python
@dataclass
class SymbolInfo:
    name: str                    # e.g., "AllocationSemantics"
    kind: str                    # e.g., "enum", "function", "class", "constant"
    file_path: str               # absolute path
    start_line: int              # 1-indexed
    end_line: int                # 1-indexed, inclusive
    container: str | None = None # parent symbol (e.g., "impl Allocator" for a method)
```

### `SymbolManifest`

A file's complete public API surface.

```python
@dataclass
class SymbolManifest:
    file_path: str
    language: str                  # from file extension
    symbols: list[SymbolInfo]
    source: str                    # "lsp" or "ast" or "unavailable"
    error: str | None = None       # if source is "unavailable", why + how to fix
```

### `ConflictReport`

Result of a workspace-wide symbol search.

```python
@dataclass
class ConflictReport:
    name: str                      # the conflicting symbol name
    definitions: list[SymbolInfo]  # all definitions found (>1 = conflict)
```

---

## Wrapper Functions

### `get_symbol_manifest(file_path: str) -> SymbolManifest`

Extract all public symbols from a file. Used by drift detection.

**LSP path:** Call `documentSymbol` on the file. Filter to top-level symbols. Map LSP `SymbolKind` to unslop kinds (function, class, enum, constant, etc.).

**Fallback path (Python only):** Use `_extract_public_symbols()` from `symbol_audit.py`.

**Unavailable path:** Return manifest with `source="unavailable"` and `error` containing the language-specific install guidance from the LSP recommendation registry (see Graceful Degradation).

### `find_symbol_conflicts(names: list[str]) -> list[ConflictReport]`

Search for symbol names across the workspace. Used by coherence.

**LSP path:** Call `workspaceSymbol` for each name. Group results by name. Any name with >1 definition is a conflict.

**Fallback:** Not available without LSP. Return error with guidance.

### `get_symbol_type(file_path: str, line: int, character: int) -> str | None`

Get the type signature of a symbol at a position. Used by consumer validation.

**LSP path:** Call `hover` at the position. Extract type information from the hover response.

**Fallback:** Not available without LSP. Return None.

### `find_consumers(file_path: str, line: int, character: int) -> list[SymbolInfo]`

Find all call sites for a function/method. Used by consumer validation.

**LSP path:** Call `findReferences` at the function definition position.

**Fallback:** Not available without LSP. Return empty list with guidance.

---

## Integration Points

### 1. Drift Detection (replaces Python-only `check_drift`)

Current: `_extract_symbol_sources()` uses Python `ast` -> Python only.
New: `get_symbol_manifest()` uses LSP `documentSymbol` -> any language.

The drift check logic stays identical: compare old manifest vs new manifest, report symbols that changed outside `affected_symbols`. Only the data source changes.

**Migration:** `check_drift()` calls `get_symbol_manifest()` instead of `_extract_symbol_sources()`. If the manifest comes back as `source="ast"` (Python fallback), existing behavior is preserved exactly. If `source="lsp"`, same logic, broader language support. If `source="unavailable"`, skip drift check with guidance (current behavior for non-Python).

### 2. Coherence Enhancement

Current: `/unslop:coherence` checks spec-level `depends-on` contracts.
New: Additionally runs `find_symbol_conflicts()` on all type names mentioned in managed specs.

**New coherence check:** After the existing spec-level validation, extract all type/function names from managed specs. Call `find_symbol_conflicts()`. Report any name with multiple definitions:

```
Symbol conflict: AllocationSemantics defined in 2 modules:
  - src/alloc_facade.rs:42 (enum, 3 variants)
  - src/compat.rs:18 (enum, 5 variants)

  Specs src/alloc_facade.rs.spec.md and src/compat.rs.spec.md both define
  this type independently. Consider:
  - Consolidating into a shared module with depends-on
  - Renaming one to avoid ambiguity
```

### 3. Consumer Validation (new capability)

Not part of existing commands. Exposed as a coherence sub-check.

After coherence validates spec contracts, it optionally runs consumer validation: for each managed function, `find_consumers()` returns all call sites. `get_symbol_type()` at each call site reveals whether the consumer's usage matches the spec's declared signature.

This is expensive (one LSP call per consumer per function). Gate it behind `--deep` flag on coherence:

```
/unslop:coherence --deep    # includes consumer type validation
/unslop:coherence            # spec-level only (fast, no LSP needed)
```

---

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| LSP available | Full semantic queries |
| LSP unavailable, Python file | Fall back to `ast` module |
| LSP unavailable, other language | Return "unavailable" with install guidance |
| LSP timeout / error | Log warning to stderr, return "unavailable" |

**Guidance format (language-aware):**

The wrapper maintains a registry of known LSP plugin recommendations by file extension. When no server is available, guidance is specific to the language:

```
Semantic analysis requires a language server for .rs files.
Install via: /plugin install rust-analyzer@superpowers-marketplace
Without it, the following features are limited for Rust files:
  - Drift detection: unavailable
  - Symbol conflict detection: unavailable
  - Consumer type validation: unavailable
```

**Known LSP recommendations:**

| Extension | Language | Recommended plugin |
|---|---|---|
| `.rs` | Rust | `rust-analyzer@superpowers-marketplace` |
| `.go` | Go | `gopls@superpowers-marketplace` |
| `.ts`, `.tsx` | TypeScript | `typescript-language-server@superpowers-marketplace` |
| `.js`, `.jsx` | JavaScript | `typescript-language-server@superpowers-marketplace` |
| `.py` | Python | `pyright@superpowers-marketplace` (optional -- `ast` fallback available) |
| `.java` | Java | `jdtls@superpowers-marketplace` |
| `.c`, `.cpp`, `.h` | C/C++ | `clangd@superpowers-marketplace` |

If the file extension is not in the registry, the guidance says:

```
Semantic analysis requires a language server for .<ext> files.
Check the superpowers marketplace for available language server plugins.
```

This guidance appears once per session per language (not per query). The wrapper tracks which languages it has already warned about.

---

## Files

### New
- `unslop/scripts/validation/lsp_queries.py` -- the wrapper module
- `tests/test_lsp_queries.py` -- tests (mocked LSP responses)

### Modified
- `unslop/scripts/validation/symbol_audit.py` -- `check_drift()` delegates to `get_symbol_manifest()`
- `unslop/scripts/orchestrator.py` -- re-export wrapper functions
- `unslop/commands/coherence.md` -- add symbol conflict check, `--deep` flag
- `unslop/skills/generation/SKILL.md` -- drift check references updated

---

## Implementation: Vertical Slice

**PR 1: Wrapper + Drift Migration.** Build `lsp_queries.py` with `get_symbol_manifest()` only. Migrate `check_drift()` to use it. Tests with mocked LSP responses + real `ast` fallback. This proves the abstraction works.

**PR 2: Coherence Enhancement.** Add `find_symbol_conflicts()` to the wrapper. Update `/unslop:coherence` to call it. Test against a fixture with intentional symbol conflicts.

**PR 3: Consumer Validation.** Add `get_symbol_type()` and `find_consumers()`. Wire into `--deep` coherence. This is the most expensive and least certain -- it depends on LSP hover responses being structured enough to extract type information programmatically.

---

## What This Does NOT Do

- It does not replace the Builder or Architect's judgment. LSP queries are diagnostic, not generative.
- It does not require LSP for basic unslop functionality. All existing commands work without LSP. LSP enhances coherence and drift detection.
- It does not cache LSP results across sessions. Each query is fresh. Caching is a future optimization if performance is an issue.
- It does not parse LSP responses into a type system. It extracts names, kinds, and ranges -- enough for conflict detection and drift checking, not for full type inference.
