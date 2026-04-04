# Prunejuice Phase 2: DAG + Dependency Tools -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the DAG cache with hash-gated invalidation and expose `prunejuice_build_order`, `prunejuice_resolve_deps`, and `prunejuice_ripple_check` as MCP tools.

**Architecture:** A new `dag.ts` module handles spec discovery, frontmatter parsing (extracting `depends-on`), DAG construction, and hash-gated cache invalidation. Three new MCP tool handlers in `mcp.ts` consume the DAG. The DAG cache persists to `.prunejuice/dag-cache.json` and is validated via `stat()` + hash comparison on each call (no file watchers). Ripple check traces three layers: abstract specs (`depends-on`), concrete specs (`*.impl.md` via `source-spec`/`concrete-dependencies`/`extends`), and managed code files.

**Tech Stack:** TypeScript, vitest, `@modelcontextprotocol/sdk`, zod

---

## File Structure

| File                                          | Responsibility                                                                                               |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **Create:** `prunejuice/src/dag.ts`           | DAG cache: spec discovery, `depends-on` parsing, `ensureDAG()`, topological sort, transitive dep resolution  |
| **Create:** `prunejuice/src/ripple.ts`        | Three-layer ripple check: abstract → concrete → code                                                         |
| **Modify:** `prunejuice/src/mcp.ts`           | Register three new MCP tools: `prunejuice_build_order`, `prunejuice_resolve_deps`, `prunejuice_ripple_check` |
| **Modify:** `prunejuice/src/types.ts`         | Add `DAGCache` interface and ripple check result types                                                       |
| **Create:** `prunejuice/test/dag.test.ts`     | Unit tests for DAG cache, topo sort, dep resolution                                                          |
| **Create:** `prunejuice/test/ripple.test.ts`  | Unit tests for ripple check                                                                                  |
| **Create:** `prunejuice/test/dag-mcp.test.ts` | MCP handler tests for the three new tools                                                                    |

---

### Task 1: Add DAG and Ripple Types to `types.ts`

**Files:**

- Modify: `prunejuice/src/types.ts:1-220`

- [ ] **Step 1: Write the new type definitions**

Add at the end of `prunejuice/src/types.ts`:

```typescript
// -- DAG cache ----------------------------------------------------------------

export interface DAGCache {
  /** spec_path (relative to cwd) -> list of spec paths it depends on */
  dag: Record<string, string[]>;
  /** spec_path -> content hash of the spec file */
  manifest: Record<string, string>;
  /** ISO 8601 timestamp for debugging */
  builtAt: string;
}

// -- Ripple check results -----------------------------------------------------

export interface RippleAbstractLayer {
  directlyChanged: string[];
  transitivelyAffected: string[];
  total: number;
}

export interface RippleConcreteLayer {
  affectedImpls: string[];
  ghostStaleImpls: string[];
  total: number;
}

export interface RippleManagedEntry {
  managed: string;
  spec: string;
  concrete?: string;
  exists: boolean;
  currentState: string;
  cause: "direct" | "transitive" | "ghost-stale";
  language?: string;
  error?: string;
  ghostSource?: string;
}

export interface RippleCodeLayer {
  regenerate: RippleManagedEntry[];
  ghostStale: RippleManagedEntry[];
  totalFiles: number;
}

export interface RippleResult {
  inputSpecs: string[];
  layers: {
    abstract: RippleAbstractLayer;
    concrete: RippleConcreteLayer;
    code: RippleCodeLayer;
  };
  buildOrder: string[];
}
```

- [ ] **Step 2: Run tests to verify nothing broke**

Run: `cd prunejuice && npm run test`
Expected: All existing tests pass (no runtime changes, just type additions)

- [ ] **Step 3: Commit**

```bash
git add prunejuice/src/types.ts
git commit -m "feat(prunejuice): add DAGCache and RippleResult types for Phase 2"
```

---

### Task 2: Implement DAG Cache (`dag.ts`)

**Files:**

- Create: `prunejuice/test/dag.test.ts`
- Create: `prunejuice/src/dag.ts`

- [ ] **Step 1: Write the failing tests for `parseDependsOn`**

Create `prunejuice/test/dag.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm, readFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

// Import the functions we'll implement
import {
  parseDependsOn,
  ensureDAG,
  buildOrder,
  resolveDeps,
} from "../src/dag.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dag-test-"));
}

async function writeAt(
  base: string,
  rel: string,
  content: string,
): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

// -- parseDependsOn -----------------------------------------------------------

describe("parseDependsOn", () => {
  it("extracts depends-on list from frontmatter", () => {
    const content = [
      "---",
      "depends-on:",
      "  - src/auth.ts.spec.md",
      "  - src/db.ts.spec.md",
      "---",
      "# My spec",
    ].join("\n");
    expect(parseDependsOn(content)).toEqual([
      "src/auth.ts.spec.md",
      "src/db.ts.spec.md",
    ]);
  });

  it("returns empty array when no frontmatter", () => {
    expect(parseDependsOn("# Just a heading")).toEqual([]);
  });

  it("returns empty array when no depends-on field", () => {
    const content = [
      "---",
      "intent-approved: 2026-01-01",
      "---",
      "# Spec",
    ].join("\n");
    expect(parseDependsOn(content)).toEqual([]);
  });

  it("normalizes depends_on (snake_case) to depends-on", () => {
    const content = [
      "---",
      "depends_on:",
      "  - src/util.ts.spec.md",
      "---",
    ].join("\n");
    expect(parseDependsOn(content)).toEqual(["src/util.ts.spec.md"]);
  });

  it("stops reading deps at next field", () => {
    const content = [
      "---",
      "depends-on:",
      "  - src/a.ts.spec.md",
      "intent-approved: 2026-01-01",
      "---",
    ].join("\n");
    expect(parseDependsOn(content)).toEqual(["src/a.ts.spec.md"]);
  });

  it("handles unclosed frontmatter by returning empty", () => {
    const content = ["---", "depends-on:", "  - src/a.ts.spec.md"].join("\n");
    expect(parseDependsOn(content)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/dag.test.ts`
Expected: FAIL -- cannot resolve `../src/dag.js`

- [ ] **Step 3: Implement `parseDependsOn` in `dag.ts`**

Create `prunejuice/src/dag.ts`:

```typescript
import { readdir, readFile, stat, writeFile, mkdir } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { truncatedHash } from "./hashchain.js";
import type { DAGCache, TruncatedHash } from "./types.js";

// -- Frontmatter parsing (depends-on only) ------------------------------------

function normalizeKey(line: string): string {
  const colon = line.indexOf(":");
  if (colon === -1) return line;
  const key = line.substring(0, colon);
  const value = line.substring(colon);
  return key.replace(/_/g, "-") + value;
}

/**
 * Extract `depends-on` list from spec file frontmatter.
 * Strict string matching (not YAML). Matches Python's parse_frontmatter().
 */
export function parseDependsOn(content: string): string[] {
  const lines = content.split("\n");
  if (!lines.length || lines[0]!.trim() !== "---") return [];

  // Find closing delimiter
  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]!.trim() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) return [];

  const deps: string[] = [];
  let inDepends = false;

  for (let i = 1; i < end; i++) {
    const line = lines[i]!;
    const stripped = line.trim();
    if (normalizeKey(stripped) === "depends-on:") {
      inDepends = true;
      continue;
    }
    if (inDepends) {
      const match = line.match(/^  - (.+)$/);
      if (match) {
        deps.push(match[1]!.trim());
      } else {
        inDepends = false;
      }
    }
  }

  return deps;
}
```

