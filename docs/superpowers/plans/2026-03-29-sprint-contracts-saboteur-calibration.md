# Sprint Contracts + Saboteur Calibration -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-execution sprint contracts (Architect/Saboteur handshake on verifiable outcomes before re-generates) and per-project saboteur calibration (few-shot examples for mutation classification alignment).

**Architecture:** Pure documentation changes -- markdown skill files, command files, and a calibration template. No Python changes. Sprint contracts add Phase 0f to the generation skill and contract-compliance to Stage 3 verification. Saboteur calibration adds a loading step to Stage 3 and a seed template to init.

**Tech Stack:** Markdown

---

### Task 1: Add Phase 0f (Sprint Contract) to generation skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md` (insert after Phase 0e.1, before Section 1)

- [ ] **Step 1: Insert Phase 0f section**

Insert after the `---` line that follows Phase 0e.1's closing paragraph (after line 951 "strategy choices are more fluid than contract constraints.") and before `## 1. Generation Mode Selection` (line 954):

```markdown
### Phase 0f: Sprint Contract (Re-Generates Only)

**When it fires:** Only on re-generates -- when the spec has changed since the last successful generate. Compare `spec-hash` in the managed file's `@unslop-managed` header against the current spec hash. If they match (fresh) or there's no prior header (first generate), skip Phase 0f.

Phase 0f negotiates a per-execution contract between the Architect and Saboteur before the Builder runs. The contract captures what specifically should change (and what should remain invariant) for this generate pass, enabling targeted verification in Stage 3.

**Step 1 -- Architect writes Expected Outcomes (normative):**

The Architect reads the spec diff (current spec vs the spec at the time of last generate, reconstructable from `spec-hash` in the managed file header). From the diff, the Architect produces a list of expected outcomes:

- Each outcome has an `id`, `description`, and `invariant` flag (true = should NOT change, false = should change)
- Outcomes describe observable behaviour changes, not implementation details
- The Architect MUST include invariants for behaviours adjacent to the change that should remain stable

**Step 2 -- Saboteur writes Verification Strategy (operational):**

The Saboteur reads the Architect's expected outcomes and produces a verification strategy:

- For each outcome: `verifiable` (true/partial/false), `method` (how it will be checked), and optionally `gap` + `fallback` for partial cases
- **HARD RULE:** The Saboteur MUST flag any outcome it cannot fully verify in an `unverifiable-gaps` list. This is the Saboteur's adversarial contribution -- surfacing where the verification strategy can't cover what the Architect claimed. Silently accepting unverifiable outcomes defeats the contract's purpose.

**Step 3 -- Write contract sidecar:**

Write the contract as `<file>.contract.yaml` next to the spec file. Format:

```yaml
spec-path: <spec-path>
spec-diff-hash: <hash of spec diff>
timestamp: <ISO8601>

expected-outcomes:
  - id: 1
    description: "<behaviour change or invariant>"
    invariant: false
  - id: 2
    description: "<behaviour that should not change>"
    invariant: true

verification-strategy:
  - outcome-id: 1
    verifiable: true
    method: "<mutation/edge case strategy>"
  - outcome-id: 2
    verifiable: partial
    gap: "<what can't be verified>"
    fallback: "<best-effort alternative>"

unverifiable-gaps:
  - outcome-id: 2
    reason: "<why it can't be verified>"
    recommendation: "<accept partial / add test infrastructure>"
```

**Contract lifecycle:**
- **Successful verification (status: pass):** Delete `<file>.contract.yaml`.
- **Failed verification (convergence loop):** Contract persists. The convergence loop uses the contract to focus repairs -- `weak_test` survivors that relate to a contract outcome get priority.
- **Abandoned generate:** Contract persists until next generate pass overwrites it.
```

- [ ] **Step 2: Verify insertion doesn't break section numbering**

Run: `grep -n "^## \|^### Phase" unslop/skills/generation/SKILL.md | head -30`
Expected: Phase 0f appears between Phase 0e.1 and Section 1, no duplicate section numbers.

- [ ] **Step 3: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Phase 0f (sprint contract) to generation skill (v0.50.0)

Pre-generate Architect/Saboteur handshake on verifiable outcomes.
Architect writes expected outcomes (normative), Saboteur writes
verification strategy (operational) with explicit unverifiable-gaps."
```

---

### Task 2: Add contract-compliance to adversarial skill Stage 3

**Files:**
- Modify: `unslop/skills/adversarial/SKILL.md` (insert after Edge Case Probing section)

- [ ] **Step 1: Insert contract-compliance section**

Insert after the Edge Case Probing section (after line 126 "The probing phase never writes tests -- it only identifies gaps."):

```markdown

### Contract Compliance (Re-Generates Only)

After edge case probing, if a `<file>.contract.yaml` sidecar exists next to the spec, the Saboteur verifies the contract's expected outcomes.

