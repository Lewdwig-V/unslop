---
description: Detect intent drift between specs and code. Surfaces meaningful discrepancies and offers per-finding remediation.
argument-hint: "[file-path] [--all]"
---

**Parse arguments:** `$ARGUMENTS` may contain a file path and optional flags.

- If a file or directory path is provided: target that single file or unit
- If `--all` is provided: target all managed files regardless of classification
- If no arguments: target files classified as `modified` (code edited directly, spec unchanged)

**0. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

**1. Target Selection**

If a file path argument is provided, validate it is a managed file (has `@unslop-managed` header and a corresponding `*.spec.md`). If not:

> "This file is not under spec management. Use `/unslop:takeover` first."

If no argument:
- Scan for all managed files using the same mechanism as `/unslop:status`.
- Default: select files classified as `modified` (code edited directly, spec unchanged).
- With `--all`: select all managed files regardless of classification.

If no targets found:

> "No files to weed."

**1b. Static drift pre-pass (Tier 1)**

Before running the full LLM analysis, perform a cheap hash-based drift check on each target:

1. For each target file: compare the `spec-hash` in its `@unslop-managed` header against the current spec content hash.
2. For each target's test file (if it has an `@unslop-managed` header): compare the test's `spec-hash` against the current spec content hash.
3. Any hash mismatch = drift candidate. Report without LLM analysis:

```
Static drift detected:
  src/retry.py -- spec-hash mismatch (code generated from older spec)
  tests/test_retry.py -- test-drifted (tests generated from older spec)
```

4. If no static drift candidates AND no explicit file targets AND `--all` was not passed:
> "No drift detected (static check). Use `--all` to run full LLM analysis regardless."

Stop here. Do not proceed to Step 2.

5. If static drift candidates exist: proceed to Step 2 (dynamic analysis) for those files only. The static pass narrows the set the LLM needs to analyze.

6. If `--all` was passed or explicit file targets were given: proceed to Step 2 for all targets regardless of static results. The static pre-pass still runs and reports its findings first, but does not filter the target set.

7. **Structural mismatch check:** For each spec in the target set, check if the managed file exists. If the managed file does not exist and the spec has active provenance (`distilled-from:`, `absorbed-from:`, or `exuded-from:` -- NOT `provenance-history:`), report as a structural mismatch:

```
Structural mismatch detected:
  src/retry.py.spec.md -> src/retry.py (file missing, has distilled-from provenance)
  src/backoff.py.spec.md -> src/backoff.py (file missing, has absorbed-from provenance)

Manual resolution required. See /unslop:absorb and /unslop:exude.
```

Structural mismatches are reported alongside static drift candidates but are NOT passed to the Tier 2 LLM analysis (there is no code to compare against). They are diagnostic only -- weed cannot determine whether the correct action is absorb, exude, or spec removal.

8. **Stale constitutional overrides:** For each spec with `constitutional-overrides:` frontmatter, cross-reference each override's `principle` field against the current content of `.unslop/principles.md`. If the principle text no longer appears in principles.md (removed or significantly reworded), flag as stale:

```
Stale constitutional overrides:
  src/retry.py.spec.md -- override for "All error handling must use typed Result types"
    Principle no longer found in .unslop/principles.md. Remove override during next elicit amendment.
```

Stale overrides are informational -- they do not block anything. They indicate the override may no longer be needed because the constraint it overrode was relaxed or removed.

Specs in `pending` state (no managed file, no provenance) are NOT structural mismatches. They are planned specs awaiting generation. Weed skips them entirely -- there is nothing to compare the spec against.

9. **Source spec existence check (skill health):** For each project-local skill in `.unslop/skills/` with `crystallized-from:` provenance in its frontmatter, extract the `spec:` field from each entry and check whether those spec files still exist on disk. If ALL source specs have been deleted, flag:

```
Skill decay (static):
  .unslop/skills/typed-error-handling/SKILL.md -- all source specs deleted
    Skill may be obsolete. Review or remove.
```

If only some source specs are deleted, do not flag -- partial provenance is expected as projects evolve.

10. **Shadow staleness check:** For each user-local skill (`~/.config/unslop/skills/<name>/SKILL.md`) that shadows a project-local or plugin skill (same name exists at a lower tier), compare file modification times. If the shadowed (lower-tier) skill was modified more recently than the shadowing (higher-tier) skill, flag:

```
Stale skill shadow:
  user-local "error-handling" (modified 2026-03-15)
    shadows project-local "error-handling" (modified 2026-03-25)
    Project skill was updated after your local copy. Review for conflicts.
```

Similarly check project-local skills that shadow plugin skills.

**Why Tier 1 first:** The static pass is cheap (hash comparison, no LLM) and catches the most common drift case (spec changed, code/tests not regenerated). This makes weed viable in CI where LLM calls are expensive or unavailable.