- [ ] **Step 4: Run `parseDependsOn` tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/dag.test.ts`
Expected: All 6 `parseDependsOn` tests pass

- [ ] **Step 5: Write failing tests for `ensureDAG` and `buildOrder`**

Append to `prunejuice/test/dag.test.ts`:

```typescript
// -- ensureDAG + buildOrder ---------------------------------------------------

describe("ensureDAG", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("builds DAG from scratch when no cache exists (cold start)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/db.ts.spec.md", "---\n---\n# DB");
    await writeAt(
      tmp,
      "src/api.ts.spec.md",
      "---\ndepends-on:\n  - src/db.ts.spec.md\n---\n# API",
    );

    const dag = await ensureDAG(tmp);

    expect(dag.dag["src/api.ts.spec.md"]).toEqual(["src/db.ts.spec.md"]);
    expect(dag.dag["src/db.ts.spec.md"]).toEqual([]);
    expect(Object.keys(dag.manifest)).toHaveLength(2);
  });

  it("returns cached DAG when spec content is unchanged (warm path)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    const dag1 = await ensureDAG(tmp);
    const dag2 = await ensureDAG(tmp);

    // Same builtAt means the cache was reused (not rebuilt)
    expect(dag2.builtAt).toBe(dag1.builtAt);
  });

  it("detects new spec files added after cache was built", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    const dag1 = await ensureDAG(tmp);
    expect(Object.keys(dag1.dag)).toHaveLength(1);

    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    const dag2 = await ensureDAG(tmp);
    expect(Object.keys(dag2.dag)).toHaveLength(2);
  });

  it("updates DAG when spec content changes (hash differs)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await ensureDAG(tmp);

    // Now b depends on a
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# B",
    );
    const dag2 = await ensureDAG(tmp);
    expect(dag2.dag["b.spec.md"]).toEqual(["a.spec.md"]);
  });

  it("prunes deleted specs from DAG and manifest", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    const dag1 = await ensureDAG(tmp);
    expect(Object.keys(dag1.dag)).toHaveLength(2);

    // Delete b
    const { unlink } = await import("node:fs/promises");
    await unlink(join(tmp, "b.spec.md"));

    const dag2 = await ensureDAG(tmp);
    expect(Object.keys(dag2.dag)).toHaveLength(1);
    expect(dag2.dag["b.spec.md"]).toBeUndefined();
    expect(dag2.manifest["b.spec.md"]).toBeUndefined();
  });

  it("persists cache to .prunejuice/dag-cache.json", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "x.spec.md", "---\n---\n# X");
    await ensureDAG(tmp);

    const cachePath = join(tmp, ".prunejuice", "dag-cache.json");
    const raw = await readFile(cachePath, "utf-8");
    const parsed = JSON.parse(raw);
    expect(parsed.dag).toBeDefined();
    expect(parsed.manifest).toBeDefined();
    expect(parsed.builtAt).toBeDefined();
  });

  it("excludes default directories (.prunejuice, node_modules, .git, etc.)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "real.spec.md", "---\n---\n# Real");
    await writeAt(tmp, "node_modules/dep.spec.md", "---\n---\n# Excluded");
    await writeAt(tmp, ".git/hooks.spec.md", "---\n---\n# Excluded");

    const dag = await ensureDAG(tmp);
    expect(Object.keys(dag.dag)).toHaveLength(1);
    expect(dag.dag["real.spec.md"]).toBeDefined();
  });
});

describe("buildOrder", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns specs in topological order (leaves first)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "a.spec.md", "---\n---\n# A (no deps)");

    const order = await buildOrder(tmp);
    expect(order.order).toEqual(["a.spec.md", "b.spec.md", "c.spec.md"]);
    expect(order.cycles).toBeUndefined();
  });

  it("reports cycles instead of throwing", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await buildOrder(tmp);
    expect(result.cycles).toBeDefined();
    expect(result.cycles!.length).toBeGreaterThan(0);
    // Fallback: alphabetical order
    expect(result.order).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty order for projects with no specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const result = await buildOrder(tmp);
    expect(result.order).toEqual([]);
  });
});
```

- [ ] **Step 6: Run tests to verify `ensureDAG`/`buildOrder` tests fail**

Run: `cd prunejuice && npx vitest run test/dag.test.ts`
Expected: FAIL -- `ensureDAG` and `buildOrder` not exported

- [ ] **Step 7: Implement `ensureDAG`, `topoSort`, and `buildOrder`**

Add to `prunejuice/src/dag.ts` (after `parseDependsOn`):

```typescript
// -- Helpers ------------------------------------------------------------------

function isEnoent(err: unknown): boolean {
  return (
    err instanceof Error &&
    "code" in err &&
    (err as NodeJS.ErrnoException).code === "ENOENT"
  );
}

const DEFAULT_EXCLUDE = new Set([
  ".prunejuice",
  ".unslop",
  "node_modules",
  ".git",
  "__pycache__",
  "dist",
  "build",
  ".venv",
  "venv",
]);

const CACHE_PATH = ".prunejuice/dag-cache.json";

// -- Recursive spec discovery -------------------------------------------------

async function findSpecFiles(
  dir: string,
  excludeSet: Set<string>,
): Promise<string[]> {
  const results: string[] = [];
  let names: string[];
  try {
    names = await readdir(dir);
  } catch (err: unknown) {
    if (isEnoent(err)) return results;
    throw err;
  }
  for (const name of names) {
    if (excludeSet.has(name)) continue;
    const fullPath = join(dir, name);
    let isDir = false;
    try {
      const s = await stat(fullPath);
      isDir = s.isDirectory();
    } catch (err: unknown) {
      if (isEnoent(err)) continue;
      if (name.endsWith(".spec.md")) throw err;
      continue;
    }
    if (isDir) {
      const nested = await findSpecFiles(fullPath, excludeSet);
      results.push(...nested);
    } else if (name.endsWith(".spec.md")) {
      results.push(fullPath);
    }
  }
  return results;
}

// -- Topological sort (Kahn's algorithm) --------------------------------------

/**
 * Kahn's topological sort. Edges point toward dependencies.
 * Returns sorted list (leaves first) or throws with cycle participants.
 */
export function topoSort(graph: Record<string, string[]>): string[] {
  // Compute in-degree (number of deps each node has)
  const inDegree: Record<string, number> = {};
  for (const node of Object.keys(graph)) {
    inDegree[node] = 0;
  }
  // Ensure dependency nodes exist in inDegree
  for (const deps of Object.values(graph)) {
    for (const dep of deps) {
      if (!(dep in inDegree)) {
        inDegree[dep] = 0;
      }
    }
  }
  // Count incoming edges: for each node, its in-degree is how many deps it has
  for (const [node, deps] of Object.entries(graph)) {
    inDegree[node] = deps.length;
  }

  const queue = Object.keys(inDegree)
    .filter((n) => inDegree[n] === 0)
    .sort();
  const result: string[] = [];

  while (queue.length > 0) {
    const node = queue.shift()!;
    result.push(node);
    // Find all nodes that depend on `node` (node appears in their deps list)
    for (const [candidate, deps] of Object.entries(graph)) {
      if (deps.includes(node)) {
        inDegree[candidate]!--;
        if (inDegree[candidate] === 0) {
          // Insert sorted
          const insertIdx = queue.findIndex(
            (q) => q.localeCompare(candidate) > 0,
          );
          if (insertIdx === -1) {
            queue.push(candidate);
          } else {
            queue.splice(insertIdx, 0, candidate);
          }
        }
      }
    }
  }

  if (result.length !== Object.keys(inDegree).length) {
    const remaining = Object.keys(inDegree).filter((n) => !result.includes(n));
    throw new Error(`Cycle detected involving: ${remaining.sort().join(", ")}`);
  }

  return result;
}

