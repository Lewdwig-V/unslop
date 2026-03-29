# Sprint Contracts + Saboteur Calibration -- Design Spec

## Problem

The adversarial pipeline has two evaluation gaps:

1. **Per-execution gap:** The Saboteur verifies against the full spec, not against what specifically changed. On re-generates after spec amendments, there's no mechanism for the Architect to say "these specific behaviours should change, everything else should be invariant" and have the Saboteur verify that claim. The Saboteur checks everything equally, missing the signal of what matters for THIS execution.

2. **Per-project gap:** The Saboteur classifies surviving mutants (`equivalent`, `weak_test`, `spec_gap`) using pure LLM judgment with no project-specific grounding. The same mutation pattern may be classified differently across runs. There's no feedback loop for correcting misclassifications or anchoring correct ones.

These are complementary: sprint contracts fix the per-execution problem (what to check this time), saboteur calibration fixes the per-project problem (how to classify findings in general).

## Approach

Two features, same PR. Both are documentation/skill changes (markdown files consumed by agents). No Python changes.

- **Sprint contracts:** New Phase 0f in the generation skill. Architect writes expected outcomes (normative), Saboteur writes verification strategy (operational). Contract is an ephemeral YAML sidecar consumed during Stage 3.
- **Saboteur calibration:** New project-local file `.unslop/saboteur-calibration.md` loaded by the Saboteur alongside `principles.md`. Few-shot examples of correct and incorrect classifications.

## Out of scope

- Prompted calibration (Saboteur asks user to confirm classifications interactively). Start with manual calibration file edits.
- Contract negotiation failure handling (what if Saboteur says all outcomes are unverifiable). Flag to user, proceed with best-effort verification.
- Calibration file schema validation. Natural language format, no structured parsing needed.
- Auto-populating calibration from verification results. Manual curation only for v1.

---

## Feature 1: Sprint Contracts

### When it fires

Phase 0f fires **only on re-generates** -- when the spec has changed since the last successful generate. Detection: compare `spec-hash` in the managed file's `@unslop-managed` header against the current spec hash. If they match (fresh) or there's no prior header (first generate), skip Phase 0f.

Phase 0f fires after Phase 0e (strategy coherence) and before Stage 1 (Mason) / Stage 2 (Builder).

### Contract lifecycle

```
Phase 0f: Contract Negotiation
  Step 1: Architect reads spec diff (current vs last-generated spec hash)
          Writes Expected Outcomes (normative)
          "What behaviours should change? What should remain invariant?"

  Step 2: Saboteur reads Expected Outcomes
          Writes Verification Strategy (operational)
          "Which outcomes can I verify? Which are partially or not verifiable?"
          Flags unverifiable-gaps explicitly

  Step 3: Contract written as <file>.contract.yaml (sidecar next to spec)

→ Builder generates (Stage 2)
→ Saboteur runs Stage 3, checks against contract in addition to full spec
→ Contract deleted after successful verification
→ If verification fails and convergence runs, contract persists through iterations
```

### Contract artifact format

```yaml
spec-path: src/retry.py.spec.md
spec-diff-hash: a1b2c3d4e5f6
timestamp: 2026-03-29T10:00:00Z

expected-outcomes:
  - id: 1
    description: "429 status treated as retryable"
    invariant: false
  - id: 2
    description: "400-499 (except 429) treated as non-retryable"
    invariant: false
  - id: 3
    description: "Exponential backoff timing unchanged"
    invariant: true

verification-strategy:
  - outcome-id: 1
    verifiable: true
    method: "mutation at retry classification, edge case probe on 429"
  - outcome-id: 2
    verifiable: true
    method: "mutation at status code boundary, probe 400/428/430/499"
  - outcome-id: 3
    verifiable: partial
    gap: "Can verify retry count but not timing -- no clock mock in test structure"
    fallback: "Verify retry count invariant only"

unverifiable-gaps:
  - outcome-id: 3
    reason: "Timing verification requires clock injection not present in current tests"
    recommendation: "Accept partial coverage or add clock mock to test structure"
```

### Asymmetric contributions

The contract's value comes from the Architect and Saboteur answering different questions:

**Architect (normative):** Given the spec amendment, what behaviours should change and what should remain invariant? This is intent-space reasoning. The Architect knows what the spec means.

**Saboteur (operational):** Given those expected changes, how will verification actually work? Which mutations are interesting? Which edge cases are newly relevant? Are any stated invariants actually untestable? The Saboteur flags where the verification strategy can't cover what the Architect claimed.

The Saboteur's adversarial contribution is the `unverifiable-gaps` list -- things the Architect said should be invariant that the Saboteur can't actually check. This surfaces Goodhart's Law risk (optimising for what's measurable rather than what matters) before the generate pass, not after.

### Saboteur Stage 3 contract integration

When a contract exists, the Saboteur's Stage 3 report includes a `contract-compliance` section:

```json
{
  "contract_compliance": {
    "outcomes_verified": 2,
    "outcomes_partial": 1,
    "outcomes_unverifiable": 0,
    "results": [
      {"outcome_id": 1, "status": "verified", "evidence": "mutation at retry_policy killed by test_429_retryable"},
      {"outcome_id": 2, "status": "verified", "evidence": "boundary mutations at 400/428/430/499 all killed"},
      {"outcome_id": 3, "status": "partial", "evidence": "retry count invariant verified, timing not testable"}
    ]
  }
}
```

