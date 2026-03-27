# Cross-Spec Coherence Checking (Milestone J)

> Catch contradictions between related specs before generation, so the Builder doesn't inherit impossible requirements.

## Problem

Each spec is validated in isolation. Phase 0a checks structure, Phase 0b checks ambiguity within a single spec, and Phase 0c processes change requests. But none of these catch contradictions *between* specs that share a dependency relationship.

When Spec B `depends-on` Spec A, the two specs share an implicit contract -- a boundary where A's outputs become B's inputs. If A says "returns a dict with key `user_id`" and B says "expects a `userId` key from A's output", both specs are internally consistent but together they're broken. The Builder will generate code that fails at the boundary, and the failure surfaces as a test error with no clear link back to the spec contradiction that caused it.

This is worse than an ambiguity within a single spec because the user has to cross-reference multiple files to find the source of the problem. The convergence loop can't fix it either -- enriching B's spec won't help if A's spec is the one that needs to change.

## Solution

A new validation phase that walks the dependency graph and checks spec pairs for contract consistency. This runs in the Architect's context (Stage A) before any Builder is dispatched.

### What coherence means

Two specs are *coherent* if:

1. **Shared interfaces agree.** When B depends on A, any interface described in both specs (function signatures, return types, error types, data shapes, event formats) must be compatible. Not identical -- A may describe more than B uses -- but the subset B references must match what A promises.

2. **Constraints don't conflict.** If A says "max 5 retries" and B says "A retries indefinitely until success", the constraint is contradictory. If A says "returns None on failure" and B says "A raises on failure", the error contract is contradictory.

3. **Naming is consistent.** If A defines `UserToken` and B references `AuthToken` for the same concept, that's an incoherence even if the behavior descriptions match. Naming mismatches cause the Builder to generate incompatible types.

### What coherence does NOT mean

- **Implementation agreement.** A says "uses SQLite" and B says "uses Postgres" is NOT an incoherence if they're independent files that don't share a database. Coherence only applies to shared contracts.
- **Completeness.** A missing constraint in A is an ambiguity problem (Phase 0b), not a coherence problem. Coherence checks what's stated, not what's missing.
- **Style consistency.** One spec using "returns" and another using "yields" is not incoherent unless the semantic difference matters (sync vs async).

## Integration Point

### Option A: New Phase 0e in the generation skill

Add a Phase 0e ("Coherence Check") after Phase 0d (Domain Skill Loading), before Section 1 (Generation Mode Selection). This runs automatically on every generation for any spec that has `depends-on` frontmatter.

**Pros:** Automatic, no user action needed. Catches coherence issues before the Builder even starts.
**Cons:** Adds latency to every generation of specs with dependencies. May be redundant for specs that haven't changed since the last coherence check.

### Option B: Standalone command `/unslop:coherence`

A command the user runs explicitly, similar to `/unslop:harden` but for cross-spec consistency.

**Pros:** No generation latency. User controls when to run it. Can check the entire project at once.
**Cons:** Not automatic -- users forget to run it. Contradictions surface as test failures instead of pre-generation warnings.

### Recommendation: Both

- Phase 0e runs a **lightweight** coherence check during generation: only checks the target spec against its direct dependencies. This is fast (reads 2-3 specs) and catches the most common issues.
- `/unslop:coherence` runs a **full** project-wide check: walks the entire dependency graph and checks all pairs. This is for project health audits, not per-generation.

## Phase 0e: Lightweight Coherence Check

### When it runs

After Phase 0d (Domain Skill Loading), before Section 1 (Generation Mode Selection). Only runs if the target spec has `depends-on` frontmatter.

### What it checks

For each dependency in the target spec's `depends-on` list:

1. Read both specs (target + dependency).
2. Identify the shared interface -- the boundary where the dependency's outputs become the target's inputs. Look for:
   - Function/method signatures referenced in both specs
   - Data types or shapes described in both specs
   - Error types or error behavior described in both specs
   - Events, messages, or protocol formats described in both specs
3. For each shared interface element, check:
   - **Type compatibility:** Do the specs agree on the shape of data crossing the boundary?
   - **Constraint compatibility:** Do numeric bounds, cardinality limits, or ordering guarantees agree?
   - **Error contract compatibility:** Do the specs agree on what constitutes an error and how it's signaled?
   - **Naming consistency:** Do the specs use the same names for the same concepts?

### Result handling

- **No incoherence found:** Report "Coherence check: specs are consistent." Proceed to Section 1.
- **Incoherence found:** Report each issue with quoted text from both specs:

> "Cross-spec incoherence between `handler.py.spec.md` and `tokens.py.spec.md`:
> - handler.spec says: "receives a `userId` string from token validation"
> - tokens.spec says: "returns a dict with key `user_id`"
> - Issue: naming mismatch (`userId` vs `user_id`) -- the generated code will use different keys.
>
> Fix one of the specs to use consistent naming, then re-run."

**Stop generation** on incoherence. Unlike ambiguity (which can be overridden with `--force-ambiguous`), coherence failures indicate a real contract mismatch that will produce broken code. There is no `--force-incoherent` flag.

### Performance

