---
name: generation
description: Use when generating or regenerating code from unslop spec files. Activates during /unslop:generate, /unslop:sync, and the generation step of /unslop:takeover.
version: 0.1.0
---

# Generation Skill

Domain reference for spec-driven code generation. This skill describes what generation is, how the pipeline is structured, and what each agent role does. Orchestration is handled by prunejuice via MCP tools -- this skill is reference material, not a procedure.

---

## What Generation Is

Generation is the process of deriving source code from a spec file as a disposable artifact. The spec (`*.spec.md`) is the source of truth; the generated file is a consequence of it. Every generated file carries an `@unslop-managed` header that binds it to its spec via content hashes, enabling staleness detection.

Code is generated in one of two modes: **full regeneration** (new file, takeover, or `--refactor`) where the Builder derives output from the spec alone; or **surgical mode** (default for existing files) where only symbols governed by changed spec sections are re-derived while everything else is copied verbatim from the existing file.

Three orchestrators compose the generation pipeline in different combinations: **takeover** (distill -> elicit -> generate), **change** (elicit -> generate with ripple check), and **sync** (generate with dependency resolution).

---

## The Five-Phase Model

| Phase | Command | What it does |
|---|---|---|
| Distill | `/unslop:distill` | Infer spec from existing code (Archaeologist reads code, produces spec draft) |
| Elicit | `/unslop:elicit` | Create or amend spec via Socratic dialogue (Architect validates intent) |
| Generate | `/unslop:generate` | Tests-then-implementation from spec (Archaeologist + Mason + Builder) |
| Cover | `/unslop:cover` | Find and fill test coverage gaps (Saboteur + Archaeologist + Mason) |
| Weed | `/unslop:weed` | Detect intent drift between spec and code |

The phases are not always run in sequence. Orchestrators compose subsets: sync skips distill and elicit; takeover runs all five in order.

---

## Agent Roles and Information Boundaries

The generation pipeline uses five specialized agents. Each agent has a defined information boundary -- what it is permitted to read. These are not style guidelines; violations break the correctness model.

### Agent Role Table

| Agent | Model | What it reads | What it produces |
|---|---|---|---|
| Architect | opus | Spec, change intent, file tree (names only) | Updated spec (staged, not committed) |
| Archaeologist | opus (distill), sonnet (generate) | Approved abstract spec, existing concrete spec (if permanent), file tree | Concrete spec (`*.impl.md`), `behaviour.yaml` fragment, `discovered:` items |
| Mason | sonnet | `behaviour.yaml` fragment ONLY | Test file |
| Builder | sonnet | Abstract spec, concrete spec, principles, config, test files | Generated source file with `@unslop-managed` header |
| Saboteur | sonnet | Managed file, spec, test file | Mutation results, compliance findings |

### The Chinese Wall

Mason never reads the concrete spec, abstract spec, or source code. It derives tests exclusively from `behaviour.yaml`. This isolation guarantees tests are derived from specified behaviour, not from implementation details -- the tests become an independent specification of correctness.

The Architect reads the file tree (names only) to understand project structure but is blocked from reading source code or test files. During normal generate/sync, the Architect sees only specs and intent. Exception: during `/unslop:takeover`, the Architect reads existing source code because the point of takeover is extracting intent FROM code.

### The Archaeologist's Dual Projection

The Archaeologist produces two artifacts from a single spec read:
- **Concrete spec** (`*.impl.md`): the implementation strategy for the Builder (algorithmic "how")
- **`behaviour.yaml` fragment**: the testable constraint set for Mason (behavioural "what")

`non-goals:` from the abstract spec are projected into `behaviour.yaml` as negative constraints (invariants asserting behaviour is NOT present) and into the concrete spec as explicit exclusions. The two projections are derived from the same spec read but delivered to different consumers. The Builder never reads `behaviour.yaml`; Mason never reads the concrete spec.

### Subagent Dependency Order

Within a single file's pipeline, agents run sequentially:

```
Archaeologist -> Discovery Gate (if discoveries) -> Mason -> Builder -> Saboteur (async)
```

Mason must complete before Builder so tests exist before code is generated. The Saboteur fires after the Builder's successful merge -- it is non-blocking and does not affect the generation output.

When processing multiple independent files, prunejuice dispatches their pipelines in parallel. Files in the same `depends-on` chain are processed sequentially in build order (leaves first).

---

## Spec Frontmatter Reference

Abstract specs (`*.spec.md`) carry YAML frontmatter that controls generation behavior and maintains provenance.

