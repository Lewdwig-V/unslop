---
description: Regenerate all stale managed files from their specs
argument-hint: "[--force] [--force-ambiguous] [--incremental]"
---

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Load context**

Use the **unslop/generation** skill for code generation discipline throughout this command.

Read `.unslop/config.json` to obtain the test command. If `config.json` does not exist, fall back to `.unslop/config.md` (legacy format). You will need the test command when validating regenerated files.

**Check for `--force` flag:** If `$ARGUMENTS` contains `--force`, note this — it allows regeneration to proceed on modified and conflict files without requiring user confirmation.

**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When this flag is present, the generation skill's ambiguity detection (Section 0, Phase 0b) reports ambiguities as warnings instead of blocking generation.

**3. Scan for spec files**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`).

**3b. Resolve build order**

Check if any of the found spec files have `depends-on` frontmatter (look for `---` at the start of any spec file). If dependency frontmatter is found:

1. Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py build-order .` to get the full build order across all specs.
2. Process files in this order instead of arbitrary order.
3. If the orchestrator reports a cycle, stop and report the error to the user.

If no specs have `depends-on` frontmatter, or if Python is not available, process in the existing order (this preserves backwards compatibility).

**4. Classify each spec file**

For each `*.spec.md` found, derive the managed file path by stripping the trailing `.spec.md` suffix (e.g., `src/retry.py.spec.md` → `src/retry.py`).

Classify it as one of:

- **New**: the managed file does not exist yet — must be generated unconditionally.
- **Fresh**: stored spec-hash matches current spec hash AND stored output-hash matches current output hash — skip it.
- **Stale**: stored spec-hash does NOT match current spec hash AND stored output-hash matches current output hash — the spec changed but code is untouched; regenerate.
- **Modified**: stored spec-hash matches current spec hash AND stored output-hash does NOT match current output hash — the code was edited directly. Warn the user and require `--force` or explicit user confirmation before regenerating.
- **Conflict**: both hashes mismatch — spec and code both changed. Block and require `--force` or explicit user confirmation before proceeding.
- **Old format**: header is present but uses the old timestamp-based format (no `spec-hash`/`output-hash` fields) — treat as stale and regenerate.

Hash algorithm: SHA-256 of content, truncated to 12 hex characters. For spec hash: hash the full spec file content. For output hash: hash the managed file body below the `@unslop-managed` header block, stripped of leading/trailing whitespace.

For unit specs (`*.unit.spec.md`): derive managed file paths from the `## Files` section in the spec rather than the naming convention.

Report the classification of every spec file before proceeding.

**5. Process stale, new, modified, and conflict files**

For **modified** files: warn the user that the managed file has been edited directly (output hash mismatch). If `--force` was passed, proceed with regeneration. Otherwise, ask the user to confirm before overwriting their edits. If the user declines, skip this file.

For **conflict** files: warn the user that both the spec and the managed file have changed. If `--force` was passed, proceed with regeneration. Otherwise, ask the user to confirm before proceeding. If the user declines, skip this file.

For each file classified as new, stale, modified (confirmed), or conflict (confirmed), in order:

1. **Select generation mode.** Files classified as **new** always use full regeneration (Mode A) — there is no existing managed file to diff against. For **stale**, **modified**, and **conflict** files, default is full regeneration (Mode A); use incremental mode (Mode B) if the user passed `--incremental` or if the spec change is a small amendment (fewer than ~20% of spec lines changed, as estimated from the spec-hash delta). In incremental mode, read the spec AND the existing managed file.
2. Generate the managed file. The file must begin with the `@unslop-managed` header as specified by the **unslop/generation** skill. In incremental mode, produce only the targeted edits needed to bring the file into conformance with the updated spec.
3. Run the test command from `.unslop/config.json`.
4. If tests pass: report success for this file and continue to the next.
5. If tests fail: report the failure output and **stop immediately**. Do NOT attempt to fix the code, re-read the spec, or enter any convergence loop. Tell the user:

> "Tests failed after regenerating `<file>`. The spec may have introduced breaking changes. Review the failures above and update the spec or downstream code as needed."

If any file causes a stop, do not process remaining files.

If a dependency was regenerated in this run, mark its dependents as stale even if their own specs haven't changed — the dependency's implementation may have changed. If cascading regeneration of a dependent (whose own spec did not change) causes test failures, stop and report: which upstream regeneration caused the failure, which dependent broke, and the test output. Do NOT attempt to fix or converge.

**6. Update the alignment summary**

After all files have been processed without a stopping failure, update `.unslop/alignment-summary.md`:

- For each newly generated or regenerated file, ensure it appears under the `## Managed files` section. If it is already listed, update the entry to reflect the regeneration date. If it is new, add it:

```
- `<managed-file-path>` <- `<spec-file-path>` (fresh, generated <ISO8601 timestamp>)
  Intent: <one-line summary of what the spec describes>
```

Read the spec's first sentence or Purpose section to derive the intent summary.

**7. Commit**

After updating the alignment summary, commit the regenerated file(s) and the updated alignment summary.
