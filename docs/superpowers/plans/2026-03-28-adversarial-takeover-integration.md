# Adversarial Takeover Integration -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the adversarial takeover pipeline as a fully supported, documented, and discoverable workflow by aligning skill docs to command reality and adding discoverability hints.

**Architecture:** Pure documentation changes across 5 files. No Python, no new commands, no new skills. The implementation is already complete -- this plan aligns docs to reality.

**Tech Stack:** Markdown, JSON

---

### Task 1: Fix generation skill -- remove stale Saboteur language

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:1267-1272`

- [ ] **Step 1: Replace section 8 content**

Replace the entire `## 8. Adversarial Quality Integration Point` section (lines 1267-1272) with:

```markdown
## 8. Adversarial Quality -- Auto-Dispatch

After the Builder succeeds and the worktree merges (Stage 2 complete), the generate command dispatches the Saboteur asynchronously in a separate worktree. This is non-blocking -- the user gets control back immediately.

The Saboteur runs the adversarial quality pipeline (mutation testing, constitutional compliance, edge case probing) and writes results to `.unslop/verification/<managed-file-hash>.json`. Findings surface in `/unslop:status`. No user action is required.

**HARD RULE:** The Saboteur auto-dispatches after every successful Builder merge. This is not optional and not conditional on `adversarial: true` in config. The async overhead is deliberately non-blocking -- it does not slow the user down, it just produces findings.

**Escape hatch:** Set `disable_async_saboteur: true` in `.unslop/config.json` to suppress auto-dispatch. This is for projects where background compute is genuinely unaffordable, not a default-off design.

**On-demand use:** `/unslop:adversarial <spec-path>` runs the same pipeline synchronously with full output. `/unslop:verify <spec-path>` runs Saboteur verification synchronously. These are for when the user wants to see results immediately rather than waiting for async findings.
```

- [ ] **Step 2: Verify no other stale references in the skill**

Run: `grep -n "planned\|not auto\|not yet.*trigger\|future enhancement" unslop/skills/generation/SKILL.md`
Expected: No matches (the only stale language was in section 8).

- [ ] **Step 3: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "fix: align generation skill with command -- Saboteur auto-dispatches (v0.49.0)

The skill doc said auto-trigger was a 'planned future enhancement' but
the generate command already dispatches the Saboteur async in Stage 3.
Agents reading the skill believed it didn't auto-run. Skill docs are
the ground truth agents read -- this is a correctness fix."
```

---

### Task 2: Expose adversarial flags in takeover command

**Files:**
- Modify: `unslop/commands/takeover.md:1-8`

- [ ] **Step 1: Update frontmatter argument-hint**

Replace the frontmatter (lines 1-4):

```yaml
---
description: Bring existing code under spec-driven management
argument-hint: <file-or-directory-path> [--spec-only] [--skip-adversarial] [--full-adversarial]
---
```

- [ ] **Step 2: Update argument parsing prose**

Replace the Parse arguments block (lines 6-8) with:

```markdown
**Parse arguments:** `$ARGUMENTS` contains the target path (file or directory) and optional flags. Extract:
- The target path: first token that does not start with `--`. May be a file (produces a file spec) or a directory (produces a unit spec).
- The `--spec-only` flag, if present (stops after distill + elicit, skips generate).
- The `--skip-adversarial` flag, if present (bypasses adversarial validation even for testless files -- user accepts risk of unvalidated takeover).
- The `--full-adversarial` flag, if present (forces adversarial validation even when tests exist -- runs adversarial pipeline in addition to existing test validation).
```

- [ ] **Step 3: Add testless routing explanation after Step 1**

Insert after the "If already managed:" block (after line 23) and before "**2. Phase 1: Distill**" (line 25):

```markdown
**1b. Testless routing decision**

Check whether tests exist for the target:
- For files: search for `tests/test_<name>.py`, `<name>_test.py`, or test files that import the target module.
- For directories: search for a parallel `tests/` directory or test files within the directory.

Route based on test presence and flags:
- **Tests exist, no flags:** Normal path -- existing tests serve as quality gate during generation.
- **No tests exist, no flags:** Adversarial path auto-activates -- Archaeologist extracts behaviour.yaml, Mason generates tests under Chinese Wall, Saboteur validates via mutation testing (kill rate >= 80% required).
- **`--skip-adversarial`:** Bypass adversarial validation even for testless files. The takeover proceeds without a quality gate. Use when you trust the distilled spec and want to skip the compute cost.
- **`--full-adversarial`:** Force adversarial validation even when tests exist. Runs the adversarial pipeline (behaviour extraction, Mason test generation, mutation testing) in addition to existing test validation. Use for belt-and-suspenders validation on critical code.
```

- [ ] **Step 4: Commit**

```bash
git add unslop/commands/takeover.md
git commit -m "feat: expose --skip-adversarial/--full-adversarial in takeover (v0.49.0)

Takeover silently routed to adversarial path when no tests existed but
didn't advertise this. Users couldn't discover the capability. Now the
argument hint shows both flags and Step 1b explains the routing logic."
```

---

### Task 3: Update AGENTS.md with testless workflow and maintenance rule

**Files:**
- Modify: `AGENTS.md:26-35` (after Five-Phase Model table), `AGENTS.md:155-167` (Conventions section)

- [ ] **Step 1: Add testless takeover variant after the orchestrators paragraph**

Insert after line 27 ("Three orchestrators compose phases: takeover (distill -> elicit -> generate), change (elicit -> generate with ripple check), sync (generate with dependency resolution).") and before "### Unified Generate Pipeline":

```markdown
### Testless Takeover (Adversarial Path)

