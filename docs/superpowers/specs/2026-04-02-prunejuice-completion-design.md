# Prunejuice Completion: Concrete Spec Correctness, Inheritance, and Python Retirement

## Context

Phases 1--5 of the prunejuice integration shipped the core MCP infrastructure: DAG cache, dependency tools, sync planning, pipeline execution, and command migration. The Python orchestrator is no longer on the MCP execution path -- all unslop commands now call prunejuice MCP tools.

However, the port is incomplete. Prunejuice has the *detection* layer for concrete specs (ghost-stale classification in ripple.ts, extends chain tracking, multi-target file support) but not the *resolution* layer (ghost staleness root cause tracing, inheritance flattening, concrete deps transitive hashing, multi-target collision detection). The Python orchestrator still contains ~2,600 lines of load-bearing logic across 6 critical modules that must move to TypeScript before the Python code can be deleted.

**The Python orchestrator dies completely.** There is no "stays as reference" category. Everything the Python orchestrator does that is not pure user interaction (presenting choices, Socratic dialogue, command hints) moves into prunejuice. The command layer becomes thin -- it constructs MCP calls and presents results. Prunejuice owns all the logic.

## Phases

Three phases with strict dependencies: Phase 7 depends on Phase 6 (flattening needs manifest for concrete deps), Phase 8 depends on Phase 7 (cannot delete Python until everything is ported).

---

## Phase 6: Ripple Correctness Foundation

**Goal:** Make `prunejuice_ripple_check` produce correct, actionable output for concrete specs -- including ghost staleness diagnostics with root cause tracing.

### New module: `manifest.ts`

Three exported functions for concrete dependency hash computation and diffing:

```typescript
// Transitive BFS through concrete-dependencies + extends providers.
// Returns combined hash of all provider contents.
function computeConcreteDepsHash(specPath: string, cwd: string): Promise<TruncatedHash>;

// Same BFS, returns per-dependency hash map for surgical diagnostics.
function computeConcreteManifest(specPath: string, cwd: string): Promise<Map<string, TruncatedHash>>;

// Structured diff between two manifests.
function diffConcreteManifests(
  previous: Map<string, TruncatedHash>,
  current: Map<string, TruncatedHash>
): { added: string[]; removed: string[]; changed: string[] };
```

The BFS walks `concrete-dependencies` and `extends` edges via `parseConcreteSpecFrontmatter`, uses a visited set for cycle safety, and calls `truncatedHash` from `hashchain.ts` on each file's content. The manifest is persisted alongside the managed file header so the diff can be computed against the last-ratified state.

**Module boundary:** `hashchain.ts` is a pure function module (content in, hash out, no IO). `manifest.ts` is IO-bound graph-walking that calls `hashchain.ts` for leaf operations. They MUST remain separate -- folding manifest into hashchain contaminates a pure module with async IO and graph traversal.

### Ghost staleness diagnostics

Extend the ripple check output with root cause tracing. Currently `ripple.ts` detects ghost-stale entries but provides no explanation of *why*. Add:

```typescript
interface GhostStaleDiagnostic {
  changedSpec: string;       // the upstream spec whose content changed
  changeHash: string;        // current hash of the changed spec
  chain: string[];           // dependency path: [root cause, ..., this spec]
  manifestDiff: {            // what specifically changed
    added: string[];
    removed: string[];
    changed: string[];
  };
}
```

Attached to `RippleManagedEntry` when `currentState` is `"ghost-stale"`. Built by:

1. Computing the current manifest for the ghost-stale spec
2. Diffing against the stored manifest from the managed file header
3. For each changed entry, tracing back through the dependency graph to find the original spec change that triggered the cascade

A new internal function `diagnoseGhostStaleness(specPath, manifest, cwd)` does the chain tracing. It lives in `manifest.ts` since it operates on manifest data. The ripple check calls it when it classifies an entry as ghost-stale.

A `formatGhostDiagnostic(diagnostic: GhostStaleDiagnostic): string` function produces the human-readable output that the command layer surfaces directly. Lives in `manifest.ts` alongside `diagnoseGhostStaleness` -- both operate on manifest data, and a standalone diagnostics module for one function is unnecessary. This keeps the command layer thin -- it passes the diagnostic string through without reconstructing the chain.

### parseConcreteSpecFrontmatter test coverage

The function exists in `ripple.ts` but has zero test coverage. Contract extraction from Python's 150+ frontmatter tests, then TS tests covering:

- Basic fields: `source-spec`, `extends`, `concrete-dependencies` (inline and list formats)
- Structured targets: `targets` array with `- path:` entries
- Relative path resolution for `source-spec`
- Snake_case key normalization
- Malformed/missing fields (error paths)
- Edge cases: empty targets, self-referential extends

### Extends chain tests

Contract extraction from Python's extends chain tests:

- Linear chain (child -> parent -> grandparent)
- Chain depth validation (cycle detection via visited set)
- Reverse edge construction for ripple propagation
- Extends combined with concrete-dependencies (both edge types in same spec)

