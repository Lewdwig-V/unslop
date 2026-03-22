---
description: Run the takeover pipeline on an existing file, directory, or glob
argument-hint: <file-path|directory|glob> [--force-ambiguous]
---

The argument `$ARGUMENTS` is the path to the target source file, a directory, or a glob pattern.

**0. Detect mode**

Determine whether this is a single-file or multi-file takeover:

- If `$ARGUMENTS` is a directory path (test with filesystem check): **multi-file mode**
- If `$ARGUMENTS` contains glob characters (`*`, `?`): expand the glob to get a file list. If multiple files match, **multi-file mode**. If one file matches, **single-file mode**.
- Otherwise: **single-file mode** (existing behavior, unchanged)

Multi-file mode requires Python 3.8+. Check that `python3` or `python` is available. If not, stop and tell the user: "Multi-file takeover requires Python 3.8+. Install Python or use single-file takeover on individual files."

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the file at `$ARGUMENTS` exists. If it does not exist, stop and tell the user:

> "File not found. If you want to create a new managed file from scratch, use `/unslop:spec` instead."

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When present, ambiguity detection reports warnings instead of blocking.

---

**Single-file mode**

**2. Load context**

Read `.unslop/config.md` to obtain the test command. You will need it during the pipeline.

**3. Run the takeover pipeline**

Use the **unslop/takeover** skill to orchestrate the full pipeline. That skill owns all pipeline logic — discovery, spec drafting, archiving, generation, validation, and the convergence loop. Do not duplicate those steps here.

Use the **unslop/spec-language** skill for guidance when drafting or reviewing the spec.

Use the **unslop/generation** skill for code generation discipline.

**4. Update the alignment summary**

After a successful takeover (tests green, files committed), add the managed file to `.unslop/alignment-summary.md` under the `## Managed files` section:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.

If the takeover ends in the abandonment state (convergence loop exhausted), do not update the alignment summary. The file is not yet under clean spec management.

---

**Multi-file mode**

If multi-file mode was detected:

1. Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py discover <directory> --extensions <detected-extensions>` to find source files. Detect the extensions from the directory contents (e.g., `.py` for Python, `.rs` for Rust, `.ts` for TypeScript).
2. Present the discovered file list to the user for confirmation. They may add or remove files.
3. After confirmation, use the **unslop/takeover** skill in multi-file mode, passing the confirmed file list.
4. Use the **unslop/spec-language** skill for spec drafting guidance.
5. Use the **unslop/generation** skill for code generation discipline.
6. Read the test command from `.unslop/config.md`.
7. After successful takeover, update `.unslop/alignment-summary.md` with entries for all newly managed files.
