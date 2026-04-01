# Prunejuice Integration -- Design Spec

## Problem

Unslop's spec-driven pipeline works, but its execution is non-deterministic. The coordination mechanism (spec layer) is sound; the execution (prompt-constructed agent dispatch via Claude Code's process model) is sloppy. Opus swooping in at the end masks the problem. Prunejuice reimplements the pipeline on top of the Claude Agent SDK with typed artifacts, structural information isolation, and programmatic convergence. The integration question: how do unslop (the user interface) and prunejuice (the execution engine) connect?

## Approach

MCP is the integration seam. Prunejuice exposes its API as MCP tools. Unslop's markdown commands call them. The Python MCP server is replaced incrementally -- both servers run in parallel during migration, commands switch tool references at the end.

## Out of scope

- Prunejuice internal implementation changes (types, agents, pipeline logic) -- that's separate work
- Sprint contracts and saboteur calibration in prunejuice (designed for unslop, will migrate later)
- Multi-file spec management in prunejuice (currently single-spec-per-project)
- Interactive elicit (Socratic dialogue stays in unslop commands, not in prunejuice)

---

## Architecture

### Three Layers

| Layer | Owner | Runtime | Responsibility |
|-------|-------|---------|----------------|
| **User interaction** | unslop (markdown commands) | Claude Code session | Socratic dialogue, spec editing, user approval gates, intent lock |
| **Pipeline execution** | prunejuice (MCP tools) | Node.js subprocess | Agent dispatch, convergence loop, mutation testing, Chinese Wall |
| **State management** | prunejuice (MCP tools) | Node.js subprocess | Freshness classification, DAG + ripple checks, build ordering, hash chain |

### What Stays in Unslop (permanently)

