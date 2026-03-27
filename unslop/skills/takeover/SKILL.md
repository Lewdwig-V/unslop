---
name: takeover
description: Use when running the unslop takeover pipeline to bring existing code under spec management. Orchestrates discovery, spec drafting, archiving, generation, and the convergence validation loop.
version: 0.14.0
---

# Takeover Skill

## Pipeline Overview

The takeover pipeline brings an existing file under spec management by **raising** it through unslop's compiler IR layers: Code → Concrete Spec → Abstract Spec. This two-phase lifting is more accurate than jumping directly from code to abstract spec, because the intermediate Concrete Spec preserves algorithmic decisions that may be load-bearing.

Steps:

0. **Pre-flight** -- Analyze complexity, split large files, detect protected regions
1. **Discover** -- Read the target file, locate its tests, determine `testless_mode`
1b. **Intent Lock** -- Articulate the extracted product intent; get user approval before drafting specs
2. **Raise to Concrete** -- Extract the algorithm, patterns, and type structure into a Concrete Spec (the current "How")
2b. **Raise to Abstract** -- Extract observable behavior and constraints into an Abstract Spec (the original "Why")
2c. **Generate Behaviour YAML** -- (testless path only) Extract given/when/then constraints for adversarial validation
3. **Archive** -- Archive the original to `.unslop/archive/` before it is replaced
4. **Lower & Generate** -- Stage A.2 (fresh Concrete Spec), Stage B.1 (auditable implementation strategy), Stage B.2 (worktree-isolated Builder)
5. **Adversarial Validation** -- (testless path only) Mason/Saboteur pipeline as quality gate
6. **Validate** -- (tests-exist path) Run tests; commit if green, enter convergence loop if red
7. **Convergence Loop** -- Enrich the spec and regenerate until tests pass or iterations are exhausted
8. **Atomic Commit** -- Commit all artifacts together

---

## Step 0: Pre-flight Analysis

Before discovery, the Architect analyzes the target file's complexity to determine if a pre-takeover split is needed and to detect protected regions.

### Step 0a: Measure and Detect

Read the target file and compute:

1. **Line count** -- total lines
2. **Public symbol count** -- count by reading the file (grep for exported functions, public types, module-level constants).
3. **Estimated token weight** -- `file_size_bytes / 4`
4. **Protected region scan** -- identify tail blocks that serve a different purpose than the implementation above them (e.g., compile-time test conditionals, main entry guards, example/benchmark blocks)

Compare against thresholds (configurable in `.unslop/config.json` under the `preflight` key):

| Metric | Suggest split | Require split |
|---|---|---|
| Line count | >1000 | >2000 |
| Public symbols | >30 | >60 |
| Token weight | >8000 | >16000 |

Either condition triggers. Present the analysis:

```
Pre-flight analysis for <file>:
  N lines | M public symbols | ~Xk tokens
  [⚠ Exceeds suggest/require threshold (reason)]
  [N protected region(s) detected: <description>]
```

**If below all thresholds and no protected regions:** Step 0 is a no-op. Proceed to Step 1.

**If protected regions detected but no split needed:** Record them for inclusion in the concrete spec's `protected-regions` frontmatter during Step 2 (Raise to Concrete). Proceed to Step 1.

### Step 0b: Split Planning (only if thresholds exceeded)

Draft an interactive split plan:

```
Proposed split into N submodules + facade:

  src/parser.rs    (~X lines, Y symbols) -- description
  src/emitter.rs   (~X lines, Y symbols) -- description
  src/lib.rs       (facade) -- re-exports preserving current public API

  Protected region: test block stays in <facade> (tests integration scope)

  Proceed with split? (y/n/edit)
```

**Split plan rules:**
- **API preservation is the prime directive.** Every public symbol accessible via the original module path MUST remain accessible after the split via re-exports in the facade.
- Group symbols by cohesion (symbols that call each other), not by size.
- Protected regions stay in the facade by default (the user can override via "edit").
- Naming follows language convention (snake_case, camelCase, etc.).
- "edit" lets the user rename modules, move symbols between groups, or exclude symbols.