**Process:** For each expected outcome in the contract:
1. If `invariant: true` -- verify the behaviour is unchanged (no surviving mutants in the invariant's domain, no test regressions in related tests)
2. If `invariant: false` -- verify the behaviour changed as expected (the new code implements the described change, validated via targeted mutation or edge case probe)
3. Cross-reference against `verification-strategy` -- use the Saboteur's own planned method for each outcome

**Output:** `contract_compliance` object in the verification JSON:

```json
{
  "contract_compliance": {
    "outcomes_verified": 0,
    "outcomes_partial": 0,
    "outcomes_unverifiable": 0,
    "results": [
      {
        "outcome_id": 1,
        "status": "verified|partial|unverifiable",
        "evidence": "description of how the outcome was verified"
      }
    ]
  }
}
```

**Effect on status:** Contract compliance is additive -- it does not independently cause `status: "fail"`. A contract with unverified outcomes produces a warning in `/unslop:status`, not a hard block. The mutation testing and constitutional compliance results remain the primary status drivers.

**Cleanup:** After a `status: "pass"` result, delete the `<file>.contract.yaml` sidecar. On `status: "fail"`, the contract persists through convergence iterations to focus repairs.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/adversarial/SKILL.md
git commit -m "feat: add contract-compliance to adversarial skill Stage 3 (v0.50.0)

Saboteur verifies sprint contract outcomes after mutation testing.
Additive -- does not independently cause status: fail."
```

---

### Task 3: Add saboteur calibration loading to adversarial skill

**Files:**
- Modify: `unslop/skills/adversarial/SKILL.md` (insert at start of Phase 3 section)

- [ ] **Step 1: Insert calibration loading step**

Insert after the Phase 3 HARD RULE about worktrees (after line 81 "This eliminates the mutation leak failure mode where an unrevetted mutation corrupts the source file.") and before "The Saboteur operates in two contexts:" (line 83):

```markdown

**Calibration loading:** At Stage 3 start, check for `.unslop/saboteur-calibration.md`. If present, load it as few-shot classification context. The calibration file contains examples of correctly classified surviving mutants and edge case assessments from previous runs. Examples are anchors, not rules -- the Saboteur uses them as strong priors for classification but can disagree if the current case is genuinely different. If the file does not exist, proceed without calibration (current behaviour).

```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/adversarial/SKILL.md
git commit -m "feat: add saboteur calibration loading to adversarial skill (v0.50.0)

Saboteur loads .unslop/saboteur-calibration.md at Stage 3 start as
few-shot classification context. Examples are anchors, not rules."
```

---

### Task 4: Add Phase 0f dispatch to generate command

**Files:**
- Modify: `unslop/commands/generate.md` (insert between Stage 0b and Stage 1)

- [ ] **Step 1: Insert Phase 0f dispatch**

Insert after Stage 0b's closing HARD RULE (after line 218 "never silently absorbed into the concrete spec.") and before `**5c. Stage 1: Mason -- Test Derivation (conditional)**` (line 220):

```markdown

**5b-1. Phase 0f: Sprint Contract (Re-Generates Only)**

If the managed file exists and has an `@unslop-managed` header with a `spec-hash` that differs from the current spec hash, negotiate a sprint contract:

1. **Architect** reads the spec diff and writes expected outcomes (normative -- what should change, what should remain invariant). See the generation skill's Phase 0f.
2. **Saboteur** reads the expected outcomes and writes a verification strategy (operational -- how each outcome will be verified, with explicit unverifiable-gaps). See the generation skill's Phase 0f.
3. Write the contract as `<file>.contract.yaml` next to the spec file.

If the managed file does not exist (new file) or the spec hash matches (fresh), skip Phase 0f.

The contract is consumed by the Saboteur in Stage 3 (Step 5e) and deleted on successful verification.

```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "feat: add Phase 0f sprint contract dispatch to generate command (v0.50.0)

Re-generates negotiate an Architect/Saboteur contract before Builder
dispatch. Contract is consumed in Stage 3 and deleted on success."
```

---

### Task 5: Add Phase 0f and calibration reference to sync command

**Files:**
- Modify: `unslop/commands/sync.md` (insert in Stage B section)

- [ ] **Step 1: Insert Phase 0f and calibration references**

Insert after `**Stage B (Builder -- worktree isolation):**` (line 294) and before the Builder dispatch line (line 295 "Dispatch a Builder Agent..."):

```markdown

**Pre-Builder: Sprint Contract (Re-Generates Only)**

Before dispatching the Builder, if the managed file has an existing `@unslop-managed` header with a `spec-hash` differing from the current spec hash, run Phase 0f (sprint contract negotiation) per the generation skill. Write the contract as `<file>.contract.yaml`. The Saboteur consumes it during async verification and deletes it on success.

**Pre-Builder: Saboteur Calibration**

If `.unslop/saboteur-calibration.md` exists, it will be loaded by the Saboteur during async verification after the Builder completes. No action needed here -- the calibration file is consumed at Stage 3 start, not at Builder dispatch.

```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "feat: add sprint contract and calibration references to sync command (v0.50.0)

Sync runs the same Phase 0f contract negotiation as generate for
re-generates. Calibration file is consumed by Saboteur at Stage 3."
```

---

### Task 6: Add calibration loading to verify and adversarial commands

**Files:**
- Modify: `unslop/commands/verify.md` (insert in Load context section)
- Modify: `unslop/commands/adversarial.md` (insert in context loading)

- [ ] **Step 1: Add calibration to verify command**

Insert after line 74 ("Load the **unslop/adversarial** skill. The Saboteur dispatch follows Phase 3 of that skill.") in `unslop/commands/verify.md`:

```markdown

If `.unslop/saboteur-calibration.md` exists, load it as few-shot classification context for the Saboteur. See the adversarial skill's Phase 3 calibration loading.

If a `<file>.contract.yaml` sidecar exists next to the spec, load it for contract-compliance verification. See the adversarial skill's Contract Compliance section.

```

- [ ] **Step 2: Add calibration to adversarial command**

Read `unslop/commands/adversarial.md` to find the context loading section, then insert the calibration reference after the skill loading step:

```markdown

If `.unslop/saboteur-calibration.md` exists, load it as few-shot classification context for the Saboteur. See the adversarial skill's Phase 3 calibration loading.

```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/verify.md unslop/commands/adversarial.md
git commit -m "feat: add calibration and contract loading to verify/adversarial commands (v0.50.0)

Both commands load saboteur-calibration.md for classification context
and contract.yaml for contract-compliance verification when present."
```

---

### Task 7: Add calibration seed template to init command

**Files:**
- Modify: `unslop/commands/init.md` (insert after principles.md section)

- [ ] **Step 1: Insert calibration seed step**

Insert after Step 5's closing line (after line 109 "If no, skip. Principles are optional.") and before `**6. Detect frameworks (optional)**` (line 111):

```markdown

**5b. Create `.unslop/saboteur-calibration.md` (optional)**

Ask the user: 'Would you like to seed Saboteur calibration? This provides few-shot examples that improve mutation classification accuracy over time.'

If yes, create `.unslop/saboteur-calibration.md` with the starter template:

```markdown
# Saboteur Calibration

Few-shot examples for mutation classification and edge case assessment.
The Saboteur loads this file at Stage 3 start as classification context.
Examples are anchors, not rules -- disagree if the current case is genuinely different.

## Correct Classifications

### equivalent: dead branch in single-match loop
- **Pattern:** Loop over non-overlapping list with break-on-first-match
- **Mutation:** Remove break statement
- **Classification:** equivalent -- no entry overlaps, break is unreachable after first match

### weak_test: existence check without value assertion
- **Pattern:** Test asserts `result is not None` but not `result == expected`
- **Mutation:** Return wrong value of correct type
- **Classification:** weak_test -- spec requires specific value, test only checks non-None

### spec_gap: unspecified boundary return type
- **Pattern:** Function returns {} vs None when all inputs filtered out
- **Mutation:** Change empty-dict return to None
- **Classification:** spec_gap -- spec doesn't specify return type when all inputs are invalid

## Misclassifications

(Add corrections here when the Saboteur gets a classification wrong.
These are more valuable than confirmations -- a single correction
teaches more than ten confirmations.)

## Edge Case Calibration

(Add examples of edge cases that should or should not be flagged.
Reference spec non-goals to suppress false positives.)
```

Present the template to the user for editing.

If no, skip. Calibration is optional and can be added later.

```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat: add saboteur calibration seed template to init command (v0.50.0)

Optional step during /unslop:init creates saboteur-calibration.md with
starter examples derived from the adversarial-hashing validation."
```

---

### Task 8: Version bump plugin.json

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version**

Change `"version": "0.49.0"` to `"version": "0.50.0"`.

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump to v0.50.0 (sprint contracts + saboteur calibration)"
```

---

### Task 9: Verify clean state

**Files:** None (verification only)

- [ ] **Step 1: Run orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: 405 passed

- [ ] **Step 2: Run stress test**

Run: `python -m pytest stress-tests/adversarial-hashing/tests/ -q`
Expected: 70 passed

- [ ] **Step 3: Verify git status is clean**

Run: `git status`
Expected: clean working tree

- [ ] **Step 4: Verify version bump**

Run: `grep '"version"' unslop/.claude-plugin/plugin.json`
Expected: `"version": "0.50.0"`

- [ ] **Step 5: Verify Phase 0f appears in generation skill**

Run: `grep -n "Phase 0f" unslop/skills/generation/SKILL.md`
Expected: At least one match showing the sprint contract section.

- [ ] **Step 6: Verify calibration loading appears in adversarial skill**

Run: `grep -n "calibration" unslop/skills/adversarial/SKILL.md`
Expected: At least two matches (loading step + contract compliance section).