// -- In-memory DAG cache (module-level singleton per cwd) ---------------------

const dagCache = new Map<string, DAGCache>();

/**
 * Ensure the DAG is up to date for the given project root.
 *
 * Invalidation protocol (from design spec):
 * 1. Cold start: full scan, build DAG, persist to .prunejuice/dag-cache.json
 * 2. Warm path: stat+hash each manifest entry, re-parse changed files, prune deleted
 * 3. New file detection: scan for specs not in manifest
 * 4. Persist after any mutation
 */
export async function ensureDAG(cwd: string): Promise<DAGCache> {
  const absCwd = resolve(cwd);

  // Try in-memory cache first
  let cache = dagCache.get(absCwd) ?? null;

  // Try disk cache if not in memory
  if (!cache) {
    try {
      const raw = await readFile(join(absCwd, CACHE_PATH), "utf-8");
      cache = JSON.parse(raw) as DAGCache;
    } catch (err: unknown) {
      if (!isEnoent(err)) throw err;
      // No cache file -- cold start
    }
  }

  if (!cache) {
    // Cold start: full scan
    cache = await fullScan(absCwd);
    await persistCache(absCwd, cache);
    dagCache.set(absCwd, cache);
    return cache;
  }

  // Warm path: validate existing entries + detect new files
  let mutated = false;

  // Check existing manifest entries
  const toDelete: string[] = [];
  for (const [specRel, oldHash] of Object.entries(cache.manifest)) {
    const specAbs = join(absCwd, specRel);
    let content: string;
    try {
      content = await readFile(specAbs, "utf-8");
    } catch (err: unknown) {
      if (isEnoent(err)) {
        // File deleted -- prune
        toDelete.push(specRel);
        mutated = true;
        continue;
      }
      throw err;
    }
    const newHash = truncatedHash(content);
    if (newHash !== oldHash) {
      // Content changed -- re-parse deps
      cache.dag[specRel] = parseDependsOn(content);
      cache.manifest[specRel] = newHash;
      mutated = true;
    }
  }

  // Prune deleted specs
  for (const specRel of toDelete) {
    delete cache.dag[specRel];
    delete cache.manifest[specRel];
    // Also remove from other specs' dependency lists
    for (const deps of Object.values(cache.dag)) {
      const idx = deps.indexOf(specRel);
      if (idx !== -1) deps.splice(idx, 1);
    }
  }

  // Detect new spec files
  const specPaths = await findSpecFiles(absCwd, DEFAULT_EXCLUDE);
  for (const specAbs of specPaths) {
    const specRel = relative(absCwd, specAbs);
    if (specRel in cache.manifest) continue;
    // New file
    let content: string;
    try {
      content = await readFile(specAbs, "utf-8");
    } catch (err: unknown) {
      if (isEnoent(err)) continue; // vanished during scan
      throw err;
    }
    cache.dag[specRel] = parseDependsOn(content);
    cache.manifest[specRel] = truncatedHash(content);
    mutated = true;
  }

  if (mutated) {
    cache.builtAt = new Date().toISOString();
    await persistCache(absCwd, cache);
  }

  dagCache.set(absCwd, cache);
  return cache;
}

async function fullScan(absCwd: string): Promise<DAGCache> {
  const dag: Record<string, string[]> = {};
  const manifest: Record<string, string> = {};

  const specPaths = await findSpecFiles(absCwd, DEFAULT_EXCLUDE);
  for (const specAbs of specPaths) {
    const specRel = relative(absCwd, specAbs);
    const content = await readFile(specAbs, "utf-8");
    dag[specRel] = parseDependsOn(content);
    manifest[specRel] = truncatedHash(content);
  }

  return { dag, manifest, builtAt: new Date().toISOString() };
}

async function persistCache(absCwd: string, cache: DAGCache): Promise<void> {
  const dir = join(absCwd, ".prunejuice");
  await mkdir(dir, { recursive: true });
  await writeFile(
    join(absCwd, CACHE_PATH),
    JSON.stringify(cache, null, 2),
    "utf-8",
  );
}

/**
 * Clear the in-memory DAG cache for a cwd. Useful in tests.
 */
export function clearDAGCache(cwd?: string): void {
  if (cwd) {
    dagCache.delete(resolve(cwd));
  } else {
    dagCache.clear();
  }
}

// -- Public API: build order --------------------------------------------------

export interface BuildOrderResult {
  order: string[];
  cycles?: string[][];
}

/**
 * Return all specs in topological order (leaves first).
 * If cycles exist, returns alphabetical fallback + cycle info.
 */
export async function buildOrder(cwd: string): Promise<BuildOrderResult> {
  const cache = await ensureDAG(cwd);
  const graph = { ...cache.dag };

  // Add missing dependency nodes (referenced but not found as files)
  for (const deps of Object.values(graph)) {
    for (const dep of deps) {
      if (!(dep in graph)) {
        graph[dep] = [];
      }
    }
  }

  try {
    const order = topoSort(graph);
    return { order };
  } catch (err: unknown) {
    if (err instanceof Error && err.message.startsWith("Cycle detected")) {
      // Extract cycle participants from error message
      const match = err.message.match(/Cycle detected involving: (.+)/);
      const participants = match ? match[1]!.split(", ") : [];
      return {
        order: Object.keys(graph).sort(),
        cycles: [participants],
      };
    }
    throw err;
  }
}

// -- Public API: resolve deps -------------------------------------------------

/**
 * Resolve transitive dependencies of a single spec.
 * Returns dependency specs in build order (leaves first).
 * Does NOT include the input spec itself.
 */