- Markdown commands (the user interaction surface)
- Skills (reference material for agents running in the user's session)
- CLAUDE.md / AGENTS.md (project documentation)
- Plugin manifest (`plugin.json`)

### What Migrates to Prunejuice

- All 8 current Python MCP tools
- The freshness classifier (already partially in `hashchain.ts`)
- The dependency DAG (`graph.py`, `concrete_graph.py`, `unified_dag.py`)
- Ripple checks (`ripple.py`)
- Build ordering (topological sort)
- Sync planning (`bulk_sync.py`, `deep_sync.py`, `resume.py`)
- Spec diff computation

### Why One System, Not Two

The hash chain and the freshness classifier are not separate concerns. The freshness classifier IS the hash chain interpreted against the dependency DAG. A spec is stale because its hash doesn't match AND a dependency triggered a ripple check AND the DAG says it's downstream. Those three things must be computed by the same system with the same data. Two state managers with overlapping concerns is where bugs hide -- the hash chain says fresh, the Python classifier says stale, and the consistency problem is hard to reproduce and harder to debug.

---

## MCP Server Design

### Tool Surface (14 tools)

**Migrated from Python (8):**

| Tool | What it does |
|------|-------------|
| `prunejuice_check_freshness` | Eight-state freshness classification for all managed files |
| `prunejuice_build_order` | Topological sort of spec DAG |
| `prunejuice_discover_files` | Find source files with spec/code filtering |
| `prunejuice_resolve_deps` | Resolve dependencies for a single spec |
| `prunejuice_ripple_check` | Blast radius of spec changes (three-layer tracing) |
| `prunejuice_deep_sync_plan` | Single-file sync with dependency resolution |
| `prunejuice_bulk_sync_plan` | Multi-file sync planning with batching |
| `prunejuice_spec_diff` | Compute changes between two specs |

**New pipeline tools (6):**

| Tool | What it does |
|------|-------------|
| `prunejuice_generate` | Full pipeline: Archaeologist -> Mason -> Builder -> Saboteur |
| `prunejuice_generate_resume` | Continue pipeline after discovery gate resolution |
| `prunejuice_distill` | Infer spec from existing code |
| `prunejuice_cover` | Mutation-driven test coverage improvement |
| `prunejuice_weed` | Detect intent drift between spec and code |
| `prunejuice_verify` | Synchronous Saboteur verification on a single file |

### Naming Convention

`prunejuice_*` prefix, matching the `unslop_*` convention the Python server uses. Commands update their MCP references from `unslop_*` to `prunejuice_*` at Phase 5 of migration.

### Error Handling

Two-tier: domain errors return clean JSON with `error` field, unexpected errors return full traceback + JSON error. The Agent SDK's structured output (`outputFormat: { type: "json_schema" }`) means pipeline tools return typed results.

### Statefulness

The MCP server is stateless for request/response. Intermediate pipeline state (e.g., during the discovery gate two-call flow) is serialised in the response and round-tripped through the client. The DAG cache is the one piece of in-memory state, but it's backed by `.prunejuice/dag-cache.json` for cold starts and is deterministically reconstructible from spec files.

---

## API Contract

### Compatibility Rule

Output schemas match what the Python tools currently return. Where the Python tools return a field, the prunejuice tools return the same field with the same name and type. New fields can be added (additive). Existing fields cannot be renamed or removed until Phase 5 (command migration).

### Key Tool Contracts

```typescript
// prunejuice_check_freshness
Input:  { cwd: string, excludePatterns?: string[] }
Output: { status: "ok" | "fail", files: FreshnessEntry[], summary: Record<FreshnessState, number> }

// prunejuice_build_order
Input:  { cwd: string }
Output: { order: string[], cycles?: string[][] }

// prunejuice_ripple_check
Input:  { specPaths: string[], cwd: string }
Output: { layers: { abstract: {...}, concrete: {...}, code: {...} }, buildOrder: string[] }

// prunejuice_generate
Input:  { spec: Spec, cwd: string }
Output: { success: boolean, result?: GenerateResult, error?: string }
       | { status: "discovery_pending", pipelineState: SerialisedPipelineState, discoveries: DiscoveredItem[] }

// prunejuice_generate_resume
Input:  {
  pipelineState: SerialisedPipelineState,
  resolutions: Array<{
    discoveryId: string,
    action: "promote" | "dismiss" | "defer",
    specAmendment?: Partial<Spec>   // present when action === "promote"
  }>
}
Output: { success: boolean, result?: GenerateResult, error?: string }

// prunejuice_distill
Input:  { cwd: string }
Output: { spec: Spec }

// prunejuice_cover
Input:  { cwd: string, spec?: Spec, maxIterations?: number }
Output: { originalKillRate: number, finalKillRate: number, iterations: number, killRateHistory: number[] }

// prunejuice_weed
Input:  { cwd: string, spec?: Spec }
Output: { findings: DriftFinding[], hasDrift: boolean, overallAssessment: string }

// prunejuice_verify
Input:  { cwd: string, specPath: string, managedFilePath: string }
Output: { status: "pass" | "fail" | "error", killRate: number, mutationResults: MutationResult[], complianceViolations: string[] }
```

### Discovery Gate (Two-Call Flow)

The `generate` pipeline has a discovery gate that requires user interaction. MCP is request/response -- no callbacks. The solution:

1. `prunejuice_generate` runs the Archaeologist, hits the discovery gate, returns `status: "discovery_pending"` with the full serialised pipeline state and the discovery list.
2. The unslop command presents discoveries to the user, collects resolutions.
3. `prunejuice_generate_resume` takes the serialised pipeline state + resolutions, continues from Mason onward.

If no discoveries exist, `prunejuice_generate` runs the full pipeline in one call.

**The MCP server is stateless.** Pipeline state round-trips through the client as serialised JSON. The unslop command holds the intermediate state (which it needs anyway to present discoveries). No server-side session store, no restart fragility.

**The `specAmendment` field** on promoted discoveries triggers hash recomputation before Mason runs. Without it, the resume call cannot update the spec that Mason and Builder work against. The resume call merges amendments into the working spec, recomputes the spec hash, and proceeds.

**Resolution semantics:**
- `promote` with `specAmendment`: merge amendment into spec, recompute hash, re-run Archaeologist to update concrete spec, then continue Mason -> Builder -> Saboteur
- `dismiss`: remove discovery from concrete spec, continue without spec change
- `defer`: retain discovery in concrete spec metadata, continue (will surface again next generate)

---

## DAG Cache

### Why Cached (Not Stateless)

The Python orchestrator rebuilds the DAG from scratch on every call -- scan all specs, parse frontmatter, build graph. This is O(n) in spec count. For 50 specs (~100ms) it's fine. For 500 specs it starts to hurt, and prunejuice's MCP tools may be called multiple times per generate pass (ripple check, freshness, build order).

### Hash-Gated Invalidation

The same trust model as the hash chain: if the hash matches, the derived artifact is current.

```typescript
interface DAGCache {
  dag: Record<string, string[]>;        // spec_path -> [dependent_spec_paths]
  manifest: Record<string, string>;     // spec_path -> content_hash (TruncatedHash)
  builtAt: string;                      // ISO 8601 for debugging
}
```

### Invalidation Protocol

On each MCP tool call that reads the DAG, `ensureDAG()` runs:

1. **Cold start (no cache file):** Full scan of `*.spec.md` files, parse all `depends-on` frontmatter, build complete DAG, write `.prunejuice/dag-cache.json`. This is an explicit code path, not an error recovery.

2. **Warm path (cache exists):** For each spec in the manifest:
   - `stat()` the file, `truncatedHash(content)`, compare against manifest
   - **Hash matches:** skip (unchanged)
   - **Hash differs:** re-parse `depends-on`, update DAG edges, update manifest hash, mark downstream dependents for freshness re-evaluation
   - **File missing (stat fails):** spec deleted -- prune the node and ALL edges involving it from the DAG, remove from manifest. Deletion is a different operation from modification and is handled explicitly.

3. **New file detection:** After checking manifest entries, scan for `*.spec.md` files not in the manifest. Parse, add to DAG, add to manifest.

4. **Persist:** After any mutation, write `.prunejuice/dag-cache.json`.

### Subgraph Rebuild

When spec A's hash changes, only rebuild the subgraph rooted at A. Diff A's old `depends-on` against the new parsed edges, propagate downstream. For a 500-spec project where A has 12 downstream dependents, this touches 13 nodes.

### Clean-Path Cost

O(n) `stat()` calls where n = number of specs in manifest. Each `stat()` is sub-millisecond. For a 500-spec project, the clean-path check adds ~1ms to every MCP call. No file reads unless a hash differs.

### Platform Note

Hash-gated invalidation sidesteps the WSL file watcher reliability problem entirely. No `inotify`, no `fs.watch`. You don't care about when the file changed, only whether it changed, checked at call time with a stat + hash.

---

## Migration Sequencing

### Phase 1: MCP Server Scaffolding + Freshness (first PR)

- Stand up the prunejuice MCP server with `prunejuice_check_freshness`
- Freshness classifier already exists in `hashchain.ts` -- wire it to an MCP tool
- No DAG cache needed yet (single-file freshness is just hash comparison)
- Register in `plugin.json` alongside existing Python MCP server
- Both servers run in parallel

### Phase 2: DAG + Dependency Tools

- Implement DAG cache (`dag-cache.json`, `ensureDAG()`, subgraph rebuild)
- Migrate `prunejuice_build_order`, `prunejuice_resolve_deps`, `prunejuice_ripple_check`
- Read-only DAG consumers -- low risk

### Phase 3: Sync Planning Tools

- Migrate `prunejuice_deep_sync_plan`, `prunejuice_bulk_sync_plan`, `prunejuice_spec_diff`
- These compose freshness + DAG -- most complex state management tools
- After this phase, Python state management is fully redundant

### Phase 4: Pipeline Execution Tools

- Expose `prunejuice_generate`, `prunejuice_generate_resume`, `prunejuice_distill`, `prunejuice_cover`, `prunejuice_weed`
- Already work as library functions -- MCP tools are thin wrappers with JSON schemas
- Two-call discovery flow implemented here

### Phase 5: Command Migration + Python Retirement

- Update unslop markdown commands: `unslop_*` MCP references -> `prunejuice_*`
- Remove Python MCP server from `plugin.json`
- Delete `mcp_server.py`
- Python orchestrator scripts remain as reference but are no longer executed
- Unslop version bump

### Per-Phase Rules

- Each phase is a PR with its own tests
- Both MCP servers run in parallel during phases 1-4 (no command breakage)
- Prunejuice version bumps each phase
- Unslop version bumps only at Phase 5

---

## Testing Strategy

### Unit Tests (existing pattern)

Prunejuice already has 84 tests in vitest. New MCP tools get unit tests following the same pattern -- test the handler function directly, mock the store layer.

### Integration Tests (new)

Phase 1 introduces integration tests: start the MCP server, call tools via the MCP protocol, verify responses match the Python server's output for the same inputs. This is the compatibility contract enforced mechanically.

### Stress Tests

The `stress-tests/adversarial-hashing/` fixture is already committed. After Phase 4, run the adversarial takeover through prunejuice's MCP tools instead of the Python orchestrator and compare results.
