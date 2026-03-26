---
description: Grow test coverage on a managed file using mutation-driven discovery
argument-hint: <managed-file-or-spec> [--budget N] [--exhaustive]
---

**Parse arguments:** `$ARGUMENTS` contains the target path and optional flags. Extract the target (first non-flag argument) and flags:

- `--budget N` -- custom mutation budget (overrides config.json `mutation_budget`)
- `--exhaustive` -- unlimited mutations (equivalent to `--budget 0`)

Strip flags before using the path in subsequent steps.

If the target path ends in `.spec.md`, derive the managed file path by stripping `.spec.md`. Otherwise, treat the target as the managed file and derive the spec path by appending `.spec.md`.

**Load and follow** the **unslop/adversarial** skill step-by-step for Steps 2-5. Do not summarize or abbreviate the pipeline. Each step must execute via subagent dispatch with the prescribed inputs.

**HARD RULE: The Architect is the orchestrator. It dispatches subagents, invokes the Prosecutor script, runs mechanical validation, and presents triage. It does NOT generate mutations, analyze constraints, or write tests.**

Every persona runs as a subagent for two reasons:
1. **Context hygiene** -- the Architect's context stays clean for multi-file runs. Mutation details, constraint analysis, and test code live in subagent contexts and are returned as summaries.
2. **Chinese Wall (Mason only)** -- the Mason must not see source code. Tests must encode expected behaviour from the behaviour.yaml, not observed implementation.

If you find yourself writing mutations, analysing constraint gaps, or writing test code directly -- STOP. Dispatch the appropriate subagent.

**Subagent dependency chain (per file):**

```
Saboteur -> Prosecutor (script) -> Archaeologist -> Mason -> Validator (Architect)
                                   ^                  ^
                                   |                  |
                              spec_gap only      all survivors
                              weak_test skips ---/
                              directly to Mason
```

Each step's output is the next step's input. `weak_test` mutants bypass the Archaeologist (the constraint already exists, the test just needs strengthening) and go directly from Prosecutor to Mason. No parallelism within a single file's cover run.

**Multi-file parallelism:** When running `/unslop:cover` on multiple files sequentially, each file's pipeline is independent. The Architect MAY dispatch the next file's Saboteur while the current file's Mason is running, as long as it can track both pipelines. The Architect SHOULD maximize parallelism across independent files to reduce wall-clock time.

**Pipeline roles:**

```
Architect (this session):
  Orchestrator -- dispatches subagents, invokes Prosecutor script,
  runs mechanical validation (Phase A/B), presents triage.
  Writes no mutations, no constraints, no tests.
  Context stays clean for multi-file cover runs.

Saboteur (subagent):
  Receives: source file, test files, test command, budget
  Produces: mutations JSON + kill/survive results
  Rationale: context hygiene + unbiased mutation selection

Prosecutor (script -- deterministic):
  Receives: source file, surviving mutants JSON
  Produces: classified mutants JSON (equivalent/weak_test/spec_gap)

Archaeologist (subagent):
  Receives: source, spec, behaviour.yaml, classified spec_gap mutants
  Produces: new behaviour.yaml constraints
  Rationale: context hygiene (per-mutant analysis stays in subagent)

Mason (subagent, Chinese Wall):
  Receives: behaviour.yaml + mutant descriptions ONLY
  Produces: test code
  MUST NOT see: source code, abstract spec, Architect context
  Rationale: context hygiene + Chinese Wall (tests encode spec, not impl)
```

> **Anti-patterns (these are pipeline violations, not style preferences):**
>
> 1. **Inline mutation generation** -- The Architect generates mutations instead of dispatching a Saboteur subagent. Bloats context and biases mutations toward spec-covered areas.
> 2. **Inline constraint analysis** -- The Architect analyzes spec gaps instead of dispatching an Archaeologist. Bloats context with per-mutant reasoning that the Architect doesn't need.
> 3. **Inline test writing** -- The Architect writes test code directly instead of dispatching a Mason. Violates the Chinese Wall.
> 4. **Mason sees source** -- Passing the managed file or spec to the Mason. The Mason works from behaviour.yaml only.
> 5. **Skipping the Prosecutor** -- Manually classifying survivors instead of invoking `prosecutor.py`. The Prosecutor's classification is deterministic and auditable; inline classification is ad-hoc.
> 6. **Skipping behaviour.yaml** -- Writing tests without extracting or updating the behaviour.yaml first. The behaviour.yaml is the Mason's sole input.
> 7. **Architect editing Mason's tests** -- If a test is wrong, the constraint is wrong. Route back to the Archaeologist or Mason, don't fix inline.

---

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