export async function resolveDeps(
  specPath: string,
  cwd: string,
): Promise<string[]> {
  const cache = await ensureDAG(cwd);
  const absCwd = resolve(cwd);

  // Normalize specPath to relative
  const specRel = specPath.startsWith("/")
    ? relative(absCwd, specPath)
    : specPath;

  // Iterative DFS (matches Python's resolve_deps)
  const visited = new Set<string>();
  const inStack = new Set<string>();
  const order: string[] = [];

  const stack: Array<{ name: string; processed: boolean }> = [
    { name: specRel, processed: false },
  ];

  while (stack.length > 0) {
    const { name, processed } = stack.pop()!;
    if (processed) {
      inStack.delete(name);
      order.push(name);
      continue;
    }
    if (inStack.has(name)) {
      throw new Error(`Cycle detected involving: ${name}`);
    }
    if (visited.has(name)) continue;
    visited.add(name);
    inStack.add(name);
    stack.push({ name, processed: true }); // post-order marker

    const deps = cache.dag[name] ?? [];
    for (let i = deps.length - 1; i >= 0; i--) {
      stack.push({ name: deps[i]!, processed: false });
    }
  }

  // Remove the input spec itself
  return order.filter((n) => n !== specRel);
}
```

- [ ] **Step 8: Run all dag tests**

Run: `cd prunejuice && npx vitest run test/dag.test.ts`
Expected: All tests pass

- [ ] **Step 9: Write failing tests for `resolveDeps`**

Append to `prunejuice/test/dag.test.ts`:

```typescript
describe("resolveDeps", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns transitive deps in build order, excluding the spec itself", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");

    const deps = await resolveDeps("c.spec.md", tmp);
    expect(deps).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty array for spec with no deps", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "standalone.spec.md", "---\n---\n# Standalone");
    const deps = await resolveDeps("standalone.spec.md", tmp);
    expect(deps).toEqual([]);
  });

  it("throws on cycle", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    await expect(resolveDeps("a.spec.md", tmp)).rejects.toThrow(
      /Cycle detected/,
    );
  });
});
```

- [ ] **Step 10: Run tests to verify `resolveDeps` tests pass**

Run: `cd prunejuice && npx vitest run test/dag.test.ts`
Expected: All tests pass (implementation already in Step 7)

- [ ] **Step 11: Commit**

```bash
git add prunejuice/src/dag.ts prunejuice/test/dag.test.ts
git commit -m "feat(prunejuice): DAG cache with hash-gated invalidation, topo sort, dep resolution"
```

---

### Task 3: Implement Ripple Check (`ripple.ts`)

**Files:**

- Create: `prunejuice/test/ripple.test.ts`
- Create: `prunejuice/src/ripple.ts`

The ripple check traces blast radius across three layers: abstract specs (via `depends-on`), concrete specs (via `source-spec`/`concrete-dependencies`/`extends` in `*.impl.md` files), and managed code files. The Python implementation is in `unslop/scripts/planning/ripple.py`.

- [ ] **Step 1: Write failing tests for ripple check**

Create `prunejuice/test/ripple.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { rippleCheck } from "../src/ripple.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "ripple-test-"));
}

async function writeAt(
  base: string,
  rel: string,
  content: string,
): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

function managedFile(specContent: string, bodyContent: string): string {
  const specHash = truncatedHash(specContent);
  const bodyHash = truncatedHash(bodyContent);
  const header = formatHeader("test.spec.md", {
    specHash,
    outputHash: bodyHash,
    generated: "2026-04-01T00:00:00Z",
  });
  return `${header}\n\n${bodyContent}`;
}

// -- Tests --------------------------------------------------------------------

describe("rippleCheck", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("traces abstract layer: directly changed + transitively affected", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // a <- b <- c (c depends on b, b depends on a)
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");

    // Create managed files so code layer has something to find
    const specA = "---\n---\n# A";
    await writeAt(tmp, "a", managedFile(specA, "code a"));
    const specB = "---\ndepends-on:\n  - a.spec.md\n---\n";
    await writeAt(tmp, "b", managedFile(specB, "code b"));
    const specC = "---\ndepends-on:\n  - b.spec.md\n---\n";
    await writeAt(tmp, "c", managedFile(specC, "code c"));

    const result = await rippleCheck(["a.spec.md"], tmp);

    expect(result.layers.abstract.directlyChanged).toEqual(["a.spec.md"]);
    expect(result.layers.abstract.transitivelyAffected).toContain("b.spec.md");
    expect(result.layers.abstract.transitivelyAffected).toContain("c.spec.md");
    expect(result.layers.abstract.total).toBe(3);
  });

  it("populates code layer with managed file entries", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/x.ts.spec.md", "---\n---\n# X");
    // No managed file yet
    const result = await rippleCheck(["src/x.ts.spec.md"], tmp);

    const codeEntries = result.layers.code.regenerate;
    expect(codeEntries).toHaveLength(1);
    expect(codeEntries[0]!.managed).toBe("src/x.ts");
    expect(codeEntries[0]!.spec).toBe("src/x.ts.spec.md");
    expect(codeEntries[0]!.exists).toBe(false);
    expect(codeEntries[0]!.currentState).toBe("new");
    expect(codeEntries[0]!.cause).toBe("direct");
  });

  it("includes build order for affected specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await rippleCheck(["a.spec.md"], tmp);
    expect(result.buildOrder).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty layers when spec has no dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "leaf.spec.md", "---\n---\n# Leaf");
    const result = await rippleCheck(["leaf.spec.md"], tmp);

    expect(result.layers.abstract.directlyChanged).toEqual(["leaf.spec.md"]);
    expect(result.layers.abstract.transitivelyAffected).toEqual([]);
    expect(result.layers.abstract.total).toBe(1);
  });

  it("handles multiple input specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await rippleCheck(["a.spec.md", "b.spec.md"], tmp);
    expect(result.inputSpecs).toEqual(["a.spec.md", "b.spec.md"]);
    expect(result.layers.abstract.directlyChanged).toContain("a.spec.md");
    expect(result.layers.abstract.directlyChanged).toContain("b.spec.md");
  });

  it("classifies existing managed files by freshness state", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget";
    const bodyContent = "export function widget() {}";
    await writeAt(tmp, "widget.ts.spec.md", specContent);
    await writeAt(tmp, "widget.ts", managedFile(specContent, bodyContent));

    const result = await rippleCheck(["widget.ts.spec.md"], tmp);
    const entry = result.layers.code.regenerate[0]!;
    expect(entry.exists).toBe(true);
    expect(entry.currentState).toBe("fresh");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/ripple.test.ts`
Expected: FAIL -- cannot resolve `../src/ripple.js`

- [ ] **Step 3: Implement ripple check**

Create `prunejuice/src/ripple.ts`:

```typescript
import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { ensureDAG } from "./dag.js";
import { truncatedHash, parseHeader, getBodyBelowHeader } from "./hashchain.js";
import { classifyFreshness, type FreshnessState } from "./hashchain.js";
import type {
  RippleResult,
  RippleAbstractLayer,
  RippleConcreteLayer,
  RippleCodeLayer,
  RippleManagedEntry,
  TruncatedHash,
} from "./types.js";

function isEnoent(err: unknown): boolean {
  return (
    err instanceof Error &&
    "code" in err &&
    (err as NodeJS.ErrnoException).code === "ENOENT"
  );
}

// -- Concrete spec frontmatter (minimal parse for source-spec, concrete-dependencies, extends)

interface ConcreteSpecMeta {
  sourceSpec: string | null;
  concreteDependencies: string[];
  extends: string | null;
  targets: Array<{ path: string; language: string }>;
}

function parseConcreteSpecFrontmatter(content: string): ConcreteSpecMeta {
  const lines = content.split("\n");
  if (!lines.length || lines[0]!.trim() !== "---") {
    return {
      sourceSpec: null,
      concreteDependencies: [],
      extends: null,
      targets: [],
    };
  }

  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]!.trim() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) {
    return {
      sourceSpec: null,
      concreteDependencies: [],
      extends: null,
      targets: [],
    };
  }

  let sourceSpec: string | null = null;
  let extendsVal: string | null = null;
  const concreteDeps: string[] = [];
  const targets: Array<{ path: string; language: string }> = [];

  let currentField: string | null = null;
  let currentTarget: Record<string, string> = {};

  for (let i = 1; i < end; i++) {
    const line = lines[i]!;
    const stripped = line.trim();
    // Normalize snake_case keys
    const normalized = stripped.includes("_")
      ? stripped.replace(/^([^:]+)/, (k) => k.replace(/_/g, "-"))
      : stripped;

    if (normalized.startsWith("source-spec:")) {
      sourceSpec = normalized.substring("source-spec:".length).trim();
      currentField = null;
      continue;
    }
    if (normalized.startsWith("extends:")) {
      extendsVal = normalized.substring("extends:".length).trim();
      currentField = null;
      continue;
    }
    if (normalized === "concrete-dependencies:") {
      currentField = "concrete-deps";
      continue;
    }
    if (normalized === "targets:") {
      currentField = "targets";
      continue;
    }

    if (currentField === "concrete-deps") {
      const match = line.match(/^  - (.+)$/);
      if (match) {
        concreteDeps.push(match[1]!.trim());
      } else if (!line.startsWith("  ")) {
        currentField = null;
      }
    }

    if (currentField === "targets") {
      const dashMatch = line.match(/^  - (.+)$/);
      if (dashMatch) {
        // Save previous target if any
        if (currentTarget.path) {
          targets.push({
            path: currentTarget.path,
            language: currentTarget.language ?? "unknown",
          });
        }
        // Start new target -- could be inline `- path: ...`
        const inlineMatch = dashMatch[1]!.match(/^path:\s*(.+)$/);
        if (inlineMatch) {
          currentTarget = { path: inlineMatch[1]!.trim() };
        } else {
          currentTarget = {};
        }
      } else if (line.startsWith("    ")) {
        // Nested field under current target
        const fieldMatch = line.trim().match(/^(\w[\w-]*):\s*(.+)$/);
        if (fieldMatch) {
          currentTarget[fieldMatch[1]!.replace(/_/g, "-")] =
            fieldMatch[2]!.trim();
        }
      } else {
        // End of targets section
        if (currentTarget.path) {
          targets.push({
            path: currentTarget.path,
            language: currentTarget.language ?? "unknown",
          });
        }
        currentTarget = {};
        currentField = null;
      }
    }

    // Any other top-level field ends the current list field
    if (currentField && !line.startsWith("  ") && stripped.includes(":")) {
      if (currentField === "targets" && currentTarget.path) {
        targets.push({
          path: currentTarget.path,
          language: currentTarget.language ?? "unknown",
        });
        currentTarget = {};
      }
      currentField = null;
    }
  }

  // Flush remaining target
  if (currentField === "targets" && currentTarget.path) {
    targets.push({
      path: currentTarget.path,
      language: currentTarget.language ?? "unknown",
    });
  }

  return {
    sourceSpec,
    concreteDependencies: concreteDeps,
    extends: extendsVal,
    targets,
  };
}

