# Command Scope Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make harden, adversarial, cover, and verify handle unit specs via per-file loops, and make generate reject accidental positional args.

**Architecture:** Pure markdown command file edits. Each command gains the three-way argument resolution convention (file/directory/spec-path) already established by takeover and spec. Unit specs trigger a per-file loop over `## Files`. No Python code changes.

**Tech Stack:** Markdown command files, plugin.json version bump.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `unslop/commands/harden.md` | Modify | Add three-way arg resolution |
| `unslop/commands/adversarial.md` | Modify | Add three-way arg resolution + per-file loop |
| `unslop/commands/cover.md` | Modify | Replace limitation notice with per-file loop |
| `unslop/commands/verify.md` | Modify | Replace limitation notice with per-file loop + unit spec resolution |
| `unslop/commands/generate.md` | Modify | Add positional arg rejection |
| `unslop/.claude-plugin/plugin.json` | Modify | Version bumps |

---

## PR 1: Scope resolution (v0.45.0)

### Task 1: harden.md -- three-way argument resolution

**Files:**
- Modify: `unslop/commands/harden.md:1-6`

- [ ] **Step 1: Update the argument-hint in frontmatter**

Change line 3 from:

```markdown
argument-hint: "<spec-path> [--promote]"
```

to:

```markdown
argument-hint: "<spec-or-directory-path> [--promote]"
```

- [ ] **Step 2: Replace the "Parse arguments" paragraph**

Replace the current argument parsing block (line 6):

```markdown
**Parse arguments:** `$ARGUMENTS` is the path to the spec file (e.g., `src/retry.py.spec.md`). Strip any flags before using the path.
```

with:

```markdown
**Parse arguments:** Extract the first non-flag token from `$ARGUMENTS` as the target path. Strip flags (`--promote`) before using the path.

**Resolve target:**

- If the target ends in `.spec.md`: use as-is (spec path). Example: `src/retry.py.spec.md`
- If the target is a directory: look for `<dirname>.unit.spec.md` inside it. Example: `src/auth/` resolves to `src/auth/auth.unit.spec.md`. If the unit spec does not exist, stop:

  > "No unit spec found at `<dir>/<dirname>.unit.spec.md`. If you meant to run on individual file specs, pass them explicitly."

- Otherwise: treat as a managed file path and append `.spec.md`. Example: `src/retry.py` resolves to `src/retry.py.spec.md`. If the spec does not exist, stop:

  > "No spec found at `<path>.spec.md`."
```

- [ ] **Step 3: Verify the rest of the body still works**

Read through Steps 1-6 of harden.md. Confirm:
- Step 1 (verify prerequisites) checks the resolved spec path -- still correct.
- Step 2 (find managed files) already handles both per-file and unit specs via `## Files` -- no change needed.
- Steps 3-6 operate on the resolved spec and managed files -- no change needed.

- [ ] **Step 4: Commit**

```bash
git add unslop/commands/harden.md
git commit -m "fix(harden): add three-way argument resolution for directory and file inputs"
```

---

### Task 2: adversarial.md -- three-way argument resolution + per-file loop

**Files:**
- Modify: `unslop/commands/adversarial.md:1-19`

- [ ] **Step 1: Update the argument-hint in frontmatter**

Change line 3 from:

```markdown
argument-hint: "<spec-path> [--phase archaeologist|mason|saboteur] [--dry-run]"
```

to:

```markdown
argument-hint: "<spec-or-directory-path> [--phase archaeologist|mason|saboteur] [--dry-run]"
```

- [ ] **Step 2: Replace the "Parse arguments" paragraph**

Replace the current argument parsing block (lines 6-8):

```markdown
**Parse arguments:** `$ARGUMENTS` is the path to the spec file (e.g., `src/retry.py.spec.md`). Optional flags:
- `--phase <name>`: Run only a specific phase (archaeologist, mason, or saboteur)
- `--dry-run`: Show what would happen without writing files
```

with:

