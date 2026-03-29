---
description: Regenerate all stale managed files from their specs
argument-hint: "[--force] [--force-ambiguous] [--force-pseudocode] [--force-strategy] [--incremental] [--refactor] [--regenerate-tests] [--dry-run]"
---

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Load context**

Use the **unslop/generation** skill for code generation discipline throughout this command.

Pending `*.change.md` entries are processed in Step 3c (Stage A) before any Builder is dispatched.

Read `.unslop/config.json` to obtain the test command. If `config.json` does not exist, fall back to `.unslop/config.md` (legacy format). You will need the test command when validating regenerated files.

**Skill loading:** Domain skills are loaded in Phase 0d of the generation skill (three-tier discovery). Skills with `enforcement: constitutional` are passed to the Saboteur alongside `principles.md` for constitutional compliance checking in Stage 3. See the generation skill's Phase 0d for the full discovery protocol.

**Check for `--force` flag:** If `$ARGUMENTS` contains `--force`, note this — it allows regeneration to proceed on modified and conflict files without requiring user confirmation.

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When this flag is present, the generation skill's ambiguity detection (Section 0, Phase 0b) reports ambiguities as warnings instead of blocking generation.

**Check for `--force-pseudocode` flag:** If `$ARGUMENTS` contains `--force-pseudocode`, note this for the generation skill. When present, pseudocode linting violations (Phase 0a.1) are reported as warnings instead of blocking generation.

**Check for `--force-strategy` flag:** If `$ARGUMENTS` contains `--force-strategy`, note this for the generation skill. When present, concrete spec strategy incoherence (Phase 0e.1) is reported as warnings instead of blocking generation.

**Check for `--regenerate-tests` flag:** If `$ARGUMENTS` contains `--regenerate-tests`, note this -- it forces Mason (Stage 1) to regenerate tests even when existing tests are present for a managed file.

**Check for `--dry-run` flag:** If `$ARGUMENTS` contains `--dry-run`, perform a ripple-effect analysis instead of generating code. This shows the user exactly what would happen -- which specs, concrete specs, and managed files would be affected -- without spawning any worktrees or modifying any files. See Step 4b below.

**Check for unrecognised positional arguments:** After extracting all recognised flags, check for remaining non-flag tokens in `$ARGUMENTS` (tokens not starting with `--`). If any remain, stop:

> "`/unslop:generate` operates project-wide and does not accept file paths. To regenerate a single file, use `/unslop:sync <file-path>`. To regenerate only stale files, use `/unslop:generate` with no path argument."

**2b. Check diagnostic cache**

For each spec file found, check for `.unslop/last-failure/<cache-key>.md`. If any failure reports exist, surface a one-liner for each before proceeding:

> "Resuming from previous failure for `<spec-path>`: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

Inject the failure report contents into the corresponding Builder's prompt via the `{previous_failure}` parameter (see generation skill).

**3. Scan for spec files**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`).

**3b. Resolve build order**

**Preferred:** If available, use MCP tools (`unslop_check_freshness`, `unslop_build_order`, `unslop_ripple_check`) instead of shelling out to `orchestrator.py`. Fall back to CLI if MCP is not available.

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

**4c. Check for `needs-review` flags**

For each spec file classified as stale, modified, or conflict (i.e., files that will be regenerated), read the spec's frontmatter and check for a `needs-review` field.

**Preferred:** If the MCP server is running and `check_freshness` was used, the `needs_review` field is already in the freshness output. Otherwise read the spec and call `parse_needs_review`.

For each spec with `needs-review`, present:

```
⚠ Spec `<spec-path>` is flagged needs-review.
  Upstream spec changed (intent-hash: <hash>).

  (a) Acknowledge and proceed -- I've verified this change doesn't affect <managed-file>
  (b) Open elicit to review the impact
  (q) Abort generation