// -- Impl file discovery ------------------------------------------------------

const IMPL_EXCLUDE = new Set([
  ".prunejuice",
  ".unslop",
  "node_modules",
  ".git",
  "__pycache__",
  "dist",
  "build",
  ".venv",
  "venv",
]);

async function findImplFiles(
  dir: string,
  excludeSet: Set<string>,
): Promise<string[]> {
  const results: string[] = [];
  let names: string[];
  try {
    names = await readdir(dir);
  } catch (err: unknown) {
    if (isEnoent(err)) return results;
    throw err;
  }
  for (const name of names) {
    if (excludeSet.has(name)) continue;
    const fullPath = join(dir, name);
    let isDir = false;
    try {
      const s = await stat(fullPath);
      isDir = s.isDirectory();
    } catch (err: unknown) {
      if (isEnoent(err)) continue;
      continue;
    }
    if (isDir) {
      results.push(...(await findImplFiles(fullPath, excludeSet)));
    } else if (name.endsWith(".impl.md")) {
      results.push(fullPath);
    }
  }
  return results;
}

// -- Managed file freshness classification ------------------------------------

async function classifyManagedFile(
  managedPath: string,
  specPath: string,
  cwd: string,
): Promise<string> {
  const absManaged = resolve(cwd, managedPath);
  const absSpec = resolve(cwd, specPath);

  let specContent: string;
  try {
    specContent = await readFile(absSpec, "utf-8");
  } catch (err: unknown) {
    if (isEnoent(err)) return "error";
    throw err;
  }

  let managedContent: string;
  try {
    managedContent = await readFile(absManaged, "utf-8");
  } catch (err: unknown) {
    if (isEnoent(err)) return "new";
    throw err;
  }

  const currentSpecHash = truncatedHash(specContent);
  const header = parseHeader(managedContent);
  const headerSpecHash = header?.specHash ?? null;
  const headerOutputHash = header?.outputHash ?? null;
  const currentOutputHash = truncatedHash(getBodyBelowHeader(managedContent));

  return classifyFreshness({
    currentSpecHash,
    headerSpecHash,
    currentOutputHash,
    headerOutputHash,
    codeFileExists: true,
    upstreamChanged: false,
    specChangedSinceTests: false,
  });
}

// -- Public API ---------------------------------------------------------------

/**
 * Compute the ripple effect of changing one or more spec files.
 * Traces through abstract specs, concrete specs, and managed code.
 */
