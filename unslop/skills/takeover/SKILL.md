---
name: takeover
description: Use when running the unslop takeover pipeline to bring existing code under spec management. Covers discovery, spec drafting, archiving, generation, and the convergence validation loop.
version: 0.14.0
---

# Takeover Skill

## What Takeover Is

Takeover brings an existing file under spec management by lifting it through unslop's IR layers: Code -> Concrete Spec -> Abstract Spec. This two-phase lifting is more accurate than jumping directly from code to abstract spec, because the intermediate Concrete Spec preserves algorithmic decisions that may be load-bearing.

The three phases are:

1. **Distill** -- read the existing code, infer intent, extract the algorithmic "How" into a Concrete Spec
2. **Elicit** -- extract observable behavior and constraints from the Concrete Spec into an Abstract Spec; get user approval
3. **Generate** -- lower the approved Abstract Spec through a fresh Concrete Spec, dispatch an isolated Builder, validate against the original test suite (or the adversarial pipeline for testless files)

The Rosetta Stone principle underpins this: the spec encodes the intent; the code is disposable. Once you have an approved Abstract Spec, the original implementation can be discarded. The spec is the artifact that matters. Takeover is the process of creating that spec from code that predates it.

---

## When to Use Takeover

Use takeover for **existing code** that has no spec. The code is the source of truth -- the goal is to infer what the code should do (not just what it does) and encode that intent as a spec.

Do not use takeover for greenfield files. For new files, use `/unslop:spec` to draft a spec first, then `/unslop:generate` to produce the implementation.

Signals that a file is a good takeover candidate:

- No corresponding `*.spec.md` or `*.unit.spec.md`
- The file is stable enough that its behavior is understood
- The file has tests, or is complex enough that adversarial validation adds value
- The file will be modified going forward and needs a spec to guide future generation

Takeover is not appropriate for:

- Pure glue/wiring files with no logic to specify
- Files that are scheduled for deletion
- Files where the current behavior is known to be wrong (fix first, then take over)

---

## The Archaeological Phase

The distill step is the heart of takeover. The Architect reads the code as an archaeologist reads an artifact -- inferring original intent from observable structure. The goal is not to describe what the code does mechanically, but to understand why it was written this way and what problem it was solving.

Key distinctions the archaeological reading must make:

- **Intentional algorithmic choices** -- e.g., exponential backoff with jitter. These reflect a deliberate decision about observable behavior. They go into the Abstract Spec as constraints ("must prevent thundering herds") or as pinned behavior if the choice is observable.
- **Observable algorithmic behavior** -- choices that produce different outputs for the same inputs. These must be preserved by default. If the Architect wants to change them, it flags the change as a **Behavioural Upgrade** with rationale; the user decides whether to preserve or upgrade.
- **Incidental implementation details** -- e.g., uses a dict for caching. These reflect no behavioral commitment. They are omitted from the Abstract Spec and left to the Builder.

The observable test: if two implementations produce different outputs for the same inputs, the choice between them is observable and must be pinned or flagged. If they produce identical outputs, the choice is incidental and can be left to the Builder. During takeover, when in doubt, pin it -- under-abstraction is safer than silent behavior change.

---

## Pre-flight: Complexity Assessment

Before discovery, the Architect assesses the target file's complexity to determine if a pre-takeover split is needed and to detect protected regions.

**Thresholds** (configurable in `.unslop/config.json` under the `preflight` key):

| Metric | Suggest split | Require split |
|---|---|---|
| Line count | >1000 | >2000 |
| Public symbols | >30 | >60 |
| Token weight (~bytes/4) | >8000 | >16000 |

Either condition triggers. The Architect presents the analysis before proceeding.

**Protected regions** are tail blocks that serve a different purpose than the implementation above them (compile-time test conditionals, main entry guards, benchmark blocks). If detected, they are recorded for inclusion in the Concrete Spec's `protected-regions` frontmatter during distill. They do not block discovery.