The plan does NOT change any logic, signatures, behavior, or rename any public symbols.

The `--force` flag overrides "require" thresholds with a warning that generation quality will degrade.

### Step 0c: Split Execution (only if user approved)

Execute the mechanical refactor:

1. **Create submodule files** -- move assigned symbol blocks, preserve internal ordering
2. **Write the facade** -- replace original with re-exports; shared internal symbols get appropriate internal visibility
3. **Update internal references** -- add imports between submodules as needed
4. **Verify compilation** -- run the project's build check command (from `.unslop/config.json`). If not configured, ask the user.
5. **Verify tests pass** -- if tests exist, run them. Any failure means the split broke something.
6. **Commit** -- `refactor: split <file> into submodules (pre-takeover)`. Standalone commit, separate from takeover.

**On failure (compilation or tests):**
- Delete created submodule files
- Restore original from git (`git checkout -- <file>`)
- Report the error
- Offer: (1) Fix and retry, (2) Proceed unsplit (only if below "require" threshold), (3) Abort

**On success:**

Queue submodules for individual takeover. The facade is taken over last (its spec is trivial and may reference submodule specs). The facade spec SHOULD declare `depends-on` entries for each submodule spec.

```
Split complete. N submodules created, build check passes, M tests pass.
Committed: refactor: split <file> into submodules (pre-takeover)

Queuing takeover for N+1 files:
  1. src/parser.rs (X lines)
  ...
  N+1. src/lib.rs (facade)

Proceeding with src/parser.rs...
```

All language used in Step 0 is language-agnostic. Describe patterns ("compile-time test conditional", "main entry guard") not syntax. The Architect identifies protected regions by reading the file.

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

**If no tests are found**, determine the takeover path:

Check for override flags from the calling command:
- If `--skip-adversarial` was passed: set `testless_mode = false` regardless of test absence. The Builder will use the standard test_policy ("Write or extend tests"). This is the escape hatch for files where mutation testing is impractical (pure I/O, GUI code).
- If `--full-adversarial` was passed: force `adversarial_intensity = "full"` for the adversarial pipeline (Step 5), overriding the Architect's assessment.

If neither override is set and the project has adversarial mode enabled (`.unslop/config.json` has `"adversarial": true` or the user has not explicitly disabled it):

> "No tests found for this file. Routing to **testless takeover** -- the adversarial pipeline will generate and validate tests automatically.
>
> This adds a behaviour.yaml extraction step and uses the Mason/Saboteur pipeline as the quality gate instead of existing tests.
>
> Proceed? (y/n)"

If adversarial mode is not available (and `--skip-adversarial` was not passed), fall back to the existing warning:

> "No tests found. Takeover without tests means the spec is unvalidated. Proceed only with explicit user confirmation."

Track which path was taken: `testless_mode = true/false`. This variable controls downstream routing for all subsequent steps.

---

## Step 1b: Intent Lock (Phase 0a.0)

After reading the target file and its tests, the Architect must articulate the extracted product intent before drafting any spec content. This prevents the Architect from confusing "how it works" (engineering) with "how it should work" (product).

Present the takeover Intent Statement:

> "From the existing code, I understand this module's purpose is [extracted intent]. I'll draft a spec that captures [key behaviors]. Does this match your understanding of what this code should do?"

**Language constraint:** The intent must be expressed in user/product language, not implementation language. "Ensure failed HTTP requests are retried with backoff" passes. "Implement exponential retry with jitter in the request handler" fails -- that is the Concrete Spec's job, not the Intent Lock's.

**If approved:** Record the intent in the spec's frontmatter before proceeding:

```yaml
intent: >
  <the approved intent statement>
intent-approved: <current UTC timestamp>
intent-hash: <computed from intent text>
```

The Architect computes `intent-hash` using the same SHA-256 truncation as other hashes. This creates a tamper-detectable audit trail -- git blame shows who approved the intent and when. Future spec changes that drift beyond the recorded intent trigger a re-lock.

Proceed to Step 2 (Raise to Concrete Spec).

