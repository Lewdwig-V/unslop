---
description: Regenerate one specific managed file from its spec
argument-hint: <file-path>
---

The argument `$ARGUMENTS` is the path to the managed file (e.g., `src/retry.py`).

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Derive the spec path**

First, check if the managed file has an `@unslop-managed` header — if so, read the spec path from the header (line 1 contains the spec path after 'Edit' and before 'instead'). Otherwise, fall back to appending `.spec.md` to the filename. This supports both per-file and per-unit specs.

Check that the spec file exists. If it does not exist, stop and tell the user:

> "No spec found at `<spec-path>`. Run `/unslop:spec <file-path>` to create one first."

**2b. Check dependencies**

If the spec has `depends-on` frontmatter, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` to find transitive dependencies.

Check if any dependencies are stale (their spec mtime > their managed file's generation timestamp). If so, regenerate stale dependencies first, in dependency order, before regenerating the target file.

If Python is not available and the spec has no `depends-on` frontmatter, proceed without dependency resolution (backwards compatible). If the spec has dependencies but Python is unavailable, report an error: "This spec has dependencies that require Python 3.8+ for resolution."

**3. Generate**

Use the **unslop/generation** skill. Read only the spec — do not read the existing generated file. Generate the managed file with the `@unslop-managed` header.

**4. Run tests**

Read the test command from `.unslop/config.md`. Run the test suite.

- If tests pass: report success and the file path.
- If tests fail: report the failures and stop. Do not attempt to fix or retry.

**5. Update the alignment summary**

Update `.unslop/alignment-summary.md` to record the sync under the `## Managed files` section. If the file already appears there, update its entry with the current timestamp:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.

**6. Commit**

After updating the alignment summary, commit the regenerated file and the updated alignment summary.
