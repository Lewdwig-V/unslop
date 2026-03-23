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

### Phase 1: Double-Lift Raise (existing takeover Steps 1-2b, modified)

```
Inputs:  source code, project principles
Outputs: *.spec.md, *.impl.md (ephemeral), *.behaviour.yaml (NEW)
```

The takeover Architect reads the code and produces three artifacts through a **Double-Lift** strategy:

**Lift 1: Code -> Concrete Spec (`*.impl.md`)**

Faithful extraction of the current implementation -- algorithms, patterns, type structure, edge cases. This is the "How" layer. Bugs and all. Do not idealize.

**Lift 2: Concrete Spec -> Abstract Spec (`*.spec.md`) + Behaviour YAML (`*.behaviour.yaml`)**

From the concrete spec, extract observable behaviour into two formats:
- Abstract Spec: human-readable intent (unchanged from today)
- Behaviour YAML: structured constraints for the Mason (NEW)

The two-lift strategy is more accurate than jumping from code to abstract spec directly, because the intermediate concrete spec forces the Architect to distinguish between intentional algorithmic choices and incidental implementation details.

#### Legacy Smell Detection

Between Lift 1 and Lift 2, the Architect cross-checks every extracted behaviour against project principles (`.unslop/principles.md`). Any behaviour that **contradicts a principle** is flagged as a **Legacy Smell** -- not an invariant.

```
Legacy Smell Detection:
  For each constraint in behaviour.yaml:
    If constraint contradicts a project principle:
      Flag as: "legacy_smell"
      Do NOT encode as invariant
      Surface to user: "Extracted behaviour X contradicts principle Y.
        This appears to be a bug in the original code, not intended behaviour.
        Exclude from behaviour.yaml? (y/n)"
```

Example: If principles say "never retry on client errors (4xx)" but the code retries on 404, the Architect flags `"retry on 404"` as a legacy smell rather than encoding it as `given: "response.status == 404" then: "retry"`.

This prevents the adversarial pipeline from generating tests that **protect bugs** -- the single most dangerous failure mode for testless takeover.

**Behaviour YAML requirements during takeover:**
- Must include at least one `given`/`when`/`then` constraint per public function
- Must include `error` entries for every exception the code raises
- Must include `invariant` entries for state consistency properties
- Must NOT include constraints flagged as legacy smells (unless user overrides)
- Must pass `validate_behaviour.py` structural validation

**User approves all three artifacts** before proceeding. Legacy smells are surfaced explicitly -- the user decides whether to preserve or discard each one.

### Phase 2: Generate with Snapshot Lockdown (existing takeover Steps 3-4, modified)

```
Inputs:  *.spec.md, *.impl.md, principles
Outputs: managed source file, API snapshot (NEW)
```

Archive the original (unchanged). Dispatch Builder in worktree (unchanged).

**Key change: `test_policy: "snapshot"`**

Instead of "skip" (no validation) or "run" (requires tests), the Builder operates under **Snapshot Lockdown**:

1. Before generation, the Orchestrator captures a **JSON Snapshot** of the original module's public API outputs:

```python
# orchestrator: capture_api_snapshot(module_path) -> dict
{
  "module": "src.retry",
  "public_functions": {
    "retry": {
      "signature": "(fn, *, max_retries=3, base_delay=1.0, max_delay=60.0, rng=None, sleep=None)",
      "return_annotation": "Any",
      "raises": ["Exception"],
    }
  },
  "public_classes": {},
  "module_level_names": ["retry"],
}
```

2. After the Builder generates code, the Orchestrator captures the same snapshot of the new module and **diffs them**.

3. **DONE is redefined:** The new code must match the snapshot's public API shape exactly -- same function signatures, same public names, same exception types. Internal implementation can differ freely. This catches:
   - Missing functions (Builder forgot to implement something)
   - Changed signatures (Builder altered the contract)
   - Missing exports (Builder made something private that was public)

This is NOT a full I/O equivalence test -- that would require running the code with inputs, which is the Mason's job. It's a structural contract check that replaces the "does it import" smoke test with something meaningful.

**Risk: Snapshot is too shallow -- catches structural drift but not behavioural drift.**

Mitigation: The snapshot is a minimum bar, not the acceptance gate. The adversarial pipeline (Phase 3) is the real validation. The snapshot prevents the Builder from shipping obviously wrong code into the adversarial pipeline.

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

**Tangled Dependency Resolution:** Legacy files often import internal modules deeply. The mock budget may reject every test the Mason writes. Resolution strategy:

