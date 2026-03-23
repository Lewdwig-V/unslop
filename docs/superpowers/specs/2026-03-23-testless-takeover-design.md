# Testless Takeover Design (Milestone N)

> Bring files without tests under spec management by chaining the existing takeover pipeline into the adversarial quality pipeline. The Mason writes tests from behaviour constraints, not from code -- structurally preventing tautological tests.

## Problem

`/unslop:takeover` currently stops at Step 1 when no tests are found:

> "Takeover without tests means the spec is unvalidated. The convergence loop cannot run."

The user must write tests manually before takeover can proceed. This blocks adoption for legacy codebases where testless files are the norm, not the exception.

## Why the v0.10.x "test case manifest" approach was wrong

The original design had the Builder generate both code and tests from a manifest. This fails because:

1. **Same agent writes both** -- the Builder can produce tautological tests (assert what it generates)
2. **No structural enforcement** -- prompt-based "don't write tautological tests" is probabilistic
3. **No validation of test quality** -- no mutation testing to verify tests actually catch regressions

## Solution: Adversarial pipeline as takeover gate

The v0.12.0 infrastructure already solves all three problems:

- **Chinese Wall** -- Mason writes tests from behaviour.yaml without seeing source code
- **Mock Budget Linter** -- AST-level rejection of internal mocks prevents test scumming
- **Saboteur** -- mutation testing validates that tests catch real behavioural changes
- **Prosecutor** -- equivalent mutant classification prevents false failures

The design chains these existing components into the takeover flow. No new agents or skills needed.

## Detailed Flow

### Phase 1: Raise (existing takeover Steps 1-2b, modified)

```
Inputs:  source code, project principles
Outputs: *.spec.md, *.impl.md (ephemeral), *.behaviour.yaml (NEW)
```

The takeover Architect reads the code and produces three artifacts:

1. **Abstract Spec** (`*.spec.md`) -- behavioural intent (unchanged from today)
2. **Concrete Spec** (`*.impl.md`) -- algorithmic strategy (unchanged from today)
3. **Behaviour YAML** (`*.behaviour.yaml`) -- NEW: structured constraints for the Mason

The Architect writes the behaviour.yaml during the raise phase, not the Archaeologist. Rationale: the Architect is already reading the code and extracting intent. The Archaeologist's role (extracting from *generated* code) is for post-takeover adversarial runs.

**Behaviour YAML requirements during takeover:**
- Must include at least one `given`/`when`/`then` constraint per public function
- Must include `error` entries for every exception the code raises
- Must include `invariant` entries for state consistency properties
- Must pass `validate_behaviour.py` structural validation

**User approves all three artifacts** before proceeding. This is one extra artifact vs today (the behaviour.yaml), but it's a natural extension of the existing approval step.

### Phase 2: Generate (existing takeover Steps 3-4, modified)

```
Inputs:  *.spec.md, *.impl.md, principles
Outputs: managed source file
```

Archive the original (unchanged). Dispatch Builder in worktree (unchanged).

**Key change: `test_policy: "skip"`**

The Builder generates code from the spec but does NOT run tests (there are none yet). It reports DONE based solely on successful generation, not test results.

This changes the DONE contract: normally DONE means "tests green." For testless takeover, DONE means "code generated, structurally valid, no compile errors." The adversarial pipeline takes over test validation.

**Risk: Builder generates garbage with no feedback loop.**

Mitigation: The concrete spec constrains the implementation strategy (algorithm, patterns, type structure). The Builder has enough guidance to produce reasonable code even without test feedback. If the concrete spec is thin, the code may drift from intent -- but the Saboteur catches this in Phase 3.

**Open question: should the Builder attempt to run a basic "does it import" smoke test even in skip mode?** This catches syntax errors and missing imports without requiring a test suite. Leaning yes -- `python -c "import <module>"` is cheap and catches obvious failures.

### Phase 3: Adversarial Validation (NEW step, replaces test-run verification)

```
Inputs:  *.behaviour.yaml, generated source code
Outputs: test_*.py, mutation results
```

This is the standard adversarial pipeline, triggered automatically (not via `/unslop:adversarial`):

**Step 3a: Mason generates tests**