This is model-driven (the LLM reads and compares specs), not deterministic. Cost: one LLM call per dependency pair. For a spec with 2 dependencies, that's 2 additional calls before generation. This is acceptable because:
- Most specs have 0-2 dependencies
- The check prevents a full Builder dispatch + worktree + test cycle that would fail anyway
- The check only runs when the target spec actually has `depends-on`

## `/unslop:coherence` Command

### Usage

```
/unslop:coherence [spec-path]
```

- With a spec path: checks that spec in **both directions** -- against its upstream dependencies (using `orchestrator.py deps`) AND against all specs that depend on it (reverse dependents). This catches the common case of editing an upstream contract provider and needing to verify downstream consumers are still coherent.
- Without arguments: checks all specs in the project against their dependencies

### What it does

**Targeted mode** (`/unslop:coherence <spec-path>`):
1. Resolve upstream dependencies: `orchestrator.py deps <spec-path> --root .`
2. Resolve reverse dependents: scan all `*.spec.md` files for `depends-on` entries referencing the target spec
3. Check coherence between the target and each upstream dependency
4. Check coherence between the target and each reverse dependent
5. Report all incoherences found

**Full mode** (`/unslop:coherence`):
1. Build the full dependency graph (`orchestrator.py build-order .`)
2. For each dependency edge in the graph, run the coherence check on that pair
3. Report all incoherences found across the project

### Output format

```
Cross-spec coherence check:

  handler.py.spec.md <-> tokens.py.spec.md
    ✗ naming mismatch: "userId" (handler) vs "user_id" (tokens)

  middleware.py.spec.md <-> handler.py.spec.md
    ✓ consistent

  adapter.py.spec.md <-> errors.py.spec.md
    ✗ error contract: adapter expects "raises AuthError", errors spec says "returns None"

2 incoherence(s) found across 3 dependency pairs.
```

### Integration with other commands

- `/unslop:status` could show a coherence indicator for specs with dependencies (e.g., `stale (incoherent)` if a dependency's spec changed since the last coherence check). This is optional and can be added later.
- `/unslop:harden` already asks "Do constraints conflict with `depends-on` specs?" (generation SKILL.md line 487). Coherence checking formalizes this as a structured check rather than an ad-hoc question.

## Orchestrator Changes

### No new subcommands needed

The existing `deps` and `build-order` subcommands provide the dependency graph. Phase 0e and the `/unslop:coherence` command use these to identify which spec pairs to check. The coherence check itself is model-driven, not deterministic, so it doesn't belong in the orchestrator.

### Possible future optimization: coherence hash

If coherence checking becomes a latency concern, the orchestrator could store a `coherence-hash` per dependency pair -- a hash of both specs' content at the time they were last checked. If neither spec has changed, skip the check. This is an optimization, not a requirement for the initial implementation.

## Unit Specs

For unit specs (`*.unit.spec.md`), coherence checking has two aspects:

### External coherence (unit spec <-> other specs)

- Coherence checking applies when a unit spec has `depends-on` entries referencing other specs (unit or per-file)
- Works identically to per-file coherence: check the shared interface between the unit spec and each dependency

### Intra-unit coherence (files within a unit spec)

Phase 0b checks ambiguity within a single document but does NOT check cross-file contract consistency. A unit spec can describe File A returning `user_id` and File B consuming `userId` without Phase 0b flagging it, because neither description is ambiguous in isolation.

Phase 0e adds an **intra-unit coherence pass** for unit specs: after checking external dependencies, also check the contracts between files listed in `## Files`. For each pair of files described in the unit spec that reference each other's outputs, apply the same coherence checks (type compatibility, constraint compatibility, naming consistency).

This only fires for unit specs -- per-file specs don't have internal file boundaries to check.

### Mixed dependencies (per-file spec depends on a file inside a unit spec)

When a per-file spec needs to declare a dependency on a file that lives inside a unit spec, the `depends-on` entry references the **unit spec path**, not the individual file (which has no standalone spec):

```markdown
---
depends-on:
  - src/auth/auth.unit.spec.md
---
```

The coherence check then reads the unit spec and identifies the relevant file's description from `## Files` based on which file the dependent spec actually references in its behavior/constraints sections. This is model-driven: the LLM reads both specs and identifies the shared interface, just as it does for per-file spec pairs.

This requires no orchestrator changes -- `depends-on` already supports any `*.spec.md` path, including `*.unit.spec.md`. The orchestrator's `deps` and `build-order` commands resolve unit spec paths the same way they resolve per-file spec paths.

## What This Does NOT Replace

- **Phase 0b (Ambiguity Detection):** Catches ambiguity within a single spec. Coherence checks between specs.
- **Section 7 (Completeness Review):** Catches missing constraints after generation. Coherence catches contradictions before generation.
- **`/unslop:harden`:** Stress-tests a single spec. Coherence tests spec *pairs*.
- **Tests:** Tests validate generated code. Coherence validates spec consistency before code exists.

## Scope

- New: Phase 0e in generation skill (lightweight, per-dependency check)
- New: `/unslop:coherence` command (full project-wide check)
- No orchestrator changes
- No changes to existing phases or commands
- Model-driven (not deterministic) -- no new Python scripts

## Plugin Structure Changes

```
unslop/
├── commands/
│   └── coherence.md          # NEW -- project-wide coherence check
├── skills/
│   └── generation/
│       └── SKILL.md           # MODIFIED -- add Phase 0e
└── ...
```
