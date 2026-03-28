# Command Scope Consistency -- Design Spec

Resolves: https://github.com/Lewdwig-V/unslop/issues/82

## Problem

Five commands have scope inconsistencies between what their argument hints advertise, what their bodies implement, and what the established convention is. PR #83 (v0.43.0) fixed five commands (takeover, cover, spec, verify, weed) with directory resolution and limitation notices. This design completes the fix by:

1. Replacing limitation notices in cover and verify with actual per-file loop logic
2. Adding directory/unit-spec resolution to harden and adversarial
3. Making generate reject unrecognised positional arguments instead of silently ignoring them

## Out of scope

- **Unsurfaced skill capabilities** (generation multi-target lowering, adversarial takeover mode, concrete-spec `protected-regions`/`blocked-by` fields). These are missing interfaces, not scope inconsistencies. Tracked separately.
- **Unit-aware pipelines** (`--integrated` flag, cross-file mutation strategies). Phase 2 work per the design resolution on #82. These commands operate per-file for now.

## Convention

All commands that target managed files accept three input forms:

```
<file-path>           -- single file (per-file spec)
<directory-path>      -- auto-resolve to <dirname>.unit.spec.md inside it
<spec-path>           -- use as-is (ends in .spec.md)
```

When a directory is passed and no `<dirname>.unit.spec.md` exists inside it, the command stops with:

> "No unit spec found at `<dir>/<dirname>.unit.spec.md`. If you meant to run on individual file specs, pass them explicitly."

For unit specs, the command reads `## Files` to get all managed file paths and runs the pipeline on each file independently (per-file loop). Results are aggregated.

Commands that are genuinely file-only (`change`) document why.

---

## PR 1: Scope resolution -- per-file loop for unit specs (v0.45.0)

### Files changed

- `unslop/commands/harden.md`
- `unslop/commands/adversarial.md`
- `unslop/commands/cover.md`
- `unslop/commands/verify.md`
- `unslop/.claude-plugin/plugin.json`

### harden.md

**Current state:** Hint says `<spec-path> [--promote]`. Body Step 2 already handles unit specs (reads `## Files`), but argument parsing only accepts literal spec paths. No directory resolution. No managed-file-path derivation.

**Changes:**

1. **Hint:** `<spec-path> [--promote]` --> `<spec-or-directory-path> [--promote]`

2. **Argument resolution** (replace current "Parse arguments" paragraph): Add three-way resolution before Step 1:

```
Parse the first non-flag token from $ARGUMENTS as the target path.

Resolve target:
- If target ends in `.spec.md`: use as-is (spec path).
- If target is a directory: look for `<dirname>.unit.spec.md` inside it.
  If not found, stop: "No unit spec found at `<dir>/<dirname>.unit.spec.md`.
  If you meant to run on individual file specs, pass them explicitly."
- Otherwise: treat as managed file path, append `.spec.md` for spec path.
  If spec does not exist, stop: "No spec found at `<path>.spec.md`."
```

No other body changes needed -- Step 2 already handles both per-file and unit specs correctly.

### adversarial.md

**Current state:** Hint says `<spec-path> [--phase ...] [--dry-run]`. Body only handles per-file specs (Step 1 strips `.spec.md` to get one managed file). No directory or unit spec handling.

**Changes:**

1. **Hint:** `<spec-path> [--phase ...] [--dry-run]` --> `<spec-or-directory-path> [--phase ...] [--dry-run]`

2. **Argument resolution** (replace current "Parse arguments" paragraph): Same three-way resolution as harden.

3. **Step 1 -- unit spec handling:** After resolving the spec path, add unit spec detection:

```
If the resolved spec is a unit spec (ends in `.unit.spec.md`):
  Read the `## Files` section. Resolve all listed file paths relative
  to the spec's directory.

  For each managed file:
    Derive its per-file spec path (<file>.spec.md).
    Run Steps 2-5 (Archaeologist, Mason, Saboteur) independently.

  After all files complete, present an aggregated summary in Step 5
  combining all per-file results:

    "Adversarial quality report for unit `<unit-spec-path>`:

    <file-1>: P mutations, Q killed (X%) -- PASS/NEEDS WORK
    <file-2>: P mutations, Q killed (X%) -- PASS/NEEDS WORK
    ...

    Unit verdict: [PASS if all files pass | NEEDS WORK otherwise]"

  Auto-convergence (Step 6) runs per-file, not across the unit.
