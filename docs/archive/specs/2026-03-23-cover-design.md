# `/unslop:cover` Design Spec -- Adversarial Coverage Growth (Milestone O)

**Target version:** v0.15.0 (incrementing from v0.14.0 which shipped Milestone N).

> Mutation-driven test hardening for already-managed files. The Saboteur discovers semantic gaps, the Archaeologist translates them to constraints, the Mason writes targeted tests to close them.

## Problem

After takeover (Milestone N), test coverage is frozen at whatever the Mason produced during the initial adversarial validation. There is no path to grow coverage incrementally. Users who want better tests must re-run the full adversarial pipeline manually, which regenerates everything from scratch.

Meanwhile, "test scum" -- tests that pass but don't prove anything useful -- can survive the initial pass. A test that asserts `result is not None` technically passes but doesn't catch `delay *= 1` replacing `delay *= 2`.

## Approach

`/unslop:cover` inverts the adversarial pipeline. Instead of generating tests and then validating them with mutations (N's flow), it runs mutations first to discover what the existing tests miss, then generates targeted tests to close the gaps.

**Key inversion:** The Saboteur is a discovery engine, not a validation gate.

---

## Pipeline

```
1. Saboteur (Strategic Mutation)
   Input:  managed source file + existing tests
   Action: generate up to N mutations (budget), prioritising high-entropy areas
   Output: mutation report (killed / survived / equivalent)

2. Prosecutor (Equivalence Filter + Routing)
   Input:  surviving mutants
   Action: heuristic + LLM classification (existing v0.12.0 infrastructure)
   Output: three streams:
           - equivalent: discarded (do not consume budget)
           - weak_test: route to Mason (Step 4) with existing constraint + mutant
           - spec_gap: route to Archaeologist (Step 3) for new constraint discovery

3. Archaeologist (Diff-Mode Discovery) -- spec_gap survivors only
   Input:  spec_gap mutants + existing behaviour.yaml + spec + source + existing tests
   Action: for each survivor, identify the missing behavioural constraint
           The mutation report is the primary signal for gap identification.
           Existing tests are read to confirm the constraint is genuinely untested.
   Output: enriched behaviour.yaml with new constraints

4. Mason (Targeted Test Generation) -- both streams converge here
   For spec_gap survivors:
     Input: new behaviour.yaml constraints ONLY (Chinese Wall enforced)
     Action: write tests targeting the new constraints
   For weak_test survivors:
     Input: existing behaviour.yaml constraint + surviving mutant description
     Action: strengthen assertions against the existing constraint
   Output: new/updated test functions marked @unslop-incidental

5. Validator (Two-Phase)
   5a. Run new tests against ORIGINAL code
       - Pass: constraint is real. Proceed to 5b.
       - Fail: FALSE REQUIREMENT. Archaeologist hallucinated a constraint
         the code doesn't satisfy. Revert behaviour.yaml change, discard
         test, log the false positive. Try next mutant.
   5b. Run new tests against each MUTANT
       - Fail (test catches mutant): killed. Success.
       - Pass (test doesn't catch): weak test. Mason retries (max 3).
       - Retries exhausted: log mutant as "uncloseable." Keep the
         behaviour.yaml constraint (it's real, just hard to test
         via black-box methods). Skip to next mutant.

6. Triage Summary (User Approval)
   Present each discovered constraint with:
   - Semantic meaning first ("Retry delay must increase between attempts")
   - Mutation evidence second ("Changing delay *= 2 to delay *= 1 on line 47
     was not caught by any existing test")
   - Choice: [Approve as Requirement] or [Keep as Incidental]
   Approved: promote to spec.md
   Incidental: retain @unslop-incidental marker on tests

7. Atomic Commit
   Commit: enriched behaviour.yaml + new tests + spec updates (if approved)
```

---

## Key Design Decisions

### 1. Mutation-only (no external coverage tools)

Line coverage is a ghost metric -- it tells you the code was executed, not that anything useful was asserted. Mutation testing proves functional consequence: if you can change a `>` to `>=` and no test breaks, you have a real semantic gap.

This also means zero external dependencies. No `pytest-cov`, no `.coveragerc`, no framework-specific coverage tooling. The Saboteur already exists.

### 2. Saboteur-first pipeline

In Milestone N, the flow is: Architect -> Builder -> Mason -> Saboteur (validation gate). In Milestone O, the flow is: Saboteur -> Prosecutor -> Archaeologist -> Mason (discovery engine).

The surviving mutants drive the Archaeologist's analysis. Instead of guessing where the spec might be weak, the Archaeologist is looking at a concrete implementation failure -- forensic discovery, not creative writing.

### 3. Split-path enrichment

- **behaviour.yaml**: enriched automatically. The Mason needs the new constraints to write tests.
- **spec.md**: user-approved only. Discovered invariants are proposed, not auto-committed.

This prevents implementation-leak into the abstract spec. Not every behaviour of the current code is a requirement -- some are incidental. Only the user can make that distinction.

### 4. The `@unslop-incidental` marker

Tests generated by `/unslop:cover` that the user does not promote to spec requirements are marked:

```python
# @unslop-incidental -- generated by /unslop:cover, not backed by spec constraint.
# Safe to update or remove during sync if behaviour changes legitimately.
def test_retry_limit_enforced():
    ...
```

**Builder policy:**
- **Spec-backed tests**: if they fail, the Builder must fix the code. These are hard gates.
- **Incidental tests** (`@unslop-incidental`): if they fail during sync/generate, the Builder may update or remove them if the new code follows the (updated) spec. These are soft assertions.

This prevents "implementation locking" where today's hardening becomes tomorrow's technical debt. The project can evolve without being held hostage by tests that document incidental behaviour.

#### Marker lifecycle

**Detection:** The Builder scans test files for the `# @unslop-incidental` comment marker using string matching (same approach as `@unslop-managed` header detection). No AST or decorator required.

**test_policy integration:** The generation skill's test_policy for generate/sync gains a carve-out:

- Current: `"Do NOT create or modify test files."`
- Updated: `"Do NOT create or modify spec-backed test files. Tests marked @unslop-incidental may be updated or removed if they fail against regenerated code that correctly follows the spec."`

**Coexistence with `@unslop-adversarial`:** Tests generated by `/unslop:adversarial` (full pipeline from scratch) are spec-backed by default -- they were generated from the behaviour.yaml during takeover and validated by the Saboteur. They do NOT carry the `@unslop-incidental` marker. Only tests generated by `/unslop:cover` where the user chose "Keep as Incidental" carry the marker.

**Promotion:** If the user later runs `/unslop:cover` and approves a previously-incidental constraint, the corresponding test's `@unslop-incidental` marker is removed -- it becomes a spec-backed test.

**Who updates failing incidental tests during sync:** The Builder. When a regenerated file causes incidental tests to fail, the Builder may update or remove them as part of its generation pass. This is the only exception to the "do not modify test files" rule.

### 5. Mutation budget

Default: **20 actionable mutations** per run. Equivalent mutants (classified by the Prosecutor) do not count against the budget -- they're free.

**Strategic selection:** The Saboteur prioritises high-entropy areas:
- Boundary conditions (`<` vs `<=`, `>` vs `>=`)
- Logical inversions (`not x` vs `x`, `and` vs `or`)
- Empty blocks (removing a side-effect call, replacing a function body with `pass`)
- Error handling paths (removing `raise`, swapping exception types)

Distribution: if the budget is 20, the Saboteur picks ~5 mutations from each of the 4 most complex functions (by branch count). Single-function files get all 20.

Configurable in `.unslop/config.json` as `mutation_budget`. Set to 0 for exhaustive mode. CLI override: `--budget N` or `--exhaustive`.

### 6. Two-phase validation

The Validator runs each new test in two phases:

1. **Against original code** (5a): the test must PASS. If it fails, the Archaeologist hallucinated a constraint the code doesn't actually satisfy. This is a "false requirement" -- revert and move on.
2. **Against the mutant** (5b): the test must FAIL. If it passes, the test is too weak to catch the mutation. The Mason retries with more specific guidance.

This two-phase structure is the guarantee that we never commit a test that's wrong about what the code does today (phase 1) or too weak to catch changes (phase 2).

### 7. Triage summary format

```
Found 4 semantic gaps in src/retry.py:

1. Retry delay must increase between attempts
   Evidence: changing `delay *= 2` to `delay *= 1` (line 47) not caught
   [Approve as Requirement] [Keep as Incidental]

2. TimeoutError must propagate, not be swallowed
   Evidence: removing `raise` from except block (line 63) not caught
   [Approve as Requirement] [Keep as Incidental]

3. Max retry attempts is exactly 3
   Evidence: changing `attempt > 3` to `attempt > 4` (line 82) not caught
   [Approve as Requirement] [Keep as Incidental]

4. Jitter must be non-negative
   Evidence: changing `random.uniform(0, 1)` to `random.uniform(-1, 1)` (line 51) not caught
   [Approve as Requirement] [Keep as Incidental]
```

Semantic meaning first, mutation evidence second. The user stays in the architect mindset, using the code diff only as a receipt for the discovery.

---

## Command Interface

```
/unslop:cover <managed-file-or-spec>           # run with default budget (20)
/unslop:cover src/retry.py --budget 50         # custom budget
/unslop:cover src/retry.py --exhaustive        # unlimited mutations
```

**Scope:** Single file only in v0.15.0. Multi-file iteration (`--stale` or `--all`) deferred to v0.16.0. The natural extension follows the same pattern as `/unslop:sync --stale-only` -- iterate in dependency order, run cover per-file, present triage per-file.

**Preconditions:**
- File must be under spec management (`@unslop-managed` header present)
- File must have existing tests (otherwise use `/unslop:takeover` first)
- `.unslop/config.json` must exist

**Output:**
- Enriched `*.behaviour.yaml`
- New test functions (with `@unslop-incidental` or spec-backed markers)
- Updated `*.spec.md` (only for approved constraints)
- Triage report to stdout

---

## Interaction with Other Commands

| Command | Relationship |
|---|---|
| `/unslop:takeover` | Produces the initial tests. `/unslop:cover` hardens them afterward. |
| `/unslop:harden` | Tightens the spec (add constraints). `/unslop:cover` tightens the tests. |
| `/unslop:generate` | Regenerates code. Respects `@unslop-incidental` markers during test policy. |
| `/unslop:sync` | Same as generate for single files. Incidental tests may be updated. |
| `/unslop:adversarial` | Full pipeline from scratch. `/unslop:cover` is additive. |

**The quality improvement workflow:**
1. `/unslop:harden <spec>` -- tighten the spec
2. `/unslop:cover <file>` -- grow test coverage for gaps
3. `/unslop:generate` -- regenerate code from tightened spec

Harden enriches the spec, cover enriches the tests, generate regenerates the code. Three commands, three concerns, no overlap.

---

## Diff-Mode Archaeologist

The Archaeologist operates differently in `/unslop:cover` than in `/unslop:takeover`:

| Aspect | Takeover (N) | Cover (O) |
|---|---|---|
| **Who writes behaviour.yaml** | The Architect (during Double-Lift) | The Archaeologist (diff-mode) |
| **Input** | Source code + spec (extraction from scratch) | Surviving mutants + existing behaviour.yaml + spec |
| **Goal** | Extract ALL behavioural intent | Find ONLY the uncovered constraints |
| **Output** | Complete behaviour.yaml | Delta: new constraints appended to existing behaviour.yaml |

The diff-mode Archaeologist answers one question per surviving mutant: "What constraint in the behaviour.yaml, if it existed, would have forced the Mason to write a test that kills this mutant?"

This is a translation problem, not an extraction problem. The input is a concrete code change (the mutation) and the output is a declarative constraint.

---

## Files Changed

### New
- `unslop/commands/cover.md` -- command definition, argument parsing, pipeline orchestration
- `docs/superpowers/specs/2026-03-23-cover-design.md` -- this document

### Modified
- `unslop/skills/adversarial/SKILL.md` -- add Archaeologist diff-mode section, Prosecutor routing split, strategic mutation selection
- `unslop/skills/generation/SKILL.md` -- update test_policy for `@unslop-incidental` lifecycle and carve-out
- `unslop/commands/init.md` -- add `mutation_budget` to config template
- `unslop/commands/sync.md` -- reference incidental test handling (test_policy change is centralised in generation skill but sync command docs should note the exception)
- `unslop/.claude-plugin/plugin.json` -- version bump to 0.15.0, add cover to command list

---

## Assumptions to Validate

1. **A1: 20 mutations per file is sufficient to find meaningful gaps.** Validate against the dirty scaffold (stress-tests/dirty-jitter/) -- does a 20-mutation budget catch the 3 known bugs?

2. **A2: The Archaeologist can reliably translate a surviving mutant into a behaviour.yaml constraint.** This is the core hypothesis. If the Archaeologist frequently hallucinates constraints (caught by the two-phase validator), the pipeline burns budget on false positives.

3. **A3: The `@unslop-incidental` marker doesn't create confusion.** Users need to understand the difference between spec-backed and incidental tests. The triage summary must make this clear.

4. **A4: Strategic mutation selection outperforms random selection.** The entropy-based prioritisation (boundary conditions, logical inversions, empty blocks, error paths) should find more gaps per mutation than random line selection.