1. **Managed dependencies get an Integration Pass.** If an imported internal module is already under unslop management (`@unslop-managed` header present), the Mason may use it directly in tests without mocking. It's spec-managed, therefore its behaviour is contractual.

2. **Unmanaged dependencies trigger cascading takeover.** If the blocking dependency is NOT managed, the Architect recommends taking it over first:

> "Cannot test `src/client.py` in isolation -- it depends on `src/auth.py` which is not under spec management. Run `/unslop:takeover src/auth.py` first, then retry."

3. **User escape hatch:** Add the blocking module to `boundaries.json` as an explicit "internal boundary" -- acknowledging the coupling but allowing the takeover to proceed. This is a conscious trade-off, not an automatic bypass.

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

### Phase 4: Convergence with Entropy Threshold (modified from existing Step 6)

The convergence loop now crosses THREE stages instead of two:

```
Iteration:
  Architect enriches behaviour.yaml (if spec_gap)
  -> Mason generates new tests (if weak_test or spec_gap)
  -> Run tests against code
  -> If tests fail: Builder re-generates code with diagnostic cache
  -> Saboteur re-validates
  -> Measure entropy delta
  -> [pass/fail/stall]
```

#### Entropy Threshold (anti-oscillation)

Each iteration tracks the **mutant kill rate** (mutants killed / total mutants). If an iteration fails to improve the kill rate by more than 5%, the loop has stalled -- the Mason and Architect are making micro-adjustments that don't meaningfully improve coverage.

On stall detection:

```
Stall detected (iteration N killed M% vs iteration N-1 killed M-1%, delta < 5%).

Action: Radical Spec Hardening
  1. Prosecutor summarizes ALL surviving mutants as a batch
  2. Architect rewrites behaviour.yaml from scratch using:
     - Original abstract spec
     - Prosecutor's surviving mutant summary
     - Previous behaviour.yaml (as reference, not template)
  3. Mason generates tests from the rewritten behaviour.yaml
  4. If this also stalls: DONE_WITH_CONCERNS (report surviving mutants)
```

Radical spec hardening is a one-shot reset -- it doesn't loop. If the rewrite also stalls, the pipeline accepts partial mutation coverage and surfaces surviving mutants as concerns.

**Maximum iterations:** 3 normal + 1 radical hardening = 4 total. On exhaustion, same abandonment state as today -- keep all artifacts, let user intervene.

### Phase 5: Commit (modified from existing Step 5)

Atomic commit includes:
- `*.spec.md` (abstract spec)
- `*.impl.md` (concrete spec, if promoted)
- `*.behaviour.yaml`
- Generated source code (with `@unslop-managed` header)
- Generated test file(s)

After this commit, the file is under full spec management with tests. Subsequent generate/sync cycles use the standard `test_policy: "do NOT modify test files"`.

## Assumptions to Validate

These assumptions must hold for the design to work. Each should be tested during implementation against the dirty jitter scaffold.

### A1: Double-Lift produces good behaviour.yaml and catches legacy smells

**Test:** Run the raise phase on a buggy `retry_v1.py` that retries on 404 errors (violating principles). Does the Architect:
- Extract the 404 retry as a behaviour?
- Cross-check against principles and flag it as a legacy smell?
- Exclude it from the behaviour.yaml (unless user overrides)?

**Failure mode:** Architect encodes the 404 retry as an invariant. Mason writes tests protecting the bug. Saboteur validates those tests. The bug is now spec-protected.

**Fallback:** If legacy smell detection is unreliable, require the Archaeologist as a second pass with explicit "smell audit" instructions. Redundant but safer.

### A2: Snapshot Lockdown catches structural drift without tests

**Test:** Run the Builder on `retry.py.spec.md` with test_policy snapshot. Intentionally break the function signature in the spec. Does the snapshot diff catch it?

**Failure mode:** Snapshot is too shallow -- misses renamed parameters, changed defaults, or altered return types that the structural check doesn't cover.

**Fallback:** Extend the snapshot to include default values and type annotations, not just function names and positional signatures. Or: generate a synthetic "canary test" that calls each public function with its default args and asserts no exception.

### A3: Mason generates useful tests from machine-drafted behaviour.yaml

**Test:** Feed the Architect's behaviour.yaml for retry.py to the Mason. Do the tests cover the key constraints? Do they pass against the generated code?

**Failure mode:** Machine-drafted behaviour.yaml uses vague constraint language ("handles errors") that the Mason interprets too narrowly (single test for one error type). The Saboteur catches surviving mutants, but convergence oscillates.