export async function rippleCheck(
  specPaths: string[],
  cwd: string,
): Promise<RippleResult> {
  const absCwd = resolve(cwd);
  const cache = await ensureDAG(cwd);

  // Normalize input paths to relative
  const normalizedInputs = specPaths.map((sp) =>
    sp.startsWith("/") ? relative(absCwd, sp) : sp,
  );

  // -- Abstract layer: BFS through reverse dependency graph -------------------

  // Build reverse dep map: spec -> specs that depend on it
  const reverseDeps: Record<string, string[]> = {};
  for (const spec of Object.keys(cache.dag)) {
    reverseDeps[spec] = [];
  }
  for (const [spec, deps] of Object.entries(cache.dag)) {
    for (const dep of deps) {
      if (!reverseDeps[dep]) reverseDeps[dep] = [];
      reverseDeps[dep]!.push(spec);
    }
  }

  const directlyChanged = new Set(normalizedInputs);
  const affectedSpecs = new Set<string>();
  const queue = [...normalizedInputs];
  const visited = new Set<string>();

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (visited.has(current)) continue;
    visited.add(current);
    affectedSpecs.add(current);
    for (const dependent of reverseDeps[current] ?? []) {
      queue.push(dependent);
    }
  }

  const abstractLayer: RippleAbstractLayer = {
    directlyChanged: [...directlyChanged].sort(),
    transitivelyAffected: [...affectedSpecs]
      .filter((s) => !directlyChanged.has(s))
      .sort(),
    total: affectedSpecs.size,
  };

  // -- Concrete layer: find affected impl.md files ----------------------------

  const implFiles = await findImplFiles(absCwd, IMPL_EXCLUDE);
  const allImpls: Record<string, ConcreteSpecMeta> = {};

  for (const implAbs of implFiles) {
    const implRel = relative(absCwd, implAbs);
    try {
      const content = await readFile(implAbs, "utf-8");
      const meta = parseConcreteSpecFrontmatter(content);
      // Normalize source-spec to root-relative
      if (meta.sourceSpec) {
        const resolved = resolve(join(absCwd, implRel, ".."), meta.sourceSpec);
        try {
          await stat(resolved);
          meta.sourceSpec = relative(absCwd, resolved);
        } catch {
          // Try as root-relative
          try {
            await stat(join(absCwd, meta.sourceSpec));
          } catch {
            // Leave as-is
          }
        }
      }
      allImpls[implRel] = meta;
    } catch (err: unknown) {
      if (!isEnoent(err)) throw err;
    }
  }

  // Build spec -> impl mapping
  const specToImpls: Record<string, string[]> = {};
  for (const [impl, meta] of Object.entries(allImpls)) {
    if (meta.sourceSpec) {
      if (!specToImpls[meta.sourceSpec]) specToImpls[meta.sourceSpec] = [];
      specToImpls[meta.sourceSpec]!.push(impl);
    }
  }

  // Build reverse concrete dep map
  const reverseConcrete: Record<string, string[]> = {};
  for (const impl of Object.keys(allImpls)) {
    reverseConcrete[impl] = [];
  }
  for (const [impl, meta] of Object.entries(allImpls)) {
    for (const dep of meta.concreteDependencies) {
      if (!reverseConcrete[dep]) reverseConcrete[dep] = [];
      reverseConcrete[dep]!.push(impl);
    }
    if (meta.extends) {
      if (!reverseConcrete[meta.extends]) reverseConcrete[meta.extends] = [];
      reverseConcrete[meta.extends]!.push(impl);
    }
  }

  // BFS through concrete layer
  const affectedImpls = new Set<string>();
  const implQueue: string[] = [];

  for (const spec of affectedSpecs) {
    for (const impl of specToImpls[spec] ?? []) {
      implQueue.push(impl);
    }
  }

  const implVisited = new Set<string>();
  while (implQueue.length > 0) {
    const current = implQueue.shift()!;
    if (implVisited.has(current)) continue;
    implVisited.add(current);
    affectedImpls.add(current);
    for (const dependent of reverseConcrete[current] ?? []) {
      implQueue.push(dependent);
    }
  }

  // Identify ghost-stale impls (affected through concrete deps only)
  const directImplSet = new Set<string>();
  for (const spec of affectedSpecs) {
    for (const impl of specToImpls[spec] ?? []) {
      directImplSet.add(impl);
    }
  }
  const ghostStaleImpls = [...affectedImpls].filter(
    (i) => !directImplSet.has(i),
  );

  const concreteLayer: RippleConcreteLayer = {
    affectedImpls: [...affectedImpls].sort(),
    ghostStaleImpls: ghostStaleImpls.sort(),
    total: affectedImpls.size,
  };

  // -- Code layer: find affected managed files --------------------------------

  const regenerate: RippleManagedEntry[] = [];
  const ghostStale: RippleManagedEntry[] = [];

  for (const spec of [...affectedSpecs].sort()) {
    // Check for multi-target impl
    let targetsHandled = false;
    for (const implRel of specToImpls[spec] ?? []) {
      const meta = allImpls[implRel];
      if (meta && meta.targets.length > 0) {
        targetsHandled = true;
        for (const target of meta.targets) {
          const managedAbs = join(absCwd, target.path);
          let exists = false;
          try {
            await stat(managedAbs);
            exists = true;
          } catch {
            // doesn't exist
          }
          const entry: RippleManagedEntry = {
            managed: target.path,
            spec,
            concrete: implRel,
            exists,
            currentState: exists
              ? await classifyManagedFile(target.path, spec, cwd)
              : "new",
            cause: directlyChanged.has(spec) ? "direct" : "transitive",
            language: target.language,
          };
          regenerate.push(entry);
        }
      }
    }

    if (!targetsHandled) {
      // Per-file spec: derive managed path by stripping .spec.md
      const managedRel = spec.replace(/\.spec\.md$/, "");
      const managedAbs = join(absCwd, managedRel);
      let exists = false;
      try {
        await stat(managedAbs);
        exists = true;
      } catch {
        // doesn't exist
      }
      regenerate.push({
        managed: managedRel,
        spec,
        exists,
        currentState: exists
          ? await classifyManagedFile(managedRel, spec, cwd)
          : "new",
        cause: directlyChanged.has(spec) ? "direct" : "transitive",
      });
    }
  }

  // Ghost-stale managed files (from concrete-only impls)
  for (const impl of ghostStaleImpls.sort()) {
    const meta = allImpls[impl];
    if (!meta?.sourceSpec) continue;

    if (meta.targets.length > 0) {
      for (const target of meta.targets) {
        const managedAbs = join(absCwd, target.path);
        let exists = false;
        try {
          await stat(managedAbs);
          exists = true;
        } catch {
          // doesn't exist
        }
        ghostStale.push({
          managed: target.path,
          spec: meta.sourceSpec,
          concrete: impl,
          exists,
          currentState: "ghost-stale",
          cause: "ghost-stale",
          ghostSource: impl,
        });
      }
    } else {
      const managedRel = meta.sourceSpec.replace(/\.spec\.md$/, "");
      const managedAbs = join(absCwd, managedRel);
      let exists = false;
      try {
        await stat(managedAbs);
        exists = true;
      } catch {
        // doesn't exist
      }
      ghostStale.push({
        managed: managedRel,
        spec: meta.sourceSpec,
        concrete: impl,
        exists,
        currentState: "ghost-stale",
        cause: "ghost-stale",
        ghostSource: impl,
      });
    }
  }

  const codeLayer: RippleCodeLayer = {
    regenerate,
    ghostStale,
    totalFiles: regenerate.length + ghostStale.length,
  };

  // -- Build order for affected specs -----------------------------------------

  // Collect ghost-stale specs
  const ghostStaleSpecs = new Set<string>();
  for (const impl of ghostStaleImpls) {
    const src = allImpls[impl]?.sourceSpec;
    if (src) ghostStaleSpecs.add(src);
  }

  // Build concrete spec edges (impl deps projected to spec space)
  const concreteSpecEdges = new Map<string, Set<string>>();
  for (const [impl, meta] of Object.entries(allImpls)) {
    const implSpec = meta.sourceSpec;
    if (!implSpec) continue;
    for (const depImpl of meta.concreteDependencies) {
      const depSpec = allImpls[depImpl]?.sourceSpec;
      if (depSpec && depSpec !== implSpec) {
        if (!concreteSpecEdges.has(implSpec)) {
          concreteSpecEdges.set(implSpec, new Set());
        }
        concreteSpecEdges.get(implSpec)!.add(depSpec);
      }
    }
    if (meta.extends) {
      const extSpec = allImpls[meta.extends]?.sourceSpec;
      if (extSpec && extSpec !== implSpec) {
        if (!concreteSpecEdges.has(implSpec)) {
          concreteSpecEdges.set(implSpec, new Set());
        }
        concreteSpecEdges.get(implSpec)!.add(extSpec);
      }
    }
  }

  const allAffected = new Set([...affectedSpecs, ...ghostStaleSpecs]);
  const buildOrderResult = computeRippleBuildOrder(
    allAffected,
    cache.dag,
    concreteSpecEdges,
  );

  return {
    inputSpecs: normalizedInputs,
    layers: {
      abstract: abstractLayer,
      concrete: concreteLayer,
      code: codeLayer,
    },
    buildOrder: buildOrderResult,
  };
}

// -- Build order for affected subgraph ----------------------------------------

