---
description: Run the takeover pipeline on an existing file, directory, or glob
argument-hint: <file-path|directory|glob> [--force-ambiguous]
---

**Parse arguments:** `$ARGUMENTS` may contain the target path and optional flags. Extract the target path (the first argument that does not start with `--`) and check for flags (`--force-ambiguous`). Strip flags before using the path in subsequent steps.

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

Check for a `*.change.md` sidecar for the target file (same directory, same base name with `.change.md` extension). If one exists with pending entries, warn: "This file has N pending changes that will be lost during takeover. Process them first with `/unslop:sync` or use `--force` to proceed." Require `--force` to continue.

---

**Single-file mode**

**2. Load context**

Read `.unslop/config.json` (or `.unslop/config.md` as legacy fallback) to obtain the test command.

**3. Run the takeover pipeline (two-stage)**

Use the **unslop/takeover** skill. The pipeline now operates in two stages:
- **Stage A (Architect -- current session):** Step 1 of the takeover skill (Discover) reads the existing code and tests. Then **Phase 0a.0 (Intent Lock)** fires: the Architect presents "From the existing code, I understand this module's purpose is [intent]. I'll draft a spec that captures [behaviors]. Does this match your understanding?" If rejected, the Architect reformulates in the same session; if the user abandons, no artifacts are left. After Intent Lock approval, Steps 2-3 (Draft Spec, Archive) proceed. This is the exception where the Architect sees source code.
- **Stage B (Builder -- worktree):** Steps 4-6 of the takeover skill (Generate, Validate, Convergence). Each Builder dispatch runs in an isolated worktree.

The spec update is staged but not committed until the Builder succeeds. On convergence failure, the staged spec is reverted.

Use the **unslop/spec-language** skill for spec drafting guidance.
Use the **unslop/generation** skill for the Builder's code generation discipline.

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
3. After confirmation, use the **unslop/takeover** skill in multi-file mode. Each Builder dispatch (Step 4) runs in an isolated worktree. For per-file mode, Builders are dispatched in build order. For per-unit mode, a single Builder generates all files in one worktree session.
4. Use the **unslop/spec-language** skill for spec drafting guidance.
5. Use the **unslop/generation** skill for code generation discipline.
6. Read the test command from `.unslop/config.json` (or `.unslop/config.md` as legacy fallback).
7. After successful takeover, update `.unslop/alignment-summary.md` with entries for all newly managed files.
