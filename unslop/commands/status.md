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

For each spec file found, derive the managed file path. The spec naming convention replaces the source file's extension with `.spec.md` (e.g., `src/retry.py` → `src/retry.spec.md`). To find the managed file, look for a file in the same directory with the same base name but a source code extension (e.g., `src/retry.spec.md` → look for `src/retry.py`, `src/retry.ts`, etc.). Check for the `@unslop-managed` header to confirm. If no matching managed file is found, list the spec under "Unmanaged specs".

Classify each spec as follows:

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
- If the header is present, extract the generation timestamp from the second line and compare:
  - Get the spec file's last-modified time (mtime).
  - Get the managed file's last-modified time (mtime).
  - **Fresh**: spec mtime <= generation timestamp AND managed file mtime <= generation timestamp
  - **Stale**: spec mtime > generation timestamp (spec was edited after last generation)
  - **Modified**: managed file mtime > generation timestamp AND spec mtime <= generation timestamp (managed file was edited directly)

---

Display results in this exact format:

```
Managed files:
  fresh    src/retry.py        <- retry.spec.md
  stale    src/parser.py       <- parser.spec.md (spec edited 2h ago)
  modified src/adapter.py      <- adapter.spec.md (edited directly)
  unmanaged (no header)  src/legacy.py  <- legacy.spec.md

Unmanaged specs:
  src/utils.spec.md  (no managed file — run /unslop:generate)
```

Rules for the display:
- Align columns where reasonable.
- For **stale** entries, include a human-readable relative time since the spec was last edited (e.g., `2h ago`, `3 days ago`).
- For **modified** entries, include the note `(edited directly)` to make the situation clear.
- If there are no entries in a section, omit that section header entirely.
- Sort entries within each section alphabetically by managed file path (or spec path for unmanaged specs).

---

This command is read-only. Do not modify any files, generate any code, or run any tests.
