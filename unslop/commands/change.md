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

Read the first line of the target file. Check that it contains an `@unslop-managed` header. If it does not, stop and tell the user:

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

**If `--tactical` was passed**, execute the tactical flow immediately:

1. Read the current spec file and the current managed file.
2. Use the **unslop/generation** skill in incremental mode (Mode B) to patch the managed file based on the change intent. Produce only the targeted edits needed to implement the described change.
3. Read the test command from `.unslop/config.json` (or `.unslop/config.md` as legacy fallback). Run the test suite.
4. If tests pass:
   a. Draft a spec update that captures the change — describe what was changed in the spec's intent/constraints language, not in implementation terms.
   b. Present the draft spec update to the user for approval.
   c. If the user approves: delete the entry from `<file>.change.md` (if the file is now empty after deletion — containing only the format marker or nothing — delete the sidecar file entirely). Update the `spec-hash` and `output-hash` in the `@unslop-managed` header to reflect the new state. Commit the managed file, spec update, and sidecar deletion/update.
   d. If the user rejects the spec update: revert the code change to its pre-tactical state, inform the user:
   > "Code change reverted. The entry remains in `<file>.change.md` for manual resolution."
5. If tests fail: report the failures and stop. Do not attempt to fix or retry. Tell the user:
   > "Tests failed after applying the tactical change. The spec and code are unchanged. The entry remains in `<file>.change.md`."

**If `[pending]` (default, no `--tactical` flag)**, inform the user:

> "Change recorded in `<file>.change.md`. Run `/unslop:generate` or `/unslop:sync <file>` to apply."