```

4. **Step 1 -- managed file derivation for per-file specs:** Keep existing logic (strip `.spec.md`), but add the managed-file-path input case: if the resolved target was a managed file path (not ending in `.spec.md`), the spec was already derived in argument resolution.

### cover.md

**Current state:** Hint says `<managed-file-or-spec-or-directory> [--budget N] [--exhaustive]`. Has directory resolution. Has a limitation notice saying unit specs aren't fully supported. Pipeline runs per-file but doesn't loop over unit spec files.

**Changes:**

1. **Replace the limitation notice** (lines 18-19 of current file) with per-file loop logic:

```
If the resolved target is a unit spec (ends in `.unit.spec.md`):
  Read the `## Files` section. Resolve all listed file paths relative
  to the spec's directory.

  For each managed file, run Steps 0-7 independently. The Architect
  SHOULD maximize parallelism across independent files -- dispatch the
  next file's Saboteur while the current file's Mason is running.

  After all files complete, present an aggregated triage summary:

    "Cover results for unit `<unit-spec-path>`:

    <file-1>: N gaps found, M promoted to spec
    <file-2>: N gaps found, M promoted to spec
    ...

    Total: X gaps found across Y files, Z promoted to spec."

  Atomic commit (Step 7) covers all files in the unit together.
```

2. **No hint change needed** -- hint already accepts directories.

### verify.md

**Current state:** Hint says `<file-or-directory-path>`. Has directory resolution. Has a limitation notice saying unit specs aren't fully supported. Pipeline runs per-file but doesn't loop over unit spec files.

**Changes:**

1. **Replace the limitation notice** (lines 43-44 of current file) with per-file loop logic:

```
If the resolved target is a unit spec (ends in `.unit.spec.md`):
  Read the `## Files` section. Resolve all listed file paths relative
  to the spec's directory.

  For each managed file:
    Derive its per-file spec path and test file path.
    Run Steps 2-5 (dispatch Saboteur, report, write result) independently.

  After all files complete, present an aggregated report:

    "Verification results for unit `<unit-spec-path>`:

    <file-1>: N/M mutants killed, K equivalent -- PASS/FAIL
    <file-2>: N/M mutants killed, K equivalent -- PASS/FAIL
    ...

    Unit verdict: [PASS if all files pass | FAIL otherwise]"

  Each file gets its own `.unslop/verification/<hash>.json` result file.
```

2. **Spec resolution for per-file within unit:** Current Step 1 checks for `@unslop-managed` header on the target and derives spec as `<file-path>.spec.md`. Two adjustments for the unit loop:
   - When the target is a directory, skip the `@unslop-managed` header check on the directory itself -- it's not a file. The header check moves inside the per-file loop (check each managed file listed in `## Files`).
   - When running per-file within a unit loop, the per-file spec may not exist (the unit spec is the authority). Add: "If no per-file spec exists but the file is listed in a unit spec's `## Files`, use the unit spec as the spec source for that file."

3. **No hint change needed** -- hint already accepts directories.

### plugin.json

Bump version `0.44.0` --> `0.45.0`.

---

## PR 2: Reject unrecognised positional args in generate (v0.46.0)

### Files changed

- `unslop/commands/generate.md`
- `unslop/.claude-plugin/plugin.json`

### generate.md

**Current state:** Hint shows flags only. Body starts with Step 1 (verify prerequisites) after flag parsing. No check for leftover non-flag tokens. A user passing `/unslop:generate src/file.py` gets a silent project-wide regeneration.

**Changes:**

1. **Add positional arg rejection** between flag parsing and Step 1:

```
After extracting all recognised flags from $ARGUMENTS, check for
remaining non-flag tokens (tokens not starting with `--`).

If any remain, stop:

  "`/unslop:generate` operates project-wide and does not accept file
  paths. To regenerate a single file, use `/unslop:sync <file-path>`.
  To regenerate only stale files, use `/unslop:generate` with no path
  argument."
```

2. **No hint change needed** -- hint already shows flags-only correctly. The fix prevents silent misuse.

### plugin.json

Bump version `0.45.0` --> `0.46.0`.

---

## Testing strategy

Both PRs are command-file-only changes (markdown). No Python code changes, so the existing 405-test orchestrator suite is unaffected. Verification is:

1. **Read review:** Each command's argument resolution follows the established three-way pattern from takeover/spec.
2. **Manual smoke test:** Pass a directory to each modified command, confirm it resolves to unit spec or errors correctly.
3. **Regression:** Run `python -m pytest tests/test_orchestrator.py -q` to confirm no orchestrator breakage.

## Ordering

PR 1 ships first (scope resolution). PR 2 ships second (arg rejection). PR 2 references PR 1's version bump as its baseline. Both reference #82. PR 2's description closes #82.