| Field | Set by | Cleared by | Purpose |
|---|---|---|---|
| `intent` | elicit, change | -- | One-line description of what the spec describes |
| `intent-approved` | elicit (timestamp) | Any spec body change resets to false | Tamper-detected approval |
| `intent-hash` | elicit | Recomputed on any body change | SHA-256 of spec body |
| `depends-on` | elicit, change | Manual | Spec dependency list |
| `non-goals` | elicit | Manual | Machine-readable exclusions |
| `managed-file` | takeover/generate | -- | Path to the generated source file |
| `needs-review` | change (downstream flagging) | elicit, review-acknowledged | Soft-block in generate/sync |
| `review-acknowledged` | generate/sync (user dismissal) | Next elicit pass | Conscious dismissal of needs-review |
| `uncertain` | distill | elicit resolves | "Was this accidental?" questions |
| `discovered` | generate Stage 0 | generate Stage 0b resolves | "Does your intent require this?" |
| `distilled-from` | distill | Never (persists) | Epistemic provenance |
| `absorbed-from` | absorb | Ratification | Structural provenance |
| `exuded-from` | exude | Ratification | Structural provenance |
| `complexity` | elicit, manual | -- | `low` / `medium` / `high` -- affects concrete spec promotion |
| `blocked-by` | manual | Manual | Deferred constraint permits for the Builder |

**Provenance field lifecycle:**
- `distilled-from:` persists after ratification (epistemic provenance -- was this spec machine-inferred?)
- `absorbed-from:` / `exuded-from:` clear on ratification, move to `provenance-history:`
- `uncertain:` clears when elicit resolves each item
- `discovered:` must be resolved before generate proceeds (transient -- never ratified silently)

---

## Concrete Spec Reference

Concrete specs (`*.impl.md`) are the Archaeologist's output -- the implementation strategy bridging abstract intent and generated code.

**Key sections:**
- `## Strategy` -- pseudocode for the core algorithm (child-only on inheritance; parent is purged)
- `## Pattern` -- named design patterns and architectural approach (overridable by key)
- `## Type Sketch` -- structural type signatures, language-agnostic (child-only on inheritance)
- `## Lowering Notes` -- language-specific considerations (additive merge with parent)

**Ephemeral vs Permanent:**
By default, concrete specs are ephemeral -- generated as the Builder's strategic input and discarded after successful generation. Promoted to permanent via `/unslop:promote`, or automatically for `complexity: high` specs. Permanent concrete specs live alongside the abstract spec as `<file>.impl.md` and are version-controlled.

**Strategy Inheritance:**
If a concrete spec has `extends: <base.impl.md>` in its frontmatter, prunejuice resolves the inheritance chain before presenting the spec to the Builder. The Builder always receives the resolved spec; it never sees the raw `extends` directive.

**Blocked-by Permits:**
If a concrete spec's frontmatter contains `blocked-by` entries, each entry names an abstract spec constraint that cannot be fulfilled yet and gives the reason. The Builder proceeds normally on all unblocked constraints. Blocked constraints are handled pragmatically (compatibility shims, legacy code paths). The Builder must not silently deviate on constraints not listed in `blocked-by`.

**Multi-target specs:**
Concrete specs may declare `targets` (a list of target files) instead of `target-language`. prunejuice dispatches parallel Builders -- one per target -- each receiving its target-specific lowering notes. Atomic merge semantics apply: all targets pass or all are discarded.

---

## Managed File Header Format

Every generated file MUST begin with a two-line header using the correct comment syntax for the file's extension.

**Line 1:** `@unslop-managed -- do not edit directly. Edit <spec-path> instead.`
**Line 2:** `spec-hash:<12hex> output-hash:<12hex> [principles-hash:<12hex>] generated:<ISO8601>`
**Line 3 (optional):** `concrete-manifest:<dep1.impl.md>:<12hex>,<dep2.impl.md>:<12hex>`
**Line N (optional):** `managed-end-line:<line-number>` -- 1-indexed line where a protected region starts. Present only when the concrete spec declares `protected-regions`. The freshness checker hashes only lines from below the header up to but not including this line.

The `output-hash` is SHA-256 of the file body (stripped), truncated to 12 hex characters. The `spec-hash` is SHA-256 of the spec file content, truncated to 12 hex characters. The header itself is not included in the `output-hash`.

The `concrete-manifest` line is written when the file has permanent concrete spec dependencies. It stores the hash of each direct strategy provider at generation time, enabling surgical ghost-staleness detection -- prunejuice can pinpoint exactly which upstream dependency changed rather than flagging all deps as suspects.

**Use UTC for the timestamp.** Format: `2026-03-20T14:32:00Z`

### Comment Syntax by Extension

| Extension | Comment syntax |
|---|---|
| `.py`, `.rb`, `.sh`, `.yaml`, `.yml` | `#` |
| `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.swift`, `.kt` | `//` |
| `.html`, `.xml`, `.svg` | `<!-- -->` |
| `.css`, `.scss` | `/* */` |
| `.lua`, `.sql`, `.hs` | `--` |

For unknown extensions, use `//` as the default.

### Examples

Python (`.py`):
```python
# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
# concrete-manifest:shared/fastapi-async.impl.md:7f2e1b8a9c04,src/core/pool.py.impl.md:b3d5a1f8e290
```

TypeScript (`.ts`):
```typescript
// @unslop-managed -- do not edit directly. Edit src/api-client.ts.spec.md instead.
// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
```

