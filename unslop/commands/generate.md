---
description: Regenerate all stale managed files from their specs
argument-hint: "[--force] [--force-ambiguous] [--force-pseudocode] [--force-strategy] [--incremental] [--dry-run]"
---

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Load context**

Use the **unslop/generation** skill for code generation discipline throughout this command.

Pending `*.change.md` entries are processed in Step 3c (Stage A) before any Builder is dispatched.

Read `.unslop/config.json` to obtain the test command. If `config.json` does not exist, fall back to `.unslop/config.md` (legacy format). You will need the test command when validating regenerated files.

**Check for `--force` flag:** If `$ARGUMENTS` contains `--force`, note this — it allows regeneration to proceed on modified and conflict files without requiring user confirmation.

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When this flag is present, the generation skill's ambiguity detection (Section 0, Phase 0b) reports ambiguities as warnings instead of blocking generation.

**Check for `--force-pseudocode` flag:** If `$ARGUMENTS` contains `--force-pseudocode`, note this for the generation skill. When present, pseudocode linting violations (Phase 0a.1) are reported as warnings instead of blocking generation.

**Check for `--force-strategy` flag:** If `$ARGUMENTS` contains `--force-strategy`, note this for the generation skill. When present, concrete spec strategy incoherence (Phase 0e.1) is reported as warnings instead of blocking generation.

**Check for `--dry-run` flag:** If `$ARGUMENTS` contains `--dry-run`, perform a ripple-effect analysis instead of generating code. This shows the user exactly what would happen — which specs, concrete specs, and managed files would be affected — without spawning any worktrees or modifying any files. See Step 4b below.

**2b. Check diagnostic cache**

For each spec file found, check for `.unslop/last-failure/<cache-key>.md`. If any failure reports exist, surface a one-liner for each before proceeding:

> "Resuming from previous failure for `<spec-path>`: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

Inject the failure report contents into the corresponding Builder's prompt via the `{previous_failure}` parameter (see generation skill).

**3. Scan for spec files**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`).

**3b. Resolve build order**

Check if any of the found spec files have `depends-on` frontmatter (look for `---` at the start of any spec file). If dependency frontmatter is found:

1. Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py build-order .` to get the full build order across all specs.
2. Process files in this order instead of arbitrary order.
3. If the orchestrator reports a cycle, stop and report the error to the user.

If no specs have `depends-on` frontmatter, or if Python is not available, process in the existing order (this preserves backwards compatibility).

**3c. Stage A: Process pending changes (Architect)**

Before dispatching any Builders, run Phase 0c for ALL files that have pending `*.change.md` entries:

**Phase 0a.0 gate:** Before running Phase 0c for a file, the generation skill's Phase 0a.0 (Intent Lock) fires -- the Architect presents an aggregated intent statement for all pending entries on that file and waits for approval. Only after approval does Phase 0c process individual entries. See the generation skill's Phase 0a.0 section for the full protocol.

1. For each file with a `*.change.md` sidecar (in build order):
   a. Run the generation skill's Phase 0c (Stage A behavior) -- propose spec updates for each pending/tactical entry, get user approval.
   b. Stage approved spec updates (`git add`). Do NOT commit.
2. After all Phase 0c processing is complete, proceed to classification and Builder dispatch.

This ensures all spec updates are finalized before any code generation begins.

**4. Classify each spec file**

For each `*.spec.md` found, derive the managed file path by stripping the trailing `.spec.md` suffix (e.g., `src/retry.py.spec.md` -> `src/retry.py`).

Classify it as one of:

- **New**: the managed file does not exist yet -- must be generated unconditionally.
- **Fresh**: stored spec-hash matches current spec hash AND stored output-hash matches current output hash -- skip it.
- **Stale**: stored spec-hash does NOT match current spec hash AND stored output-hash matches current output hash -- the spec changed but code is untouched; regenerate.
- **Modified**: stored spec-hash matches current spec hash AND stored output-hash does NOT match current output hash -- the code was edited directly. Warn the user and require `--force` or explicit user confirmation before regenerating.
- **Conflict**: both hashes mismatch -- spec and code both changed. Block and require `--force` or explicit user confirmation before proceeding.
- **Old format**: header is present but uses the old timestamp-based format (no `spec-hash`/`output-hash` fields) -- treat as stale and regenerate.

