---
description: Regenerate managed files from their specs
argument-hint: "[<file-path>] [--force] [--force-ambiguous] [--force-pseudocode] [--force-strategy] [--incremental] [--refactor] [--deep] [--dry-run] [--stale-only] [--resume] [--max-batch N]"
---

**Parse arguments:** `$ARGUMENTS` may contain the file path and optional flags. Extract the file path (the first argument that does not start with `--`) and check for flags (`--force`, `--force-ambiguous`, `--force-pseudocode`, `--force-strategy`, `--incremental`, `--refactor`, `--deep`, `--dry-run`, `--stale-only`, `--resume`, `--max-batch`). Strip flags before using the path in subsequent steps. Note: `--stale-only` and `--resume` do not require a file path.

**Check for `--force` flag:** If `$ARGUMENTS` contains `--force`, note this — it allows regeneration to proceed on modified and conflict files without requiring user confirmation.

**Check for `--deep` flag:** If `$ARGUMENTS` contains `--deep`, this sync will regenerate not just the target file but its entire downstream blast radius — all files transitively affected by the target's spec/concrete dependencies. See **Step 2d** below for the deep sync workflow.

**Check for `--dry-run` flag:** If `$ARGUMENTS` contains `--dry-run` (meaningful with `--deep` or `--stale-only`), show the sync plan without regenerating any files.

**Check for `--stale-only` flag:** If `$ARGUMENTS` contains `--stale-only`, this sync will find and batch-regenerate ALL stale files in the project — no file path required. See **Step 2e** below for the bulk sync workflow.

**Check for `--resume` flag:** If `$ARGUMENTS` contains `--resume`, this sync resumes a previously failed bulk or deep sync. It reads the failure report from `.unslop/last-sync-state.json`, computes only the downstream branch of the failure, and skips files that already succeeded. See **Step 2f** below for the resume workflow. No file path required.

**Check for `--force-pseudocode` flag:** If `$ARGUMENTS` contains `--force-pseudocode`, note this for the generation skill. When present, pseudocode linting violations (Phase 0a.1) are reported as warnings instead of blocking generation.

**Check for `--force-strategy` flag:** If `$ARGUMENTS` contains `--force-strategy`, note this for the generation skill. When present, concrete spec strategy incoherence (Phase 0e.1) is reported as warnings instead of blocking generation.

**Check for `--max-batch` flag:** If `$ARGUMENTS` contains `--max-batch N`, use N as the maximum number of files per worktree batch (default: 8). Only meaningful with `--stale-only` or `--resume`.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

If `--stale-only` was passed, skip directly to **Step 2e** — no file path is needed.

If `--resume` was passed, skip directly to **Step 2f** — no file path is needed.

If none of `--stale-only`, `--resume` was passed and no file path was provided, stop and tell the user:

> "Usage: `/unslop:sync <file-path>` or `/unslop:sync --stale-only` or `/unslop:sync --resume`"

**2. Derive the spec path**

First, check if the managed file has an `@unslop-managed` header — if so, read the spec path from the header (line 1 contains the spec path after 'Edit' and before 'instead'). Otherwise, fall back to appending `.spec.md` to the filename. This supports both per-file and per-unit specs.

Check that the spec file exists. If it does not exist, stop and tell the user:

> "No spec found at `<spec-path>`. Run `/unslop:spec <file-path>` to create one first."

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When present, ambiguity detection reports warnings instead of blocking.

**2b. Check dependencies**

If the spec has `depends-on` frontmatter, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` to find transitive dependencies.

Check if any dependencies are stale or conflict (using hash-based classification: compare stored spec-hash against current spec hash; if mismatch, the dependency is stale). If so, regenerate stale dependencies first, in dependency order, before regenerating the target file.

If Python is not available and the spec has no `depends-on` frontmatter, proceed without dependency resolution (backwards compatible). If the spec has dependencies but Python is unavailable, report an error: "This spec has dependencies that require Python 3.8+ for resolution."

**2c. Check diagnostic cache**

Check for `.unslop/last-failure/<cache-key>.md` where `<cache-key>` is the spec path with `/` replaced by `--`. If a failure report exists, surface a one-liner before proceeding:

> "Resuming from previous failure: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

Inject the failure report contents into the Builder's prompt via the `{previous_failure}` parameter (see generation skill).

**2d. Deep sync workflow (if `--deep`)**

If `--deep` was passed, switch to the deep sync workflow instead of the single-file flow:

1. Call the orchestrator to compute the deep sync plan:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deep-sync-plan <file-path> --root . [--force]
```

This returns a JSON response with:
- `trigger`: The spec that initiated the deep sync.
- `plan`: Ordered list of files to regenerate (in topological order).
- `skipped`: Files that need user confirmation (modified/conflict state).
- `stats`: Summary counts.
- `build_order`: Topological spec order.

2. **Display the plan** to the user before proceeding:

