import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { ensureDAG } from "./dag.js";
import {
  truncatedHash,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
} from "./hashchain.js";
import type {
  RippleResult,
  RippleAbstractLayer,
  RippleConcreteLayer,
  RippleCodeLayer,
  RippleManagedEntry,
  TruncatedHash,
} from "./types.js";

// -- Internal helpers ---------------------------------------------------------

function isEnoent(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    (err as { code: string }).code === "ENOENT"
  );
}

interface ConcreteSpecMeta {
  sourceSpec: string | null;
  concreteDependencies: string[];
  extends: string | null;
  targets: string[];
}

function parseConcreteSpecFrontmatter(content: string): ConcreteSpecMeta {
  const lines = content.split("\n");
  const result: ConcreteSpecMeta = {
    sourceSpec: null,
    concreteDependencies: [],
    extends: null,
    targets: [],
  };

  if (lines.length === 0 || lines[0]!.trim() !== "---") return result;

  let closingIdx = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]!.trim() === "---") {
      closingIdx = i;
      break;
    }
  }
  if (closingIdx === -1) return result;

  const fmLines = lines.slice(1, closingIdx);
  let currentList: string[] | null = null;

  for (const raw of fmLines) {
    // Normalize snake_case to kebab-case for the key portion
    const colonIdx = raw.indexOf(":");
    if (colonIdx === -1 && currentList !== null) {
      const trimmed = raw.trim();
      if (trimmed.startsWith("- ")) {
        currentList.push(trimmed.slice(2).trim().replace(/^["']|["']$/g, ""));
      } else {
        currentList = null;
      }
      continue;
    }

    const key =
      colonIdx !== -1
        ? raw
            .slice(0, colonIdx)
            .trim()
            .replace(/_/g, "-")
        : raw.trim().replace(/_/g, "-");
    const value =
      colonIdx !== -1
        ? raw
            .slice(colonIdx + 1)
            .trim()
            .replace(/^["']|["']$/g, "")
        : "";

    currentList = null;

    if (key === "source-spec") {
      result.sourceSpec = value || null;
    } else if (key === "extends") {
      result.extends = value || null;
    } else if (key === "concrete-dependencies") {
      if (value.startsWith("[")) {
        const inner = value.slice(1, value.indexOf("]"));
        for (const item of inner.split(",")) {
          const trimmed = item.trim().replace(/^["']|["']$/g, "");
          if (trimmed) result.concreteDependencies.push(trimmed);
        }
      } else if (value) {
        result.concreteDependencies.push(value);
      } else {
        currentList = result.concreteDependencies;
      }
    } else if (key === "targets") {
      if (value.startsWith("[")) {
        const inner = value.slice(1, value.indexOf("]"));
        for (const item of inner.split(",")) {
          const trimmed = item.trim().replace(/^["']|["']$/g, "");
          if (trimmed) result.targets.push(trimmed);
        }
      } else if (value) {
        result.targets.push(value);
      } else {
        currentList = result.targets;
      }
    }
  }

  return result;
}

const EXCLUDE_DIRS = new Set([
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
      } else if (entry.isFile() && entry.name.endsWith(".impl.md")) {
        results.push(join(current, entry.name));
      }
    }
  }

  return results;
}

async function classifyManagedFile(
  managedPath: string,
  specPath: string,
  cwd: string,
): Promise<RippleManagedEntry["currentState"]> {
  const absCwd = resolve(cwd);
  const absSpec = join(absCwd, specPath);
  const absManaged = join(absCwd, managedPath);

  let specContent: string;
  try {
    specContent = await readFile(absSpec, "utf-8");
  } catch (err) {
    if (isEnoent(err)) return "error";
    throw err;
  }

  let managedContent: string;
  try {
    managedContent = await readFile(absManaged, "utf-8");
  } catch (err) {
    if (isEnoent(err)) return "new";
    throw err;
  }

  const currentSpecHash = truncatedHash(specContent);
  const header = parseHeader(managedContent);
  const body = getBodyBelowHeader(managedContent);
  const currentOutputHash = truncatedHash(body);

  const state = classifyFreshness({
    currentSpecHash,
    headerSpecHash: header?.specHash ?? null,
    currentOutputHash,
    headerOutputHash: header?.outputHash ?? null,
    codeFileExists: true,
    upstreamChanged: false,
    specChangedSinceTests: false,
  });

  return state;
}

function computeRippleBuildOrder(
  affected: Set<string>,
  graph: Record<string, string[]>,
  concreteSpecEdges: Map<string, string[]>,
): string[] {
  // Build subgraph of affected specs
  const subgraph: Record<string, string[]> = {};
  for (const node of affected) {
    const deps = (graph[node] ?? []).filter((d) => affected.has(d));
    // Also add concrete spec edges projected to spec space
    const concreteDeps = concreteSpecEdges.get(node) ?? [];
    const allDeps = [
      ...new Set([...deps, ...concreteDeps.filter((d) => affected.has(d))]),
    ];
    subgraph[node] = allDeps;
  }

  // Inline Kahn's sort (avoid importing topoSort to prevent circular deps)
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of Object.keys(subgraph)) {
    if (!inDegree.has(node)) inDegree.set(node, 0);
    if (!adjacency.has(node)) adjacency.set(node, []);
    for (const dep of subgraph[node]!) {
      if (!inDegree.has(dep)) inDegree.set(dep, 0);
      if (!adjacency.has(dep)) adjacency.set(dep, []);
    }
  }

  for (const [node, deps] of Object.entries(subgraph)) {
    for (const dep of deps) {
      adjacency.get(dep)!.push(node);
      inDegree.set(node, inDegree.get(node)! + 1);
    }
  }

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
        const insertIdx = queue.findIndex((q) => q > dependent);
        if (insertIdx === -1) queue.push(dependent);
        else queue.splice(insertIdx, 0, dependent);
      }
    }
  }

  // Cycle fallback: alphabetical
  if (result.length < inDegree.size) {
    return [...affected].sort();
  }

  return result;
}

// -- Exported function --------------------------------------------------------

export async function rippleCheck(
  specPaths: string[],
  cwd: string,
): Promise<RippleResult> {
  const absCwd = resolve(cwd);
  const cache = await ensureDAG(cwd);
  const dag = cache.dag;

  // -- Layer 1: Abstract (BFS through reverse deps) ---------------------------

  // Build reverse dep map
  const reverseDeps = new Map<string, string[]>();
  for (const [spec, deps] of Object.entries(dag)) {
    for (const dep of deps) {
      if (!reverseDeps.has(dep)) reverseDeps.set(dep, []);
      reverseDeps.get(dep)!.push(spec);
    }
  }

  // BFS from input specs
  const inputSet = new Set(specPaths);
  const allAffected = new Set(specPaths);
  const bfsQueue = [...specPaths];

  while (bfsQueue.length > 0) {
    const current = bfsQueue.shift()!;
    const dependents = reverseDeps.get(current) ?? [];
    for (const dep of dependents) {
      if (!allAffected.has(dep)) {
        allAffected.add(dep);
        bfsQueue.push(dep);
      }
    }
  }

  const directlyChanged = [...inputSet].filter((s) => s in dag || allAffected.has(s));
  const transitivelyAffected = [...allAffected].filter(
    (s) => !inputSet.has(s),
  );

  const abstractLayer: RippleAbstractLayer = {
    directlyChanged: directlyChanged.sort(),
    transitivelyAffected: transitivelyAffected.sort(),
    total: allAffected.size,
  };

  // -- Layer 2: Concrete (impl files) ----------------------------------------

  const implAbsPaths = await findImplFiles(absCwd, EXCLUDE_DIRS);
  const specToImpls = new Map<string, string[]>();
  const implMeta = new Map<string, ConcreteSpecMeta>();
  const reverseConcrete = new Map<string, string[]>();

  for (const absPath of implAbsPaths) {
    const rel = relative(absCwd, absPath);
    let content: string;
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err: unknown) {
      if (isEnoent(err)) continue;
      throw err;
    }
    const meta = parseConcreteSpecFrontmatter(content);
    implMeta.set(rel, meta);

    if (meta.sourceSpec) {
      if (!specToImpls.has(meta.sourceSpec))
        specToImpls.set(meta.sourceSpec, []);
      specToImpls.get(meta.sourceSpec)!.push(rel);
    }

    // Build reverse concrete dep edges
    for (const dep of meta.concreteDependencies) {
      if (!reverseConcrete.has(dep)) reverseConcrete.set(dep, []);
      reverseConcrete.get(dep)!.push(rel);
    }
    if (meta.extends) {
      if (!reverseConcrete.has(meta.extends))
        reverseConcrete.set(meta.extends, []);
      reverseConcrete.get(meta.extends)!.push(rel);
    }
  }

  // BFS from impls whose sourceSpec is in affectedSpecs
  const affectedImplSet = new Set<string>();
  const implQueue: string[] = [];

  for (const spec of allAffected) {
    const impls = specToImpls.get(spec) ?? [];
    for (const impl of impls) {
      if (!affectedImplSet.has(impl)) {
        affectedImplSet.add(impl);
        implQueue.push(impl);
      }
    }
  }

  while (implQueue.length > 0) {
    const current = implQueue.shift()!;
    const dependents = reverseConcrete.get(current) ?? [];
    for (const dep of dependents) {
      if (!affectedImplSet.has(dep)) {
        affectedImplSet.add(dep);
        implQueue.push(dep);
      }
    }
  }

  // Ghost-stale impls: affected impls NOT directly reachable from affected specs
  const directlyReachableImpls = new Set<string>();
  for (const spec of allAffected) {
    for (const impl of specToImpls.get(spec) ?? []) {
      directlyReachableImpls.add(impl);
    }
  }
  const ghostStaleImpls = [...affectedImplSet].filter(
    (impl) => !directlyReachableImpls.has(impl),
  );

  const concreteLayer: RippleConcreteLayer = {
    affectedImpls: [...affectedImplSet].sort(),
    ghostStaleImpls: ghostStaleImpls.sort(),
    total: affectedImplSet.size,
  };

  // -- Layer 3: Code (managed file entries) -----------------------------------

  const regenerate: RippleManagedEntry[] = [];
  const ghostStale: RippleManagedEntry[] = [];

  // For each affected spec, derive managed file paths
  for (const spec of allAffected) {
    const impls = specToImpls.get(spec) ?? [];
    const cause = inputSet.has(spec) ? "direct" : "transitive";

    // Check if any impl has multi-target
    let targets: string[] = [];
    for (const impl of impls) {
      const meta = implMeta.get(impl);
      if (meta && meta.targets.length > 0) {
        targets = [...targets, ...meta.targets];
      }
    }

    if (targets.length > 0) {
      // Multi-target: use targets from impl
      for (const target of targets) {
        const state = await classifyManagedFile(target, spec, cwd);
        const absTarget = join(absCwd, target);
        let exists = true;
        try {
          await stat(absTarget);
        } catch (err: unknown) {
          if (!isEnoent(err)) throw err;
          exists = false;
        }

        const entry: RippleManagedEntry = {
          managed: target,
          spec,
          exists,
          currentState: exists ? state : "new",
          cause: cause as "direct" | "transitive",
        };
        regenerate.push(entry);
      }
    } else {
      // Single target: strip .spec.md suffix
      const managed = spec.replace(/\.spec\.md$/, "");
      const state = await classifyManagedFile(managed, spec, cwd);
      const absManaged = join(absCwd, managed);
      let exists = true;
      try {
        await stat(absManaged);
      } catch (err: unknown) {
        if (!isEnoent(err)) throw err;
        exists = false;
      }

      const entry: RippleManagedEntry = {
        managed,
        spec,
        exists,
        currentState: exists ? state : "new",
        cause: cause as "direct" | "transitive",
      };
      regenerate.push(entry);
    }
  }

  // Ghost-stale managed entries from ghost-stale impls
  for (const impl of ghostStaleImpls) {
    const meta = implMeta.get(impl);
    if (!meta) continue;

    const targets =
      meta.targets.length > 0
        ? meta.targets
        : [impl.replace(/\.impl\.md$/, "")];

    for (const target of targets) {
      const absTarget = join(absCwd, target);
      let exists = true;
      try {
        await stat(absTarget);
      } catch (err: unknown) {
        if (!isEnoent(err)) throw err;
        exists = false;
      }

      const entry: RippleManagedEntry = {
        managed: target,
        spec: meta.sourceSpec ?? impl,
        concrete: impl,
        exists,
        currentState: "ghost-stale",
        cause: "ghost-stale",
        ghostSource: impl,
      };
      ghostStale.push(entry);
    }
  }

  const codeLayer: RippleCodeLayer = {
    regenerate,
    ghostStale,
    totalFiles: regenerate.length + ghostStale.length,
  };

  // -- Build order ------------------------------------------------------------

  const concreteSpecEdges = new Map<string, string[]>();
  // Project concrete edges to spec space
  for (const [implRel, meta] of implMeta) {
    if (!meta.sourceSpec) continue;
    for (const dep of meta.concreteDependencies) {
      const depMeta = implMeta.get(dep);
      if (depMeta?.sourceSpec) {
        if (!concreteSpecEdges.has(meta.sourceSpec))
          concreteSpecEdges.set(meta.sourceSpec, []);
        concreteSpecEdges.get(meta.sourceSpec)!.push(depMeta.sourceSpec);
      }
    }
  }

  const buildOrder = computeRippleBuildOrder(
    allAffected,
    dag,
    concreteSpecEdges,
  );

  return {
    inputSpecs: [...specPaths],
    layers: {
      abstract: abstractLayer,
      concrete: concreteLayer,
      code: codeLayer,
    },
    buildOrder,
  };
}