When `/unslop:takeover` discovers no existing tests for the target, the adversarial pipeline becomes the quality gate instead of existing tests:

1. **Distill + Elicit** proceed normally (spec inference and review)
2. **Generate Stage 0:** Archaeologist produces concrete spec + `behaviour.yaml` (behavioural contract)
3. **Generate Stage 1:** Mason generates tests from `behaviour.yaml` ONLY (Chinese Wall -- never sees source code or spec)
4. **Generate Stage 2:** Builder implements from concrete spec, validated against Mason's tests
5. **Generate Stage 3:** Saboteur runs mutation testing (kill rate >= 80% required)

If kill rate is below threshold, the convergence loop runs (up to 3 iterations + 1 radical spec hardening if entropy stalls). Each iteration classifies surviving mutants as `weak_test` (Mason strengthens), `spec_gap` (Architect enriches behaviour.yaml), or `equivalent` (no action).

Override with `--skip-adversarial` (bypass) or `--full-adversarial` (force even when tests exist).
```

- [ ] **Step 2: Add skill/command alignment rule to Conventions**

Insert after the "### Version Bumps" section (line 167) at the end of AGENTS.md:

```markdown
### Skill/Command Alignment

Skill docs are the ground truth agents read. After any command implementation that diverges from its reference skill, the skill update is a correctness fix, not optional housekeeping.

- **Command** is loaded at execution time. It's what runs.
- **Skill** is loaded as reference during planning. It's what agents believe.

When they diverge, the skill wins the epistemic battle even when the command is correct. An agent consulting the skill during planning will reason from stale information and may route around a capability that actually exists. After shipping a command change, update the corresponding skill in the same PR.
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add testless takeover workflow and skill/command alignment rule (v0.49.0)

AGENTS.md now documents the adversarial takeover path as a distinct
workflow in the Five-Phase Model. Also adds a maintenance rule: skill
updates after command changes are correctness fixes, not housekeeping."
```

---

### Task 4: Version bump plugin.json

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version and add keyword**

Update plugin.json:

```json
{
  "name": "unslop",
  "version": "0.49.0",
  "description": "Spec-driven development harness for Claude Code -- 20 commands, five-phase model, five agents, three-tier domain skills, crystallize, constitutional principles, 405 tests",
  "author": {
    "name": "lewdwig"
  },
  "repository": "https://github.com/Lewdwig-V/unslop",
  "license": "MPL-2.0",
  "keywords": ["spec-driven", "codegen", "takeover", "testless-takeover", "vibe-coding", "code-management", "adversarial-testing", "mutation-testing"]
}
```

Changes: `version` 0.48.0 -> 0.49.0, added `"testless-takeover"` to keywords.

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump to v0.49.0, add testless-takeover keyword"
```

---

### Task 5: Commit stress test artifacts and add alignment summary

**Files:**
- Create: `stress-tests/adversarial-hashing/alignment-summary.md`
- Stage: all existing stress-tests/adversarial-hashing/ files

- [ ] **Step 1: Create alignment-summary.md**

```markdown
## Managed files

- `src/hashing.py` <- `src/hashing.py.spec.md` (fresh, generated 2026-03-28)
  Intent: Deterministic content hashing and structured header parsing for managed files
```

- [ ] **Step 2: Stage all adversarial-hashing artifacts**

```bash
git add stress-tests/adversarial-hashing/
```

Verify the staging includes:
- `src/__init__.py`
- `src/hashing.py` (regenerated by Builder)
- `src/hashing.py.spec.md` (distilled + elicited)
- `src/hashing.py.impl.md` (concrete spec)
- `src/hashing.py.behaviour.yaml` (Chinese Wall artifact)
- `tests/__init__.py`
- `tests/test_hashing.py` (68 tests by Mason)
- `.unslop/config.json`
- `.unslop/boundaries.json`
- `.unslop/.gitignore`
- `.unslop/verification/hashing_verification.json` (Saboteur results)
- `alignment-summary.md`

- [ ] **Step 3: Commit**

```bash
git commit -m "test: add adversarial-hashing stress test (validated testless takeover)

Cleanroom stress test validating the adversarial takeover pipeline
against hashing.py (154 lines, 3 functions, no existing tests).

Results:
- Mason: 68 black-box tests from behaviour.yaml (Chinese Wall)
- Builder: structurally different but behaviourally equivalent impl
- Saboteur: 88.2% adjusted kill rate (15/17 non-equivalent killed)
- Edge cases: 10 adversarial inputs, all clean"
```

---

### Task 6: Run existing tests and verify clean state

**Files:** None (verification only)

- [ ] **Step 1: Run orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: 405 passed

- [ ] **Step 2: Run stress test**

Run: `python -m pytest stress-tests/adversarial-hashing/tests/ -q`
Expected: 68 passed

- [ ] **Step 3: Verify git status is clean**

Run: `git status`
Expected: clean working tree, all changes committed

- [ ] **Step 4: Verify version bump**

Run: `grep '"version"' unslop/.claude-plugin/plugin.json`
Expected: `"version": "0.49.0"`