**2. Analysis**

For each target file:

1. Read the spec file (abstract spec `*.spec.md`).
2. Read the concrete spec (`*.impl.md`) if it exists.
3. Read the managed file (the generated/edited code).
4. Compare spec intent against code behavior and identify **concerns**.

A concern is a meaningful discrepancy between what the spec says and what the code does. Not a style issue. Not a naming preference. A place where behavior has drifted from intent.

Each concern has:

| Field | Description |
|-------|-------------|
| **title** | Short description, e.g., "Unbounded retry loop" |
| **direction** | `spec-behind` (code is right, spec incomplete) or `code-drifted` (spec is right, code diverged) |
| **spec-reference** | Which section(s) of the spec are relevant |
| **code-reference** | File path + line range |
| **rationale** | Why this is a meaningful discrepancy |

**Direction heuristic:** If the file is `modified` (code edited directly), lean toward `spec-behind` -- the human edit was probably intentional. If the file is `fresh` (generated), lean toward `code-drifted` -- the generator probably missed something. Override with your own judgment if the heuristic doesn't fit.

**2b. Skill Adherence Check (Tier 2 -- LLM analysis)**

After file drift analysis, check project-local skills for adherence. User-local skills are excluded from adherence checks -- they are personal preferences, not project-wide contracts.

1. For each project-local skill in `.unslop/skills/` with `applies-to` patterns, find all specs matching the globs.
2. For each matching spec, assess whether the pattern described by the skill is still followed in the spec and its managed file.
3. Compute adherence rate: (specs following pattern) / (total applicable specs).
4. If adherence drops below `config.skill_adherence_threshold` (default: 50%), flag the skill as potentially stale.

Display skill health results before the drift report:

```
Skill health:
  "typed-error-handling" -- 8/10 applicable specs follow pattern (80%)
  "kafka-consumer-pattern" -- 2/7 applicable specs follow pattern (28%)
    Pattern may be stale. Review with /unslop:elicit or remove skill.
```

For `constitutional` skills with adherence below the threshold, add a specific warning:

```
  "strict-validation" (constitutional) -- 3/12 applicable specs follow pattern (25%)
    Constitutional skill with low adherence -- either the codebase is non-compliant
    or the skill is too aggressive. Consider downgrading to advisory.
```

Skills with no `applies-to` patterns (applies to all files) are checked against the full spec corpus. Skills at or above the threshold are reported with a checkmark but only if `--verbose` is passed -- otherwise healthy skills are omitted from the output.

**3. Report**

Display all findings grouped by file, all at once, before any remediation:

```
Weed report: 2 files, 4 concerns

  src/auth/handler.py  (modified)
    1. [spec-behind] Unbounded retry loop
       Spec ## Retry Policy says "retry with backoff" but doesn't cap retries.
       Code caps at 5 (handler.py:42-58). Spec should document the cap.

    2. [code-drifted] Silent exception swallowing
       Spec ## Error Handling says "propagate all errors to caller."
       Code catches ConnectionError and returns None (handler.py:61-65).

  src/auth/tokens.py  (modified)
    3. [spec-behind] Token refresh adds jitter
       Spec ## Refresh says "refresh token before expiry."
       Code adds 0-5s jitter to avoid thundering herd (tokens.py:88-94).
       Spec should document the jitter strategy.

    4. [code-drifted] Missing token revocation
       Spec ## Lifecycle says "tokens can be revoked."
       Code has no revocation path (tokens.py).
```

If no concerns: "No drift detected across N files."

**4. Remediation**

Walk through each finding one at a time.

**If `spec-behind`:**
> Concern N: "<title>" -- spec should document <what>.
> (u) Update spec to match code  |  (s) Skip  |  (q) Quit remediation

If the user chooses "update spec": edit the spec file directly. Add or modify the relevant section to reflect what the code actually does. The file will show as `stale` in `/unslop:status` (spec changed, code unchanged) -- but since the spec now matches the code, the next sync will be a no-op or trivially confirmed.

**If `code-drifted`:**
> Concern N: "<title>" -- code should <what> per spec.
> (r) Regenerate to match spec  |  (s) Skip  |  (q) Quit remediation

If the user chooses "regenerate": mark the file for sync. Do NOT regenerate inline. Display a reminder at the end: "N files queued for sync -- run `/unslop:sync` to regenerate."

**Quit** stops remediation but keeps the report visible. Unanswered findings are simply skipped.

**5. Post-Remediation Summary**

```
Remediation complete:
  2 specs updated (src/auth/handler.py.spec.md, src/auth/tokens.py.spec.md)
  1 file queued for sync (src/auth/tokens.py)
  1 skipped

Run /unslop:sync to regenerate queued files.
```
