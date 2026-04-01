---
description: Record a change request for a managed file
argument-hint: <file-path> "description" [--tactical]
---

**Parse arguments:** `$ARGUMENTS` contains the file path, an optional description in quotes, and an optional `--tactical` flag. Extract:
- The file path: the first token that does not start with `--` and is not a quoted string.
- The description: a quoted string (single or double quotes), if present.
- The flag: `--tactical`, if present.

Strip all flags before using the path in subsequent steps.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the target file exists. If it does not exist, stop and tell the user:

> "File not found: `<file-path>`."

Read the first 5 lines of the target file (to accommodate shebangs, doctype declarations, etc.). Check whether at least one line contains `@unslop-managed`.

**If `@unslop-managed` header is found:** Extract the spec path (the path that appears after `Edit` and before `instead`). Check that the spec file exists. If it does not, stop:

> "Spec not found. The managed file references a spec that no longer exists."

**If `@unslop-managed` header is NOT found:** Check for a corresponding spec file using naming conventions:
- For file `src/foo.py`, check for `src/foo.py.spec.md`
- For file in a directory with a unit spec, check for `<dirname>.unit.spec.md`

If a spec file exists, the file is in **distilled-but-not-yet-generated** state (spec was created via `/unslop:distill` but the Builder hasn't run yet). Use this spec path and **skip hash-based classification** -- there is no header to extract hashes from. Treat the file as `pending` state and proceed directly to the change recording step. The change will amend the spec; the user runs `/unslop:sync` or `/unslop:generate` later to produce managed code with a proper header.

If no spec file exists either, stop:

> "File is not managed by unslop. Run `/unslop:takeover` or `/unslop:spec` first."

**Classify the file state** (header-present path only) using hash-based logic:
- Extract the stored `spec-hash` and `output-hash` from the `@unslop-managed` header.
- Compute the current spec hash: SHA-256 of the spec file content, truncated to 12 hex characters.
- Compute the current output hash: SHA-256 of the managed file body below the `@unslop-managed` header block, stripped of leading/trailing whitespace, truncated to 12 hex characters.
- **Conflict**: both hashes mismatch (spec changed AND code changed directly).
- **Modified**: spec-hash matches but output-hash does not (code was edited directly, spec unchanged).
- **Stale**: spec-hash mismatches but output-hash matches (spec changed, code untouched).
- **Fresh**: both hashes match.

If the file is in **conflict** state, stop and tell the user:

> "File has unresolved conflicts. Resolve with `/unslop:sync --force` before adding changes."

If the file is in **modified** state AND `--tactical` was passed, warn the user:

> "File was edited directly. The tactical change will be applied on top of direct edits. Proceed?"

Wait for explicit user confirmation before proceeding. If the user declines, stop.

**1b. Ripple check (invariant -- always runs)**

**HARD RULE:** The ripple check runs on every `/unslop:change` invocation. Do not skip it, even for tactical changes.

Call MCP tool `prunejuice_ripple_check` with `{ specPaths: ["<spec-path>"], cwd: "." }`. The spec is guaranteed to exist (Step 1 verified this).

Store the result for:
- Downstream flagging after spec mutation (Step 5c)
- Elicitation decision (Step 1c)

**1c. Elicitation decision**

Note: `/unslop:change` requires a managed file with an existing spec (Step 1 prerequisites). For creating specs from scratch, use `/unslop:elicit` directly.

**Route to `/unslop:elicit`** when ANY of these conditions hold:

1. **Vague or broad request** -- the description (from arguments or user input) does not target a single specific section, or is ambiguous about scope. Use your judgment.
2. **Multiple specs affected** -- the ripple check (Step 1b) identifies 2+ specs in the blast radius that would need mutation.
3. **Locked downstream dependent** -- any downstream spec in the ripple blast radius has `intent-approved` set to a timestamp (intent is locked). A locked downstream spec signals that the change may have already-ratified semantic consequences worth surfacing.

**Skip elicitation** when ALL of these hold:

1. Change description is concrete, narrow, and targets a single section.
2. No downstream dependents have locked intent.
3. The user passed `--tactical` (explicit fast-path).

**1d. Granularity change suggestion (heuristic)**

If the change description mentions restructuring keywords ("merge," "combine," "split," "extract," "reorganize," "consolidate," "partition"), suggest spec-layer operations:

> "This sounds like it might involve restructuring the spec layer. Did you mean to merge specs (`/unslop:absorb`) or split a spec (`/unslop:exude`) before making this change?"

This is always a suggestion, never an automatic redirect. The user can dismiss and proceed with the normal change flow. The heuristic has high false-positive rates for common words -- change never routes to absorb/exude automatically.

When elicitation is triggered, run `/unslop:elicit <target-path>` (which handles the Socratic dialogue, candidate output, approval, and downstream flagging) and then return. The change entry in `*.change.md` is NOT written -- the elicit flow writes the spec directly.

When elicitation is skipped, continue to Step 2 (the existing change flow).

**2. Check for existing changes**

Derive the sidecar path by appending `.change.md` to the managed file path (e.g., `src/retry.py` → `src/retry.py.change.md`).

If the sidecar file exists, count the number of `### ` entries in it. If there are 5 or more, warn the user:

> "This file has N pending changes. Consider running `/unslop:generate` to process them before adding more."

(Continue regardless — this is a warning, not a block.)

**3. Get the description**

If a description was provided in the arguments (the quoted string extracted above), use it verbatim.

If no description was provided, ask the user:

> "Describe the change intent for `<file-path>`:"

Wait for the user's response and use it as the description.

If the description is a single short sentence, ask: "Would you like to add more detail to this change request?" If yes, append the user's elaboration. If no, proceed.

**4. Write the entry**

Determine the status tag:
- `[tactical]` if `--tactical` was passed.
- `[pending]` otherwise.

Get the current timestamp in ISO 8601 UTC format (e.g., `2026-03-22T14:05:00Z`).

If the sidecar file does not exist, create it with the format marker as its first line:

```
<!-- unslop-changes v1 -->
```

Append the new entry to the sidecar file:

```
### [status] description -- ISO8601-UTC-timestamp

[description or elaborated body]

---
```

The `[description or elaborated body]` should be the description text as provided. Do not invent or expand the body beyond what the user provided.

**5. Execute or defer**

**If `--tactical` was passed**, execute the two-stage tactical flow immediately:

**5a. Check diagnostic cache**

Check for `.unslop/last-failure/<cache-key>.md`. If a failure report exists, surface a one-liner before proceeding:

> "Resuming from previous failure: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

Inject the failure report contents as "Previous Attempt Post-Mortem" context for the Architect in Stage A.

**Stage A (Architect -- current session):**
0. **Intent Lock (Phase 0a.0):** Draft an Intent Statement from the change description in product language: "I understand you want to [goal]. To achieve this, I'll update [spec] to [constraint]." Present to the user and wait for approval. If rejected: ask "Could you clarify the requirement? I misunderstood [X] as [Y]." and reformulate. The entry remains in `<file>.change.md` until an Intent Lock succeeds. Only proceed to step 1 after explicit approval.
1. Read the current spec, `.unslop/principles.md` (if it exists), the file tree (use Glob or LS to read the file tree), and the previous failure report (if injected from Step 5a). Do NOT read the managed source file.
2. Based on the change intent, propose a spec update that captures the change in the spec's constraints/behavior language. Do not describe implementation -- describe intent.
3. Present the draft spec update to the user for approval.

(Note: Step 0 validates "am I solving the right problem?" Step 3 validates "is this the right spec change?" These are independent gates -- see Phase 0a.0 in the generation skill.)

4. If approved: apply the spec update to the spec file, stage it (`git add <spec_path>`). Do NOT commit.
   **Changelog entry:** After writing the spec update, append both:
   1. A `spec-changelog:` frontmatter entry with the new intent-hash, current timestamp, the appropriate operation (`change-tactical` or `change-pending`), and the prior intent-hash.
   2. A `## Changelog` prose entry at the bottom of the spec body (reverse chronological -- prepend to the section) describing what changed and why.
5. If rejected: stop. The entry remains in `<file>.change.md` for manual resolution.

**Stage B (Builder -- worktree isolation):**
6. Dispatch a Builder Agent using the generation skill's two-stage execution model. Use test_policy: `"Extend tests if the spec update introduced new constraints that lack coverage. Do not modify existing assertions"`.
7. The Builder implements from the updated spec in an isolated worktree, runs tests.

**Verification (back in controlling session):**
8. If Builder succeeds (DONE, green tests):
   a. Worktree merges automatically.
   b. Compute `output-hash` on the merged code, update `@unslop-managed` header (including `spec-hash`, `output-hash`, `principles-hash`).
   c. Delete `.unslop/last-failure/<cache-key>.md` if it exists (previous failure resolved).
   d. Delete the tactical entry from `<file>.change.md` (if file is now empty, delete the sidecar entirely).
   d. Commit the spec update + generated code + sidecar change as a single atomic commit.
9. If Builder fails (BLOCKED or tests fail):
   a. Discard the worktree.
   b. Revert the staged spec update: `git checkout HEAD -- <spec_path>`.
   c. Report the Builder's failure report (failing tests, what was attempted, suspected spec gaps).
   d. The entry remains in `<file>.change.md`.

**5c. Downstream flagging (after spec mutation)**

After any spec mutation is committed (tactical Stage A approval or pending batch processing), use the ripple check result from Step 1b to flag downstream dependents:

**Depth 1 (direct dependents):** Offer to queue elicit on each.

> "Spec `<dep>` depends on the spec you just changed. Run elicit on it now? (y/n)"

If yes: run `/unslop:elicit <dep-managed-file>` in amendment mode after the current change completes.
If no: write `needs-review: <intent-hash of changed spec>` into the dependent spec's frontmatter. Stage the change.

**Depth 2+ (transitive dependents):** Write `needs-review: <intent-hash of changed spec>` into each transitive dependent's frontmatter. Stage the changes. Report:

> "N transitive dependents flagged for review."

**If `[pending]` (default, no `--tactical` flag)**, inform the user:

> "Change recorded in `<file>.change.md`. Run `/unslop:generate` or `/unslop:sync <file>` to apply."

**Batched changes (path c):** When pending changes are processed via `/unslop:generate` or `/unslop:sync`, Phase 0a.0 fires once per file with an aggregated intent statement before Phase 0c processes individual entries. See the generation skill's Phase 0a.0 section for the batched intent protocol.