**Fallback:** Entropy threshold triggers radical spec hardening. If that also fails, the user tightens the behaviour.yaml manually.

### A4: Mock budget works for takeover targets with tangled dependencies

**Test:** Take over a file that imports internal modules. Can the Mason write useful tests using the Integration Pass (managed deps allowed) without mocking internals?

**Failure mode:** The file's dependencies are not managed. Every test gets rejected. The cascade recommendation ("take over deps first") is correct but annoying for large dependency trees.

**Fallback:** The user adds blocking modules to boundaries.json as internal boundaries. This is an explicit trade-off -- documented, not silent. For deeply coupled files, recommend extracting a boundary interface before takeover.

### A5: Convergence with entropy threshold terminates correctly

**Test:** Run the full pipeline on the dirty scaffold. Does it converge? Does the entropy threshold trigger? Does radical hardening help?

**Failure mode:** Radical hardening produces a behaviour.yaml that's too different from the original -- the Mason generates incompatible tests, and the loop terminates with DONE_WITH_CONCERNS after 4 iterations.

**Fallback:** Accept DONE_WITH_CONCERNS as a valid outcome for legacy code. The file is under spec management with partial mutation coverage. The user can run `/unslop:cover` later to grow coverage incrementally.

## Scope of Changes

### Takeover Skill (`unslop/skills/takeover/SKILL.md`)

- Step 1: Remove "stop and warn" for no tests. Replace with automatic testless routing.
- Step 2: Add Double-Lift with legacy smell detection. Add behaviour.yaml generation.
- Step 4: Add `test_policy: "snapshot"` with API snapshot capture + diff.
- New Step 5: Adversarial pipeline invocation after Builder DONE.
- Step 6: Update convergence loop to three stages + entropy threshold + radical hardening.
- Atomic commit: Include behaviour.yaml and generated tests.

### Takeover Command (`unslop/commands/takeover.md`)

- Detect test absence automatically (check for test files matching the target).
- No `--no-tests` flag -- testless takeover is the default when no tests found.
- Add `--skip-adversarial` flag as escape hatch.

### Generation Skill (`unslop/skills/generation/SKILL.md`)

- Add `test_policy: "snapshot"` to the policy table.
- Document what DONE means in snapshot mode (API shape matches, no test validation).

### Adversarial Skill (`unslop/skills/adversarial/SKILL.md`)

- Add "takeover mode" section.
- Document Integration Pass for managed dependencies.
- Document entropy threshold and radical hardening.

### Orchestrator (`unslop/scripts/orchestrator.py`)

- New subcommand: `capture-api-snapshot <module-path>` -- captures public API shape as JSON.
- New subcommand: `diff-api-snapshot <old.json> <new.json>` -- diffs two snapshots.

### Config (`init.md`)

- Add `adversarial_max_iterations` to config template (default: 3).
- Add `mutation_tool` to config template (default: "mutmut").
- Add `entropy_threshold` to config template (default: 0.05).

## What This Does NOT Cover

- **Partial coverage** (file has some tests): Use standard takeover, then `/unslop:cover` to grow coverage.
- **Files where mutation testing is impractical** (pure I/O, GUI): Use `--skip-adversarial`.
- **Multi-file testless takeover**: Same flow, behaviour.yaml covers the unit. Validate separately.
- **Prosecutor suggesting code refactors**: Out of scope. Prosecutor classifies mutants only. Refactoring recommendations are the Architect's job.

## Dirty Scaffold Validation Plan

Build a deliberately buggy `retry_v1.py` in the stress-test project:

1. **Bug 1:** Retries on HTTP 404 (client error -- should not retry)
2. **Bug 2:** No max_delay cap (delay grows unbounded on high attempt counts)
3. **Bug 3:** Catches `BaseException` instead of `Exception` (swallows KeyboardInterrupt)

Add project principles that contradict each bug:
- "Never retry on client errors (4xx status codes)"
- "All delays must have a finite upper bound"
- "Never catch BaseException -- use Exception for retry logic"

Then run each phase manually:
1. Does the Double-Lift flag all three as legacy smells?
2. Does the snapshot catch structural drift if the Builder changes the signature?
3. Does the Mason's blind test catch the bugs (or at least not protect them)?
4. Does the Saboteur kill mutants that change the 404/cap/BaseException logic?
5. Does the entropy threshold prevent oscillation?
6. How many iterations to converge?