**Split planning** (only if thresholds exceeded): the Architect drafts a module split that preserves every public symbol accessible via the original module path. API preservation is the prime directive -- all public symbols remain accessible after the split via re-exports in a facade. The split plan is interactive; the user can rename modules, move symbols between groups, or override the proposal. The `--force` flag bypasses "require" thresholds with a warning.

Split execution runs as a mechanical refactor (no logic changes, no signature changes), followed by a build check, test run, and a standalone commit before takeover begins. On failure, the split is reverted and the user chooses whether to proceed unsplit or abort.

---

## Discovery Flow

Discovery is the first phase of takeover. It establishes what the pipeline is working with before any spec drafting begins.

**What discovery does:**

1. Reads the target file in full
2. Locates test files by convention (adjacent files, standard naming patterns for the project's language)
3. Reads all discovered test files
4. Determines whether the file has tests (`testless_mode`)
5. Checks for override flags (`--skip-adversarial`, `--full-adversarial`) that affect downstream routing

**Testless routing:** If no tests are found and adversarial mode is available, discovery proposes the testless takeover path -- the adversarial pipeline will generate and validate tests automatically. The user confirms before proceeding. If adversarial mode is not available, the user is warned that the spec will be unvalidated and must confirm explicitly.

In multi-file mode, prunejuice discovers source files and the user confirms the file list before the Architect reads them. Testless mode is tracked independently per file -- some files in a multi-file takeover may have tests while others do not.

---

## Intent Lock

After reading the target file and its tests, the Architect articulates the extracted product intent before drafting any spec content. This prevents confusing "how it works" with "how it should work."

The intent statement uses user/product language, not implementation language. "Ensure failed HTTP requests are retried with backoff" passes. "Implement exponential retry with jitter in the request handler" fails -- that is the Concrete Spec's job.

The intent statement is presented to the user for approval. On approval, the intent is recorded in the spec's frontmatter with a timestamp and hash (SHA-256 truncated). This creates a tamper-detectable audit trail: git blame shows who approved the intent and when. Future spec changes that drift beyond the recorded intent trigger a re-lock.

**No force-approve.** Intent Lock is mandatory. There is no `--skip-intent` or auto-approve mechanism. If the user rejects the intent, the Architect reformulates. If the session is abandoned, no artifacts are left behind.

---

## Three-Phase Flow

### Phase 1: Distill (Raise to Concrete Spec)

The Architect reads the target file and all discovered test files, then extracts the implementation strategy:

- **Algorithm** -- What approach does the code use? (expressed as pseudocode)
- **Patterns** -- What design patterns are in play?
- **Type structure** -- Key types/interfaces and their relationships
- **Data flow** -- How data moves through the system
- **Edge cases** -- What special cases does the code handle, and which are intentional vs. incidental?

The result is a Concrete Spec (`*.impl.md`) that faithfully describes the current "How" -- including bugs and warts. Do not idealize. This spec is ephemeral during takeover; it serves as a stepping stone to the Abstract Spec and as diagnostic context during convergence.

For complex files (multiple algorithms, async flows, non-obvious state machines), the Concrete Spec is presented to the user. For straightforward files, the Architect proceeds directly to Phase 2.

### Phase 2: Elicit (Raise to Abstract Spec)

From the Concrete Spec and the original code/tests, the Architect extracts the observable behavior:

- **Intent** -- What is this code for? What problem does it solve?
- **Contracts** -- Inputs, outputs, invariants
- **Error conditions** -- What inputs or states are invalid? How are errors surfaced?
- **Constraints** -- Size limits, retry counts, timeouts, ordering guarantees, concurrency expectations

Implementation details do NOT go into the Abstract Spec. The Concrete Spec captures the "How"; the Abstract Spec captures only the "What" and "Why". Algorithms, data structures, variable names, and internal control flow belong in the Concrete Spec or in code.

The draft Abstract Spec is presented to the user with the prompt:

> "Review this spec. Does it capture what this code is supposed to do? I'll regenerate fresh code from this spec alone, so anything missing here will be lost. The implementation strategy (algorithm, patterns) will be re-derived during generation."

**User approval is required before Phase 3.** The Architect incorporates corrections and re-presents if needed.

**Testless path addition:** For files without tests, a `*.behaviour.yaml` is also generated alongside the Abstract Spec. This encodes given/when/then constraints for each public function, error entries for every exception the code raises, and invariant entries for state consistency properties. BehaviourContract TS interface enforces the schema at construction time. The behaviour.yaml and abstract spec are presented jointly for user approval.

Legacy smell detection runs before the behaviour.yaml is written: each extracted behaviour is cross-checked against `.unslop/principles.md`. Constraints that contradict a principle are flagged as `legacy_smell` and presented neutrally ("contradicts principle X. Preserve or discard?"). Legacy smells are not encoded as invariants unless the user overrides.

### Phase 3: Generate (Lower & Validate)

Generation follows the standard unslop generation pipeline:

1. **Archaeologist** derives a fresh Concrete Spec from the approved Abstract Spec. The previously raised Concrete Spec (from Phase 1) is available as reference -- the Archaeologist may reuse algorithmic choices the user confirmed as intentional, but is free to choose a different strategy if the Abstract Spec permits it. The Archaeologist runs for every file regardless of complexity.

2. **Builder** is dispatched in a worktree-isolated subagent. It receives only the spec files and the Archaeologist's Concrete Spec -- never the archived original or the Architect's conversation context. This isolation is the integrity guarantee: if the Builder reproduces the code from the spec alone, the spec is proven sufficient.

3. **Validation** follows the tests-exist or testless path (see below).

---

## User Confirmation Checkpoints

Takeover has four points where the user must explicitly approve before proceeding. These are not optional pauses -- they are gates.

| Checkpoint | What the user sees | What happens on rejection |
|---|---|---|
| **Split plan** (if thresholds exceeded) | Module split proposal with symbol counts | Architect revises or user overrides; Abort exits cleanly |
| **Intent Lock** | Extracted product intent in user/product language | Architect reformulates; no artifacts left if abandoned |
| **Concrete Spec** (complex files only) | Algorithm, patterns, type structure extracted from code | Architect revises based on user corrections |
| **Abstract Spec** (+ behaviour.yaml for testless) | Observable behavior, contracts, constraints | Architect incorporates corrections, re-presents |

After all gates, the pipeline proceeds autonomously through archive, generation, and validation. The next user interaction point is convergence (if tests fail) or the post-takeover hardening offer (if tests pass).

---

## Granularity: Per-File vs. Per-Unit

When taking over a directory, the user chooses the spec granularity before drafting begins:

- **Per-file specs** -- one spec per source file, with `depends-on` declarations between them. Better for loosely coupled files or large units. prunejuice computes build order from the dependency graph so generation runs leaves-first.
- **Per-unit spec** -- one `<dir>.unit.spec.md` describing the entire module with a `## Files` section. Better for tightly coupled files with shared internal APIs.

For units larger than ~10 files, per-file mode is recommended due to context limits.

**Per-file mode discovery and ordering:** prunejuice discovers source files; the user confirms the list. For generation, prunejuice computes build order from `depends-on` frontmatter so leaves are generated before their dependents.

**Per-unit mode:** All files are read together; a single spec covers the module; generation produces all files in a single Builder session in the order listed under `## Files`.

In both modes, all specs are presented to the user together for review before any generation begins.

---

## Validation and Convergence

### Tests-exist path

After the Builder completes, the test suite runs against the generated file. If green, the pipeline proceeds to commit. If red, the convergence loop begins.

**Convergence** (maximum 3 iterations):

1. The Builder's failure report is read -- failing test names, assertion messages, suspected spec gaps
2. The raised Concrete Spec from Phase 1 provides diagnostic context -- it shows why the original code handled certain cases
3. The Architect enriches the Abstract Spec with missing constraints (in spec-language voice -- no implementation suggestions)
4. The enriched spec is presented to the user for approval
5. A fresh Archaeologist derives a new Concrete Spec; a fresh Builder is dispatched in a new worktree
6. Tests run again

If maximum iterations are reached without green tests, the worktree is discarded, staged spec updates are reverted, and the user is given the Builder's latest failure report plus the archive location for manual recovery.

### Testless path

Validation uses the adversarial pipeline as quality gate:

1. Mason generates tests from the behaviour.yaml only (Chinese Wall -- Mason does not read the generated implementation)
2. Saboteur reports compliance violations for internal mocks
3. Tests run against the generated code
4. Saboteur runs mutation testing against the generated code using Mason's tests

Convergence classifies failures as `weak_test` (Mason's assertions insufficient), `spec_gap` (behaviour.yaml missing constraints), or `test_failure` (generated code does not match behaviour.yaml). Each type routes to a different repair action.

Entropy tracking: if kill rate improvement stalls below the entropy threshold, Radical Spec Hardening triggers -- a one-shot rewrite of behaviour.yaml using the Archaeologist's surviving mutant summary. If that also stalls, the pipeline commits with a warning annotation noting the unresolved kill rate gap.

---

## Archive

Before generation begins, the original file is archived at:

```
.unslop/archive/<relative-path>.<ISO8601-compact-timestamp>
```

Example: `.unslop/archive/src/retry.py.20260320T143200Z`

The timestamp is compact ISO 8601 UTC: `YYYYMMDDTHHMMSSZ`. The archive is a safety net -- the user can recover the original manually if needed. It is never deleted or modified after creation.

---

## Atomic Commit

On successful validation, all artifacts are committed together:

- Abstract spec
- Generated implementation
- Concrete spec (if promoted)
- `*.behaviour.yaml` (testless path)
- Generated tests from Mason (testless path)

Generated files are updated with the `output-hash` in their `@unslop-managed` header.

After a successful commit on the tests-exist path, the pipeline offers post-takeover test hardening:

> "Takeover complete. The Builder wrote tests based on the spec, but they haven't been validated via mutation testing. Run `/unslop:cover <file>` to check for weak assertions and test scum?"

This is advisory, not automatic.

---

## Abandonment State

When the convergence loop exhausts its iterations without green tests:

- The draft spec is kept -- it contains the constraints identified so far; the user can edit it and resume
- The last generated attempt is kept -- the user can inspect it to understand what the current spec produces
- The original remains in the archive -- available for manual recovery

No artifacts are deleted, overwritten, or cleaned up. The working tree is left in a state the user can reason about and act on.

---

## Multi-File Context Management

For takeovers of 6 or more files, the Architect processes files in dependency layers (leaves first, then dependents). Each layer is committed atomically before the next layer's source files are loaded. This keeps the Architect's working set to one layer at a time and allows resume from the last committed layer if the session hits context limits.

For batches of 5 or fewer files, all files are processed in a single pass without layering.

---

## Design Rationale: Why This Works

**The Rosetta Stone.** The spec is the Rosetta Stone: it encodes the intent in a form that can generate the code in any future version of the language, framework, or runtime. The code is the translation -- disposable once the spec exists. Takeover is the process of recovering the Rosetta Stone from a translation when the original was lost.

**Two-phase lifting.** Going directly from code to abstract spec risks collapsing important algorithmic distinctions. The intermediate Concrete Spec preserves the "How" long enough for the Architect to decide what is intentional, what is observable, and what is incidental. This classification is the core intellectual work of takeover.

**Intent Lock before spec drafting.** The Intent Lock forces the Architect to articulate what the code is for before describing how it works. This prevents the most common failure mode of archaeological spec inference: mistaking implementation accident for design intent.

**Isolated Builder as proof.** The Builder's isolation is not a security measure -- it is a correctness proof. If the Builder can reproduce working code from the spec alone, without access to the original, the spec is proven sufficient to regenerate the module. If the Builder cannot, the spec is incomplete, and the convergence loop is the mechanism for discovering what is missing.