```markdown
**Parse arguments:** Extract the first non-flag token from `$ARGUMENTS` as the target path. Optional flags:
- `--phase <name>`: Run only a specific phase (archaeologist, mason, or saboteur)
- `--dry-run`: Show what would happen without writing files

**Resolve target:**

- If the target ends in `.spec.md`: use as-is (spec path). Example: `src/retry.py.spec.md`
- If the target is a directory: look for `<dirname>.unit.spec.md` inside it. Example: `src/auth/` resolves to `src/auth/auth.unit.spec.md`. If the unit spec does not exist, stop:

  > "No unit spec found at `<dir>/<dirname>.unit.spec.md`. If you meant to run on individual file specs, pass them explicitly."

- Otherwise: treat as a managed file path and append `.spec.md`. Example: `src/retry.py` resolves to `src/retry.py.spec.md`. If the spec does not exist, stop:

  > "No spec found at `<path>.spec.md`."
```

- [ ] **Step 3: Add unit spec per-file loop to Step 1**

After the existing Step 1 prerequisite checks (lines 10-19), insert a new section between Step 1 and Step 2. Replace the current managed file derivation paragraph (line 16: "Check that the spec file exists. Derive the managed file path by stripping `.spec.md`."):

```markdown
Check that the resolved spec file exists. Derive managed file path(s):

- For per-file specs (`*.spec.md` but not `*.unit.spec.md`): strip `.spec.md` to get the managed file path (e.g., `src/retry.py.spec.md` --> `src/retry.py`).
- For unit specs (`*.unit.spec.md`): read the `## Files` section and resolve all listed file paths relative to the spec's directory.

Check that all derived managed file paths exist. If not:

> "No generated file found for this spec. Run `/unslop:generate` first."

