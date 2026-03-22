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

**CRITICAL: Takeover always uses full regeneration mode (Mode A). Do NOT read the archived original. Generate from the spec ONLY.**

The entire point of the takeover pipeline is that the spec becomes the source of truth. Reading the original would contaminate the generation with implementation details that were not captured in the spec. If the spec is missing something important, the convergence loop will surface it. Incremental mode (Mode B) is never appropriate during takeover — there is no trusted baseline to diff against.

Write the generated file to the original path. Include the `@unslop-managed` header as specified by the generation skill.

---

## Step 5: Validate

Read the test command from `.unslop/config.json`.

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

d. **Regenerate** — Generate the file again from the enriched spec using **full regeneration mode (Mode A)**. Still no peeking at the archived original.

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

---

## Multi-File Mode

When the takeover command provides a list of files (from directory scanning or glob expansion), the pipeline operates on the entire set as a unit.

### Discovery (replaces Step 1)

The command has already called `orchestrator.py discover` and the user has confirmed the file list. You receive the confirmed list of source files.

Find tests for the unit as a whole — look for test files adjacent to or within the directory being taken over. Read all source files and all test files together before drafting specs.

If no tests are found for the unit, warn the user as in single-file mode.

### Granularity Choice (new step, before Draft Spec)

Ask the user:

> "This directory contains N files. Would you like:
> 1. **Per-file specs** — one spec per file, with dependency declarations between them
> 2. **Per-unit spec** — one spec describing the entire module
>
> Per-file is better for loosely coupled files or large units. Per-unit is better for tightly coupled files with shared internal APIs."

For units larger than ~10 files, recommend per-file mode with a note about context limits.

### Draft Specs (updated Step 2)

**Per-file mode:**
- Read ALL files in the unit together to understand cross-file relationships
- Draft one spec per file
- Analyze imports to determine `depends-on` frontmatter for each spec
- Present ALL specs to the user together for review

**Per-unit mode:**
- Read ALL files in the unit together
- Draft a single `<dir>.unit.spec.md` with a `## Files` section
- Present to the user for review

In both modes, wait for user approval of ALL specs before proceeding.

### Archive (Step 3 — updated)

Archive ALL original files in the unit, not just one.

### Build Order (new step, before Generate)

**Per-file mode only.** Call `orchestrator.py build-order` with the **project root directory** (not the spec directory). Dependency paths in `depends-on` frontmatter are project-root-relative, so the orchestrator must scan from the root to match them correctly. Generate files in the returned order — leaves first, dependents after their dependencies.

**Per-unit mode:** Skip this step. Generate all files from the single spec in the order listed in `## Files`.

### Validate (Step 5 — updated)

Run tests once for the entire unit (not per-file). The test command from `.unslop/config.json` should cover the unit. If tests pass, commit ALL specs and generated files together.

### Convergence Loop (Step 6 — updated)

The loop works the same as single-file mode with these changes:
- Enrich whichever spec(s) are relevant to the failing tests
- **Do NOT change `depends-on` frontmatter during convergence** — changing the dependency graph mid-loop creates cascading instability
- Regenerate only files whose specs were enriched, plus files that depend on them (check the build order)
- If the orchestrator reports an error during convergence (e.g., a cycle introduced despite the rule), abort immediately and surface the error

### Abandonment State (updated)

Same as single-file: keep all draft specs, keep all last generated attempts, all originals remain in archive. Do not clean up.
