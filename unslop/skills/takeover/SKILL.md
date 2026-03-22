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

## Step 4: Generate (Stage B -- Builder in Worktree)

Use the **unslop/generation** skill's two-stage execution model.

**CRITICAL: Takeover always uses full regeneration mode (Mode A). The Builder does NOT read the archived original.**

Dispatch a Builder Agent with:
- test_policy: `"Write or extend tests as needed for newly explicit constraints"`
- Mode A (full regeneration) -- always, no incremental for takeover
- The spec path as the sole source of truth

The Architect stage (Steps 1-2) already ran in the user's session -- it read the code, drafted the spec, and got user approval. The Builder starts fresh with zero knowledge of the original code.

---

## Step 5: Validate (Verification in Controlling Session)

After the Builder Agent completes:

**If DONE with green tests:**

- Worktree merges automatically
- Compute `output-hash` on merged code, update `@unslop-managed` header
- Commit the spec file and the generated file together as a single atomic commit
- Report success to the calling command

**If BLOCKED or tests fail:**

- Discard the worktree
- Enter the convergence loop (Step 6) using the Builder's failure report

---

## Step 6: Convergence Loop (Cross-Stage)

Maximum **3 iterations**. Track the iteration count.

For each iteration:

a. **Read the Builder's failure report** -- failing test names, assertion messages, what was attempted, suspected spec gaps. Do NOT request raw test output or code snippets.

b. **Enrich the spec (Stage A)** -- Based on the failure report's suspected spec gaps, add missing constraints in spec-language voice. The Architect identifies gaps only -- it does NOT copy implementation suggestions from the Builder.

c. **Get user approval** -- Present the enriched spec to the user. Wait for approval.

d. **Stage the spec update** -- `git add <spec_path>`. Do NOT commit.

e. **Dispatch a new Builder (Stage B)** -- Fresh Agent, new worktree. The Builder never knows why the spec changed. test_policy: `"Write or extend tests as needed for newly explicit constraints"`.

f. **Verify** -- Same as Step 5. If green: commit atomically, done. If red: next iteration.

**If maximum iterations reached:** discard the worktree, revert the staged spec update. Present:
- The Builder's latest failure report
- What constraints were added during convergence
- The archive location for manual recovery

Then ask the user for guidance.

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

### Convergence Loop (Step 6 -- updated)

The loop works the same as single-file mode with these changes:
- Each convergence iteration dispatches a fresh Builder Agent in a new worktree
- Enrich whichever spec(s) are relevant to the failing tests (based on the Builder's failure report)
- **Do NOT change `depends-on` frontmatter during convergence**
- Regenerate only files whose specs were enriched, plus dependents (check build order)
- For per-unit specs: the Builder generates all files in a single worktree session
- On convergence failure: discard the worktree, revert all staged spec updates

### Abandonment State (updated)

Same as single-file: keep all draft specs, keep all last generated attempts, all originals remain in archive. Do not clean up.
