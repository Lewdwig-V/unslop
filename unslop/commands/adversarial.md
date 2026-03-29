---
description: Run the adversarial quality pipeline on a managed file. Extracts behaviour, generates black-box tests, and validates via mutation.
argument-hint: "<spec-or-directory-path> [--phase archaeologist|mason|saboteur] [--dry-run]"
---

**Parse arguments:** Extract the first non-flag token from `$ARGUMENTS` as the target path. Optional flags:
- `--phase <name>`: Run only a specific phase (archaeologist, mason, or saboteur)
- `--dry-run`: Show what would happen without writing files

**Resolve target:**

- If the target ends in `.spec.md`: use as-is (spec path). Example: `src/retry.py.spec.md`
- If the target is a directory: look for `<dirname>.unit.spec.md` inside it. Example: `src/auth/` resolves to `src/auth/auth.unit.spec.md`. If the unit spec does not exist, stop:

  > "No unit spec found at `<dir>/<dirname>.unit.spec.md`. If you meant to run on individual file specs, pass them explicitly."

- Otherwise: treat as a managed file path and append `.spec.md`. Example: `src/retry.py` resolves to `src/retry.py.spec.md`. If the spec does not exist, stop:

  > "No spec found at `<path>.spec.md`."

**1. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the resolved spec file exists. Derive managed file path(s):

- For per-file specs (`*.spec.md` but not `*.unit.spec.md`): strip `.spec.md` to get the managed file path (e.g., `src/retry.py.spec.md` --> `src/retry.py`).
- For unit specs (`*.unit.spec.md`): read the `## Files` section and resolve all listed file paths relative to the spec's directory.

Check that all derived managed file paths exist:

- If none exist, stop: "No generated files found for this spec. Run `/unslop:generate` first."
- If some but not all exist (unit spec case), list the missing ones as a warning and proceed with the files that do exist.

