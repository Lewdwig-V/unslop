---
description: Grow test coverage on a managed file using mutation-driven discovery
argument-hint: <managed-file-or-spec> [--budget N] [--exhaustive]
---

**Parse arguments:** `$ARGUMENTS` contains the target path and optional flags. Extract the target (first non-flag argument) and flags:

- `--budget N` -- custom mutation budget (overrides config.json `mutation_budget`)
- `--exhaustive` -- unlimited mutations (equivalent to `--budget 0`)

Strip flags before using the path in subsequent steps.

If the target path ends in `.spec.md`, derive the managed file path by stripping `.spec.md`. Otherwise, treat the target as the managed file and derive the spec path by appending `.spec.md`.

**0. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the managed file exists and is under spec management (has an `@unslop-managed` header or a corresponding `*.spec.md`). If not:

> "This file is not under spec management. Use `/unslop:takeover` first."

Check that test files exist for the target. Search for test files using standard conventions (`tests/test_<name>.py`, `test_<name>.py`, `<name>_test.py`, or the test path referenced in `.unslop/config.json`). If no tests exist:

> "This file has no tests. Use `/unslop:takeover` to bring it under management with test generation, then run `/unslop:cover` to harden."

Check that `.unslop/boundaries.json` exists. If not, create it with an empty array `[]` and warn:

> "Created `.unslop/boundaries.json` with empty boundary list. Add your external dependencies to enable mock budget enforcement."

**1. Load context**

Read:
- The managed source file
- The `*.spec.md` (abstract spec)
- The `*.behaviour.yaml` (if it exists -- may not for files taken over before v0.14.0)
- The test file(s) for this managed file
- `.unslop/config.json` for `mutation_budget` (default 20) and `mutation_tool`
- `.unslop/boundaries.json` for mock budget enforcement

If no `*.behaviour.yaml` exists, inform the user and generate one first:

> "No behaviour.yaml found for this file. I'll extract one from the existing spec and tests before running coverage analysis."

Use the **unslop/adversarial** skill's Archaeologist in extraction mode (not diff-mode) to generate the initial behaviour.yaml from the spec and source. Present to the user for approval before proceeding.

**2. Saboteur: Strategic Mutation**

Use the **unslop/adversarial** skill's Strategic Mutation Selection (Cover Mode) to generate mutations against the managed source file.

Determine the budget:
- If `--exhaustive`: no limit
- If `--budget N`: use N
- Otherwise: read `mutation_budget` from config.json (default 20)

**Baseline check:** Before generating any mutations, run the existing test suite against the unmodified source file. If any tests fail, stop:

> "The test suite has failures against the current code. Fix the failing tests before running /unslop:cover -- mutation analysis requires a green baseline to distinguish real survivors from pre-existing failures."

Prioritise high-entropy areas:
1. Boundary conditions (`<` vs `<=`, `>` vs `>=`, `==` vs `!=`)
2. Logical inversions (`not x` vs `x`, `and` vs `or`)
3. Empty blocks (removing a side-effect call, replacing function body with `pass`)
4. Error handling paths (removing `raise`, swapping exception types, removing `except` blocks)

For files with multiple functions, distribute the budget across the most complex functions (by branch count). Single-function files get the full budget.

Run the existing test suite against each mutation. Record each mutant as: killed, survived, or errored.

If all mutants are killed: report "All mutants killed. Existing test suite covers the mutation budget for this file." and exit.

**3. Prosecutor: Filter and Route**

Pass surviving mutants to the Prosecutor for classification:

