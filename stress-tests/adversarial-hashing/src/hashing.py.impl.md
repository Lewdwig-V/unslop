---
source-spec: src/hashing.py.spec.md
target-language: python
complexity: low
ephemeral: true
concrete-dependencies: []
---

## Strategy

Pure-function module with no classes. Three public functions, two module-level sentinel constants, one private set.

1. `compute_hash`: Single-expression SHA-256 pipeline -- strip, encode, digest, truncate.
2. `parse_header`: Linear scan of first 5 lines with comment-prefix/suffix stripping, regex field extraction. Single-pass prefix matching (first match wins, break). Accumulates fields into local variables, returns dict or None.
3. `get_body_below_header`: Linear scan of first 5 lines for header markers, tracks body_start index. Optional end_line truncation with validation and stderr warning on invalid values.

## Type Sketch

```python
MISSING_SENTINEL: str       # "missing00000" -- 12 chars, non-hex
UNREADABLE_SENTINEL: str    # "unreadabl000" -- 12 chars, non-hex
_SENTINEL_HASHES: set[str]  # {MISSING_SENTINEL, UNREADABLE_SENTINEL}

def compute_hash(content: str) -> str: ...          # always 12 hex chars
def parse_header(content: str) -> dict | None: ...  # None if no @unslop-managed
def get_body_below_header(content: str, end_line: int | None = None) -> str: ...
```

## Representation Invariants

- `compute_hash` output matches `^[0-9a-f]{12}$` for all inputs.
- `parse_header` returns exactly 9 keys when non-None: `spec_path`, `spec_hash`, `output_hash`, `principles_hash`, `concrete_deps_hash`, `concrete_manifest`, `managed_end_line`, `generated`, `old_format`.
- Sentinel constants are exactly 12 characters and contain at least one non-hex character.
- `_SENTINEL_HASHES` contains exactly the two sentinel constants.

## Safety Contracts

- No exceptions raised by any public function.
- `get_body_below_header` warns to stderr on invalid end_line, never raises.
- `parse_header` returns None (not empty dict) on missing marker.
- Malformed manifest entries are silently dropped (not raised).

## Exclusions

- MUST NOT validate hash input encoding or emptiness.
- MUST NOT support comment syntaxes beyond #, //, --, /*, <!--.
- MUST NOT cache hash results.
- MUST NOT handle binary content -- text-only with newline splitting.

## Lowering Notes

### Python

- Use `from __future__ import annotations` for `X | Y` union syntax on Python 3.8+.
- `hashlib.sha256` for hashing, `re.search` for field extraction.
- `sys.stderr` for warnings via `print(..., file=sys.stderr)`.
- Comment prefixes as a list literal, iterated with break-on-first-match.
- `rfind(":")` for manifest entry splitting (paths may contain colons).