This is additive -- the existing mutation testing, constitutional compliance, and edge case probing still run unchanged. The contract adds targeted verification for the specific changes in this execution.

### Contract cleanup

- **Successful verification (status: pass):** Delete `<file>.contract.yaml`. The contract served its purpose.
- **Failed verification (convergence loop):** Contract persists. The convergence loop uses the contract to focus repairs -- `weak_test` survivors that relate to a contract outcome get priority.
- **Abandoned generate (user cancels):** Contract persists until next generate pass, which will produce a new contract (overwriting the stale one).

### Files changed

- `unslop/skills/generation/SKILL.md`: Add Phase 0f section after Phase 0e
- `unslop/commands/generate.md`: Add Phase 0f dispatch in Step 5a (after Archaeologist, before Mason)
- `unslop/commands/sync.md`: Same Phase 0f dispatch (sync uses the same pipeline)
- `unslop/skills/adversarial/SKILL.md`: Add contract-compliance section to Stage 3 output

---

## Feature 2: Saboteur Calibration

### What it is

A project-local file (`.unslop/saboteur-calibration.md`) containing few-shot examples of correctly classified Saboteur findings. The Saboteur loads this at the start of Stage 3 as classification context, the same way it loads `principles.md` for constitutional compliance.

### How it works

1. **Loading:** Saboteur checks for `.unslop/saboteur-calibration.md` at Stage 3 start. If present, loads it as few-shot context. If absent, proceeds without calibration (current behaviour).

2. **Effect:** The examples anchor the Saboteur's classification judgment. When classifying a surviving mutant, the Saboteur considers whether the current case matches any calibration example. If it does, the calibration example's classification is a strong prior (not a rule -- the Saboteur can disagree if the current case is genuinely different).

3. **Accumulation:** Manual only for v1. After a verification run, if the user disagrees with a classification, they edit `saboteur-calibration.md` to add a correction example. Over time, the file accumulates project-specific judgment that reduces classification drift.

### File format

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
- **Source:** adversarial-hashing M5/M6 (2026-03-28)

### weak_test: existence check without value assertion
- **Pattern:** Test asserts `result is not None` but not `result == expected`
- **Mutation:** Return wrong value of correct type
- **Classification:** weak_test -- spec requires specific value, test only checks non-None
- **Source:** adversarial-hashing M19 (2026-03-28)

### spec_gap: unspecified boundary return type
- **Pattern:** Function returns {} vs None when all inputs filtered out
- **Mutation:** Change empty-dict return to None
- **Classification:** spec_gap -- spec says "entries silently skipped" but doesn't specify return when ALL entries filtered
- **Source:** adversarial-hashing M15 (2026-03-28)

## Misclassifications

(Corrections for cases where the Saboteur got it wrong. These are more
valuable than correct examples -- a single correction teaches more than
ten confirmations.)

## Edge Case Calibration

### acceptable: whitespace-only input to hash function
- **Input:** compute_hash("   ")
- **Expected:** NOT flagged -- spec non-goal explicitly allows empty/whitespace inputs
- **Rationale:** Non-goal ratified during elicit, not an edge case finding
```

### Key design decisions

- **Natural language, not structured YAML.** The Saboteur is doing LLM-native classification. Few-shot examples in prose are the right format for steering judgment. No schema validation needed.
- **Corrections over confirmations.** The `## Misclassifications` section is more valuable than `## Correct Classifications`. A single "you called this equivalent but it was actually spec_gap because..." teaches more than ten "yes, correctly equivalent." The file format emphasizes this.
- **Advisory, not enforced.** The calibration file is context, not rules. The Saboteur reads it for grounding but can disagree. This avoids overfitting to past examples that may not generalise.
- **Project-local, not plugin-level.** Different projects have different patterns. A web framework project and a data pipeline have different mutation signatures. Calibration is per-project.
- **No auto-population.** v1 is manually curated. Auto-populating from verification results risks amplifying classification errors rather than correcting them. The human curation step is load-bearing.

### Seeding from adversarial-hashing

The adversarial-hashing stress test produced 5 surviving mutants with classifications. These become the initial calibration examples for any project that runs `/unslop:init`:

- 3 correct `equivalent` classifications (M5, M6, M12)
- 1 correct `weak_test` classification (M19)
- 1 correct `spec_gap` classification (M15)

The `/unslop:init` command can optionally seed `.unslop/saboteur-calibration.md` with a starter template containing these examples. Projects can then add their own examples as the Saboteur runs.

### Files changed

- `unslop/skills/adversarial/SKILL.md`: Add calibration loading step at Stage 3 start
- `unslop/commands/adversarial.md`: Reference calibration file in context loading
- `unslop/commands/verify.md`: Same calibration loading
- `unslop/commands/init.md`: Optionally seed calibration template

---

## Interaction between the two features

Sprint contracts and saboteur calibration are independent but reinforcing:

- **Contract tells the Saboteur what to focus on** (per-execution targeting)
- **Calibration tells the Saboteur how to classify** (per-project judgment)

When both are present during Stage 3:
1. Saboteur loads calibration file (project-level context)
2. Saboteur loads contract (execution-level targeting)
3. Mutation testing runs (existing behaviour)
4. Classification uses calibration examples as few-shot anchors (new behaviour)
5. Contract-compliance section added to verification output (new behaviour)
6. Contract deleted on success (cleanup)

No ordering dependency -- either feature works without the other.

---

## Version

Both features ship in the same PR. Version bump: 0.49.0 -> 0.50.0.