Hash algorithm: SHA-256 of content, truncated to 12 hex characters. For spec hash: hash the full spec file content. For output hash: hash the managed file body below the `@unslop-managed` header block, stripped of leading/trailing whitespace.

For unit specs (`*.unit.spec.md`): derive managed file paths from the `## Files` section in the spec rather than the naming convention.

Report the classification of every spec file before proceeding.

**4b. Dry-run ripple analysis (if `--dry-run`)**

If `--dry-run` was specified, run the ripple-effect analysis instead of dispatching Builders:

1. Collect all spec paths classified as new, stale, modified, conflict, or old_format in Step 4.
2. Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ripple-check <spec-path>... --root .` with all affected spec paths.
3. Display the ripple report in three layers:

```
Ripple Effect Analysis (dry run — no files will be modified)

Abstract Specs:
  CHANGED    src/core/pool.py.spec.md           (directly changed)
  AFFECTED   src/api/handler.py.spec.md         (depends on pool.py.spec.md)
  AFFECTED   src/api/middleware.py.spec.md       (depends on handler.py.spec.md)

Concrete Specs:
  REGEN      src/core/pool.py.impl.md           (source spec changed)
  GHOST      src/api/handler.py.impl.md         (upstream concrete dep: pool.py.impl.md)

Managed Files:
  REGEN      src/core/pool.py                   <- pool.py.spec.md (stale)
  REGEN      src/api/handler.py                 <- handler.py.spec.md (transitive)
  GHOST      src/api/middleware.py               <- middleware.py.spec.md (ghost-stale)

Build Order: pool.py.spec.md → handler.py.spec.md → middleware.py.spec.md

Total: 3 specs, 2 concrete specs, 3 managed files would be regenerated.
```

4. **Stop.** Do not proceed to Step 5. The `--dry-run` flag is read-only — no files are modified, no worktrees are spawned, no commits are made.

This gives the user a complete view of the "blast radius" before committing to a bulk regeneration.

**5. Dispatch Builders (Stage B -- worktree isolation)**

For each file classified as new, stale, modified (confirmed), or conflict (confirmed), in build order:

1. **Select generation mode.** New files always use Mode A. For others, default is Mode A; use Mode B if `--incremental` was passed.
2. **Dispatch a Builder Agent** using the generation skill's two-stage execution model:
   - test_policy: `"Do NOT create or modify spec-backed test files. Use existing tests for validation only. Tests marked @unslop-incidental may be updated or removed if they fail against regenerated code that correctly follows the spec."`
   - Pass `--incremental` to the Builder prompt if Mode B was selected.
3. **Verify result:**
   - If DONE with green tests: worktree merges automatically. Compute `output-hash`, update header.
   - If BLOCKED or tests fail: discard worktree, revert ALL staged spec updates from Step 3c (`git checkout HEAD -- <spec_path>` for every spec that was staged), not just the failing file's spec. Report failure and **stop immediately**. Do not process remaining files.
4. If a dependency was regenerated in this run, mark its dependents as stale even if their own specs haven't changed.

If cascading regeneration of a dependent causes Builder failure, stop and report: which upstream regeneration caused the failure, which dependent broke, and the Builder's failure report.

**6. Update the alignment summary**

After all files have been processed without a stopping failure, update `.unslop/alignment-summary.md`:

- For each newly generated or regenerated file, ensure it appears under the `## Managed files` section. If it is already listed, update the entry to reflect the regeneration date. If it is new, add it:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.

**7. Commit**

After all Builders have succeeded and worktrees are merged, commit all changes atomically:
- All staged spec updates (from Phase 0c)
- All merged generated code (from Builder worktrees)
- Updated alignment summary

This is a single atomic commit covering all files processed in this run.

**8. Clean up diagnostic cache**

After the atomic commit succeeds, delete `.unslop/last-failure/<cache-key>.md` for every spec that was successfully generated in this run. Cache files must not be deleted before the commit -- if a later Builder fails in Step 5 and the run is aborted, the post-mortem for earlier specs must survive for the next retry.