```
Deep Sync Plan for <file-path>
Trigger: <trigger-spec>

Files to regenerate (in topological order):
  1. <managed-file>  <- <spec>  (state: stale, cause: direct)
  2. <managed-file>  <- <spec>  (state: ghost-stale, cause: transitive)
  ...

Skipped (need --force or confirmation):
  - <managed-file>  (state: modified)

Total: N files to regenerate, M skipped.
```

3. **If `--dry-run`**: Stop here. Do not regenerate any files. The plan is read-only.

4. **If skipped files exist** and `--force` was not passed: Ask the user whether to proceed without the skipped files, or abort so they can re-run with `--force`.

5. **Process each file in the plan**, in the order returned by the orchestrator:
   - For each file, check for its diagnostic cache entry at `.unslop/last-failure/<cache-key>.md`. If found, inject `{previous_failure}` into the Builder prompt.
   - For each file, run the normal sync Steps 3-6 (classify, dispatch Builder, verify, update alignment, commit).
   - **Critical**: After each successful regeneration, the downstream files in the plan may now have updated concrete-manifests. This is expected — they will be regenerated in their turn.
   - If a Builder fails for any file: **stop immediately**. Report which file in the chain failed and its position in the plan. Do not process remaining files.

6. After all files in the plan are regenerated successfully, report:

```
Deep sync complete: N/N files regenerated successfully.
Build order: spec1 -> spec2 -> spec3
```

After displaying the plan or completing the deep sync, **return** — do not fall through to the single-file sync flow below.

**2e. Bulk sync workflow (if `--stale-only`)**

If `--stale-only` was passed, switch to the bulk sync workflow. This scans the entire project for stale files and batches them into worktree groups that respect topological order.

1. Call the orchestrator to compute the bulk sync plan:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py bulk-sync-plan --root . [--force] [--max-batch N]
```

This returns a JSON response with:
- `batches`: Ordered list of worktree batches, each containing a `files` array of entries with `managed`, `spec`, `state`, `cause`, and optionally `concrete`.
- `skipped`: Files that need user confirmation (modified/conflict state).
- `stats`: Summary counts (`total_stale`, `total_batches`, `to_regenerate`, `skipped_need_confirm`).
- `build_order`: Topological spec order used for sequencing.

2. **Display the plan** to the user before proceeding:

```
Bulk Sync Plan (--stale-only)

Batch 1 of N (M files):
  1. <managed-file>  <- <spec>  (state: stale, cause: direct)
  2. <managed-file>  <- <spec>  (state: ghost-stale, cause: transitive)

Batch 2 of N (M files):
  3. <managed-file>  <- <spec>  (state: stale, cause: direct)
  ...

Skipped (need --force or confirmation):
  - <managed-file>  (state: modified)

Total: N files to regenerate across B batches, M skipped.
```

3. **If `--dry-run`**: Stop here. Do not regenerate any files. The plan is read-only.

4. **If skipped files exist** and `--force` was not passed: Ask the user whether to proceed without the skipped files, or abort so they can re-run with `--force`.

5. **Process each batch sequentially**, in the order returned by the orchestrator:
   - Before starting a batch, report: `Starting batch K/N (M files)...`
   - For each file in the batch, check for its diagnostic cache entry at `.unslop/last-failure/<cache-key>.md`. If found, inject `{previous_failure}` into the Builder prompt.
   - For each file in the batch, run the normal sync Steps 3-6 (classify, dispatch Builder, verify, update alignment, commit).
   - Files within the same batch are at the same topological depth (no dependency edges between them), so their order within the batch is flexible.
   - **Critical**: After completing a batch, downstream files in later batches may now have updated concrete-manifests. This is expected — they will be regenerated in their batch.
   - If a Builder fails for any file in a batch: let the **other files in the same batch finish** (they are independent — no dependency edges), then **stop**. Do not process any subsequent batches.
   - **Save sync state**: Write `.unslop/last-sync-state.json` with the lists of succeeded and failed managed file paths:
     ```json
     {
       "failed": ["service.py"],
       "succeeded": ["auth.py", "utils.py"],
       "timestamp": "<ISO8601>"
     }
     ```
   - Report which file(s) failed, which succeeded in the same batch, and how many batches remain. Tell the user they can fix the spec and run `/unslop:sync --resume` to continue.

6. After all batches are processed successfully, report:

```
Bulk sync complete: N/N files regenerated across B batches.
Build order: spec1 -> spec2 -> spec3
```

After displaying the plan or completing the bulk sync, **return** — do not fall through to the single-file sync flow below.

**2f. Resume workflow (if `--resume`)**

If `--resume` was passed, resume a previously failed bulk sync using the saved state.

1. Read `.unslop/last-sync-state.json`. If it does not exist, stop and tell the user:

> "No previous sync state found. Run `/unslop:sync --stale-only` first."

2. Call the orchestrator to compute the resume plan:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py resume-sync-plan --failed <f1,f2> --succeeded <s1,s2> --root . [--force] [--max-batch N]
```

This returns the same structure as `bulk-sync-plan`, plus:
- `resumed_from`: The failed files that triggered the resume.
- `already_done`: Count of succeeded files excluded from the plan.

