---
description: Regenerate all stale managed files from their specs
---

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Load context**

Use the **unslop/generation** skill for code generation discipline throughout this command.

Read `.unslop/config.md` to obtain the test command. You will need it when validating regenerated files.

**3. Scan for spec files**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`).

**4. Classify each spec file**

For each `*.spec.md` found, derive the managed file path. The spec naming convention replaces the source file's extension with `.spec.md` (e.g., `src/retry.py` → `src/retry.spec.md`). To find the managed file, look for a file in the same directory with the same base name but a source code extension (e.g., `src/retry.spec.md` → look for `src/retry.py`, `src/retry.ts`, etc.). If the `@unslop-managed` header exists in a candidate file, that's the managed file.

Classify it as one of:

- **New**: the managed file does not exist yet — must be generated.
- **Stale**: the managed file exists but the spec file's modification time is newer — must be regenerated.
- **Fresh**: the managed file exists and is at least as recent as the spec — skip it.

Report the classification of every spec file before proceeding.

**5. Process stale and new files**

For each file classified as new or stale, in order:

1. Read only the spec file. Do not read the existing managed file (if any) — generate from the spec alone.
2. Generate the managed file. The file must begin with the `@unslop-managed` header as specified by the **unslop/generation** skill.
3. Run the test command from `.unslop/config.md`.
4. If tests pass: report success for this file and continue to the next.
5. If tests fail: report the failure output and **stop immediately**. Do NOT attempt to fix the code, re-read the spec, or enter any convergence loop. Tell the user:

> "Tests failed after regenerating `<file>`. The spec may have introduced breaking changes. Review the failures above and update the spec or downstream code as needed."

If any file causes a stop, do not process remaining files.

**6. Update the alignment summary**

After all files have been processed without a stopping failure, update `.unslop/alignment-summary.md`:

- For each newly generated or regenerated file, ensure it appears under the `## Managed files` section. If it is already listed, update the entry to reflect the regeneration date. If it is new, add it:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.
