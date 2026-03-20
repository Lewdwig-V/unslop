---
description: Run the takeover pipeline on an existing file
argument-hint: <file-path>
---

The argument `$ARGUMENTS` is the path to the target source file.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the file at `$ARGUMENTS` exists. If it does not exist, stop and tell the user:

> "File not found. If you want to create a new managed file from scratch, use `/unslop:spec` instead."

**2. Load context**

Read `.unslop/config.md` to obtain the test command. You will need it during the pipeline.

**3. Run the takeover pipeline**

Use the **unslop/takeover** skill to orchestrate the full pipeline. That skill owns all pipeline logic — discovery, spec drafting, archiving, generation, validation, and the convergence loop. Do not duplicate those steps here.

Use the **unslop/spec-language** skill for guidance when drafting or reviewing the spec.

Use the **unslop/generation** skill for code generation discipline.

**4. Update the alignment summary**

After a successful takeover (tests green, files committed), add the managed file to `.unslop/alignment-summary.md` under the `## Managed files` section:

```
- `<relative-path>` — taken over <ISO8601 date>
```

If the takeover ends in the abandonment state (convergence loop exhausted), do not update the alignment summary. The file is not yet under clean spec management.