**If rejected:** The Architect asks "Could you clarify the requirement? I understood this module's purpose as [X], but that doesn't match your intent." and reformulates. No limit on reformulation attempts. If the user abandons (exits the session), no artifacts are left behind.

**No force-approve.** The Intent Lock is mandatory for all takeover operations. There is no `--skip-intent` or auto-approve mechanism.

---

## Step 2: Raise to Concrete Spec

Use the **unslop/concrete-spec** skill for format guidance throughout this step.

Read the target file and all discovered test files. Extract the implementation strategy:

- **Algorithm** — What algorithm or approach does the code use? Express as pseudocode.
- **Patterns** — What design patterns are in play? (e.g., decorator, strategy, observer)
- **Type structure** — What are the key types/interfaces and their relationships?
- **Data flow** — How does data move through the system? (Mermaid diagrams for complex flows)
- **Edge cases** — What special cases does the code handle? Which are intentional vs incidental?

Write a Concrete Spec (`*.impl.md`) capturing the current "How" — the algorithm, structure, and patterns the legacy code uses. This is a **faithful description** of existing behavior, bugs and all. Do not idealize.

**Present the Concrete Spec to the user only if the file is complex** (multiple algorithms, async flows, non-obvious state machines). For straightforward files, proceed directly to Step 2b.

> "Here's the implementation strategy I extracted from the existing code. Note any algorithmic choices that are intentional vs incidental — this will help me extract the right abstract spec."

The Concrete Spec is ephemeral during takeover — it serves as a stepping stone to the Abstract Spec and as a reference during convergence. It is not committed unless the user later promotes it.

---

## Step 2b: Raise to Abstract Spec

Use the **unslop/spec-language** skill for writing guidance throughout this step.

From the Concrete Spec (and the original code/tests), extract the **observable behavior**:

- **Intent** — What is this code for? What problem does it solve?
- **Contracts** — What are its inputs and outputs? What invariants hold?
- **Error conditions** — What inputs or states are invalid? How are errors surfaced?
- **Constraints** — Size limits, retry counts, timeouts, ordering guarantees, concurrency expectations

**Do NOT copy implementation details into the abstract spec.** The Concrete Spec captures the "How" — the Abstract Spec captures only the "What" and "Why." Algorithms, data structures, variable names, and internal control flow belong in the Concrete Spec or in code, not in the Abstract Spec.