Write the surviving mutants to a temporary JSON file. Each mutant is an object with keys `original` (the original line), `mutated` (the mutated line), and `line` (the line number). Then invoke:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/prosecutor.py <managed-source-file> <mutants.json>
```

The Prosecutor returns a JSON summary with mutants grouped by verdict (`equivalent`, `weak_test`, `spec_gap`, `inconclusive`).

Route by verdict using the **unslop/adversarial** skill's Prosecutor Routing (Cover Mode):

- **equivalent**: discard. Does not consume the mutation budget.
- **weak_test**: queue for Mason (Step 5) with the existing behaviour.yaml constraint and the surviving mutant as guidance. The Archaeologist is skipped -- the constraint already exists, the test just needs strengthening.
- **spec_gap**: queue for Archaeologist diff-mode analysis (Step 4). A genuinely missing constraint needs to be identified before the Mason can write a test.

If no non-equivalent survivors remain: report "All surviving mutants are equivalent. Test suite is strong for this file." and exit.

**4. Archaeologist: Diff-Mode Discovery (spec_gap only)**

For each `spec_gap` survivor, use the **unslop/adversarial** skill's Archaeologist Diff-Mode (Cover Mode).

For each mutant, the Archaeologist answers: "What constraint, if it existed in the behaviour.yaml, would have forced the Mason to write a test that kills this mutant?"

Input per mutant:
- The mutation (original line, mutated line, line number)
- The source file (for surrounding context)
- The existing behaviour.yaml (to avoid duplicating existing constraints)
- The existing tests (to confirm the constraint is genuinely untested)
- The spec (to ground the new constraint in the project's intent language)

Output per mutant:
- A new `given`/`when`/`then`, `error`, `invariant`, or `property` entry for the behaviour.yaml
- A one-line semantic summary (for the triage report)

Append each new constraint to the `*.behaviour.yaml`.

**5. Mason: Targeted Test Generation**

For each surviving mutant (both `spec_gap` and `weak_test`):

Use the **unslop/adversarial** skill's Mason. The Mason receives ONLY the behaviour.yaml constraint and the surviving mutant description. **The Chinese Wall is enforced -- no source code access for the Mason.**

For `weak_test` mutants: the Mason strengthens assertions against the existing constraint, using the surviving mutant as guidance for what the test should catch.

For `spec_gap` mutants: the Mason writes a new test function from the Archaeologist's new constraint.

**Marker rules:**

- `weak_test` fixes: these tests strengthen an **existing** constraint that is already spec-backed. They do NOT get the `@unslop-incidental` marker -- they are spec-backed from creation, since the constraint they test was already approved.
- `spec_gap` fixes: these tests cover a **new** constraint discovered by the Archaeologist. They carry the `@unslop-incidental` marker until the user promotes the constraint to the spec:

```python
# @unslop-incidental -- generated by /unslop:cover, backed by behaviour.yaml but not yet promoted to spec.
# Safe to update or remove during sync if behaviour changes legitimately.
def test_<descriptive_name>():
    ...
```

Run mock budget validation on each new test:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_mocks.py <test-file> --project-root .
```

If mock budget violations are detected: Mason retries without the offending mock (max 2 rewrite attempts). If still violating after retries, discard the test and log the failure.

**6. Validator: Two-Phase Check**

For each new test function:

**Phase A -- test against original code:**

Run the new test against the unmodified managed file using the project's test command from config.json.

- **Pass**: the constraint is real. Proceed to Phase B.
- **Fail**: FALSE REQUIREMENT. The Archaeologist hallucinated a constraint the code does not satisfy. Revert the corresponding behaviour.yaml change, discard the test, log the false positive. Skip to the next mutant.

**Phase B -- test against mutant:**

Apply the specific mutation to the managed file and run the new test.

- **Fail** (test catches mutant): mutant killed. Success.
- **Pass** (test does not catch mutant): weak test. Mason retries with more specific guidance about what the test should assert (max 3 attempts per mutant).
- **Retries exhausted**: log mutant as "uncloseable." Keep the behaviour.yaml constraint (the constraint is real, just hard to test via black-box methods). Skip to the next mutant.

Restore the original source file after each Phase B check.

**7. Triage Summary**

Present all successfully validated constraints to the user:

```
Found N semantic gaps in <file>:

1. <Semantic meaning of the constraint>
   Evidence: changing `<original>` to `<mutated>` (line N) not caught by existing tests
   [Approve as Requirement] [Keep as Incidental]

2. <Semantic meaning>
   Evidence: removing `raise` from except block (line N) not caught
   [Approve as Requirement] [Keep as Incidental]

...

Uncloseable (kept as constraints but no test written): M
False positives (reverted): K
```

Wait for user choices on each constraint.

- **Approve as Requirement**: add the constraint to `*.spec.md` under an appropriate section, remove the `# @unslop-incidental` marker from the corresponding test function -- the test becomes spec-backed.
- **Keep as Incidental**: retain the `# @unslop-incidental` marker. Do NOT update `*.spec.md`.

**8. Atomic Commit**

Stage and commit together:
- Updated `*.behaviour.yaml` (all new constraints, regardless of approval choice)
- New test functions (with appropriate markers based on user choices)
- Updated `*.spec.md` (only for constraints the user approved as requirements)

Commit message: `cover: harden tests for <file> (N gaps found, M promoted to spec)`
