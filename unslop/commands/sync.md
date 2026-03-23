---
description: Regenerate one specific managed file from its spec
argument-hint: <file-path> [--force] [--force-ambiguous] [--incremental] [--deep] [--dry-run]
---

**Parse arguments:** `$ARGUMENTS` may contain the file path and optional flags. Extract the file path (the first argument that does not start with `--`) and check for flags (`--force`, `--force-ambiguous`, `--incremental`, `--deep`, `--dry-run`). Strip flags before using the path in subsequent steps.

**Check for `--force` flag:** If `$ARGUMENTS` contains `--force`, note this — it allows regeneration to proceed on modified and conflict files without requiring user confirmation.

**Check for `--deep` flag:** If `$ARGUMENTS` contains `--deep`, this sync will regenerate not just the target file but its entire downstream blast radius — all files transitively affected by the target's spec/concrete dependencies. See **Step 2d** below for the deep sync workflow.

**Check for `--dry-run` flag:** If `$ARGUMENTS` contains `--dry-run` (only meaningful with `--deep`), show the deep sync plan without regenerating any files.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Derive the spec path**

First, check if the managed file has an `@unslop-managed` header — if so, read the spec path from the header (line 1 contains the spec path after 'Edit' and before 'instead'). Otherwise, fall back to appending `.spec.md` to the filename. This supports both per-file and per-unit specs.

Check that the spec file exists. If it does not exist, stop and tell the user:

> "No spec found at `<spec-path>`. Run `/unslop:spec <file-path>` to create one first."

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When present, ambiguity detection reports warnings instead of blocking.

**2b. Check dependencies**

If the spec has `depends-on` frontmatter, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` to find transitive dependencies.

Check if any dependencies are stale or conflict (using hash-based classification: compare stored spec-hash against current spec hash; if mismatch, the dependency is stale). If so, regenerate stale dependencies first, in dependency order, before regenerating the target file.

If Python is not available and the spec has no `depends-on` frontmatter, proceed without dependency resolution (backwards compatible). If the spec has dependencies but Python is unavailable, report an error: "This spec has dependencies that require Python 3.8+ for resolution."

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
   - For each file, run the normal sync Steps 3-6 (classify, dispatch Builder, verify, update alignment, commit).
   - **Critical**: After each successful regeneration, the downstream files in the plan may now have updated concrete-manifests. This is expected — they will be regenerated in their turn.
   - If a Builder fails for any file: **stop immediately**. Report which file in the chain failed and its position in the plan. Do not process remaining files.

6. After all files in the plan are regenerated successfully, report:

```
Deep sync complete: N/N files regenerated successfully.
Build order: spec1 -> spec2 -> spec3
```

After displaying the plan or completing the deep sync, **return** — do not fall through to the single-file sync flow below.

**2c. Check diagnostic cache**

Check for `.unslop/last-failure/<cache-key>.md` where `<cache-key>` is the spec path with `/` replaced by `--`. If a failure report exists, surface a one-liner before proceeding:

> "Resuming from previous failure: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

Inject the failure report contents into the Builder's prompt via the `{previous_failure}` parameter (see generation skill).

**3. Classify and dispatch**

Classify the target file using hash-based logic (same as `/unslop:generate`):
- Compute current spec hash (SHA-256 of spec content, truncated to 12 hex) and current output hash (SHA-256 of managed file body below the header, stripped, truncated to 12 hex).
- Extract stored `spec-hash` and `output-hash` from the `@unslop-managed` header.
- **Modified** (spec-hash match, output-hash mismatch): warn the user the file was edited directly. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.
- **Conflict** (both hashes mismatch): warn that both spec and code changed. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.
- **Old format** (no hash fields in header): treat as stale and proceed.

**Stage A (Architect -- if pending changes exist):**
If a `*.change.md` sidecar exists for this file with pending entries, run the generation skill's Phase 0c (Stage A behavior):
- Propose spec updates for each entry, get user approval.
- Stage approved spec updates (`git add`). Do NOT commit.

**Stage B (Builder -- worktree isolation):**
Dispatch a Builder Agent using the generation skill's two-stage execution model:
- test_policy: `"Do NOT create or modify test files. Use existing tests for validation only"`
- If `--incremental` was passed: pass through to Builder prompt for Mode B.
- If the managed file does not yet exist: always Mode A.

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