### Test strategy

Hybrid approach: extract behavioral contracts from Python tests as one-line descriptions, reuse Python test fixtures (YAML frontmatter strings, directory layouts) directly as TS test data, write TS tests matching prunejuice's module structure.

For each Python test, the contract extraction step produces a one-line description of what behavior it enforces. If the contract cannot be stated in one line, either the test is testing implementation internals (skip) or the behavior is not yet understood (understand before porting).

Ghost staleness diagnostic tests get extra scrutiny during contract extraction -- the diagnostic output is user-facing and complex. Getting the contract wrong produces confusing output in production.

---

## Phase 7: Inheritance Flattening + Collision Detection

**Goal:** Give Archaeologist and Builder the resolved concrete spec view, and prevent sync plans from producing non-deterministic output when multiple specs claim the same target.

### New module: `inheritance.ts`

On-demand inheritance flattening -- consumers call it when they need the resolved view, raw parse remains available for ripple analysis:

```typescript
interface FlattenedSection {
  content: string;
  source: string;        // which spec in the chain provided this section
  rule: "strict_child_only" | "additive" | "overridable";
}

interface FlattenedConcreteSpec {
  specPath: string;
  chain: string[];        // [child, parent, grandparent, ...]
  sections: Map<string, FlattenedSection>;
}

function flattenInheritanceChain(
  specPath: string,
  cwd: string
): Promise<FlattenedConcreteSpec>;
```

**Merge rules:**

- **STRICT_CHILD_ONLY** (Strategy, Type Sketch): child's section wins completely, parent ignored. If child has no section, parent's is used.
- **Additive** (Lowering Notes): concatenated from all levels, child first, with attribution markers between levels.
- **Overridable** (Pattern): child overrides if present, otherwise inherits from nearest ancestor that has it.

**Cycle detection:** visited set (primary defense) + `MAX_EXTENDS_DEPTH=3` cap (secondary sanity check). Throws `InheritanceCycleError` with the full cycle path. Not a partial result, not a fallback -- a circular extends chain is a spec authoring error.

**Design rationale for on-demand (not parse-time) flattening:** The ripple check needs raw extends metadata to build correct reverse edges. If `loadConcreteSpec` returned a flattened view that silently consumed the extends relationship, the ripple check would have to re-parse the raw file to recover structural information, or the extends edges would be lost entirely. Keeping raw parse and flattening separate means each consumer gets exactly what it needs:

```typescript
// ripple check -- needs raw extends for graph traversal
const raw = parseConcreteSpecFrontmatter(content);
buildReverseEdges(raw.extends, specPath);

// Archaeologist + Builder dispatch -- need resolved view
const resolved = await flattenInheritanceChain(specPath, cwd);
dispatchArchaeologist(resolved);
```

**Section extraction:** `extractSections(content: string): Map<string, string>` splits a concrete spec by `## ` headings. Internal to `inheritance.ts`, not exported.

### Multi-target collision detection

Extend `partitionPlan` in `sync.ts` to detect target collisions across concrete specs:

```typescript
interface CollisionEntry {
  status: "collision";
  targetPath: string;
  claimants: string[];        // both spec paths
  preferSpec?: string;        // set when force: true, names the winner
  skippedSpec?: string;       // the loser, logged but not executed
}
```

**Detection:** After building the sync plan but before returning it, scan all plan entries' targets. If two specs claim the same target path, emit a `CollisionEntry`. Plan entries for colliding specs are blocked from execution.

**Resolution:** `force: true` alone is insufficient -- MUST be paired with `preferSpec` naming one of the claimants. Without `preferSpec`, collision entries remain unresolvable and execution is blocked. The winning spec's plan entry proceeds normally; the losing spec's entry is marked with `skippedSpec` and logged for audit.

**Design rationale:** The explicit winner via `preferSpec` is consistent with unslop's philosophy -- consequential decisions require explicit human ratification, not implicit resolution by system internals. Build-order-wins would produce non-deterministic output depending on topological sort ordering, which is worse than blocking.

**Integration:** `bulkSyncPlan` and `deepSyncPlan` both call `partitionPlan`, so collision detection is automatic for both paths. `resumeSyncPlan` inherits the collision state from the original plan.

### Concrete build ordering (extends-aware)

Extend `computeParallelBatches` in `sync.ts` to account for extends edges alongside concrete-dependencies when computing batch boundaries. Currently the topological sort uses `depends-on` edges from abstract specs. Concrete specs add two additional edge types:

