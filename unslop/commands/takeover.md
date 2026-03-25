---
description: Run the takeover pipeline on an existing file, directory, or glob
argument-hint: <file-path|directory|glob> [--force-ambiguous] [--skip-adversarial] [--full-adversarial]
---

**Parse arguments:** `$ARGUMENTS` may contain the target path and optional flags. Extract the target path (the first argument that does not start with `--`) and check for flags:

- `--force-ambiguous` -- allow ambiguous specs (existing)
- `--skip-adversarial` -- skip the adversarial pipeline even for testless files. The Builder generates with the standard test_policy ("Write or extend tests") instead of the testless path. Use for files where mutation testing is impractical (pure I/O, GUI code).
- `--full-adversarial` -- force full mutation testing (Mason + Saboteur) regardless of the Architect's intensity assessment.

Strip flags before using the path in subsequent steps.

**Testless detection:** The takeover skill (Step 1) detects test absence automatically and routes to the testless path. No `--no-tests` flag is needed. If `--skip-adversarial` is set, pass it to the skill so it uses the standard Builder-writes-tests path even when no tests exist.

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

**3. Run the takeover pipeline**

**Load and follow** the **unslop/takeover** skill step-by-step. Do not summarize or abbreviate the pipeline. Each step (0 through 8) MUST execute in order.

**No complexity shortcuts.** The full pipeline (Pre-flight -> Raise to Concrete -> Raise to Abstract -> Archive -> Builder in worktree) runs for ALL files regardless of perceived complexity. A trait definition with zero implementation logic still goes through a worktree Builder. The pipeline is proving the spec, not the code.

The pipeline operates in two stages:

- **Stage A (Architect -- current session):** Step 0 (Pre-flight) analyzes complexity and splits large files. Step 1 (Discover) reads the existing code and tests. Then **Phase 0a.0 (Intent Lock)** fires: the Architect presents "From the existing code, I understand this module's purpose is [intent]. I'll draft a spec that captures [behaviors]. Does this match your understanding?" If rejected, the Architect reformulates; if abandoned, no artifacts are left. After Intent Lock approval, the Architect raises through two levels:
  - **Step 2 (Raise to Concrete):** Extract the implementation strategy into a Concrete Spec (`*.impl.md`) -- algorithms, patterns, type structure. This is mandatory even for simple files; it provides the Builder's strategic guide.
  - **Step 2b (Raise to Abstract):** Extract observable behavior into the Abstract Spec (`*.spec.md`). Present to user for approval.
  - **Step 3 (Archive):** Archive originals to `.unslop/archive/`.

- **Stage B (Builder -- worktree):** Steps 4-6 of the takeover skill (Generate, Validate, Convergence).

  **HARD RULE:** The Builder MUST run as a subagent dispatched with `isolation="worktree"` and `model` from config. The Builder receives ONLY:
  - The abstract spec (`*.spec.md`)
  - The concrete spec (`*.impl.md`) from Stage B.1
  - `.unslop/config.json`
  - `.unslop/principles.md`

  The Builder MUST NOT receive the archived original, the Architect's conversation context, or any code the Architect read during Stage A. This isolation is the integrity guarantee: if the Builder reproduces the code from the spec alone, the spec is proven sufficient. Generating inline (in the Architect session) violates this because the Architect has already seen the original source code.

  If you find yourself using Write/Edit on the managed file directly -- STOP. You are violating worktree isolation.

> **Anti-patterns (these are pipeline violations, not style preferences):**
>
> 1. **Inline generation** -- The Architect writes code directly using Write/Edit instead of dispatching a Builder subagent. Violates isolation guarantee.
> 2. **Skipping concrete spec** -- Going from abstract spec directly to code. The Builder generates with no strategic constraints, producing unpredictable output even for "simple" files.
> 3. **Batch commits without validation** -- Committing specs without running the Builder first. The spec's sufficiency is unproven.
> 4. **Passing archive to Builder** -- Giving the Builder access to the original code, defeating the spec-completeness proof.

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
3. After confirmation, **load and follow** the **unslop/takeover** skill in multi-file mode step-by-step. The Architect raises ALL files to concrete then abstract specs before any Builder is dispatched. Each Builder dispatch runs in an isolated worktree with `model` from config. For per-file mode, dispatch Builders in dependency order (leaves first). For per-unit mode, a single Builder generates all files in one worktree session. The same HARD RULE, anti-patterns, and "no complexity shortcuts" constraints from single-file mode apply to every file in the batch.
4. Use the **unslop/spec-language** skill for spec drafting guidance.
5. Use the **unslop/generation** skill for code generation discipline.
6. Read the test command from `.unslop/config.json` (or `.unslop/config.md` as legacy fallback).
7. After successful takeover, update `.unslop/alignment-summary.md` with entries for all newly managed files.
