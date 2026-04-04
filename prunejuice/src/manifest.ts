import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { truncatedHash } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import { parseConcreteSpecFrontmatter } from "./ripple.js";
import type { TruncatedHash, ManifestDiff } from "./types.js";
import { MISSING_SENTINEL, UNREADABLE_SENTINEL } from "./types.js";

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
 * Returns null if the spec has no providers.
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
      manifest.set(depPath, UNREADABLE_SENTINEL);
      continue;
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
