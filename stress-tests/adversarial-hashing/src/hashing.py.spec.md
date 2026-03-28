---
intent: >
  Deterministic content hashing and structured header parsing for
  unslop-managed files. Provides SHA-256-based content fingerprinting
  (truncated to 12 hex chars), multi-syntax comment-aware header
  extraction from managed file preambles, and body extraction with
  optional protected-region truncation.
intent-approved: false
intent-hash: a6c4fdfc6106
distilled-from:
  - path: stress-tests/adversarial-hashing/src/hashing.py
    hash: b91506f9fe1f
non-goals:
  - Does not validate that hash inputs are well-formed or non-empty -- callers may hash empty strings
  - Does not support comment syntaxes beyond #, //, --, /*, <!--
  - Does not cache hash results across calls
  - Does not handle binary file content -- assumes text with newline splitting
uncertain: []
spec-changelog:
  - intent-hash: a6c4fdfc6106
    timestamp: 2026-03-28T00:01:00Z
    operation: elicit-distill-review
    prior-intent-hash: a6c4fdfc6106
  - intent-hash: a6c4fdfc6106
    timestamp: 2026-03-28T00:00:00Z
    operation: distill
    prior-intent-hash: null
depends-on: []
---

## Purpose

Content-addressable fingerprinting and header parsing for files managed by unslop. Every managed file carries a structured comment header in its first 5 lines containing provenance metadata (spec path, content hashes, generation timestamp, concrete dependency manifest). This module reads and interprets those headers, computes deterministic content hashes for staleness detection, and extracts the code body below the header for output-hash comparison.

## Behavior

- `compute_hash(content)` returns a 12-character lowercase hex string. Identical content with differing leading/trailing whitespace produces the same hash. The hash is the first 12 characters of the SHA-256 digest of the stripped UTF-8-encoded content.
- `parse_header(content)` scans the first 5 lines for `@unslop-managed` markers. Returns `None` if no marker with `Edit <path> instead` is found. Otherwise returns a dict with keys: `spec_path`, `spec_hash`, `output_hash`, `principles_hash`, `concrete_deps_hash`, `concrete_manifest`, `managed_end_line`, `generated`, `old_format`.
- Comment prefix stripping supports 5 syntaxes: `#` (Python/Shell), `//` (JS/TS/Go/Rust), `--` (SQL/Lua), `/*` (C-style block open), `<!--` (HTML/XML). Suffix stripping handles `*/` and `-->`.
- `concrete_manifest` is parsed from `concrete-manifest:path1:hash1,path2:hash2` format using rfind(`:`) to split path from hash. Only entries with valid 12-char hex hashes or recognized sentinel values are included.
- `parse_header` detects legacy `Generated from spec at` format and sets `old_format: true`.
- `get_body_below_header(content, end_line)` returns all content after the header. Header lines are identified by presence of header markers or being blank. Scanning stops at the first non-header, non-blank line within the first 5 lines.
- When `end_line` is provided and valid (>= 1, after header), body is truncated to lines between header end and `end_line - 1` (1-indexed, exclusive). Invalid `end_line` triggers a stderr warning and returns the full body.

## Constraints

- Hash output is always exactly 12 lowercase hex characters.
- Header scanning window is exactly the first 5 lines -- headers on line 6+ are invisible.
- `MISSING_SENTINEL` and `UNREADABLE_SENTINEL` are exactly 12 characters each, contain non-hex characters, and are recognizable as non-hash values.
- Prefix stripping is single-pass: only the first matching prefix is removed per line.
- `parse_header` returns `None` (not an empty dict) when no managed marker is found.
- `get_body_below_header` never raises exceptions -- it degrades gracefully with a stderr warning.

## Error Handling

- No exceptions are raised by any public function.
- `parse_header` returns `None` for unparseable or non-managed input.
- `get_body_below_header` prints a warning to stderr when `end_line` is invalid, then returns the full body as fallback.
- Malformed `concrete-manifest` entries (missing colon, invalid hash length) are silently skipped -- only valid entries populate the manifest dict.

## Dependencies

- `hashlib` -- SHA-256 computation
- `re` -- regex-based header field extraction
- `sys` -- stderr access for warnings

## Changelog

- 2026-03-28: Distillation review via elicit. All 3 uncertainties resolved as deliberate design choices. All 4 non-goals ratified. Intent confirmed as prescriptive.
- 2026-03-28: Initial distillation from `stress-tests/adversarial-hashing/src/hashing.py` (hash: b91506f9fe1f). Archaeologist inferred intent, contracts, and 3 uncertainties from 154 lines of source with no existing tests.
