---
description: List managed files and their staleness status
---

Check that `.unslop/` exists in the current working directory. If it does not, stop and inform the user that unslop is not initialized — they should run `/unslop:init` first.

Scan the project recursively for all `*.spec.md` files. Exclude anything inside `.unslop/` or `node_modules/`.

If no spec files are found anywhere, stop and output:

```
No specs found. Get started with /unslop:spec <file> or /unslop:takeover <file>.
```

---

**Separate unit specs from per-file specs.** If a spec filename matches `*.unit.spec.md`, it is a unit spec — handle it separately (see Unit Specs section below). For all other `*.spec.md` files, proceed with per-file classification.

For each per-file spec, derive the managed file path by stripping the trailing `.spec.md` suffix (e.g., `src/retry.py.spec.md` → `src/retry.py`). If the managed file does not exist, list the spec under "Unmanaged specs".

Classify each per-file spec as follows:

**If the managed file does not exist:**
- List under "Unmanaged specs".

**If the managed file exists:**
- Read the `@unslop-managed` header near the top of the managed file. It is a two-line header:
  ```
  # @unslop-managed — do not edit directly. Edit <spec-path> instead.
  # Generated from spec at <ISO 8601 timestamp>
  ```
  (Comment syntax varies by language — `#`, `//`, `<!-- -->`, `/* */`, `--`.)
- If the header is missing or malformed, classify as `unmanaged (no header)` and list under "Managed files" with that label.
- If the header uses the old two-line format (no `spec-hash` or `output-hash` fields), classify as `old_format` and display with the note `(old header — regenerate to update)`.
- If the header is present and contains `spec-hash` and `output-hash` fields, apply the 4-state hash-based classification:
  - Compute the **current spec hash**: SHA-256 of the spec file's content, truncated to 12 hex characters.
  - Compute the **current output hash**: SHA-256 of the managed file's body (everything below the `@unslop-managed` header block), with leading/trailing whitespace stripped, truncated to 12 hex characters.
  - Extract `spec-hash` and `output-hash` from the header.
  - **Fresh**: stored spec-hash matches current spec hash AND stored output-hash matches current output hash.
  - **Modified**: stored spec-hash matches current spec hash AND stored output-hash does NOT match current output hash (code was edited directly, spec unchanged).
  - **Stale**: stored spec-hash does NOT match current spec hash AND stored output-hash matches current output hash (spec changed, code untouched).
  - **Conflict**: stored spec-hash does NOT match current spec hash AND stored output-hash does NOT match current output hash (both spec and code changed).

---

If the managed file's `@unslop-managed` header contains a `principles-hash` field, compare it against the current hash of `.unslop/principles.md`. If the hashes don't match, add `(principles changed)` to the status annotation. This is additive — a file can show `modified (principles changed)` or `conflict (principles changed)`. If `principles.md` has been deleted but files still have `principles-hash`, annotate as `(principles removed)`.

If a principles change makes many files stale, display a summary note:
```
Note: N files are stale due to project principle changes.
```

**Preferred:** If the MCP server is running, use the `unslop_check_freshness` tool directly instead of shelling out to the orchestrator CLI. The MCP tool provides typed inputs and structured JSON output. Fall back to the CLI if the MCP server is not available.

For files classified as fresh, check if any of their dependencies (from `depends-on` frontmatter in their spec) are stale or conflict. If so, reclassify as `stale*` with the note `(dependency stale)`. To detect transitive staleness, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` and check each dependency's classification using the hash-based method above. If Python is not available, skip transitive staleness checks and note: `(dependency checking unavailable — install Python 3.8+)`.

**Concrete spec ghost staleness.** For files classified as fresh, check if a permanent concrete spec (`*.impl.md`) exists with `concrete-dependencies` in its frontmatter. If any upstream concrete dependency has changed (use `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py concrete-deps <impl-path> --root .`), reclassify as `ghost-stale` with the note indicating which upstream changed:

```
  ghost-stale  src/api/handler.py     <- src/api/handler.py.spec.md
                                          upstream concrete spec changed: src/core/pool.py.impl.md
```

Ghost staleness means the abstract spec and generated code are both unchanged, but an upstream implementation strategy has shifted — the Builder needs to re-lower through a fresh concrete spec.

---

**Unit spec classification.** For each `*.unit.spec.md` file:
- Read the spec's `## Files` section to get the list of managed files in the unit
- Resolve file paths relative to the directory containing the unit spec
- For each listed file, check if it exists and has an `@unslop-managed` header pointing to this unit spec
- Classify the unit as:
  - **Fresh**: all listed files exist, all have headers whose stored spec-hash matches the current spec hash
  - **Stale**: any listed file's stored spec-hash does not match the current spec hash
  - **Partial**: some listed files exist with headers but others are missing — note which are missing
- Display under the `Unit specs:` section with the directory path, spec name, and file count

---

Display results in this exact format:

```
Managed files:
  fresh      src/auth/tokens.py       <- src/auth/tokens.py.spec.md
             Δ 2 pending changes [1 pending, 1 tactical]
  fresh      src/auth/errors.py       <- src/auth/errors.py.spec.md
  stale      src/auth/handler.py      <- src/auth/handler.py.spec.md
                                         depends on: tokens.py.spec.md, errors.py.spec.md
  stale*     src/auth/middleware.py   <- src/auth/middleware.py.spec.md (dependency stale)
                                         depends on: handler.py.spec.md
  conflict   src/adapter.py           <- src/adapter.py.spec.md (spec and code both changed)
  old_fmt    src/legacy.py            <- src/legacy.py.spec.md (old header — regenerate to update)

Unit specs:
  fresh    src/utils/               <- src/utils/utils.unit.spec.md (4 files)

Unmanaged specs:
  src/utils.py.spec.md  (no managed file — run /unslop:generate)
```

Rules for the display:
- Align columns where reasonable.
- For **stale** entries, the spec hash changed — no timestamp note needed (hash mismatch is self-explanatory).
- For **modified** entries, include the note `(edited directly)` to make the situation clear.
- For **conflict** entries, include the note `(spec and code both changed)`.
- For **old_format** entries, include the note `(old header — regenerate to update)`.
- For **stale\*** entries, include the note `(dependency stale)`.
- For **ghost-stale** entries, include the note `(upstream concrete spec changed: <path>)`.
- If a spec has `depends-on` frontmatter, show the dependencies on an indented line below the entry.
- For unit specs (`*.unit.spec.md`): display under a `Unit specs:` section showing the directory path, spec name, and file count rather than listing each managed file individually.
- If there are no entries in a section, omit that section header entirely.
- Sort entries within each section alphabetically by managed file path (or spec path for unmanaged specs).

---

After classifying each managed file, check for a corresponding `*.change.md` sidecar (same directory, same base name with `.change.md` extension). If present, read it and count entries by status. Display a summary line indented below the file entry:

```
           Δ N pending changes [X pending, Y tactical]
```

The Δ indicator appears regardless of the file's staleness state.

After classifying each managed file, check for `blocked_constraints` in the freshness result. If present, display a summary line indented below the file entry:

```
             ⊘ N blocked constraint(s): <affects-1>, <affects-2>
               waiting on <symbol-1>, <symbol-2>
```

The ⊘ indicator is a new annotation type parallel to Δ (pending changes). It appears regardless of the file's staleness state. A file can show both ⊘ and Δ simultaneously. Blocked constraints do NOT change the file's staleness classification -- they are informational only.

---

This command is read-only. Do not modify any files, generate any code, or run any tests.