**Unit spec dispatch:** If the resolved spec is a unit spec, run Steps 2-5 independently for each managed file (using the file's per-file spec if it exists, otherwise using the unit spec). After all files complete, present an aggregated summary in Step 5:

> "Adversarial quality report for unit `<unit-spec-path>`:
>
> `<file-1>`: P mutations, Q killed (X%) -- PASS/NEEDS WORK
> `<file-2>`: P mutations, Q killed (X%) -- PASS/NEEDS WORK
> ...
>
> Unit verdict: [PASS if all files pass | NEEDS WORK otherwise]"

Auto-convergence (Step 6) runs per-file, not across the unit.
```

- [ ] **Step 4: Verify pipeline steps are unit-loop safe**

Read Steps 2-6. Confirm each step operates on a single managed file + spec pair and does not assume singleton state. Check:
- Step 2 (Archaeologist): reads one spec + one managed file -- safe in a loop.
- Step 3 (Mason): reads one `behaviour.yaml` -- safe.
- Step 4 (Saboteur): mutates one source file in a worktree -- safe.
- Step 5 (results): presents per-file results -- safe (aggregated at unit level above).
- Step 6 (auto-convergence): per-file iteration tracking -- safe.

- [ ] **Step 5: Commit**

```bash
git add unslop/commands/adversarial.md
git commit -m "fix(adversarial): add three-way arg resolution and per-file loop for unit specs"
```

---

### Task 3: cover.md -- replace limitation notice with per-file loop

**Files:**
- Modify: `unslop/commands/cover.md:18-19`

- [ ] **Step 1: Replace the limitation notice**

Replace the current limitation notice (lines 18-19):

```markdown
> **Limitation:** Unit spec targets (directories) are not yet fully supported. Cover operates on each file within the unit independently -- it does not yet have a unit-aware mutation or test discovery model. The per-file pipeline (Saboteur -> Archaeologist -> Mason -> Validator) runs for each file in the unit, but cross-file mutation strategies and shared test suites are not yet handled.
```

with:

```markdown
**Unit spec dispatch:** If the resolved target is a unit spec (ends in `.unit.spec.md`), read the `## Files` section and resolve all listed file paths relative to the spec's directory.

For each managed file, run Steps 0-7 independently using the file's per-file spec if it exists, otherwise using the unit spec. The Architect SHOULD maximize parallelism across independent files -- dispatch the next file's Saboteur while the current file's Mason is running.

After all files complete, present an aggregated triage summary:

> "Cover results for unit `<unit-spec-path>`:
>
> `<file-1>`: N gaps found, M promoted to spec
> `<file-2>`: N gaps found, M promoted to spec
> ...
>
> Total: X gaps found across Y files, Z promoted to spec."

Atomic commit (Step 7) covers all files in the unit together.
```

- [ ] **Step 2: Verify prerequisite checks handle unit scope**

Read Step 0 (verify prerequisites, lines 79-93). It checks for `@unslop-managed` header and test files on a single file. When running the per-file loop, these checks run per-file inside the loop, not on the directory. Confirm the existing argument resolution (lines 13-16) correctly resolves directories to unit spec paths before Step 0 runs.

Current resolution (lines 13-16) already does this:
```markdown
- If the target is a directory: look for `<dirname>.unit.spec.md` inside it.
```

Step 0 starts with "Check that the managed file exists" -- in the unit loop, this applies to each file from `## Files`. No change needed to Step 0 itself; the per-file loop dispatches Step 0 per file.

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/cover.md
git commit -m "fix(cover): replace limitation notice with per-file loop for unit specs"
```

---

### Task 4: verify.md -- replace limitation notice with per-file loop + unit resolution

**Files:**
- Modify: `unslop/commands/verify.md:6-44`

- [ ] **Step 1: Replace the limitation notice**

Replace the current limitation notice (lines 43-44):

```markdown
> **Limitation:** Unit spec targets (directories) are not yet fully supported. Verify operates on each file spec within the unit independently -- it does not yet have a unit-aware verification model. Spec resolution and test discovery work, but mutation testing, constitutional compliance, and edge case probing run per-file rather than across the unit boundary.
```

with:

```markdown
**Unit spec dispatch:** If the resolved spec is a unit spec (ends in `.unit.spec.md`), read the `## Files` section and resolve all listed file paths relative to the spec's directory.

For each managed file:
- Derive its per-file spec path (`<file>.spec.md`). If no per-file spec exists but the file is listed in the unit spec's `## Files`, use the unit spec as the spec source for that file.
- Derive test file path(s) using the standard conventions from Step 1.
- Run Steps 2-5 (load context, dispatch Saboteur, report, write result) independently.

After all files complete, present an aggregated report:

> "Verification results for unit `<unit-spec-path>`:
>
> `<file-1>`: N/M mutants killed, K equivalent -- PASS/FAIL
> `<file-2>`: N/M mutants killed, K equivalent -- PASS/FAIL
> ...
>
> Unit verdict: [PASS if all files pass | FAIL otherwise]"

Each file gets its own `.unslop/verification/<hash>.json` result file.
```

- [ ] **Step 2: Update Step 1 prerequisite checks for directory targets**

The current Step 1 (lines 6-42) has this flow:
1. Check `.unslop/` exists
2. Check target file exists
3. Check for `@unslop-managed` header in first 10 lines
4. Resolve spec path (file vs directory)
5. Derive test file path

When the target is a directory, steps 2-3 don't apply (can't check a directory for a file header). Update the flow after the argument parsing (line 6) by modifying the existing spec resolution block (lines 25-27):

Replace:

```markdown
Resolve the spec path:
- If the target is a file: check for `<file-path>.spec.md`.
- If the target is a directory: check for `<dirname>.unit.spec.md` inside the directory.
```

with:

```markdown
Resolve the spec path:
- If the target is a file: check for `@unslop-managed` header in the first 10 lines. If absent, stop: "This file is not under spec management. Use `/unslop:takeover` first." Then check for `<file-path>.spec.md`.
- If the target is a directory: check for `<dirname>.unit.spec.md` inside the directory. Skip the file-existence and `@unslop-managed` header checks -- these run per-file inside the unit loop.
```

And remove the standalone `@unslop-managed` header check (lines 18-22) since it's now part of the spec resolution block:

```markdown
Read the first 10 lines of the file and check for an `@unslop-managed` header. If the header is absent, stop and tell the user:

> "This file is not under spec management. Use `/unslop:takeover` first."
```

Replace with:

```markdown
If the target is a file, read the first 10 lines and check for an `@unslop-managed` header. If the header is absent, stop and tell the user:

> "This file is not under spec management. Use `/unslop:takeover` first."

If the target is a directory, skip this check -- it runs per-file inside the unit loop.
```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/verify.md
git commit -m "fix(verify): replace limitation notice with per-file loop for unit specs"
```

---

### Task 5: Bump version + regression test + PR

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Bump plugin version**

In `unslop/.claude-plugin/plugin.json`, change line 3 from:

```json
  "version": "0.44.0",
```

to:

```json
  "version": "0.45.0",
```

- [ ] **Step 2: Run regression tests**

```bash
python -m pytest tests/test_orchestrator.py -q
```

Expected: 405 passed. These are command-file-only changes so no test breakage expected, but confirm the orchestrator's spec/command parsing still works.

- [ ] **Step 3: Commit version bump**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump version to 0.45.0 for scope resolution fix"
```

- [ ] **Step 4: Create PR**

```bash
gh pr create --title "fix: per-file loop for unit specs in harden/adversarial/cover/verify (v0.45.0)" --body "$(cat <<'EOF'
## Summary

- harden, adversarial: add three-way argument resolution (file/directory/spec-path)
- adversarial: add per-file loop dispatching Steps 2-5 for each file in a unit spec
- cover, verify: replace limitation notices with actual per-file loop logic
- verify: handle directory targets correctly in prerequisite checks

Follows the convention established by takeover, cover, spec, verify, and weed in PR #83.

Refs #82

## Test plan

- [ ] Run `python -m pytest tests/test_orchestrator.py -q` -- 405 pass, no regressions
- [ ] Pass a directory to `/unslop:harden` -- resolves to unit spec or errors with clear message
- [ ] Pass a directory to `/unslop:adversarial` -- resolves to unit spec, runs per-file pipeline
- [ ] Pass a directory to `/unslop:cover` -- runs per-file loop instead of showing limitation notice
- [ ] Pass a directory to `/unslop:verify` -- runs per-file loop instead of showing limitation notice
- [ ] Pass a nonexistent directory to any command -- errors with "No unit spec found" message

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR 2: Reject positional args in generate (v0.46.0)

### Task 6: generate.md -- add positional arg rejection

**Files:**
- Modify: `unslop/commands/generate.md:6-32`

- [ ] **Step 1: Add positional arg rejection after flag parsing**

The current flag parsing runs from lines 6-32 (a series of "Check for `--flag`" paragraphs). After the last flag check (line 32, `--dry-run`), insert:

```markdown
**Check for unrecognised positional arguments:** After extracting all recognised flags, check for remaining non-flag tokens in `$ARGUMENTS` (tokens not starting with `--`). If any remain, stop:

> "`/unslop:generate` operates project-wide and does not accept file paths. To regenerate a single file, use `/unslop:sync <file-path>`. To regenerate only stale files, use `/unslop:generate` with no path argument."
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "fix(generate): reject unrecognised positional arguments instead of silently ignoring them"
```

---

### Task 7: Bump version + regression test + PR

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Bump plugin version**

In `unslop/.claude-plugin/plugin.json`, change line 3 from:

```json
  "version": "0.45.0",
```

to:

```json
  "version": "0.46.0",
```

- [ ] **Step 2: Run regression tests**

```bash
python -m pytest tests/test_orchestrator.py -q
```

Expected: 405 passed.

- [ ] **Step 3: Commit version bump**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump version to 0.46.0 for generate arg rejection fix"
```

- [ ] **Step 4: Create PR**

```bash
gh pr create --title "fix: reject positional args in generate with helpful redirect (v0.46.0)" --body "$(cat <<'EOF'
## Summary

- generate: reject unrecognised positional arguments instead of silently ignoring them
- Error message redirects users to `/unslop:sync` for single-file regeneration

Completes the scope inconsistency fixes from #82.

Closes #82

## Test plan

- [ ] Run `python -m pytest tests/test_orchestrator.py -q` -- 405 pass, no regressions
- [ ] Run `/unslop:generate` with no args -- works as before (project-wide scan)
- [ ] Run `/unslop:generate src/file.py` -- stops with error message pointing to `/unslop:sync`
- [ ] Run `/unslop:generate --force` -- works as before (flag-only)
- [ ] Run `/unslop:generate src/file.py --force` -- stops with error (positional arg detected before flags processed)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