**Unit spec dispatch:** If the resolved spec is a unit spec, run Steps 2-6 independently for each managed file (using the file's per-file spec if it exists, otherwise using the unit spec). Auto-convergence (Step 6) runs per-file after each file's Step 5 completes, not as a unit-level pass. After all files complete, present an aggregated summary:

> "Adversarial quality report for unit `<unit-spec-path>`:
>
> `<file-1>`: P mutations, Q killed, E equivalent (X% adjusted) -- PASS/NEEDS WORK
> `<file-2>`: P mutations, Q killed, E equivalent (X% adjusted) -- PASS/NEEDS WORK
> ...
>
> Unit verdict: [PASS if all files pass | NEEDS WORK otherwise]"

Check that `.unslop/boundaries.json` exists. If not, create it with an empty array `[]` and warn:

> "Created `.unslop/boundaries.json` with empty boundary list. Add your external dependencies (e.g., `[\"requests\", \"boto3\"]`) to enable mock budget enforcement."

**2. Phase 1 — Archaeologist (Intent Extraction)**

If `--phase` is not set or is `archaeologist`:

Read the abstract spec (`*.spec.md`), the concrete spec (`*.impl.md`) if it exists, and the managed source file.

Extract behavioural intent into the **Behaviour DSL** format. Write the output to a sibling file with `.behaviour.yaml` extension (e.g., `src/retry.py.behaviour.yaml`).

The behaviour file must:
- Use the `behaviour` field for a human-readable name
- Use the `interface` field with the module path and entry point
- List all behavioural constraints using typed entries (`given`, `when`, `then`, `invariant`, `error`, `property`)
- List error conditions with exception names
- List invariants that must hold across all invocations
- List dependencies from the spec's `depends-on` frontmatter

**Validation:** Run `validate_behaviour.py` on the output. If validation fails, fix the behaviour file and retry (max 2 attempts).

If `--dry-run`, print the behaviour YAML to stdout instead of writing it.

**Calibration context:** If `.unslop/saboteur-calibration.md` exists, load it for Saboteur classification context in Phase 3. See the adversarial skill's Phase 3 calibration loading.


**3. Phase 2 — Mason (Spec-Blind Test Construction)**

If `--phase` is not set or is `mason`:

**CRITICAL: The Mason must NOT read the source code.** This is the information asymmetry firewall.

Read ONLY:
- The behaviour YAML file (`*.behaviour.yaml`)
- The project's `.unslop/boundaries.json`
- The project's `.unslop/config.json` (for test_command and framework info)

Do NOT read:
- The managed source file
- The abstract spec
- The concrete spec
- Any other source files in the project

Generate a test file at the standard test location (e.g., `tests/test_retry.py` for `src/retry.py`). The test file must:

- Import only the public interface declared in the behaviour YAML
- Test every constraint, invariant, and error condition
- Use ONLY boundary-approved mocks (stdlib + boundaries.json entries)
- Include a header comment: `# @unslop-adversarial — generated from behaviour spec, not source code`

**Mock Budget Validation:** Run `validate_mocks.py` on the generated test. If it fails (internal mocks detected), rewrite the test to remove internal mock violations. Maximum 2 rewrite attempts.

If `--dry-run`, print the test file to stdout instead of writing it.

**4. Phase 3 — Saboteur (Mutation Validation)**

If `--phase` is not set or is `saboteur`:

Check if a mutation tool is available. Check for `mutmut` first, then fall back to a built-in minimal mutator.

**4a. Run baseline tests:** Execute the project's test command. If tests fail before mutation, stop:

> "Baseline tests fail. Fix test failures before running mutation validation."

**4b. Run mutation testing:** Apply mutations to the managed source file and run tests against each mutant.

**Built-in mutations** (used when mutmut is unavailable):
- Arithmetic: `+` ↔ `-`, `*` ↔ `/`
- Comparison: `<` ↔ `<=`, `>` ↔ `>=`, `==` ↔ `!=`
- Boolean: `True` ↔ `False`, `and` ↔ `or`
- Constant: integer ± 1, string → empty string
- Return: replace return value with None

**4c. Classify surviving mutants:**

For each mutant that survives (tests pass despite mutation):

1. **Heuristic check:** Is it a known equivalent pattern?
   - Off-by-one equivalence (e.g., `i < 10` → `i <= 9` when i is always integer)
   - Dead code mutation (mutated code is unreachable)
   - Redundant condition (condition is always true/false regardless of mutation)

2. **If heuristics inconclusive:** Classify using analysis:
   - Read the original line and the mutated line
   - Determine if the mutation changes observable behaviour
   - Verdict: `equivalent`, `weak_test`, or `spec_gap`

**4d. Route feedback:**

- `equivalent` → Log and skip. No action needed.
- `weak_test` → Report to user: "Mason's test doesn't catch mutation at line N: `original` → `mutated`. Consider strengthening assertions."
- `spec_gap` → Report to user: "Archaeologist missed a constraint. The mutation at line N changes behaviour but no constraint covers it. Consider adding to the behaviour spec."

**5. Present results**

Summarize the adversarial run:

> "Adversarial quality report for `<spec-path>`:
>
> **Archaeologist:** Extracted N constraints, M invariants, K error conditions
> **Mason:** Generated test file with T test cases, B boundary mocks (0 internal — clean)
> **Saboteur:** Applied P mutations, killed Q, survived R
>   - Equivalent mutants: E
>   - Weak tests: W
>   - Spec gaps: S
>
> **Mutation Kill Rate:** Q/P (X%)
> **Verdict:** [PASS if kill rate ≥ 80% after filtering equivalents | NEEDS WORK otherwise]"

If `--phase` was specified, only show results for that phase.

**6. Auto-convergence (full pipeline only)**

If running all phases and the verdict is NEEDS WORK:

Check `adversarial_max_iterations` in `.unslop/config.json` (default: 3). If iterations remain:

1. Feed surviving mutant details back to the appropriate phase
2. Re-run from that phase
3. Repeat until convergence or iteration limit

If iteration limit reached:

> "Adversarial pipeline did not converge after N iterations. Remaining issues:
> - [list of surviving non-equivalent mutants]
>
> Manual review needed for these edge cases."