HTML (`.html`):
```html
<!-- @unslop-managed -- do not edit directly. Edit src/index.html.spec.md instead. -->
<!-- spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z -->
```

CSS (`.css`):
```css
/* @unslop-managed -- do not edit directly. Edit src/styles.css.spec.md instead. */
/* spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z */
```

---

## Hash Chain Freshness States

prunejuice's `prunejuice_check_freshness` MCP tool classifies each managed file into one of these states.

| State | Meaning | Generate behavior |
|---|---|---|
| `fresh` | `spec-hash` and `output-hash` match current files | Skip (already up to date) |
| `stale` | `spec-hash` changed; managed file not manually modified | Regenerate (spec-driven change) |
| `modified` | `output-hash` changed; managed file was edited directly | Warn; user must decide |
| `conflict` | Both spec and managed file changed | Hard block; resolve spec or revert code change |
| `pending` | Managed file does not exist; no active provenance | Generate for the first time (neutral state) |
| `structural` | Managed file missing; spec has active provenance (`distilled-from:`, `absorbed-from:`, `exuded-from:`) | Hard block in generate/sync; spec's subject disappeared -- absorb, exude, or remove spec |
| `ghost-stale` | An upstream concrete spec dependency changed; `concrete-manifest` diverges from current dep hashes | Regenerate with updated strategy context |
| `test-drifted` | Spec changed since Mason generated tests | Regenerate tests (Mason re-run before Builder) |

`pending` is neutral (planned, not yet generated). `structural` is a warning that requires structural repair before generation can proceed.

---

## Discovery Items

During spec projection, the Archaeologist may discover correctness requirements the abstract spec did not anticipate -- implicit ordering constraints, hidden dependencies, boundary conditions the spec failed to specify. These are returned as `discovered:` entries (title / observation / question) alongside the concrete spec and `behaviour.yaml`.

prunejuice presents each discovery to the user at the discovery gate (Stage 0b) for promote-or-dismiss resolution. Promoted discoveries update the abstract spec and trigger a Stage 0 re-run. Dismissed discoveries are noted and the pipeline proceeds.

The concrete spec must never silently absorb a constraint the user did not explicitly approve. This invariant is the reason the discovery gate blocks rather than auto-promoting.

---

## Convergence Loop

When verification fails (kill rate below threshold), prunejuice runs the convergence loop. Up to 3 normal iterations plus 1 radical hardening iteration (4 total).

### Kill Rate

Kill rate = `mutants_killed / (mutants_total - mutants_equivalent)`. Equivalent mutants (semantically identical code transformations) are excluded from the denominator. A kill rate of 1.0 means all non-equivalent mutations were detected by the test suite.

### Survivor Classification

Each surviving mutant is classified into one of three categories:

| Classification | Meaning | Who acts |
|---|---|---|
| `weak_test` | A test exists but does not assert strongly enough | Mason strengthens the test |
| `spec_gap` | No test covers this behavior -- the spec is silent | Architect enriches `behaviour.yaml` |
| `equivalent` | The mutation produces semantically identical behavior | No action; excluded from kill rate |

### Radical Hardening

If the kill rate stalls across multiple convergence iterations (entropy plateau), prunejuice triggers radical hardening: the Architect reviews all surviving `spec_gap` mutants together and enriches the abstract spec with new explicit constraints. This is a spec-level intervention, not a test-level one. After radical hardening, Stage 0 re-runs to produce a new concrete spec and `behaviour.yaml` reflecting the strengthened constraints.

Radical hardening fires at most once per generate pass. If kill rate remains below threshold after radical hardening, the pipeline aborts and surfaces the surviving mutants for manual review.

---

## Design Rationale

### Why Physical Worktree Isolation?

Every Builder runs as a fresh agent in an isolated git worktree with zero conversation history. This prevents context contamination between iterations and ensures failed Builders can be discarded without corrupting the main branch. The spec update and generated code commit atomically -- if the Builder fails, the staged spec update is reverted and main is untouched.

### Why Mutation Testing?

Standard code coverage confirms that lines were executed, not that behavior was verified. A test can execute every line while asserting nothing meaningful. Mutation testing introduces small semantic changes to the code (mutants) and checks whether the test suite catches them. Surviving mutants are evidence that some behavior is untested or under-specified, not merely un-executed.

### Why the Chinese Wall?

If Mason read the concrete spec, its tests would reflect implementation choices rather than specified behavior. When the Builder then generates code matching those tests, it passes tests that were calibrated to its own implementation -- circular validation. The Chinese Wall breaks this circuit: Mason's tests are derived from `behaviour.yaml` (the behavioral contract) without knowledge of how the code will be structured. The tests are an independent specification of correctness.

### Why TypeScript Orchestration (prunejuice)?

The original Python orchestrator was a single 3000-line script with no type guarantees, no structural isolation between pipeline stages, and no programmatic interface for tooling. prunejuice provides typed MCP tools, a DAG-based dependency model, and composable pipeline stages. The architectural boundary is intentional: prunejuice handles all orchestration; unslop's markdown commands and skills handle agent prompting and domain knowledge.