The Mason reads ONLY the behaviour.yaml. It cannot see the generated source code (Chinese Wall). It writes black-box tests that exercise the constraints.

Mock budget is enforced: the Mason must declare which external dependencies it mocks via `.unslop/boundaries.json`. Internal module mocks are hard rejected.

**Step 3b: Mock Budget Lint**

`validate_mocks.py` runs against the generated tests. If any test mocks an internal module, it's rejected. The Mason retries without the offending mock.

**Step 3c: Run tests against generated code**

The Mason's tests are executed against the Builder's generated code. This is the first time the tests and code meet.

Possible outcomes:
- **All green**: Proceed to mutation testing (Step 3d)
- **Failures**: The Mason's tests expose a gap between the behaviour.yaml and the generated code. Route to convergence (Phase 4).

**Step 3d: Saboteur runs mutation testing**

The Saboteur mutates the generated source code and runs the Mason's tests against each mutant. The Prosecutor classifies surviving mutants.

Possible outcomes:
- **All mutants killed or classified equivalent**: Tests are strong. Proceed to commit.
- **Weak tests identified**: Mason retries with surviving mutant guidance
- **Spec gaps identified**: Architect enriches behaviour.yaml, Mason retries

### Phase 4: Convergence (modified from existing Step 6)

The convergence loop now crosses THREE stages instead of two:

```
Iteration:
  Architect enriches behaviour.yaml (if spec_gap)
  -> Mason generates new tests (if weak_test or spec_gap)
  -> Run tests against code
  -> If tests fail: Builder re-generates code with diagnostic cache
  -> Saboteur re-validates
  -> [pass/fail]
```

**Important: the convergence loop can trigger BOTH spec enrichment AND code regeneration in the same iteration.** If the Mason's new tests expose a code bug (not a spec gap), the Builder must regenerate. The diagnostic cache (`{previous_failure}`) carries the context.

Maximum 3 iterations (unchanged). On exhaustion, same abandonment state as today -- keep all artifacts, let user intervene.

### Phase 5: Commit (modified from existing Step 5)

Atomic commit includes:
- `*.spec.md` (abstract spec)
- `*.impl.md` (concrete spec, if promoted)
- `*.behaviour.yaml`
- Generated source code (with `@unslop-managed` header)
- Generated test file(s)

After this commit, the file is under full spec management with tests. Subsequent generate/sync cycles use the standard `test_policy: "do NOT modify test files"`.

## Assumptions to Validate

These assumptions must hold for the design to work. Each should be tested during implementation against the jitter stress-test project.

### A1: The Architect produces good behaviour.yaml from legacy code

**Test:** Run the raise phase on `stress-tests/jitter/src/retry.py` (pretend it has no tests). Does the behaviour.yaml capture: retry count semantics, delay bounds, jitter distribution, injectability, error propagation?

**Failure mode:** Architect misses constraints that the tests currently enforce (e.g., "delay can be zero"). The Mason then writes tests without those constraints, and the Saboteur catches them as spec gaps -- but only if mutmut generates mutations that hit those paths.

**Fallback:** If the Architect's behaviour.yaml is consistently weak, we may need the Archaeologist as a separate pass (redundant code reading, but more thorough extraction).

### A2: `test_policy: "skip"` doesn't break Builder invariants

**Test:** Run the Builder on `retry.py.spec.md` with test_policy skip. Does it produce valid code? Does it report DONE correctly?

**Failure mode:** The Builder's convergence logic assumes test output is available. With skip, it may get confused about iteration state or report incorrect status.

**Fallback:** Instead of "skip", use a synthetic "always-pass" test that just imports the module. This gives the Builder its expected test feedback without requiring real tests.

### A3: Mason generates useful tests from machine-drafted behaviour.yaml

**Test:** Feed the Architect's behaviour.yaml for retry.py to the Mason. Do the tests cover the key constraints? Do they pass against the generated code?

**Failure mode:** Machine-drafted behaviour.yaml uses vague constraint language ("handles errors") that the Mason interprets too narrowly (single test for one error type). The Saboteur then catches surviving mutants, but the convergence loop may not converge if the enrichment is also vague.

**Fallback:** Require human review of the behaviour.yaml before Mason runs (this is already in the flow -- user approval step). The user can tighten vague constraints.

