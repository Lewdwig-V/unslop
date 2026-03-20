---
name: takeover
description: Use when running the unslop takeover pipeline to bring existing code under spec management. Orchestrates discovery, spec drafting, archiving, generation, and the convergence validation loop.
version: 0.1.0
---

# Takeover Skill

## Pipeline Overview

The takeover pipeline brings an existing file under spec management by extracting its intent, archiving the original, and regenerating it from a spec. The spec becomes the source of truth; the original code is discarded.

Steps:

1. **Discover** — Read the target file and locate its tests
2. **Draft Spec** — Extract intent from code and tests; get user approval
3. **Archive** — Archive the original to `.unslop/archive/` before it is replaced
4. **Generate** — Regenerate the file from the approved spec only
5. **Validate** — Run tests; commit if green, enter convergence loop if red
6. **Convergence Loop** — Enrich the spec and regenerate until tests pass or iterations are exhausted

---

## Step 1: Discover

Read the target file in full.

Then search for tests by convention. Look for files matching these patterns relative to the target's location and project root:

- `*_test.py`, `test_*.py`
- `*.test.ts`, `*.test.js`
- `*.spec.ts`, `*.spec.js`
- `__tests__/*.ts`, `__tests__/*.js`
- `*_test.go`
- `*_test.rb`, `spec/*_spec.rb`

Read any discovered test files in full.

**If no tests are found**, stop and warn the user explicitly:

> "Takeover without tests means the spec is unvalidated. The convergence loop cannot run. Proceed only if the user confirms."

Do not continue past this point until the user explicitly confirms they want to proceed without tests.

---

## Step 2: Draft Spec

Use the **unslop/spec-language** skill for writing guidance throughout this step.

Read the target file and all discovered test files. From them, extract:

- **Intent** — What is this code for? What problem does it solve?
- **Contracts** — What are its inputs and outputs? What invariants hold?
- **Error conditions** — What inputs or states are invalid? How are errors surfaced?
- **Constraints** — Size limits, retry counts, timeouts, ordering guarantees, concurrency expectations

**Do NOT copy implementation details into the spec.** Data structures, algorithms, variable names, and internal control flow belong in code, not in the spec. Describe what the code does, not how it does it.

Present the draft spec to the user:

> "Review this spec. Does it capture what this code is supposed to do? I'll regenerate fresh code from this spec alone, so anything missing here will be lost."

**Wait for explicit user approval before proceeding.** Incorporate any corrections the user requests and re-present if needed. Do not advance to Step 3 until the user says the spec is correct.

---

## Step 3: Archive

Before touching the original file, archive it.

Archive path format: `.unslop/archive/<relative-path>.<ISO8601-compact-timestamp>`

Example: `.unslop/archive/src/retry.py.20260320T143200Z`

- The relative path mirrors the file's location within the project root
- The timestamp is compact ISO 8601 in UTC: `YYYYMMDDTHHMMSSZ` — no colons, no dashes in the date portion (e.g., `20260320T143200Z`)
- Create parent directories as needed

This archive is a safety net. The user can manually recover the original from it if anything goes wrong. Do not delete or modify the archive after creating it.

---

## Step 4: Generate

Use the **unslop/generation** skill for code generation discipline.

**CRITICAL: Do NOT read the archived original. Generate from the spec ONLY.**

The entire point of the takeover pipeline is that the spec becomes the source of truth. Reading the original would contaminate the generation with implementation details that were not captured in the spec. If the spec is missing something important, the convergence loop will surface it.

Write the generated file to the original path. Include the `@unslop-managed` header as specified by the generation skill.

---

## Step 5: Validate

Read the test command from `.unslop/config.md`.

Run the tests.

**If all tests pass:**

- Commit the spec file and the generated file together
- Report success to the calling command. The command handles alignment summary updates.

**If any tests fail:**

- Enter the convergence loop (Step 6)

---

## Step 6: Convergence Loop

Maximum **3 iterations**. Track the iteration count.

For each iteration:

a. **Analyze test failures** — Read the test output carefully. What behavior is the test asserting that the generated code does not exhibit?

b. **Identify the missing semantic constraint** — Trace the failure back to a gap in the spec. What does the spec fail to say about the expected behavior?

c. **Enrich the spec** — Add the missing constraint to the spec in spec-language voice: intent and observable behavior, not implementation. Do not add code-level detail.

d. **Regenerate** — Generate the file again from the enriched spec. **Still no peeking at the archived original.**

e. **Re-run tests** — Run the full test suite again.

**If tests go green at any iteration:** done. Commit the enriched spec and the generated file. Report which constraints were added during convergence.

**If maximum iterations are reached and tests are still red:** stop. Do not attempt another iteration. Present to the user:

- Which tests are still failing
- What constraints were added to the spec during the convergence loop
- The location of the original file in the archive

Then ask the user for guidance.

**NEVER patch the generated code directly. Always enrich the spec and regenerate.** Patching the code directly breaks the invariant that the spec is the source of truth. A patched file will diverge from any future regeneration.

---

## Abandonment State

When the convergence loop exhausts its iterations without green tests:

- **Keep the draft spec** — it contains the constraints identified so far; the user can edit it and resume
- **Keep the last generated attempt** — the user can inspect it to understand what the current spec produces
- **Leave the original in the archive** — it is available for manual recovery

Do not delete, overwrite, or clean up any of these artifacts. Leave the working tree in a state the user can reason about and act on.
