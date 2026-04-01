import { readdir, readFile, stat, writeFile, mkdir } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { truncatedHash } from "./hashchain.js";
import { isEnoent, EXCLUDE_DIRS } from "./fs-utils.js";
import type { DAGCache, TruncatedHash } from "./types.js";

// -- In-memory singleton cache ------------------------------------------------

const memoryCache = new Map<string, DAGCache>();

// -- Internal helpers ---------------------------------------------------------

function normalizeKey(line: string): string {
  const colonIdx = line.indexOf(":");
  if (colonIdx === -1) return line;
  const key = line.slice(0, colonIdx);
  const rest = line.slice(colonIdx);
  return key.replace(/_/g, "-") + rest;
}

async function findSpecFiles(
  dir: string,
  excludeSet: Set<string>,
): Promise<string[]> {
  const results: string[] = [];
  const stack = [dir];

  while (stack.length > 0) {
    const current = stack.pop()!;
    let entries;
    try {
      entries = await readdir(current, { withFileTypes: true });
    } catch (err: unknown) {
      if (isEnoent(err)) continue;
      throw err;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (!excludeSet.has(entry.name)) {
          stack.push(join(current, entry.name));
        }
      } else if (entry.isFile() && entry.name.endsWith(".spec.md")) {
        results.push(join(current, entry.name));
      }
    }
  }

  return results;
}

async function fullScan(absCwd: string): Promise<DAGCache> {
  const specPaths = await findSpecFiles(absCwd, EXCLUDE_DIRS);
  const dag: Record<string, string[]> = {};
  const manifest: Record<string, TruncatedHash> = {};

  for (const absPath of specPaths) {
    const rel = relative(absCwd, absPath);
    const content = await readFile(absPath, "utf-8");
    const hash = truncatedHash(content);
    const deps = parseDependsOn(content);
    dag[rel] = deps;
    manifest[rel] = hash;
  }

  const cache: DAGCache = {
    dag,
    manifest,
    builtAt: new Date().toISOString(),
  };

  return cache;
}

async function persistCache(
  absCwd: string,
  cache: DAGCache,
): Promise<void> {
  const cacheDir = join(absCwd, ".prunejuice");
  await mkdir(cacheDir, { recursive: true });
  await writeFile(
    join(cacheDir, "dag-cache.json"),
    JSON.stringify(cache, null, 2),
    "utf-8",
  );
}

// -- Exported functions -------------------------------------------------------

/**
 * Extract `depends-on` list from spec file frontmatter.
 * Strict string matching (not YAML). Normalizes snake_case keys to kebab-case.
 */
