import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { ensureDAG, topoSort } from "./dag.js";
import {
  truncatedHash,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
  parseManifestLine,
} from "./hashchain.js";
import { isEnoent, EXCLUDE_DIRS } from "./fs-utils.js";
import {
  diagnoseGhostStaleness,
} from "./manifest.js";
import type { GhostStaleDiagnostic } from "./types.js";
import type {
  RippleResult,
  RippleAbstractLayer,
  RippleConcreteLayer,
  RippleCodeLayer,
  RippleManagedEntry,
  TruncatedHash,
} from "./types.js";

export interface ConcreteSpecMeta {
  sourceSpec: string | null;
  concreteDependencies: string[];
  extends: string | null;
  targets: Array<{ path: string; language?: string }>;
}

/**
 * Construct a ghost-stale RippleManagedEntry with a release-mode invariant
 * check. A diagnostic may be absent (no stored manifest found) but when
 * present it must describe this entry's ghost-stale cause.
 */
function makeGhostStaleEntry(args: {
  managed: string;
  spec: string;
  concrete: string;
  exists: boolean;
  ghostSource: string;
  diagnostic?: GhostStaleDiagnostic;
}): RippleManagedEntry {
  // Release-mode invariant: diagnostics are only valid on ghost-stale entries.
  // This factory is the only path that sets diagnostic, so the invariant holds
  // by construction -- the assertion is defensive against future refactors.
  if (args.diagnostic !== undefined && args.diagnostic.chain.length === 0) {
    throw new Error(
      `makeGhostStaleEntry: diagnostic.chain must be non-empty (managed=${args.managed})`,
    );
  }
  return {
    managed: args.managed,
    spec: args.spec,
    concrete: args.concrete,
    exists: args.exists,
    currentState: "ghost-stale",
    cause: "ghost-stale",
    ghostSource: args.ghostSource,
    diagnostic: args.diagnostic,
  };
}

