import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { truncatedHash } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import { parseConcreteSpecFrontmatter } from "./ripple.js";
import type { TruncatedHash, ManifestDiff, GhostStaleDiagnostic } from "./types.js";
import { MISSING_SENTINEL } from "./types.js";

// -- Manifest diffing (pure, no IO) ------------------------------------------

/** Compute the structural diff between two concrete dependency manifests. */
export function diffConcreteManifests(
  previous: Map<string, TruncatedHash>,
  current: Map<string, TruncatedHash>,
): ManifestDiff {
  const added: string[] = [];
  const removed: string[] = [];
  const changed: string[] = [];

  for (const [path, hash] of current) {
    const prev = previous.get(path);
    if (prev === undefined) {
      added.push(path);
    } else if (prev !== hash) {
      changed.push(path);
    }
  }

  for (const path of previous.keys()) {
    if (!current.has(path)) {
      removed.push(path);
    }
  }

  added.sort();
  removed.sort();
  changed.sort();

  return { added, removed, changed };
}

// -- Strategy provider resolution ---------------------------------------------

/** Get all strategy providers: concrete-dependencies union extends. */
function getAllStrategyProviders(meta: {
  concreteDependencies: string[];
  extends: string | null;
}): string[] {
  const providers = new Set(meta.concreteDependencies);
  if (meta.extends) providers.add(meta.extends);
  return [...providers].sort();
}

// -- Manifest computation (IO-bound BFS) --------------------------------------

/**
 * Compute per-dependency manifest for a concrete spec.
 * BFS through concrete-dependencies + extends, hashing each file's content.
 * Returns null if the spec file doesn't exist or has no providers.
 *
 * Throws on any non-ENOENT read error (permission denied, I/O failure, etc.)
 * to avoid poisoning the manifest with bogus hashes.
 */
export async function computeConcreteManifest(
  specPath: string,
  cwd: string,
): Promise<Map<string, TruncatedHash> | null> {
  const absCwd = resolve(cwd);
  const absSpec = join(absCwd, specPath);

  let content: string;
  try {
    content = await readFile(absSpec, "utf-8");
  } catch (err) {
    if (isEnoent(err)) return null;
    throw err;
  }

  const meta = parseConcreteSpecFrontmatter(content);
  const directProviders = getAllStrategyProviders(meta);
  if (directProviders.length === 0) return null;

  const manifest = new Map<string, TruncatedHash>();
  const visited = new Set<string>();
  const queue = [...directProviders];

  while (queue.length > 0) {
    const depPath = queue.shift()!;
    if (visited.has(depPath)) continue;
    visited.add(depPath);

    const absDep = join(absCwd, depPath);
    let depContent: string;
    try {
      depContent = await readFile(absDep, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        manifest.set(depPath, MISSING_SENTINEL);
        continue;
      }
      throw err;
    }

    manifest.set(depPath, truncatedHash(depContent));

    // Walk transitive providers
    const depMeta = parseConcreteSpecFrontmatter(depContent);
    for (const upstream of getAllStrategyProviders(depMeta)) {
      if (!visited.has(upstream)) {
        queue.push(upstream);
      }
    }
  }

  return manifest.size > 0 ? manifest : null;
}

/**
 * Compute a single opaque hash of all transitive strategy providers.
 * Returns null if the spec has no providers.
 */
export async function computeConcreteDepsHash(
  specPath: string,
  cwd: string,
): Promise<TruncatedHash | null> {
  const manifest = await computeConcreteManifest(specPath, cwd);
  if (!manifest) return null;

  const combined = [...manifest.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, hash]) => `${path}:${hash}`)
    .join("\n");

  return truncatedHash(combined);
}

// -- Ghost staleness chain tracing --------------------------------------------

/**
 * Walk upstream from a changed dep, following only edges to other changed deps,
 * to find the deepest changed node (the root cause).
 *
 * Returns a chain from `startPath` to the deepest changed upstream. If `startPath`
 * has no changed upstream, returns `[startPath]`. The chain only contains deps
 * that actually differ from their stored hash -- unchanged intermediaries are
 * not traversed.
 *
 * Throws on non-ENOENT read errors to avoid silently truncating chains.
 */
async function traceChangeChain(
  startPath: string,
  changedPaths: Set<string>,
  cwd: string,
): Promise<string[]> {
  const absCwd = resolve(cwd);
  const chain = [startPath];
  const visited = new Set([startPath]);
  let current = startPath;

  while (true) {
    const absPath = join(absCwd, current);
    let content: string;
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err) {
      if (isEnoent(err)) break; // missing spec terminates chain
      throw err;
    }

    const meta = parseConcreteSpecFrontmatter(content);
    const upstreams = getAllStrategyProviders(meta);

    // Only follow upstreams that are themselves in the changed set.
    // Pick deterministically (first alphabetically) among unvisited changed upstreams.
    let foundDeeper = false;
    for (const up of upstreams) {
      if (visited.has(up)) continue;
      if (!changedPaths.has(up)) continue;
      visited.add(up);
      chain.push(up);
      current = up;
      foundDeeper = true;
      break;
    }

    if (!foundDeeper) break;
  }

  return chain;
}

/**
 * Compare stored manifest against current disk state.
 * Returns one diagnostic per dependency that has changed, with a chain tracing
 * back to the root cause within the changed set.
 */
export async function diagnoseGhostStaleness(
  storedManifest: Map<string, TruncatedHash>,
  cwd: string,
): Promise<GhostStaleDiagnostic[]> {
  const absCwd = resolve(cwd);

  // Pass 1: build full current manifest before computing any diffs
  const currentManifest = new Map<string, TruncatedHash>();
  const changedDeps: Array<{ depPath: string; currentHash: TruncatedHash }> = [];

  for (const [depPath, storedHash] of [...storedManifest.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const absDep = join(absCwd, depPath);
    let depContent: string;

    try {
      depContent = await readFile(absDep, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        currentManifest.set(depPath, MISSING_SENTINEL);
        if (storedHash !== MISSING_SENTINEL) {
          changedDeps.push({ depPath, currentHash: MISSING_SENTINEL });
        }
        continue;
      }
      throw err;
    }

    const currentHash = truncatedHash(depContent);
    currentManifest.set(depPath, currentHash);

    if (currentHash !== storedHash) {
      changedDeps.push({ depPath, currentHash });
    }
  }

  // Pass 2: compute diagnostics with complete manifest diff
  const manifestDiff = diffConcreteManifests(storedManifest, currentManifest);
  const changedPaths = new Set(changedDeps.map((d) => d.depPath));
  const diagnostics: GhostStaleDiagnostic[] = [];

  for (const { depPath, currentHash } of changedDeps) {
    const chain = currentHash === MISSING_SENTINEL
      ? [depPath]
      : await traceChangeChain(depPath, changedPaths, cwd);

    diagnostics.push({
      changedSpec: depPath,
      changeHash: currentHash,
      chain,
      manifestDiff,
    });
  }

  return diagnostics;
}

/**
 * Format a ghost staleness diagnostic into a human-readable string.
 * This is the output the command layer surfaces directly.
 */
export function formatGhostDiagnostic(diagnostic: GhostStaleDiagnostic): string {
  const { changedSpec, changeHash, chain } = diagnostic;

  if (changeHash === MISSING_SENTINEL) {
    return `upstream \`${changedSpec}\` not found`;
  }

  if (chain.length <= 1) {
    return `upstream \`${changedSpec}\` changed`;
  }

  const via = chain.slice(1).join(" -> ");
  return `upstream \`${changedSpec}\` changed (via ${via})`;
}