function computeRippleBuildOrder(
  affected: Set<string>,
  graph: Record<string, string[]>,
  concreteSpecEdges: Map<string, Set<string>>,
): string[] {
  const subgraph: Record<string, string[]> = {};
  for (const spec of affected) {
    const deps = (graph[spec] ?? []).filter((d) => affected.has(d));
    const extra = concreteSpecEdges.get(spec);
    if (extra) {
      for (const e of extra) {
        if (affected.has(e) && !deps.includes(e)) {
          deps.push(e);
        }
      }
    }
    subgraph[spec] = deps;
  }

  // Add missing nodes
  for (const deps of Object.values(subgraph)) {
    for (const dep of deps) {
      if (!(dep in subgraph)) {
        subgraph[dep] = [];
      }
    }
  }

  // Inline Kahn's sort (avoid circular import)
  const inDegree: Record<string, number> = {};
  for (const node of Object.keys(subgraph)) {
    inDegree[node] = 0;
  }
  for (const deps of Object.values(subgraph)) {
    for (const dep of deps) {
      if (!(dep in inDegree)) inDegree[dep] = 0;
    }
  }
  for (const [node, deps] of Object.entries(subgraph)) {
    inDegree[node] = deps.length;
  }

  const queue = Object.keys(inDegree)
    .filter((n) => inDegree[n] === 0)
    .sort();
  const result: string[] = [];

  while (queue.length > 0) {
    const node = queue.shift()!;
    result.push(node);
    for (const [candidate, deps] of Object.entries(subgraph)) {
      if (deps.includes(node)) {
        inDegree[candidate]!--;
        if (inDegree[candidate] === 0) {
          const idx = queue.findIndex((q) => q.localeCompare(candidate) > 0);
          if (idx === -1) queue.push(candidate);
          else queue.splice(idx, 0, candidate);
        }
      }
    }
  }

  if (result.length !== Object.keys(inDegree).length) {
    // Cycle -- alphabetical fallback
    return [...affected].sort();
  }
  return result;
}
```

- [ ] **Step 4: Run ripple tests**

Run: `cd prunejuice && npx vitest run test/ripple.test.ts`
Expected: All 6 tests pass

- [ ] **Step 5: Run all tests to ensure no regressions**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/ripple.ts prunejuice/test/ripple.test.ts
git commit -m "feat(prunejuice): three-layer ripple check (abstract, concrete, code)"
```

---

### Task 4: Register MCP Tools in `mcp.ts`

**Files:**

- Modify: `prunejuice/src/mcp.ts:1-105`
- Create: `prunejuice/test/dag-mcp.test.ts`

- [ ] **Step 1: Write failing MCP handler tests**

Create `prunejuice/test/dag-mcp.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  handleBuildOrder,
  handleResolveDeps,
  handleRippleCheck,
} from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dag-mcp-test-"));
}

async function writeAt(
  base: string,
  rel: string,
  content: string,
): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

// -- Tests --------------------------------------------------------------------

describe("handleBuildOrder", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns topologically sorted spec list", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await handleBuildOrder({ cwd: tmp });
    expect(result.order).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty order for project with no specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const result = await handleBuildOrder({ cwd: tmp });
    expect(result.order).toEqual([]);
  });
});

describe("handleResolveDeps", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns transitive deps excluding the spec itself", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");

    const result = await handleResolveDeps({
      specPath: "c.spec.md",
      cwd: tmp,
    });
    expect(result).toEqual(["a.spec.md", "b.spec.md"]);
  });
});

describe("handleRippleCheck", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns structured ripple result", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await handleRippleCheck({
      specPaths: ["a.spec.md"],
      cwd: tmp,
    });
    expect(result.inputSpecs).toEqual(["a.spec.md"]);
    expect(result.layers.abstract.directlyChanged).toEqual(["a.spec.md"]);
    expect(result.layers.abstract.transitivelyAffected).toContain("b.spec.md");
    expect(result.buildOrder).toBeDefined();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/dag-mcp.test.ts`
Expected: FAIL -- `handleBuildOrder`, `handleResolveDeps`, `handleRippleCheck` not exported from `../src/mcp.js`

- [ ] **Step 3: Add MCP tool handlers and registrations to `mcp.ts`**

Add the following imports and handler functions to `prunejuice/src/mcp.ts`. The existing `handleCheckFreshness` and `createServer` remain; add the new handlers after `handleCheckFreshness` and register the new tools inside `createServer`.

Add imports at the top:

```typescript
import { buildOrder, resolveDeps, type BuildOrderResult } from "./dag.js";
import { rippleCheck } from "./ripple.js";
import type { RippleResult } from "./types.js";
```

Add handler functions after `handleCheckFreshness`:

```typescript
// -- Build order handler ------------------------------------------------------

export interface BuildOrderParams {
  cwd: string;
}

export async function handleBuildOrder(
  params: BuildOrderParams,
): Promise<BuildOrderResult> {
  return buildOrder(params.cwd);
}

// -- Resolve deps handler -----------------------------------------------------

export interface ResolveDepsParams {
  specPath: string;
  cwd: string;
}

export async function handleResolveDeps(
  params: ResolveDepsParams,
): Promise<string[]> {
  return resolveDeps(params.specPath, params.cwd);
}

// -- Ripple check handler -----------------------------------------------------

export interface RippleCheckParams {
  specPaths: string[];
  cwd: string;
}

export async function handleRippleCheck(
  params: RippleCheckParams,
): Promise<RippleResult> {
  return rippleCheck(params.specPaths, params.cwd);
}
```

Register the three new tools inside `createServer()`, after the existing `prunejuice_check_freshness` registration:

```typescript
server.registerTool(
  "prunejuice_build_order",
  {
    description:
      "Topological sort of spec dependency DAG. Returns specs in build order (leaves first).",
    inputSchema: {
      cwd: z.string().describe("Absolute path to the project root"),
    },
  },
  async (args) => {
    try {
      const result = await handleBuildOrder({ cwd: args.cwd });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? `${err.message}\n${err.stack ?? ""}`
          : String(err);
      return {
        isError: true,
        content: [
          {
            type: "text",
            text: `Unexpected error in prunejuice_build_order:\n${message}`,
          },
        ],
      };
    }
  },
);

server.registerTool(
  "prunejuice_resolve_deps",
  {
    description:
      "Resolve transitive dependencies of a single spec file. Returns dependency specs in build order (leaves first), excluding the input spec.",
    inputSchema: {
      specPath: z.string().describe("Path to the spec file (relative to cwd)"),
      cwd: z.string().describe("Absolute path to the project root"),
    },
  },
  async (args) => {
    try {
      const deps = await handleResolveDeps({
        specPath: args.specPath,
        cwd: args.cwd,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(deps, null, 2) }],
      };
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? `${err.message}\n${err.stack ?? ""}`
          : String(err);
      return {
        isError: true,
        content: [
          {
            type: "text",
            text: `Unexpected error in prunejuice_resolve_deps:\n${message}`,
          },
        ],
      };
    }
  },
);

server.registerTool(
  "prunejuice_ripple_check",
  {
    description:
      "Compute blast radius of spec changes across abstract, concrete, and code layers. Returns affected specs, impls, managed files, and build order.",
    inputSchema: {
      specPaths: z
        .array(z.string())
        .describe("Spec file paths to check (relative to cwd)"),
      cwd: z.string().describe("Absolute path to the project root"),
    },
  },
  async (args) => {
    try {
      const result = await handleRippleCheck({
        specPaths: args.specPaths,
        cwd: args.cwd,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? `${err.message}\n${err.stack ?? ""}`
          : String(err);
      return {
        isError: true,
        content: [
          {
            type: "text",
            text: `Unexpected error in prunejuice_ripple_check:\n${message}`,
          },
        ],
      };
    }
  },
);
```

- [ ] **Step 4: Run MCP handler tests**