export function parseConcreteSpecFrontmatter(content: string): ConcreteSpecMeta {
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

  let currentField: "concrete-deps" | "targets" | null = null;
  let currentTarget: { path: string; language?: string } | null = null;

  for (let i = 1; i < closingIdx; i++) {
    const raw = lines[i]!;
    const stripped = raw.trim();
    if (stripped === "") continue;

    // Normalize snake_case key
    const colonIdx = raw.indexOf(":");
    const key = colonIdx !== -1
      ? raw.slice(0, colonIdx).trim().replace(/_/g, "-")
      : "";
    const value = colonIdx !== -1
      ? raw.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, "")
      : "";

    // Check if this is a top-level field (no leading whitespace)
    if (!raw.startsWith(" ") && !raw.startsWith("\t")) {
      // Flush any pending target
      if (currentTarget?.path) {
        result.targets.push(currentTarget);
        currentTarget = null;
      }
      currentField = null;

      if (key === "source-spec") {
        result.sourceSpec = value || null;
      } else if (key === "extends") {
        result.extends = value || null;
      } else if (key === "concrete-dependencies") {
        if (value) {
          result.concreteDependencies.push(value);
        } else {
          currentField = "concrete-deps";
        }
      } else if (key === "targets") {
        currentField = "targets";
      }
      continue;
    }

    // Indented line -- part of a list
    if (currentField === "concrete-deps" && stripped.startsWith("- ")) {
      result.concreteDependencies.push(
        stripped.slice(2).trim().replace(/^["']|["']$/g, ""),
      );
    } else if (currentField === "targets") {
      if (stripped.startsWith("- ")) {
        // New target entry -- flush previous
        if (currentTarget?.path) {
          result.targets.push(currentTarget);
        }
        // Check for inline `- path: value`
        const inlineMatch = stripped.match(/^- path:\s*(.+)$/);
        if (inlineMatch) {
          currentTarget = { path: inlineMatch[1]!.trim() };
        } else {
          // Simple string target (e.g. `- src/foo.py`)
          const simpleValue = stripped.slice(2).trim().replace(/^["']|["']$/g, "");
          currentTarget = { path: simpleValue };
        }
      } else if (currentTarget && raw.startsWith("    ")) {
        // Nested field under current target (4-space indent)
        const fieldMatch = stripped.match(/^(\w[\w-]*):\s*(.+)$/);
        if (fieldMatch) {
          const fieldKey = fieldMatch[1]!.replace(/_/g, "-");
          const fieldVal = fieldMatch[2]!.trim().replace(/^["']|["']$/g, "");
          if (fieldKey === "language") {
            currentTarget.language = fieldVal;
          } else if (fieldKey === "path") {
            currentTarget.path = fieldVal;
          }
        }
      }
    }
  }

  // Flush remaining target
  if (currentTarget?.path) {
    result.targets.push(currentTarget);
  }

  return result;
}

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
    const concreteDeps = concreteSpecEdges.get(node) ?? [];
    const allDeps = [
      ...new Set([...deps, ...concreteDeps.filter((d) => affected.has(d))]),
    ];
    subgraph[node] = allDeps;
  }

  try {
    return topoSort(subgraph);
  } catch {
    // Cycle fallback: alphabetical
    return [...affected].sort();
  }
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

    // Resolve source-spec relative to impl location (may be "../src/api.spec.md")
    if (meta.sourceSpec) {
      const implDir = join(absCwd, rel, "..");
      const resolved = resolve(implDir, meta.sourceSpec);
      meta.sourceSpec = relative(absCwd, resolved);
    }

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
    let targetPaths: string[] = [];
    for (const impl of impls) {
      const meta = implMeta.get(impl);
      if (meta && meta.targets.length > 0) {
        targetPaths = [...targetPaths, ...meta.targets.map((t) => t.path)];
      }
    }

    if (targetPaths.length > 0) {
      // Multi-target: use targets from impl
      for (const target of targetPaths) {
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

    const targetPaths =
      meta.targets.length > 0
        ? meta.targets.map((t) => t.path)
        : [impl.replace(/\.impl\.md$/, "")];

    // Try to compute ghost diagnostic from stored manifest
    let diagnostic: GhostStaleDiagnostic | undefined;

    for (const target of targetPaths) {
      const absTarget = join(absCwd, target);
      let exists = true;
      try {
        await stat(absTarget);
      } catch (err: unknown) {
        if (!isEnoent(err)) throw err;
        exists = false;
      }

      // Look for stored manifest in managed file header.
      // Narrow readFile errors to ENOENT only -- let diagnoseGhostStaleness
      // errors propagate so real failures aren't masked.
      if (exists && !diagnostic) {
        let managedContent: string | null = null;
        try {
          managedContent = await readFile(absTarget, "utf-8");
        } catch (err: unknown) {
          if (!isEnoent(err)) throw err;
        }

        if (managedContent !== null) {
          const headerLines = managedContent.split("\n").slice(0, 10);
          for (const line of headerLines) {
            const storedManifest = parseManifestLine(line);
            if (storedManifest && storedManifest.size > 0) {
              const diagnostics = await diagnoseGhostStaleness(
                storedManifest,
                cwd,
              );
              if (diagnostics.length > 0) {
                diagnostic = diagnostics[0];
              }
              break;
            }
          }
        }
      }

      const entry = makeGhostStaleEntry({
        managed: target,
        spec: meta.sourceSpec ?? impl,
        concrete: impl,
        exists,
        ghostSource: impl,
        diagnostic,
      });
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

  // Collect ghost-stale specs for build order
  const ghostStaleSpecs = new Set<string>();
  for (const impl of ghostStaleImpls) {
    const meta = implMeta.get(impl);
    if (meta?.sourceSpec) ghostStaleSpecs.add(meta.sourceSpec);
  }

  const allForBuildOrder = new Set([...allAffected, ...ghostStaleSpecs]);

  const buildOrder = computeRippleBuildOrder(
    allForBuildOrder,
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