```

**Option (a):** Write `review-acknowledged: <needs-review-hash>` into the spec's frontmatter. Remove the `needs-review` field. Stage the spec change (`git add`). Continue with generation.

**Option (b):** Route to `/unslop:elicit <managed-file>` in amendment mode. After elicit completes, the spec will have been updated (which removes `needs-review`). Re-classify and continue.

**Option (q):** Stop generation. The flag remains. No files are modified.

If multiple specs have `needs-review`, present them one at a time. If the user chooses (q) on any, stop entirely.

**HARD RULE:** Do not silently skip `needs-review` flags. The user MUST explicitly acknowledge or address each one before generation proceeds.

**4d. Check for structural mismatches**

For each spec that will be processed, check if the managed file exists. If the managed file does not exist:

1. Check the spec's frontmatter for provenance fields (`distilled-from:`, `absorbed-from:`, `exuded-from:`). **Do not check `provenance-history:` -- it is an audit log, not an active signal.**
2. **If provenance present (structural mismatch):** Hard block. Stop generation for this file with:

```
Cannot generate: managed file `<path>` does not exist.
  Spec has active provenance indicating a lifecycle in progress.

  If this file was merged into another module, use `/unslop:absorb`.
  If this file was moved, update the spec's managed file reference.
  If this file was deleted, remove the spec.
```

This is NOT a soft-block. Do not offer acknowledge/proceed options. The precondition (managed file exists) is not met.

3. **If no provenance (pending state):** The spec describes intent for a file that doesn't exist yet. This is a valid generate target -- the Builder will create the file. Proceed with generation.

**HARD RULE:** Structural mismatches are precondition failures, not review concerns. Generate must not proceed on a spec whose managed file disappeared unexpectedly (indicated by active provenance on the spec).

**5. Dispatch pipeline (four-stage)**

For each file classified as new, stale, modified (confirmed), or conflict (confirmed), in build order:

**5a. Stage 0: Archaeologist -- Spec Projection**

Dispatch an Archaeologist subagent to produce the concrete spec and behaviour specification in a single pass. The Archaeologist replaces the former Strategist role.

- **Input:** abstract spec (including any `non-goals:` and `rejected:` frontmatter), `.unslop/principles.md` (if present), file tree context
- **Output:** concrete spec + `behaviour.yaml` (written as sidecar next to the spec, e.g. `src/retry.py.behaviour.yaml`)
- **Rejected alternatives:** If the abstract spec contains `rejected:`, the Archaeologist reads each entry before choosing an implementation strategy. If the Archaeologist's preferred strategy aligns with a rejected entry, it must surface this as a `discovered:` item: "The most natural implementation strategy aligns with a previously rejected approach: [title]. Rationale for rejection was: [rationale]. Should I proceed differently?"
- **Non-goals projection:** If the abstract spec contains `non-goals:`, the Archaeologist:
  1. Projects each non-goal into `behaviour.yaml` as a negative constraint (invariant asserting the behaviour is NOT present, prefixed `MUST NOT`)
  2. Projects each non-goal into the concrete spec as an explicit exclusion under a `## Exclusions` section
- **Model:** `config.models.archaeologist`
- **Note:** The Archaeologist reads the abstract spec, NOT source code. Source reading is for distill mode only.
- **Pending specs:** When processing a spec in `pending` state (no existing implementation), the Archaeologist skips the existing-code read entirely and projects from the abstract spec alone. The discovery gate (Stage 0b) is especially important for pending specs -- it catches correctness requirements the spec didn't anticipate, without the safety net of existing code.

**5b. Stage 0b: Discovery Gate (conditional)**

If the Archaeologist produced `discovered:` entries during Stage 0, generate pauses before proceeding to Mason.

For each discovery, present:

```
⚠ Archaeologist discovery: [title]
  [observation]
  [question]

  (p) Promote to abstract spec -- add this constraint
  (d) Dismiss -- proceed without this constraint
```

**If promoted:** Update the abstract spec body with the new constraint. Set `intent-approved: false`. Recompute `intent-hash`. Stage the spec change (`git add`).

**If dismissed:** Remove the `discovered:` entry. The concrete spec must not encode the dismissed constraint.