The Architect reads only orchestration-level context (not source code or test content -- those stay in subagent contexts):
- The `*.spec.md` (abstract spec -- the Architect needs this for triage decisions)
- The `*.behaviour.yaml` (if it exists -- may not for files taken over before v0.14.0)
- `.unslop/config.json` for `mutation_budget` (default 20), `mutation_tool`, and subagent model keys (`saboteur`, `archaeologist`, `mason`)
- Determine file paths for the managed source file and test files (for passing to subagents -- do not read their content into the Architect's context)

If no `*.behaviour.yaml` exists, inform the user and dispatch an Archaeologist subagent in extraction mode:

> "No behaviour.yaml found for this file. Dispatching Archaeologist to extract one from the spec and source."

The Archaeologist subagent receives the source file, spec, and test files in its own context. It returns the behaviour.yaml content. Present to the user for approval before proceeding.

**2. Saboteur (subagent)**

Dispatch a Saboteur subagent with `model` from config (`saboteur` key). The Saboteur receives:
- The managed source file
- The test file(s)
- The test command from config
- The mutation budget:
  - If `--exhaustive`: no limit
  - If `--budget N`: use N
  - Otherwise: read `mutation_budget` from config.json (default 20)

The Saboteur does NOT receive the abstract spec or behaviour.yaml -- it works from source code structure only. This prevents spec-awareness from biasing mutation selection toward "interesting" areas the spec already covers.

**Baseline check:** The Saboteur runs the existing test suite against the unmodified source file first. If any tests fail, it reports failure and the Architect stops:

> "The test suite has failures against the current code. Fix the failing tests before running /unslop:cover -- mutation analysis requires a green baseline to distinguish real survivors from pre-existing failures."

The Saboteur generates mutations prioritizing high-entropy areas:
1. Boundary conditions (`<` vs `<=`, `>` vs `>=`, `==` vs `!=`)
2. Logical inversions (`not x` vs `x`, `and` vs `or`)
3. Empty blocks (removing a side-effect call, replacing function body with `pass`)
4. Error handling paths (removing `raise`, swapping exception types, removing `except` blocks)

The Saboteur runs the existing test suite against each mutation and returns a JSON summary of killed/survived/errored mutants.

If all mutants are killed: report "All mutants killed. Existing test suite covers the mutation budget for this file." and exit.

**3. Prosecutor: MANDATORY script invocation**

Do NOT classify survivors manually. Invoke the Prosecutor script:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/prosecutor.py <managed-source-file> <mutants.json>
```

Write the surviving mutants to a temporary JSON file first. Each mutant is an object with keys `original` (the original line), `mutated` (the mutated line), and `line` (the line number).

The Prosecutor returns a JSON summary with mutants grouped by verdict (`equivalent`, `weak_test`, `spec_gap`, `inconclusive`).

The Prosecutor's classification is deterministic and auditable. Inline classification is ad-hoc and influenced by the Architect's source knowledge. If the script is unavailable or errors, report the error and stop -- do not fall back to manual classification.

Route by verdict:

- **equivalent**: discard. Does not consume the mutation budget.
- **weak_test**: queue for Mason (Step 5) with the existing behaviour.yaml constraint and the surviving mutant as guidance.
- **spec_gap**: queue for Archaeologist analysis (Step 4). A genuinely missing constraint needs to be identified before the Mason can write a test.
- **inconclusive**: queue for Archaeologist analysis (Step 4), same as spec_gap. The Archaeologist has source context to resolve ambiguity that the deterministic Prosecutor could not.

If no non-equivalent survivors remain: report "All surviving mutants are equivalent. Test suite is strong for this file." and exit.

**4. Archaeologist (subagent)**

Dispatch an Archaeologist subagent with `model` from config (`archaeologist` key). The Archaeologist receives:
- The classified `spec_gap` mutants from the Prosecutor
- The managed source file (needs source context to identify semantic gaps)
- The existing behaviour.yaml
- The existing tests
- The abstract spec

The Archaeologist returns new behaviour.yaml constraints (given/when/then entries) -- not test code. Its output feeds into the Mason.

The Archaeologist runs as a subagent even though it produces constraints, not code. This is for context hygiene: the per-mutant semantic analysis is verbose and would bloat the Architect's context, making multi-file cover runs impossible.

For each `spec_gap` survivor, the Archaeologist answers: "What constraint, if it existed in the behaviour.yaml, would have forced the Mason to write a test that kills this mutant?"

Output per mutant:
- A new `given`/`when`/`then`, `error`, `invariant`, or `property` entry for the behaviour.yaml
- A one-line semantic summary (for the triage report)

Append each new constraint to the `*.behaviour.yaml`.

**5. Mason (subagent, Chinese Wall)**

**HARD RULE:** The Mason MUST run as a subagent dispatched with `isolation="worktree"` and `model` from config (`mason` key). The Mason receives ONLY:
- The `*.behaviour.yaml` (with any new constraints from Step 4)
- The surviving mutant descriptions (original line, mutated line, line number)
- The test file path to write to
- `.unslop/config.json` for the test command

The Mason MUST NOT receive:
- The managed source file
- The abstract spec
- The Architect's conversation context
- Any code the Architect read during Steps 1-4

This is the Chinese Wall. The Mason writes tests from behavioural constraints, not from source code knowledge. If the Mason could see the source, it would write tests that mirror the implementation rather than tests that encode the specification -- defeating the purpose of mutation-driven coverage growth.

For `weak_test` mutants: the Mason strengthens assertions against the existing constraint, using the surviving mutant as guidance for what the test should catch.

For `spec_gap` mutants: the Mason writes a new test function from the Archaeologist's new constraint.

**Marker rules:**

- `weak_test` fixes: these tests strengthen an **existing** constraint that is already spec-backed. They do NOT get the `@unslop-incidental` marker -- they are spec-backed from creation.
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

**6. Validator -- runs in the Architect session**

This is the one step the Architect runs directly, because it's mechanical test execution (no reasoning, no code generation).

**Phase A -- test against original code:**

Run the new test against the unmodified managed file using the project's test command from config.json.

- **Pass**: the constraint is real. Proceed to Phase B.
- **Fail**: FALSE REQUIREMENT. The Archaeologist hallucinated a constraint the code does not satisfy. Revert the corresponding behaviour.yaml change, discard the test, log the false positive. Do NOT fix the test -- route back to the Archaeologist for constraint correction, then re-dispatch the Mason.

**Phase B -- test against mutant:**

Apply the specific mutation to the managed file and run the new test.

- **Fail** (test catches mutant): mutant killed. Success.
- **Pass** (test does not catch mutant): weak test. Route back to the Mason with more specific mutant guidance (max 3 attempts per mutant). Do NOT strengthen the test inline.
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
