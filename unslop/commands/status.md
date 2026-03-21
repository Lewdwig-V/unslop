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

For each spec file found, derive the managed file path by stripping the trailing `.spec.md` suffix (e.g., `src/retry.py.spec.md` → `src/retry.py`). If the managed file does not exist, list the spec under "Unmanaged specs".

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

For files classified as fresh, check if any of their dependencies (from `depends-on` frontmatter in their spec) are stale. If so, reclassify as `stale*` with the note `(dependency stale)`. To detect transitive staleness, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` and check each dependency's staleness. If Python is not available, skip transitive staleness checks and note: `(dependency checking unavailable — install Python 3.8+)`.

---

Display results in this exact format:

```
Managed files:
  fresh    src/auth/tokens.py       <- src/auth/tokens.py.spec.md
  fresh    src/auth/errors.py       <- src/auth/errors.py.spec.md
  stale    src/auth/handler.py      <- src/auth/handler.py.spec.md (spec edited 2h ago)
                                       depends on: tokens.py.spec.md, errors.py.spec.md
  stale*   src/auth/middleware.py   <- src/auth/middleware.py.spec.md (dependency stale)
                                       depends on: handler.py.spec.md

Unit specs:
  fresh    src/utils/               <- src/utils/utils.unit.spec.md (4 files)

Unmanaged specs:
  src/utils.py.spec.md  (no managed file — run /unslop:generate)
```

Rules for the display:
- Align columns where reasonable.
- For **stale** entries, include a human-readable relative time since the spec was last edited (e.g., `2h ago`, `3 days ago`).
- For **modified** entries, include the note `(edited directly)` to make the situation clear.
- For **stale\*** entries, include the note `(dependency stale)`.
- If a spec has `depends-on` frontmatter, show the dependencies on an indented line below the entry.
- For unit specs (`*.unit.spec.md`): display under a `Unit specs:` section showing the directory path, spec name, and file count rather than listing each managed file individually.
- If there are no entries in a section, omit that section header entirely.
- Sort entries within each section alphabetically by managed file path (or spec path for unmanaged specs).

---

This command is read-only. Do not modify any files, generate any code, or run any tests.