The plan contains only the failed files (for retry) and their transitive downstream dependents that are still stale.

3. **Display the resume plan** to the user:

```
Resume Plan (from previous failure)
Previously failed: service.py
Already succeeded: auth.py, utils.py (skipped)

Batch 1 of N (M files):
  1. service.py  <- service.py.spec.md  (retry)
  ...

Batch 2 of N (M files):
  2. api.py  <- api.py.spec.md  (downstream of service.py)
  ...

Total: N files to regenerate across B batches.
```

4. **If `--dry-run`**: Stop here.

5. **Process batches** using the same logic as Step 2e.5 (sequential batches, parallel-safe within each batch, save state on failure). For each file dispatched, check for its diagnostic cache entry at `.unslop/last-failure/<cache-key>.md` and inject `{previous_failure}` into the Builder prompt if found.

6. After all batches succeed, delete `.unslop/last-sync-state.json` and report:

```
Resume complete: N/N files regenerated across B batches.
Previous failures resolved.
```

After completing the resume, **return** — do not fall through to the single-file sync flow below.

**3. Classify and dispatch**

Classify the target file using hash-based logic (same as `/unslop:generate`):
- Compute current spec hash (SHA-256 of spec content, truncated to 12 hex) and current output hash (SHA-256 of managed file body below the header, stripped, truncated to 12 hex).
- Extract stored `spec-hash` and `output-hash` from the `@unslop-managed` header.
- **Modified** (spec-hash match, output-hash mismatch): warn the user the file was edited directly. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.
- **Conflict** (both hashes mismatch): warn that both spec and code changed. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.
- **Old format** (no hash fields in header): treat as stale and proceed.

**Stage A (Architect -- if pending changes exist):**

**Phase 0a.0 gate:** Before processing pending entries, the generation skill's Phase 0a.0 (Intent Lock) fires -- the Architect presents an aggregated intent statement and waits for approval. See the generation skill's Phase 0a.0 section.

If a `*.change.md` sidecar exists for this file with pending entries, run the generation skill's Phase 0c (Stage A behavior):
- Propose spec updates for each entry, get user approval.
- Stage approved spec updates (`git add`). Do NOT commit.

**Modified file pre-flight (surgical mode only):**

If the managed file has state `modified` (user hand-edited the code) and the spec also changed:

> "src/file.py has manual edits (modified state). The spec also changed.
>   [a] Overwrite -- discard manual edits, regenerate from spec (Mode A)
>   [b] Absorb -- incorporate manual edits into the spec first, then regenerate
>   [c] Skip -- leave this file alone for now"

Option (a) uses Mode A (full regen). Option (b) routes to `/unslop:change`. Option (c) skips.

**Check for `needs-review` flags**

Before dispatching any Builder, check each target spec's frontmatter for `needs-review`. For bulk and deep sync, check all specs in the plan.

For each flagged spec, present:

```
⚠ Spec `<spec-path>` is flagged needs-review.
  Upstream spec changed (intent-hash: <hash>).

  (a) Acknowledge and proceed
  (b) Open elicit to review the impact
  (q) Abort sync
```

**Option (a):** Write `review-acknowledged: <needs-review-hash>` into the spec frontmatter. Remove `needs-review`. Stage.

**Option (b):** Route to `/unslop:elicit <managed-file>` in amendment mode. After elicit completes, re-classify and continue.

**Option (q):** Stop sync.

**HARD RULE:** Do not silently skip `needs-review` flags.

**Stage B (Builder -- worktree isolation):**
Dispatch a Builder Agent using the generation skill's two-stage execution model:
- test_policy: `"Do NOT create or modify spec-backed test files. Use existing tests for validation only. Tests marked @unslop-incidental may be updated or removed if they fail against regenerated code that correctly follows the spec."` See the generation skill's `@unslop-incidental Test Lifecycle` section for details.

**Mode selection:**
- If the managed file does not exist: Mode A (full generation).
- If `--refactor` was passed: Mode A (full generation, ignore existing structure).
- If `--incremental` was passed: emit deprecation warning `"--incremental is deprecated. Surgical mode is now the default. Use --refactor for full regeneration."` and proceed with Surgical mode.
- Otherwise: **Surgical mode** (default). The Builder receives the existing file as Compilation Target with Spec Diff and Affected Symbols context. See the generation skill's Surgical Context section.

**4. Verify result**

- If DONE with green tests: worktree merges automatically. Compute `output-hash`, update `@unslop-managed` header. Delete `.unslop/last-failure/<cache-key>.md` if it exists.
- If BLOCKED or tests fail: discard worktree, revert any staged spec update (`git checkout HEAD -- <spec_path>`). Report the Builder's failure report and stop. Do not attempt to fix or retry.

**5. Update the alignment summary**

Update `.unslop/alignment-summary.md` to record the sync under the `## Managed files` section. If the file already appears there, update its entry with the current timestamp:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.

**6. Commit**

After Builder success and worktree merge, commit atomically:
- Staged spec update (if Phase 0c ran)
- Merged generated code
- Updated alignment summary