**After all discoveries are resolved:**
- If any were promoted: the abstract spec has changed. Re-run Stage 0 (Archaeologist) with the updated spec to produce a consistent concrete spec + behaviour.yaml. The re-run will not produce new discoveries for constraints that were just promoted (they're now in the spec).
- If all were dismissed (or no discoveries existed): proceed to Stage 1.

**HARD RULE:** Discovered constraints flow back through the abstract spec via explicit user approval. The concrete spec is never a ratification path for abstract spec changes. If the Archaeologist finds a correctness requirement the abstract spec doesn't cover, it must surface via `discovered:` -- never silently absorbed into the concrete spec.

**5b-1. Phase 0f: Sprint Contract (Re-Generates Only)**

If the managed file exists and has an `@unslop-managed` header with a `spec-hash` that differs from the current spec hash, negotiate a sprint contract:

1. **Architect** reads the spec diff and writes expected outcomes (normative -- what should change, what should remain invariant). See the generation skill's Phase 0f.
2. **Saboteur** reads the expected outcomes and writes a verification strategy (operational -- how each outcome will be verified, with explicit unverifiable-gaps). See the generation skill's Phase 0f.
3. Write the contract as `<managed-file>.contract.yaml` next to the spec file.

If the managed file does not exist (new file) or the spec hash matches (fresh), skip Phase 0f.

The contract is consumed by the Saboteur in Stage 3 (Step 5e) and deleted on successful verification.

**5c. Stage 1: Mason -- Test Derivation (conditional)**

Derive the expected test file path from project conventions (e.g. `src/retry.py` -> `tests/test_retry.py`).

- **If tests exist AND `--regenerate-tests` was NOT passed:** Skip Stage 1. The Builder will use existing tests for validation.
- **If no tests exist OR `--regenerate-tests` was passed:** Dispatch a Mason subagent in a worktree:
  - **Input:** `behaviour.yaml` ONLY.
  - **HARD RULE:** Mason NEVER sees the abstract spec, concrete spec, or source code. Chinese Wall -- behaviour.yaml is the sole input. This ensures tests are derived purely from observable behaviour, not implementation details.
  - **Output:** test file with `@unslop-managed` header containing `spec-hash` (hash of the **abstract spec**, not behaviour.yaml -- this ensures status/weed drift checks compare tests against the same spec hash used for code files) and `generated` timestamp
  - **Model:** `config.models.mason`
  - **Isolation:** worktree (merge test file on success)

**5d. Stage 2: Code Implementation (Builder)**

Select generation mode and dispatch the Builder:

1. **Select generation mode:**
   - New file (no existing code): Mode A (full generation).
   - `--refactor` flag: Mode A (full generation, ignore existing structure).
   - `--incremental` flag: emit deprecation warning `"--incremental is deprecated. Surgical mode is now the default. Use --refactor for full regeneration."` and proceed with Surgical mode.
   - Otherwise: **Surgical mode** (default). See the generation skill's Surgical Context section.
2. **Dispatch a Builder Agent** using the generation skill's execution model:
   - The Builder receives the concrete spec from Stage 0 (Archaeologist output).
   - If Stage 1 produced a test file, the Builder receives it as additional validation input.
   - test_policy: `"Do NOT create or modify spec-backed test files. Use existing tests for validation only. Tests marked @unslop-incidental may be updated or removed if they fail against regenerated code that correctly follows the spec."`
   - For Surgical mode: include Existing Code, Spec Diff, and Affected Symbols context blocks.
   - If the concrete spec has `protected-regions`: the Builder MUST preserve these regions verbatim. Extract the protected region before generation, append it unchanged after generation, and write `managed-end-line` in the header to mark where the protected region starts. After the Builder completes, the Architect MUST verify the protected region hash matches before accepting the worktree. See the generation skill's protected-regions protocol.
   - If the concrete spec has `blocked-by` entries: the Builder treats each as an explicit deviation permit. Proceed normally with unblocked constraints. Add a code comment at each deviation site using the target language's comment syntax: `blocked-by: <symbol> -- <reason>`. **HARD RULE:** The Builder MUST NOT deviate on any constraint not explicitly listed in `blocked-by`. The `blocked-by` list is exhaustive -- unlisted constraints are fully binding.
   - If the concrete spec has `targets` (instead of `target-language`): generation dispatches parallel Builders -- one per target. Each Builder receives the same Abstract Spec, `## Strategy`, and `## Type Sketch`, but gets target-specific `## Lowering Notes` and `targets[].notes`. **HARD RULE:** All Builders MUST succeed for the merge to proceed -- if any Builder fails, all worktrees are discarded. Partial merges (some targets succeed, some fail) MUST NOT proceed. See the `unslop/concrete-spec` skill for multi-target syntax and the `unslop/generation` skill for dispatch mechanics.
3. **Verify result:**
   - If DONE with green tests: worktree merges automatically. Compute `output-hash`, update header.
   - If BLOCKED or tests fail: discard worktree, revert ALL staged spec updates from Step 3c (`git checkout HEAD -- <spec_path>` for every spec that was staged), not just the failing file's spec. Report failure and **stop immediately**. Do not process remaining files.
4. If a dependency was regenerated in this run, mark its dependents as stale even if their own specs haven't changed.

If cascading regeneration of a dependent causes Builder failure, stop and report: which upstream regeneration caused the failure, which dependent broke, and the Builder's failure report.

**5e. Stage 3: Async Verification (Saboteur)**

After the Builder succeeds and the worktree merges, dispatch the Saboteur in the background with `isolation: "worktree"`. **HARD RULE:** Generate returns immediately after Builder success. The Saboteur does NOT block. **HARD RULE:** The Saboteur MUST run in a worktree. Mutations are applied in the worktree copy, never in the main working tree. The worktree is discarded after verification.

- **Input:** abstract spec + source file (post-merge) + test file
- **Timeout:** `config.verification_timeout` (default: 300s)
- **Output:** Write result to `.unslop/verification/<managed-file-hash>.json`. The schema is shared with `/unslop:verify`:
  ```json
  {
    "managed_path": "<managed-file-path>",
    "spec_path": "<spec-file-path>",
    "timestamp": "<ISO8601>",
    "status": "pass|fail|error|timeout",
    "mutants_total": 0,
    "mutants_killed": 0,
    "mutants_survived": 0,
    "mutants_equivalent": 0,
    "mutants_errored": 0,
    "source_hash": "<12-hex>",
    "spec_hash": "<12-hex>",
    "surviving_mutants": [],
    "constitutional_violations": [],
    "edge_case_findings": [],
    "contract_compliance": null,
    "error_message": null
  }
  ```
- **Failure modes:**
  - Saboteur crashes -> `{"status": "error", "error_message": "...", ...}`
  - Saboteur exceeds timeout -> `{"status": "timeout", "error_message": "exceeded verification_timeout", ...}`
  - Source or spec changed during run: detectable by comparing `source_hash`/`spec_hash` in the result against current file hashes. Status shows `(stale)` annotation but the result file itself uses the terminal status (pass/fail/error/timeout).
- The Saboteur uses the adversarial pipeline (Archaeologist -> Mason -> Saboteur from the adversarial skill) to run mutation testing against the generated code.
- **Constitutional compliance.** After mutation testing, if `.unslop/principles.md` exists, the Saboteur checks whether the generated code violates any principle. This is LLM-native analysis -- principles are natural language, violations require judgment. Each violation is recorded as `{"principle": "<text>", "location": "<file:lines>", "violation": "<what code does>", "required": "<what principle requires>"}` in the `constitutional_violations` array. Constitutional violations cause `status: "fail"` even if all mutants were killed.
- **Edge case probing.** After constitutional checking, the Saboteur probes the code's attack surface for edge cases the spec didn't anticipate. Generates adversarial inputs (boundary values, malformed data, null/empty/oversized inputs) and assesses graceful handling vs silent failure. Budget: `config.edge_case_budget` findings (default: 10), severity-ranked (silent data corruption > unhandled exception > resource leak > unexpected behaviour). Each finding: `{"input": "<desc>", "expected": "<expected>", "actual": "<actual>", "severity": "<level>", "spec_gap": true|false}` in the `edge_case_findings` array. Edge case findings are **informational only** -- they do NOT affect `status` and do NOT block anything.
- **Contract cleanup.** The Saboteur runs in a worktree and cannot delete files from the main tree. After the Saboteur completes and writes its verification JSON to `.unslop/verification/`, the controlling command (generate or sync) checks the result status. If `status: "pass"` and a `<managed-file>.contract.yaml` sidecar exists, the controlling command deletes it from the main tree. This is a main-tree operation, not a worktree operation.

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
