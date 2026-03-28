# Adversarial Takeover Integration -- Design Spec

## Problem

The adversarial takeover pipeline (Archaeologist -> Mason -> Saboteur) is fully implemented and validated against real code (stress-tests/adversarial-hashing), but invisible to users:

1. `/unslop:takeover` silently routes to the adversarial path when no tests exist, but doesn't advertise this in its argument hint or early prose. Users don't know the capability exists.
2. The generation skill says Saboteur auto-trigger is a "planned enhancement" when the generate command already dispatches it async in Stage 3. Agents reading the skill believe the Saboteur doesn't auto-run.
3. AGENTS.md doesn't mention testless takeover as a distinct workflow, so the Five-Phase Model gives no signal that adversarial validation exists.
4. The stress test artifacts from the validated run aren't committed.

Root cause: the command spec and skill doc serve different agents at different times. The command is loaded at execution (it's what runs). The skill is loaded as reference (it's what informs). When they diverge, agents reason from stale information regardless of what the command actually does.

## Validation

The adversarial takeover was validated end-to-end against `core/hashing.py` (154 lines, 3 public functions) extracted into a cleanroom stress test with no existing tests:

- Archaeologist: distilled spec from code, produced concrete spec + behaviour.yaml
- Mason: generated 68 black-box tests from behaviour.yaml alone (Chinese Wall held)
- Builder: regenerated structurally different but behaviourally equivalent implementation
- Saboteur: 20 mutations, 88.2% adjusted kill rate (15 killed, 3 equivalent, 2 weak test)
- Edge cases: 10 adversarial inputs all handled cleanly

All 68 Mason tests pass against both the original and regenerated code.

## Approach

Documentation-first alignment. No new commands, no new skills, no Python changes. The workflow is implemented -- we're aligning docs to reality and making it discoverable.

## Out of scope

- No new `/unslop:adversarial-takeover` command (discoverability via flags on existing command, not command proliferation)
- No Python orchestrator changes
- No changes to `takeover/SKILL.md` (already comprehensive)
- No changes to `verify.md` or `cover.md`

---

## Changes

### 1. `unslop/skills/generation/SKILL.md` -- critical fix

**What:** Remove "planned enhancement" / "not auto-triggered" language about Saboteur. Replace with present-tense description of current behavior.

**Why:** This is the trust fix. Any agent loading the generation skill during planning will read "auto-trigger is a planned future enhancement" and conclude the Saboteur doesn't run. The command spec dispatches it in Stage 3. The skill must match.

**Content:**

Replace the integration-point language with:

- Saboteur dispatches async after Builder success (Stage 3), in a worktree
- Non-blocking -- user gets control back immediately after Builder merges
- Writes result to `.unslop/verification/<managed-file-hash>.json`
- No user action required; findings surface in `/unslop:status`
- Escape hatch: `config.disable_async_saboteur: true` suppresses auto-dispatch for projects where background compute is genuinely unaffordable

### 2. `unslop/commands/takeover.md` -- discoverability

**What:** Expose adversarial flags in argument hint. Add testless routing explanation.

**Argument hint change:**

Before: `<file-or-directory-path> [--spec-only]`
After: `<file-or-directory-path> [--spec-only] [--skip-adversarial] [--full-adversarial]`

**Prose addition after Step 1 (Discover):**

Testless routing decision:
- If tests exist: normal path (existing tests as quality gate)
- If no tests: adversarial path auto-activates (Archaeologist -> Mason -> Saboteur as quality gate)
- `--skip-adversarial`: bypass adversarial validation even for testless files (user accepts risk of unvalidated takeover)
- `--full-adversarial`: force adversarial validation even when tests exist (runs adversarial pipeline in addition to existing test validation)

### 3. `AGENTS.md` -- two additions

**Addition 1: Testless takeover workflow**

In the Five-Phase Model section, add the testless variant as a distinct path:

- When takeover discovers no tests, the adversarial pipeline becomes the quality gate
- Behaviour YAML replaces existing tests as the behavioural contract
- Mason generates tests from behaviour.yaml under Chinese Wall (never sees source code)
- Saboteur validates via mutation testing (kill rate >= 80% required)
- Convergence loop: up to 3 iterations + 1 radical spec hardening if entropy stalls

**Addition 2: Skill/command alignment maintenance rule**

Under process conventions, add:

> Skill docs are the ground truth agents read. After any command implementation that diverges from its reference skill, the skill update is a correctness fix, not optional housekeeping. Command spec describes what runs; skill doc describes what agents believe. When they diverge, agents reason from stale information.

### 4. `plugin.json` -- mechanical

- `version`: "0.48.0" -> "0.49.0"
- `keywords`: add `"testless-takeover"`

### 5. `unslop/skills/adversarial/SKILL.md` -- no changes needed

Verified: the adversarial skill has no stale language about auto-trigger or planned enhancements. The stale language is isolated to `generation/SKILL.md` (section 8, line 1271). The adversarial skill is already accurate.

### 6. `stress-tests/adversarial-hashing/` -- commit validated artifacts

**Add `alignment-summary.md`:**
```
## Managed files
- `src/hashing.py` <- `src/hashing.py.spec.md` (fresh, generated 2026-03-28)
  Intent: Deterministic content hashing and structured header parsing for managed files
```

**Commit all artifacts from the validated run:**
- `src/hashing.py` (regenerated by Builder)
- `src/hashing.py.spec.md` (distilled + elicited)
- `src/hashing.py.impl.md` (concrete spec by Archaeologist)
- `src/hashing.py.behaviour.yaml` (Chinese Wall artifact)
- `tests/__init__.py` + `tests/test_hashing.py` (68 tests by Mason)
- `.unslop/config.json`, `.unslop/boundaries.json`, `.unslop/.gitignore`
- `.unslop/verification/hashing_verification.json` (Saboteur mutation results)
- `alignment-summary.md`

---

## Maintenance lesson (encode in AGENTS.md)

The command spec and skill doc serve different agents at different times:

- **Command** is loaded at execution time. It's what runs.
- **Skill** is loaded as reference during planning. It's what agents believe.

When they diverge, the skill wins the epistemic battle even when the command is correct. An agent consulting the skill during planning will reason from stale information and may route around a capability that actually exists (or rely on one that doesn't).

This is the same failure mode as the adversarial takeover path being "unsurfaced" -- except inverted. There, the skill described something that didn't work. Here, the skill fails to describe something that does work. Both produce agents with wrong models of the system. The fix: skill updates after command changes are correctness fixes, not housekeeping.
