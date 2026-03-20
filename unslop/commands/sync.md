---
description: Regenerate one specific managed file from its spec
argument-hint: <file-path>
---

The argument `$ARGUMENTS` is the path to the managed file (e.g., `src/retry.py`).

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Derive the spec path**

Append `.spec.md` to the filename (e.g., `src/retry.py` → `src/retry.py.spec.md`).

Check that the spec file exists. If it does not exist, stop and tell the user:

> "No spec found at `<spec-path>`. Run `/unslop:spec <file-path>` to create one first."

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