### A4: Mock budget works for takeover targets

**Test:** Take over a file with tangled dependencies (e.g., a file that imports 5 internal modules). Can the Mason write useful tests without mocking internals?

**Failure mode:** The Mason can only mock stdlib and declared boundaries. If the file under test has deep internal dependencies, the Mason may not be able to construct a test scenario without mocking them. Every test gets rejected by the mock budget.

**Fallback options:**
1. The boundaries.json can be expanded to include "internal boundaries" -- modules treated as external for testing purposes. This is an explicit user decision, not an automatic bypass.
2. The `/unslop:cover` command (Milestone O) can be used after takeover to add tests incrementally, starting with the most testable functions.
3. For deeply coupled files, recommend refactoring (extract boundaries) before takeover.

### A5: Saboteur mutation testing converges within 3 iterations

**Test:** Run the full pipeline on retry.py. Does it converge? How many iterations?

**Failure mode:** The Mason writes tests that kill most mutants, but 2-3 surviving mutants cause spec_gap/weak_test cycles that don't converge. Each iteration adds tests but doesn't kill the remaining mutants because they require testing interaction effects, not single-function behaviour.

**Fallback:** Increase max iterations to 5 for testless takeover (more room for convergence). Or: accept partial mutation coverage and report surviving mutants as DONE_WITH_CONCERNS rather than blocking.

## Changes Required to Existing Components

### Takeover Skill (`unslop/skills/takeover/SKILL.md`)

- Step 1: Remove the "stop and warn" for no tests. Replace with automatic testless takeover routing.
- Step 2: Add behaviour.yaml generation to the raise phase.
- Step 4: Add `test_policy: "skip"` option to Builder dispatch.
- Step 5: Add adversarial pipeline invocation after Builder DONE.
- Step 6: Update convergence loop to cross three stages (Architect -> Mason -> Builder).
- Atomic commit: Include behaviour.yaml and generated tests.

### Takeover Command (`unslop/commands/takeover.md`)

- Detect test absence automatically (check for test files matching the target).
- No `--no-tests` flag -- testless takeover is the default when no tests found.
- Add `--skip-adversarial` flag for users who want to proceed without test generation (escape hatch).

### Generation Skill (`unslop/skills/generation/SKILL.md`)

- Add `test_policy: "skip"` to the policy table.
- Document what DONE means in skip mode (code generated, no test validation).
- Add import-smoke-test as a minimum validation for skip mode.

### Adversarial Skill (`unslop/skills/adversarial/SKILL.md`)

- Add "takeover mode" section documenting how the pipeline is invoked during takeover (automatically, not manually).
- Document that the behaviour.yaml comes from the takeover Architect, not the Archaeologist, in this mode.
- Document the three-stage convergence loop.

### Orchestrator (`unslop/scripts/orchestrator.py`)

- No changes expected. The orchestrator handles build order, freshness, and ripple checking -- none of which are affected by how tests are generated.

### Config (`init.md`)

- Add `adversarial_max_iterations` to config template (default: 3).
- Add `mutation_tool` to config template (default: "mutmut").

## What This Does NOT Cover

- **Partial coverage** (file has some tests): Use standard takeover, then `/unslop:cover` to grow coverage. Not a special mode.
- **Files where mutation testing is impractical** (pure I/O, GUI): Use `--skip-adversarial` escape hatch. Tests must be written manually.
- **Multi-file testless takeover**: Same flow, but the Mason generates tests for the entire unit. Behaviour.yaml covers all files in the unit spec. This is a natural extension but should be validated separately.

## Validation Plan

Before implementing, validate each assumption (A1-A5) against the jitter stress-test project:

1. Strip the tests from the jitter project: `git rm stress-tests/jitter/tests/test_retry.py`
2. Run the raise phase manually: draft spec + impl + behaviour.yaml for retry.py
3. Run the Builder with `test_policy: "skip"`: verify DONE contract
4. Run the Mason against the behaviour.yaml: verify test quality
5. Run the Saboteur: verify mutation coverage
6. Run full convergence: verify it converges within 3 iterations
7. Compare generated tests against the original tests: are they equivalent in coverage?

If any assumption fails, document the failure mode and refactor the affected component before proceeding to implementation.
