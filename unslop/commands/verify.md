---
description: Run Saboteur verification synchronously on a managed file
argument-hint: <file-path>
---

**Parse arguments:** `$ARGUMENTS` is the path to the managed source file (required). If no argument is provided, stop and tell the user:

> "Usage: /unslop:verify <file-path>"

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the file at the given path exists. If it does not exist, stop and tell the user:

> "File not found: `<file-path>`"

Read the first 10 lines of the file and check for an `@unslop-managed` header. If the header is absent, stop and tell the user:

> "This file is not under spec management. Use `/unslop:takeover` first."

Check that a corresponding spec file exists at `<file-path>.spec.md`. If it does not exist, stop and tell the user:

> "No spec found at `<file-path>.spec.md`. Use `/unslop:takeover` first."

Derive the test file path using standard conventions (in order of priority):

1. `tests/test_<basename>.<ext>` (e.g., `tests/test_retry.py`)
2. `test_<basename>.<ext>` (same directory as source)
3. `<basename>_test.<ext>` (same directory as source)
4. The `test_path` entry in `.unslop/config.json` if present

If no test file is found at any of those paths, stop and tell the user:

> "No test file found for `<file-path>`. Run `/unslop:cover` to generate tests first."

**2. Load context**

Read the following into the current session:

- `<file-path>.spec.md` -- the abstract spec
- `<file-path>` -- the managed source file
- The resolved test file path

Read `.unslop/config.json` if it exists. Extract:
- `models.saboteur` -- model to use for Saboteur dispatch (default: `sonnet`)
- `test_command` -- command used to run tests (default: `pytest`)
- `mutation_budget` -- default mutation budget for the Saboteur (default: `20`)

Load the **unslop/adversarial** skill. The Saboteur dispatch follows Phase 3 of that skill.

**3. Dispatch Saboteur subagent**

Dispatch a Saboteur subagent synchronously using `model` from `config.models.saboteur` (default: `sonnet`).

The Saboteur receives:
- The managed source file (full content)
- The test file(s)
- The test command from config
- The mutation budget from config (default 20)

The Saboteur does NOT receive the spec during mutation testing -- mutation selection must be unbiased. However, the spec IS provided for the constitutional compliance and edge case probing phases (which run after mutation testing), since those phases need spec context to assess `spec_gap` and principle-spec alignment.

**Baseline check:** The Saboteur runs the existing test suite against the unmodified source file first. If any tests fail, do not proceed with mutation testing. Report:

> "Verification error: baseline test suite is failing. Fix failing tests before running /unslop:verify."

Write an error result to `.unslop/verification/<managed-file-hash>.json` (see Step 5) with `status: "error"` and `error_message` set to the baseline failure details.

If the baseline is green, the Saboteur generates and runs mutations per Phase 3 of the adversarial skill and returns a JSON summary of killed/survived/errored mutants.

After mutation testing, the Saboteur also runs:

**Constitutional compliance:** If `.unslop/principles.md` exists, check the source file against each principle. Record violations in the result JSON under `constitutional_violations`.

**Edge case probing:** Probe the code's attack surface for edge cases the spec didn't anticipate. Budget: `config.edge_case_budget` (default: 10). Record findings in the result JSON under `edge_case_findings`.

**Block until the Saboteur subagent completes before proceeding.**

**4. Report result**

Compute the kill rate: `killed / (total - errored)`. Treat equivalent mutants as killed for the purpose of this ratio. A result is a **pass** if all non-equivalent mutants are killed.

**Pass** (no surviving non-equivalent mutants AND no constitutional violations):

> "Verified: N/M mutants killed, K equivalent. Code satisfies spec and principles."

**Fail** (one or more surviving mutants OR one or more constitutional violations):

> "Verification failed: N surviving mutants, M constitutional violation(s). Run /unslop:cover to investigate."
>
> Surviving mutants:
> 1. Line <N>: `<original>` -> `<mutated>` -- <one-line semantic description>
> 2. Line <N>: `<original>` -> `<mutated>` -- <one-line semantic description>
> ...

**Constitutional violations** (if any, displayed after mutation results):

> ⚠ Constitutional violation: "<principle>"
>   <location> -- <violation>
>   Required: <required>

**Edge cases** (if any, displayed after constitutional violations):

> ⚠ N edge case(s) found:
> 1. <input> -- <actual> (severity: <level>, spec gap: yes/no)

**Error** (baseline failure, test runner crash, or Saboteur error):

> "Verification error: <message>. Check test setup."

**5. Write result**

Compute the managed file hash: SHA-256 of the managed file path string (not its content), truncated to 12 hex characters. This is the cache key.

Create `.unslop/verification/` if it does not exist.

Write `.unslop/verification/<managed-file-hash>.json` with the following fields:

```json
{
  "managed_path": "<file-path>",
  "spec_path": "<file-path>.spec.md",
  "timestamp": "<ISO 8601 UTC timestamp>",
  "status": "pass" | "fail" | "error" | "timeout",
  "mutants_total": N,
  "mutants_killed": N,
  "mutants_survived": N,
  "mutants_equivalent": N,
  "mutants_errored": N,
  "source_hash": "<SHA-256 of source file content, truncated to 12 hex characters>",
  "spec_hash": "<SHA-256 of spec file content, truncated to 12 hex characters>",
  "surviving_mutants": [
    {
      "line": N,
      "original": "<original code>",
      "mutated": "<mutated code>",
      "description": "<one-line semantic description>"
    }
  ],
  "constitutional_violations": [
    {
      "principle": "<text>",
      "location": "<file:lines>",
      "violation": "<what code does>",
      "required": "<what principle requires>"
    }
  ],
  "edge_case_findings": [
    {
      "input": "<desc>",
      "expected": "<expected>",
      "actual": "<actual>",
      "severity": "<level>",
      "spec_gap": true|false
    }
  ],
  "error_message": "<error details, present only when status is error>"
}
```

The `surviving_mutants` array is empty on pass or error. The `error_message` field is omitted on pass or fail.

---

**HARD RULE:** verify is read-only. It does not modify the managed source file, test files, or spec files. The only file writes permitted are to `.unslop/verification/<hash>.json`. Any mutation applied during Saboteur execution must be reverted before the Saboteur subagent completes.