export function parseDependsOn(content: string): string[] {
  const lines = content.split("\n");

  // Must start with ---
  if (lines.length === 0 || lines[0]!.trim() !== "---") return [];

  // Find closing ---
  let closingIdx = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]!.trim() === "---") {
      closingIdx = i;
      break;
    }
  }

  // Unclosed frontmatter
  if (closingIdx === -1) return [];

  const frontmatterLines = lines.slice(1, closingIdx);
  const deps: string[] = [];
  let inDependsOn = false;

  for (const raw of frontmatterLines) {
    const normalized = normalizeKey(raw);

    if (/^depends-on\s*:/.test(normalized.trim())) {
      inDependsOn = true;
      // Check for inline value (single-line format)
      const after = normalized.trim().replace(/^depends-on\s*:\s*/, "");
      if (after.startsWith("[")) {
        // Inline array: depends-on: [a, b]
        const inner = after.slice(1, after.indexOf("]"));
        for (const item of inner.split(",")) {
          const trimmed = item.trim().replace(/^["']|["']$/g, "");
          if (trimmed) deps.push(trimmed);
        }
        inDependsOn = false;
      }
      continue;
    }

    if (inDependsOn) {
      const trimmed = raw.trim();
      if (trimmed.startsWith("- ")) {
        deps.push(trimmed.slice(2).trim().replace(/^["']|["']$/g, ""));
      } else {
        // Next field or non-list line -- stop
        inDependsOn = false;
      }
    }
  }

  return deps;
}

/**
 * Kahn's topological sort. Edges point toward dependencies.
 * Returns sorted list (leaves first -- nodes with 0 in-degree).
 * Throws Error with "Cycle detected involving: ..." message on cycles.
 */
export function topoSort(graph: Record<string, string[]>): string[] {
  // Build in-degree map
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>(); // node -> dependents

  // Initialize all nodes
  for (const node of Object.keys(graph)) {
    if (!inDegree.has(node)) inDegree.set(node, 0);
    if (!adjacency.has(node)) adjacency.set(node, []);
    for (const dep of graph[node]!) {
      if (!inDegree.has(dep)) inDegree.set(dep, 0);
      if (!adjacency.has(dep)) adjacency.set(dep, []);
    }
  }

  // For each edge: A depends on B means B -> A in adjacency
  // A has in-degree +1 for each dependency
  for (const [node, deps] of Object.entries(graph)) {
    for (const dep of deps) {
      adjacency.get(dep)!.push(node);
      inDegree.set(node, inDegree.get(node)! + 1);
    }
  }

  // Seed queue with 0 in-degree nodes (sorted for determinism)
  const queue: string[] = [];
  for (const [node, deg] of inDegree) {
    if (deg === 0) queue.push(node);
  }
  queue.sort();

  const result: string[] = [];

  while (queue.length > 0) {
    const node = queue.shift()!;
    result.push(node);

    for (const dependent of adjacency.get(node)!) {
      const newDeg = inDegree.get(dependent)! - 1;
      inDegree.set(dependent, newDeg);
      if (newDeg === 0) {
        // Insert sorted
        const insertIdx = queue.findIndex((q) => q > dependent);
        if (insertIdx === -1) queue.push(dependent);
        else queue.splice(insertIdx, 0, dependent);
      }
    }
  }

  if (result.length < inDegree.size) {
    const cycleNodes = [...inDegree.entries()]
      .filter(([, deg]) => deg > 0)
      .map(([node]) => node)
      .sort();
    throw new Error(`Cycle detected involving: ${cycleNodes.join(", ")}`);
  }

  return result;
}

/** Build order result */
export interface BuildOrderResult {
  order: string[];
  cycles?: string[][];
}

/**
 * Hash-gated DAG cache with cold start, warm path, deletion pruning,
 * and new file detection. Persists to `.prunejuice/dag-cache.json`.
 */
export async function ensureDAG(cwd: string): Promise<DAGCache> {
  const absCwd = resolve(cwd);

  // Check in-memory cache
  const cached = memoryCache.get(absCwd);
  if (cached) {
    // Warm path: check for changes
    let mutated = false;

    // Check existing manifest entries
    const toDelete: string[] = [];
    for (const [rel, oldHash] of Object.entries(cached.manifest)) {
      const absPath = join(absCwd, rel);
      try {
        const content = await readFile(absPath, "utf-8");
        const hash = truncatedHash(content);
        if (hash !== oldHash) {
          // Hash differs -- re-parse
          const deps = parseDependsOn(content);
          cached.dag[rel] = deps;
          cached.manifest[rel] = hash;
          mutated = true;
        }
      } catch (err) {
        if (isEnoent(err)) {
          toDelete.push(rel);
          mutated = true;
        }
      }
    }

    // Prune deleted specs
    for (const rel of toDelete) {
      delete cached.dag[rel];
      delete cached.manifest[rel];
      // Remove edges pointing to deleted spec
      for (const deps of Object.values(cached.dag)) {
        const idx = deps.indexOf(rel);
        if (idx !== -1) deps.splice(idx, 1);
      }
    }

    // New file detection
    const specPaths = await findSpecFiles(absCwd, EXCLUDE_DIRS);
    for (const absPath of specPaths) {
      const rel = relative(absCwd, absPath);
      if (!(rel in cached.manifest)) {
        const content = await readFile(absPath, "utf-8");
        const hash = truncatedHash(content);
        const deps = parseDependsOn(content);
        cached.dag[rel] = deps;
        cached.manifest[rel] = hash;
        mutated = true;
      }
    }

    if (mutated) {
      cached.builtAt = new Date().toISOString();
      await persistCache(absCwd, cached);
    }

    return cached;
  }

  // Cold start: try to load from disk
  const cachePath = join(absCwd, ".prunejuice", "dag-cache.json");
  let diskCache: DAGCache | null = null;
  try {
    const raw = await readFile(cachePath, "utf-8");
    try {
      diskCache = JSON.parse(raw) as DAGCache;
    } catch {
      // Corrupt cache -- fall through to full scan
      process.stderr.write(
        `prunejuice: corrupt dag-cache.json, rebuilding\n`,
      );
    }
  } catch (err: unknown) {
    if (!isEnoent(err)) throw err;
  }

  if (diskCache) {
    memoryCache.set(absCwd, diskCache);
    // Re-enter to do warm path validation
    return ensureDAG(cwd);
  }

  // Full scan
  const cache = await fullScan(absCwd);
  memoryCache.set(absCwd, cache);
  await persistCache(absCwd, cache);
  return cache;
}

/** Clear in-memory cache. For tests. */
export function clearDAGCache(cwd?: string): void {
  if (cwd) {
    memoryCache.delete(resolve(cwd));
  } else {
    memoryCache.clear();
  }
}

/**
 * Returns build order and cycles (if any).
 * On cycle, returns alphabetical fallback + cycle info.
 */
export async function buildOrder(cwd: string): Promise<BuildOrderResult> {
  const cache = await ensureDAG(cwd);

  try {
    const order = topoSort(cache.dag);
    return { order };
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("Cycle detected")) {
      // Extract cycle nodes from error message
      const match = err.message.match(/Cycle detected involving: (.+)/);
      const cycleNodes = match ? match[1]!.split(", ") : [];
      const allNodes = Object.keys(cache.dag).sort();
      return {
        order: allNodes,
        cycles: [cycleNodes],
      };
    }
    throw err;
  }
}

/**
 * Iterative DFS for transitive deps. Does NOT include the input spec.
 * Throws on cycle.
 */
export async function resolveDeps(
  specPath: string,
  cwd: string,
): Promise<string[]> {
  const cache = await ensureDAG(cwd);
  const visited = new Set<string>();
  const inStack = new Set<string>();
  const result: string[] = [];

  // Iterative DFS with cycle detection
  const stack: Array<{ node: string; phase: "enter" | "exit" }> = [
    { node: specPath, phase: "enter" },
  ];

  while (stack.length > 0) {
    const { node, phase } = stack.pop()!;

    if (phase === "exit") {
      inStack.delete(node);
      if (node !== specPath) {
        result.push(node);
      }
      continue;
    }

    if (inStack.has(node)) {
      throw new Error(`Cycle detected involving: ${node}`);
    }
    if (visited.has(node)) continue;

    visited.add(node);
    inStack.add(node);
    stack.push({ node, phase: "exit" });

    const deps = cache.dag[node] ?? [];
    // Push in reverse for deterministic order
    for (let i = deps.length - 1; i >= 0; i--) {
      stack.push({ node: deps[i]!, phase: "enter" });
    }
  }

  // Return in dependency order (leaves first) using topoSort on the subgraph
  if (result.length === 0) return [];

  const subgraph: Record<string, string[]> = {};
  for (const node of result) {
    subgraph[node] = (cache.dag[node] ?? []).filter((d) => result.includes(d));
  }

  return topoSort(subgraph);
}