- `concrete-dependencies` -> already parsed, may not be in the sort
- `extends` -> parent MUST build before child (parent's output may be needed for flattening validation)

The combined edge set feeds into the same Kahn's algorithm. No new module -- this extends existing batch computation with additional edges projected from concrete spec metadata.

### Test contracts

**Inheritance:**

- STRICT_CHILD_ONLY: child Strategy completely replaces parent Strategy
- Additive: Lowering Notes from child + parent + grandparent concatenated with attribution
- Overridable: Pattern inherited when child omits it, overridden when child provides it
- Cycle: `a extends b extends a` throws `InheritanceCycleError`
- Depth: chain of 4 (exceeding MAX_EXTENDS_DEPTH=3) throws
- Missing parent: `extends` pointing to nonexistent file throws

**Collision:**

- Two specs claiming same target -> `CollisionEntry` in plan
- `force: true` without `preferSpec` -> plan still blocked
- `force: true` with `preferSpec` -> winner proceeds, loser skipped with audit trail
- No collision -> plan proceeds normally (regression guard)

**Build ordering:**

- Extends edge enforces parent-before-child in batch ordering
- Concrete-dependencies + extends combined produce correct topological sort
- Diamond: A depends on B and C, both extend D -> D in earliest batch

---

## Phase 8: Python Retirement

**Goal:** Delete all Python orchestrator code. No logic changes -- pure removal plus config cleanup.

### Delete Python source

All `.py` files under `unslop/`:

- `orchestrator.py` (CLI facade)
- `frontmatter.py`, `hashing.py`, `spec_discovery.py`
- `graph.py`, `concrete_graph.py`, `unified_dag.py`
- `manifest.py`, `checker.py`
- `ripple.py`, `bulk_sync.py`, `deep_sync.py`, `resume.py`
- `spec_diff.py`, `graph_renderer.py`, `discover.py`
- `__init__.py`, any remaining `.py` files

### Delete Python tests

- `tests/test_orchestrator.py` (~7,700 lines, 408 tests)
- Any other Python test files under `tests/`

### Config cleanup

- Verify no remaining Python MCP server references in `.claude-plugin/mcp.json`
- Remove Python-specific entries from `.gitignore` if present (`__pycache__`, `*.pyc`, `.venv`)
- Remove `requirements.txt` or `setup.py` if they exist
- Update `CLAUDE.md` -- replace `python -m pytest tests/test_orchestrator.py -q` with prunejuice's test command
- Update `AGENTS.md` if it references Python modules or the orchestrator architecture

### CI workflow

`init.md` currently references the Python orchestrator CLI for CI (standalone script). This needs a replacement -- either prunejuice exposes a CLI entry point, or the CI workflow calls prunejuice directly. Resolution during Phase 7 or early Phase 8 planning.

### Version bump

Bump `plugin.json` version (0.53.0 -> 0.54.0).

### Verification

After deletion:

- `npx vitest` in `prunejuice/` -- all TS tests pass
- `grep -r "orchestrator\|unslop_\|\.py" unslop/` -- no stale references to Python
- `grep -r "python\|pytest" .github/` -- no CI references to Python

### Constraints

- No new functionality in this phase
- No refactoring of prunejuice code
- No test additions (those happened in Phases 6 and 7)
- If something breaks after deletion, `git revert` is the immediate fix

---

## Phase Dependencies

```
Phase 6 (ripple correctness)
    |
    v
Phase 7 (inheritance + collision)
    |
    v
Phase 8 (Python deletion)
```

Phase 7 depends on Phase 6: flattening needs `computeConcreteManifest` for concrete deps validation. Phase 8 depends on Phase 7: cannot delete Python until all load-bearing logic is ported.

## Module Map

New files created across Phases 6--7:

| File | Phase | Purpose |
|------|-------|---------|
| `prunejuice/src/manifest.ts` | 6 | Concrete deps transitive hashing + manifest diffing |
| `prunejuice/tests/manifest.test.ts` | 6 | Manifest computation and diff tests |
| `prunejuice/tests/concrete-frontmatter.test.ts` | 6 | parseConcreteSpecFrontmatter contract tests |
| `prunejuice/tests/extends-chain.test.ts` | 6 | Extends chain traversal contract tests |
| `prunejuice/tests/ghost-diagnostic.test.ts` | 6 | Ghost staleness diagnostic chain tests |
| `prunejuice/src/inheritance.ts` | 7 | On-demand inheritance flattening |
| `prunejuice/tests/inheritance.test.ts` | 7 | Inheritance merge rule tests |
| `prunejuice/tests/collision.test.ts` | 7 | Multi-target collision detection tests |

Modified files:

| File | Phase | Change |
|------|-------|--------|
| `prunejuice/src/ripple.ts` | 6 | Attach `GhostStaleDiagnostic` to ghost-stale entries |
| `prunejuice/src/types.ts` | 6, 7 | Add `GhostStaleDiagnostic`, `CollisionEntry`, `FlattenedConcreteSpec` types |
| `prunejuice/src/sync.ts` | 7 | Collision detection in `partitionPlan`, extends-aware batch ordering |
| `prunejuice/src/mcp.ts` | 6 | No new tools, but ripple_check output schema changes |
| `.claude-plugin/plugin.json` | 8 | Version bump |
| `CLAUDE.md` | 8 | Update build/test commands |
| `AGENTS.md` | 8 | Remove Python architecture references |
