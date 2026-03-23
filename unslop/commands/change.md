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

Read the first 5 lines of the target file (to accommodate shebangs, doctype declarations, etc.). Check that at least one line contains `@unslop-managed`. If none do, stop and tell the user:

> "File is not managed by unslop. Run `/unslop:takeover` or `/unslop:spec` first."

Read the `@unslop-managed` header to extract the spec path (the path that appears after `Edit` and before `instead`). Check that the spec file exists. If it does not, stop and tell the user:

> "Spec not found. The managed file references a spec that no longer exists."

**Classify the file state** using hash-based logic:
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
1. Read the current spec, `.unslop/principles.md` (if it exists), the file tree (`python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py file-tree .`), and the previous failure report (if injected from Step 5a). Do NOT read the managed source file.
2. Based on the change intent, propose a spec update that captures the change in the spec's constraints/behavior language. Do not describe implementation -- describe intent.
3. Present the draft spec update to the user for approval.

(Note: Step 0 validates "am I solving the right problem?" Step 3 validates "is this the right spec change?" These are independent gates -- see Phase 0a.0 in the generation skill.)

4. If approved: apply the spec update to the spec file, stage it (`git add <spec_path>`). Do NOT commit.
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

**If `[pending]` (default, no `--tactical` flag)**, inform the user:

> "Change recorded in `<file>.change.md`. Run `/unslop:generate` or `/unslop:sync <file>` to apply."

**Batched changes (path c):** When pending changes are processed via `/unslop:generate` or `/unslop:sync`, Phase 0a.0 fires once per file with an aggregated intent statement before Phase 0c processes individual entries. See the generation skill's Phase 0a.0 section for the batched intent protocol.