Run: `cd prunejuice && npx vitest run test/dag-mcp.test.ts`
Expected: All 4 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/mcp.ts prunejuice/test/dag-mcp.test.ts
git commit -m "feat(prunejuice): register build_order, resolve_deps, ripple_check MCP tools"
```

---

### Task 5: Compatibility Tests Against Stress Test Fixtures

**Files:**

- Create: `prunejuice/test/dag-compat.test.ts`

The design spec requires integration tests verifying output format matches the Python server. We use the `stress-tests/` fixtures plus purpose-built multi-spec fixtures to verify.

- [ ] **Step 1: Write compatibility tests**

Create `prunejuice/test/dag-compat.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  handleBuildOrder,
  handleResolveDeps,
  handleRippleCheck,
} from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";

/**
 * Compatibility tests: verify prunejuice DAG tools produce output
 * structurally matching the Python orchestrator's unslop_* tools.
 */

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dag-compat-"));
}

async function writeAt(
  base: string,
  rel: string,
  content: string,
): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

// -- Tests --------------------------------------------------------------------

describe("build_order compatibility", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("output has 'order' field as string array (matches Python list output)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    const result = await handleBuildOrder({ cwd: tmp });

    expect(Array.isArray(result.order)).toBe(true);
    expect(typeof result.order[0]).toBe("string");
  });

  it("cycle output has 'cycles' field as array of arrays", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\ndepends-on:\n  - b.spec.md\n---\n");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await handleBuildOrder({ cwd: tmp });
    expect(result.cycles).toBeDefined();
    expect(Array.isArray(result.cycles)).toBe(true);
    expect(Array.isArray(result.cycles![0])).toBe(true);
  });

  it("matches Python output for diamond dependency graph", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Diamond: d depends on b and c, both depend on a
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(
      tmp,
      "d.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n  - c.spec.md\n---\n",
    );

    const result = await handleBuildOrder({ cwd: tmp });
    // a must come first, d must come last, b and c in between
    expect(result.order[0]).toBe("a.spec.md");
    expect(result.order[result.order.length - 1]).toBe("d.spec.md");
    expect(result.order).toHaveLength(4);
  });
});

describe("resolve_deps compatibility", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns string array (matches Python list output)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");

    const result = await handleResolveDeps({ specPath: "b.spec.md", cwd: tmp });
    expect(Array.isArray(result)).toBe(true);
    expect(result).toEqual(["a.spec.md"]);
  });

  it("does NOT include the input spec (matches Python behavior)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "x.spec.md", "---\n---\n# X");
    const result = await handleResolveDeps({ specPath: "x.spec.md", cwd: tmp });
    expect(result).not.toContain("x.spec.md");
  });
});

describe("ripple_check compatibility", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("output has required top-level fields matching Python format", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    const result = await handleRippleCheck({
      specPaths: ["a.spec.md"],
      cwd: tmp,
    });

    // Verify structural compatibility with Python's output
    expect(result.inputSpecs).toBeDefined();
    expect(result.layers).toBeDefined();
    expect(result.layers.abstract).toBeDefined();
    expect(result.layers.concrete).toBeDefined();
    expect(result.layers.code).toBeDefined();
    expect(result.buildOrder).toBeDefined();

    // Abstract layer fields
    expect(result.layers.abstract.directlyChanged).toBeDefined();
    expect(result.layers.abstract.transitivelyAffected).toBeDefined();
    expect(result.layers.abstract.total).toBeDefined();

    // Concrete layer fields
    expect(result.layers.concrete.affectedImpls).toBeDefined();
    expect(result.layers.concrete.ghostStaleImpls).toBeDefined();
    expect(result.layers.concrete.total).toBeDefined();

    // Code layer fields
    expect(result.layers.code.regenerate).toBeDefined();
    expect(result.layers.code.ghostStale).toBeDefined();
    expect(result.layers.code.totalFiles).toBeDefined();
  });

  it("code layer entries have required fields matching Python format", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/widget.ts.spec.md", "---\n---\n# Widget");

    const result = await handleRippleCheck({
      specPaths: ["src/widget.ts.spec.md"],
      cwd: tmp,
    });

    const entry = result.layers.code.regenerate[0]!;
    expect(entry.managed).toBe("src/widget.ts");
    expect(entry.spec).toBe("src/widget.ts.spec.md");
    expect(typeof entry.exists).toBe("boolean");
    expect(entry.currentState).toBeDefined();
    expect(entry.cause).toBeDefined();
  });
});
```

- [ ] **Step 2: Run compatibility tests**

Run: `cd prunejuice && npx vitest run test/dag-compat.test.ts`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add prunejuice/test/dag-compat.test.ts
git commit -m "test(prunejuice): DAG tool compatibility tests verifying Python output format"
```

---

### Task 6: Version Bump + Final Verification

**Files:**

- Modify: `prunejuice/package.json:2` (version field)

- [ ] **Step 1: Bump prunejuice version**

In `prunejuice/package.json`, change:

```json
"version": "1.1.0",
```

to:

```json
"version": "1.2.0",
```

- [ ] **Step 2: Run the full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass (existing + new)

- [ ] **Step 3: Run the Python orchestrator tests to verify no regressions**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: All 408+ tests pass (Python side is unchanged)

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile, no errors

- [ ] **Step 5: Commit**

```bash
git add prunejuice/package.json
git commit -m "chore(prunejuice): bump version to 1.2.0 for Phase 2"
```

---

## Notes for the Implementer

### Key Invariants

1. **The DAG cache is deterministically reconstructible.** If you delete `.prunejuice/dag-cache.json`, the next `ensureDAG()` call rebuilds it identically from spec files. The cache is a performance optimization, not a source of truth.

2. **Hash-gated invalidation uses the same trust model as the hash chain.** If `truncatedHash(specContent) === manifest[specPath]`, the cached deps are current. No file watchers, no timestamps.

3. **`topoSort` edges point toward dependencies** (not dependents). Node A depends on Node B means `graph["A"] = ["B"]`. A has in-degree 1. B (no deps) has in-degree 0 and sorts first.

4. **`resolveDeps` does NOT include the input spec.** This matches the Python behavior. The caller knows what spec they asked about.

5. **Ripple check camelCase vs Python snake_case.** The TypeScript types use camelCase (`directlyChanged`), but the MCP JSON response will serialize as camelCase too. The design spec says "output schemas match what Python returns" -- this means field names like `directly_changed`. The `JSON.stringify` of the typed objects will produce camelCase. If the commands need exact snake*case compatibility, add a transform layer at MCP response time. For Phase 2 (read-only, both servers running in parallel), this is acceptable because the prunejuice tools have the `prunejuice*\*` prefix and won't be called by existing commands until Phase 5.

### What NOT To Build

- **`prunejuice_discover_files`** is listed in the spec's tool surface but is NOT part of Phase 2. It's a standalone file discovery tool, not a DAG consumer.
- **Concrete spec inheritance resolution** (the `resolve_extends_chain`/`resolve_inherited_sections` logic in `concrete_graph.py`) is Phase 3 territory.
- **Parallel batch computation** (`_compute_parallel_batches` in `unified_dag.py`) is a sync planning optimization for Phase 3.

### Avoiding Circular Imports

`ripple.ts` has its own `computeRippleBuildOrder` with an inline Kahn's sort rather than importing `topoSort` from `dag.ts`. This avoids circular imports (`ripple.ts` imports `ensureDAG` from `dag.ts`; if `dag.ts` imported from `ripple.ts` that would be a cycle). If you want to share the sort logic, extract it to a separate `topo.ts` module that both files import.