The two-phase raising makes this extraction more accurate: the Architect can reference the Concrete Spec to distinguish between three categories:
- **Intentional algorithmic choices** (e.g., "uses exponential backoff" → constraint in Abstract Spec: "must prevent thundering herds")
- **Observable algorithmic behaviour** (e.g., "jitter range is [0.5*delay, delay]" → pin in Abstract Spec unless there's a reason to change it). During takeover, algorithmic choices that produce **observable differences in output** must be preserved by default. If the Architect wants to change them (e.g., upgrading half-jitter to full-jitter), it must flag the change explicitly as a **Behavioural Upgrade** with rationale, not silently substitute a different strategy. The user decides whether to preserve or upgrade.
- **Incidental implementation details** (e.g., "uses a dict for caching" → omit from Abstract Spec, leave to Builder)

**The "observable" test:** If two implementations produce different outputs for the same inputs, the choice between them is observable and must be pinned or flagged. If they produce identical outputs, the choice is incidental and can be left to the Builder. During takeover, when in doubt, pin it -- under-abstraction is safer than silent behaviour change.

Present the draft Abstract Spec to the user:

> "Review this spec. Does it capture what this code is supposed to do? I'll regenerate fresh code from this spec alone, so anything missing here will be lost. The implementation strategy (algorithm, patterns) will be re-derived during generation."

**Wait for explicit user approval before proceeding.** Incorporate any corrections the user requests and re-present if needed. Do not advance to Step 3 until the user says the spec is correct.

---

## Step 2c: Generate Behaviour YAML (testless path only)

Skip this step if `testless_mode = false` (tests exist).

From the Concrete Spec and Abstract Spec, generate a `*.behaviour.yaml` file. Requirements:

- At least one given/when/then constraint per public function
- `error` entries for every exception the code raises
- `invariant` entries for state consistency properties
- Must pass `validate_behaviour.py` structural validation

**Legacy Smell Detection:** Before writing the behaviour.yaml, cross-check every extracted behaviour against `.unslop/principles.md`. For each constraint that contradicts a principle, flag as `legacy_smell`. Present to user:

> "Extracted behaviour '{constraint}' contradicts principle '{principle}'. Preserve or discard?"

Do NOT encode legacy smells as invariants unless user overrides.

**Bias guard:** Present smells neutrally -- "contradicts principle X. Preserve or discard?" NOT "This is a bug, discard it?"

**Observable Behaviour Preservation:** The behaviour.yaml MUST reflect original observable behaviour. Apply the observable test: if two implementations produce different outputs for the same inputs, pin the choice. Silent substitution is a spec defect. If the Architect wants to change an observable behaviour, flag as **Behavioural Upgrade** with rationale.

Present the behaviour.yaml alongside the abstract spec for joint user approval.

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

## Step 4: Lower & Generate (Archaeologist subagent -> Builder subagent)

Use the **unslop/generation** skill's multi-stage execution model.

**CRITICAL: Takeover always uses full regeneration mode (Mode A). The Builder does NOT read the archived original.**

**Archaeologist (subagent) -- MANDATORY:** Dispatch an Archaeologist subagent (`model` from config, `archaeologist` key) to derive a fresh Concrete Spec from the approved Abstract Spec. The Archaeologist receives the abstract spec, principles, file tree, and domain skills. It returns a concrete spec documenting implementation strategy: algorithms, patterns, type structure, and any decisions not dictated by the abstract spec. This is the auditable reasoning step -- reviewers can verify the implementation plan before seeing generated code. Use the **unslop/concrete-spec** skill for format guidance.

During takeover, the previously raised Concrete Spec (from Step 2) is available as reference -- the Archaeologist may reuse algorithmic choices that the user confirmed as intentional, but is free to choose a different strategy if the Abstract Spec permits it.

Stage A.2 runs for ALL files regardless of perceived complexity. Even a single-function file gets a Archaeologist subagent that produces an ephemeral Concrete Spec. The Archaeologist's context hygiene benefit applies equally to simple and complex files -- the Architect's context stays clean for orchestration. Skipping Stage A.2 means the Builder generates with no strategic constraints, producing unpredictable output.

**Builder (subagent, worktree) -- MANDATORY:** Dispatch a Builder Agent with `isolation="worktree"` and `model` from config (`builder` key). The Builder receives ONLY the spec file(s), the Archaeologist's concrete spec, and `.unslop/config.json` -- never the archived originals or the Architect's conversation context. This isolation is the integrity guarantee: if the Builder can reproduce the code from the spec alone, the spec is proven sufficient. Generating inline (in the Architect session) violates this because the Architect has already seen the original source code during Stage A discovery. **Do NOT write code directly -- ALL code generation goes through a worktree-isolated Builder Agent.**

Dispatch with:
- test_policy (path-dependent):
  - Tests exist (`testless_mode = false`): `"Write or extend tests as needed for newly explicit constraints"`
  - Testless path (`testless_mode = true`): `"skip"` -- the adversarial pipeline generates tests separately
- Mode A (full regeneration) -- always, no incremental for takeover
- The abstract spec path as the primary source of truth
- The concrete spec (from Stage B.1) as strategic guidance

---

## Step 5: Adversarial Validation (testless path only)

Skip this entire step if `testless_mode = false` (tests exist). Proceed directly to Step 6.

Use the **unslop/adversarial** skill for pipeline execution throughout this step.

**Step 5a: Mason generates tests.** Mason generates tests from the behaviour.yaml only (Chinese Wall -- Mason does NOT read the generated implementation). This ensures tests encode expected behaviour, not implementation details.

**Step 5b: Mock Budget Lint.** Run `validate_mocks.py` against the generated tests.
- **Integration Pass** for managed dependencies (deps under spec management).
- **Cascade recommendation** for unmanaged dependencies -- recommend the user bring those deps under management or accept mock risk.

**Step 5c: Run tests** against the generated code.
- Green: proceed to Step 5d.
- Failures: enter testless convergence (Step 7).

**Step 5d: Saboteur mutation testing.** Run the Saboteur against the generated code using Mason's tests.
- All mutants killed: proceed to commit (Step 8).
- `weak_test`: Mason retries with stronger assertions. Re-run from Step 5c.
- `spec_gap`: Architect enriches the behaviour.yaml and abstract spec. Re-run from Step 5a.

**Adversarial intensity** (Architect-selected): `"full"` (default -- Mason + Saboteur) or `"mason-only"` (skip Step 5d).

---

## Step 6: Validate (tests-exist path)

After the Builder Agent completes, follow the Verification protocol from the **unslop/generation** skill. This includes auto-merge detection (worktree-live vs auto-merged), ground-truth file inspection, and the Revert Protocol for invalid auto-merges. The key steps: check outcome, inspect output, compute hashes, commit atomically.

**If DONE with green tests and validated:**

- Proceed to Step 8 (Atomic Commit)
- Report success to the calling command

**If BLOCKED or tests fail:**

- Discard the worktree
- Enter the convergence loop (Step 7) using the Builder's failure report
- The raised Concrete Spec from Step 2 is available as diagnostic context during convergence

---

## Step 7: Convergence Loop (Cross-Stage)

### Tests-exist convergence (`testless_mode = false`)

Maximum **3 iterations**. Track the iteration count.

For each iteration:

a. **Read the Builder's failure report** -- failing test names, assertion messages, what was attempted, suspected spec gaps. Do NOT request raw test output or code snippets.

b. **Diagnose using the Concrete Spec** -- The raised Concrete Spec from Step 2 provides context for why the original code handled certain cases. Compare the Builder's failure report against the Concrete Spec to identify algorithmic choices that were load-bearing but not captured in the Abstract Spec.

c. **Enrich the Abstract Spec (Stage A.1)** -- Based on the failure report and Concrete Spec context, add missing constraints in spec-language voice. The Architect identifies gaps only -- it does NOT copy implementation suggestions from the Builder.

d. **Get user approval** -- Present the enriched spec to the user. Wait for approval.

e. **Stage the spec update** -- `git add <spec_path>`. Do NOT commit.

f. **Re-lower (Stage A.2)** -- The Archaeologist derives a fresh Concrete Spec from the enriched Abstract Spec.

g. **Dispatch a new Builder (Stage B.1 + B.2)** -- Re-lower through a fresh Concrete Spec (B.1), then dispatch a fresh Builder Agent in a new worktree (B.2). The Builder never knows why the spec changed. test_policy: `"Write or extend tests as needed for newly explicit constraints"`.

h. **Verify** -- Same as Step 6. If green: commit atomically, done. If red: next iteration.

**If maximum iterations reached:** discard the worktree, revert the staged spec update. Present:
- The Builder's latest failure report
- What constraints were added during convergence
- The archive location for manual recovery

Then ask the user for guidance.

### Testless convergence (`testless_mode = true`)

Three-stage convergence with maximum **3 normal + 1 radical = 4 total iterations**. Track the iteration count and kill rate per iteration.

For each iteration:

a. **Diagnose** -- Read the failure source. Classify as one of:
   - `weak_test`: Mason's tests are insufficient (low kill rate, assertion gaps)
   - `spec_gap`: behaviour.yaml is missing constraints (Saboteur found spec holes)
   - `test_failure`: generated code does not match behaviour.yaml (Mason's tests fail)

b. **Route** based on diagnosis:
   - `weak_test`: Mason retries with stronger assertions. Re-run from Step 5c.
   - `spec_gap`: Architect enriches behaviour.yaml and abstract spec. Get user approval. Re-run from Step 5a.
   - `test_failure`: Enrich abstract spec, re-lower, dispatch new Builder. Re-run from Step 5a.

c. **Re-build** -- Dispatch fresh Builder if needed (same as tests-exist convergence step g).

d. **Re-validate** -- Re-run adversarial validation (Step 5).

e. **Measure entropy** -- Track kill rate delta between iterations.

**Entropy Threshold:** If delta < `entropy_threshold` (kill rate improvement is stalling) and kill rate < 100%, trigger **Radical Spec Hardening**: a one-shot rewrite of behaviour.yaml using the Archaeologist's surviving mutant summary. This consumes the radical iteration slot.

If Radical Spec Hardening also stalls: **DONE_WITH_CONCERNS**. Commit what exists with a warning annotation in the spec noting the unresolved kill rate gap.

---

## Step 8: Atomic Commit

**Tests-exist path (`testless_mode = false`):** Commit the abstract spec and the generated file (+ concrete spec if promoted) together as a single atomic commit.

**Post-takeover test hardening (tests-exist path only):** After a successful commit, offer to harden the Builder-generated tests via mutation testing:

> "Takeover complete. The Builder wrote tests based on the spec, but they haven't been validated via mutation testing. Run `/unslop:cover <file>` to check for weak assertions and test scum?"

This is advisory, not automatic. The user decides whether to harden immediately or defer. If they choose to harden, `/unslop:cover` runs the Saboteur against the Builder's tests to discover gaps the Builder missed.

**Testless path (`testless_mode = true`):** Commit all artifacts together as a single atomic commit:
- Abstract spec
- Generated implementation (if promoted)
- `*.behaviour.yaml`
- Generated code
- Generated tests (from Mason)
- Concrete spec (if promoted)

Update `@unslop-managed` header with `output-hash` on all generated files.

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

### Context Management for Large Batches

For takeovers of 6 or more files, the Architect session accumulates significant context: all source files, all specs, all concrete specs, and orchestration state. To prevent context exhaustion:

**Layer-based processing:** Group files by dependency layer (leaves first, then dependents). Complete each layer fully (specs drafted, Builders dispatched, results verified) before loading the next layer's source files. This keeps the Architect's working set to one layer at a time.

**Commit checkpoints:** After each layer's Builders succeed, commit the completed layer's specs and generated files atomically. This frees context -- the Architect no longer needs the completed layer's source files or specs in memory for subsequent layers.

**Resume on failure:** If the Architect session hits context limits mid-batch, the user can start a new session and resume from the last committed layer. Completed layers are already on disk; only incomplete layers need re-processing.

For batches of 5 or fewer files, process all files in a single pass without layering.

### Discovery (replaces Step 1)

The command has already called `orchestrator.py discover` and the user has confirmed the file list. You receive the confirmed list of source files.

Find tests for the unit as a whole — look for test files adjacent to or within the directory being taken over. Read all source files and all test files together before drafting specs.

If no tests are found for the unit, apply the same testless routing as single-file mode.

**Note:** Testless mode applies per-file -- some files in a multi-file takeover may have tests (standard path) while others don't (testless path). Track `testless_mode` independently for each file.

### Intent Lock (Phase 0a.0, replaces Step 1b for multi-file)

After reading all source files and tests for the unit, present a single aggregated Intent Statement covering the module as a whole:

> "From the existing code, I understand this module's purpose is [extracted intent for the unit]. The key responsibilities are: [list 2-4 top-level behaviors]. I'll draft specs that capture these behaviors. Does this match your understanding?"

Same approval/rejection protocol as single-file Step 1b. If rejected, reformulate. If abandoned, no artifacts left behind.

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

### Validate (Step 6 -- updated)

Run tests once for the entire unit (not per-file). The test command from `.unslop/config.json` should cover the unit. For files on the testless path, run adversarial validation (Step 5) per-file. If all pass, commit ALL specs and generated files together (Step 8).

### Convergence Loop (Step 7 -- updated)

The loop works the same as single-file mode with these changes:
- Each convergence iteration dispatches a fresh Builder Agent in a new worktree
- Enrich whichever spec(s) are relevant to the failing tests (based on the Builder's failure report)
- **Do NOT change `depends-on` frontmatter during convergence**
- Regenerate only files whose specs were enriched, plus dependents (check build order)
- For per-unit specs: the Builder generates all files in a single worktree session
- On convergence failure: discard the worktree, revert all staged spec updates

### Abandonment State (updated)

Same as single-file: keep all draft specs, keep all last generated attempts, all originals remain in archive. Do not clean up.
