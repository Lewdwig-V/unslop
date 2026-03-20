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

For each spec file found, derive the managed file path by replacing the `.spec.md` extension with the original source extension (e.g., `src/retry.spec.md` → `src/retry.py`). The source extension is whatever non-`.spec.md` extension the base filename implies. If the spec filename is ambiguous (e.g., `foo.spec.md` with no clear source extension), skip classification and list it under "Unmanaged specs" with a note that the source path cannot be determined.

Classify each spec as follows:

**If the managed file does not exist:**
- List under "Unmanaged specs".

**If the managed file exists:**
- Read the `@unslop-managed` header line near the top of the managed file. It will look like:
  ```
  # @unslop-managed generated:<ISO8601 timestamp>
  ```
- If the header is missing or malformed, classify as `unmanaged (no header)` and list under "Managed files" with that label.
- If the header is present, extract the generation timestamp and compare:
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
