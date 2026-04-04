import { readFile, stat } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { checkFreshnessAll, type FreshnessEntry } from "./freshness.js";
import { ensureDAG, topoSort } from "./dag.js";
import { rippleCheck } from "./ripple.js";
import { parseHeader } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import type {
  DeepSyncResult,
  BulkSyncResult,
  ResumeSyncResult,
  SyncPlanEntry,
  SyncBatch,
  CollisionEntry,
} from "./types.js";

// -- Option types -------------------------------------------------------------

export interface DeepSyncOptions {
  force?: boolean;
  /** Map from target path to the concrete spec that should win a collision. */
  preferSpec?: Record<string, string>;
}

export interface BulkSyncOptions {
  force?: boolean;
  maxBatchSize?: number;
  preferSpec?: Record<string, string>;
}

export interface ResumeSyncOptions {
  failedFiles: string[];
  succeededFiles: string[];
  force?: boolean;
  maxBatchSize?: number;
  preferSpec?: Record<string, string>;
}

// -- Internal helpers ---------------------------------------------------------

/**
 * Identify the claimant for a sync plan entry. Concrete-spec-backed entries
 * use the impl path; plain abstract single-target entries use the spec path.
 * This lets collision detection see conflicts across both styles.
 */
function claimantOf(entry: SyncPlanEntry): string {
  return entry.concrete ?? entry.spec;
}

/**
 * Detect target collisions across concrete and abstract specs.
 *
 * Scans all plan entries and groups them by managed target path. Any target
 * claimed by more than one source (concrete impl OR abstract spec) produces a
 * CollisionEntry. If `preferSpec` names a winner for a given target, the
 * collision is marked resolved -- the winner proceeds normally and losers are
 * skipped with audit.
 *
 * Returns:
 *   - `collisions`: list of collision records (one per conflicting target)
 *   - `blockedTargets`: set of target paths with unresolved collisions
 *   - `allowedClaimant`: for resolved collisions, targetPath -> winning claimant
 *     (matches the result of `claimantOf` on the winning entry)
 */
function detectCollisions(
  entries: SyncPlanEntry[],
  preferSpec: Record<string, string>,
): {
  collisions: CollisionEntry[];
  blockedTargets: Set<string>;
  allowedClaimant: Map<string, string>;
} {
  // Group entries by target path, tracking unique claimants per target.
  // Claimant identity = concrete impl path when present, otherwise spec path.
  const byTarget = new Map<string, Set<string>>();
  for (const entry of entries) {
    const key = claimantOf(entry);
    if (!byTarget.has(entry.managed)) byTarget.set(entry.managed, new Set());
    byTarget.get(entry.managed)!.add(key);
  }

  const collisions: CollisionEntry[] = [];
  const blockedTargets = new Set<string>();
  const allowedClaimant = new Map<string, string>();

  for (const [targetPath, claimantSet] of byTarget) {
    if (claimantSet.size < 2) continue; // no collision

    const sorted = [...claimantSet].sort();
    // Safe cast: claimantSet.size >= 2 guarantees at least 2 elements
    const claimants = sorted as unknown as readonly [string, string, ...string[]];
    const winner = preferSpec[targetPath];

    if (winner && claimants.includes(winner)) {
      // Resolved: winner proceeds, losers skipped
      const skippedSpecs = claimants.filter((c) => c !== winner);
      collisions.push({
        status: "resolved",
        targetPath,
        claimants,
        preferSpec: winner,
        skippedSpecs,
      });
      allowedClaimant.set(targetPath, winner);
    } else {
      // Unresolved: block all claimants
      collisions.push({
        status: "unresolved",
        targetPath,
        claimants,
      });
      blockedTargets.add(targetPath);
    }
  }

  return { collisions, blockedTargets, allowedClaimant };
}

function partitionPlan(
  entries: SyncPlanEntry[],
  force: boolean,
  blockedTargets: Set<string>,
  allowedClaimant: Map<string, string>,
): { plan: SyncPlanEntry[]; skipped: SyncPlanEntry[] } {
  const plan: SyncPlanEntry[] = [];
  const skipped: SyncPlanEntry[] = [];

  for (const entry of entries) {
    // Collision filtering: applies regardless of force
    if (blockedTargets.has(entry.managed)) {
      // Unresolved collision -- block this entry
      continue;
    }
    const winner = allowedClaimant.get(entry.managed);
    if (winner !== undefined && claimantOf(entry) !== winner) {
      // Resolved collision, this entry is the loser -- skip it
      continue;
    }

    // Standard partitioning: modified/conflict need coordinator confirmation
    if (!force && (entry.state === "modified" || entry.state === "conflict")) {
      skipped.push(entry);
    } else {
      plan.push(entry);
    }
  }

  return { plan, skipped };
}

function computeParallelBatches(
  entries: SyncPlanEntry[],
  graph: Record<string, string[]>,
  concreteEdges: Readonly<Record<string, readonly string[]>>,
  maxBatchSize: number,
): SyncBatch[] {
  if (maxBatchSize < 1) maxBatchSize = 8;
  if (entries.length === 0) return [];

  // Build subgraph of only entries' specs, merging abstract depends-on edges
  // with concrete extends/concrete-dependencies edges projected to spec space.
  const specSet = new Set(entries.map((e) => e.spec));
  const subgraph: Record<string, string[]> = {};
  for (const spec of specSet) {
    const abstractDeps = (graph[spec] ?? []).filter((d) => specSet.has(d));
    const concreteDeps = (concreteEdges[spec] ?? []).filter((d) =>
      specSet.has(d),
    );
    subgraph[spec] = [...new Set([...abstractDeps, ...concreteDeps])];
  }

  // Kahn's algorithm with depth grouping
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>(); // dep -> dependents

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

  // Group by topological depth
  const depthGroups: string[][] = [];
  let currentLevel: string[] = [];
  for (const [node, deg] of inDegree) {
    if (deg === 0) currentLevel.push(node);
  }
  currentLevel.sort();

  while (currentLevel.length > 0) {
    depthGroups.push(currentLevel);
    const nextLevel: string[] = [];
    for (const node of currentLevel) {
      for (const dependent of adjacency.get(node) ?? []) {
        const newDeg = inDegree.get(dependent)! - 1;
        inDegree.set(dependent, newDeg);
        if (newDeg === 0) {
          nextLevel.push(dependent);
        }
      }
    }
    nextLevel.sort();
    currentLevel = nextLevel;
  }

  // Map entries by spec for lookup
  const entriesBySpec = new Map<string, SyncPlanEntry[]>();
  for (const entry of entries) {
    if (!entriesBySpec.has(entry.spec)) entriesBySpec.set(entry.spec, []);
    entriesBySpec.get(entry.spec)!.push(entry);
  }

  // Split depth groups into batches by maxBatchSize
  const batches: SyncBatch[] = [];
  let batchIndex = 0;

  for (const group of depthGroups) {
    // Collect all entries for specs in this depth group
    const groupEntries: SyncPlanEntry[] = [];
    for (const spec of group) {
      const specEntries = entriesBySpec.get(spec) ?? [];
      groupEntries.push(...specEntries);
    }

    // Split into chunks of maxBatchSize
    for (let i = 0; i < groupEntries.length; i += maxBatchSize) {
      const chunk = groupEntries.slice(i, i + maxBatchSize);
      batches.push({
        batchIndex,
        files: chunk,
        size: chunk.length,
      });
      batchIndex++;
    }
  }

  // Cycle fallback: emit any specs not yet batched
  const emittedSpecs = new Set(depthGroups.flatMap((g) => g));
  const unbatched = entries.filter((e) => !emittedSpecs.has(e.spec));
  if (unbatched.length > 0) {
    for (let i = 0; i < unbatched.length; i += maxBatchSize) {
      const chunk = unbatched.slice(i, i + maxBatchSize);
      batches.push({ batchIndex, files: chunk, size: chunk.length });
      batchIndex++;
    }
  }

  return batches;
}

// -- Exported functions -------------------------------------------------------

/**
 * Plan a deep sync starting from a single spec (or managed file path).
 * Traces all downstream dependents via ripple check and returns a
 * topologically ordered plan.
 */
export async function deepSyncPlan(
  filePath: string,
  cwd: string,
  options?: DeepSyncOptions,
): Promise<DeepSyncResult> {
  const absCwd = resolve(cwd);
  const force = options?.force ?? false;

  // Resolve to spec path
  let specRel = filePath;
  if (!filePath.endsWith(".spec.md")) {
    specRel = `${filePath}.spec.md`;
  }

  // Verify spec exists
  const absSpec = resolve(absCwd, specRel);
  try {
    await stat(absSpec);
  } catch (err: unknown) {
    if (isEnoent(err)) {
      throw new Error(`Spec not found: ${specRel}`);
    }
    throw err;
  }

  // Get freshness and ripple
  const freshness = await checkFreshnessAll(cwd);
  const ripple = await rippleCheck([specRel], cwd);

  // Build freshness state map
  const freshnessMap = new Map<string, FreshnessEntry>();
  for (const entry of freshness.files) {
    freshnessMap.set(entry.managed, entry);
  }

  // Collect plan entries from ripple result, skip fresh ones
  const allEntries: SyncPlanEntry[] = [];
  let freshSkipped = 0;

  for (const re of ripple.layers.code.regenerate) {
    const fe = freshnessMap.get(re.managed);
    const state = fe?.state ?? re.currentState;

    if (state === "fresh") {
      freshSkipped++;
      continue;
    }

    allEntries.push({
      managed: re.managed,
      spec: re.spec,
      state,
      cause: re.cause,
      concrete: re.concrete,
    });
  }

  for (const entry of ripple.layers.code.ghostStale) {
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state: "ghost-stale",
      cause: "ghost-stale",
      concrete: entry.concrete,
    });
  }

  // Collision detection
  const preferSpec = options?.preferSpec ?? {};
  const { collisions, blockedTargets, allowedClaimant } = detectCollisions(
    allEntries,
    preferSpec,
  );

  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedClaimant,
  );

  // Sort plan by ripple's buildOrder
  const orderMap = new Map<string, number>();
  for (let i = 0; i < ripple.buildOrder.length; i++) {
    orderMap.set(ripple.buildOrder[i]!, i);
  }
  plan.sort(
    (a, b) => (orderMap.get(a.spec) ?? Infinity) - (orderMap.get(b.spec) ?? Infinity),
  );

  return {
    trigger: specRel,
    plan,
    skipped,
    collisions,
    stats: {
      totalAffected: allEntries.length + freshSkipped,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped,
    },
    buildOrder: ripple.buildOrder,
  };
}

/**
 * Plan a bulk sync of all stale files in the project.
 * Groups independent specs into parallel batches.
 */
export async function bulkSyncPlan(
  cwd: string,
  options?: BulkSyncOptions,
): Promise<BulkSyncResult> {
  const force = options?.force ?? false;
  const maxBatchSize = options?.maxBatchSize ?? 10;

  const freshness = await checkFreshnessAll(cwd);
  const staleEntries = freshness.files.filter((f) => f.state !== "fresh");

  if (staleEntries.length === 0) {
    return {
      batches: [],
      skipped: [],
      collisions: [],
      stats: {
        totalStale: 0,
        totalBatches: 0,
        toRegenerate: 0,
        skippedNeedConfirm: 0,
        freshSkipped: freshness.files.length,
      },
      buildOrder: [],
    };
  }

  const staleSpecs = staleEntries.map((e) => e.spec);
  const ripple = await rippleCheck(staleSpecs, cwd);

  // Collect entries from ripple.
  // Deduplication is keyed on (managed, concrete) so that multiple concrete
  // specs claiming the same target path are all preserved for collision
  // detection. Within the same concrete spec, the first entry wins.
  const seen = new Set<string>();
  const allEntries: SyncPlanEntry[] = [];

  for (const re of ripple.layers.code.regenerate) {
    const key = `${re.managed}\0${re.concrete ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);

    allEntries.push({
      managed: re.managed,
      spec: re.spec,
      state: re.currentState,
      cause: re.cause,
      concrete: re.concrete,
    });
  }

  for (const entry of ripple.layers.code.ghostStale) {
    const key = `${entry.managed}\0${entry.concrete ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state: "ghost-stale",
      cause: "ghost-stale",
      concrete: entry.concrete,
    });
  }

  // Collision detection
  const preferSpec = options?.preferSpec ?? {};
  const { collisions, blockedTargets, allowedClaimant } = detectCollisions(
    allEntries,
    preferSpec,
  );

  // Partition (applies collision filtering inside)
  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedClaimant,
  );

  // Get DAG for batching
  const dag = await ensureDAG(cwd);
  const batches = computeParallelBatches(
    plan,
    dag.dag,
    ripple.concreteEdges,
    maxBatchSize,
  );

  // Build order from ripple
  const buildOrder = ripple.buildOrder;

  return {
    batches,
    skipped,
    collisions,
    stats: {
      totalStale: staleEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: freshness.files.filter((f) => f.state === "fresh").length,
    },
    buildOrder,
  };
}

/**
 * Plan a resume sync for failed files and their downstream dependents.
 * Excludes files that already succeeded.
 */
export async function resumeSyncPlan(
  cwd: string,
  options: ResumeSyncOptions,
): Promise<ResumeSyncResult> {
  const force = options.force ?? false;
  const maxBatchSize = options.maxBatchSize ?? 10;
  const { failedFiles, succeededFiles } = options;

  const freshness = await checkFreshnessAll(cwd);
  const succeededSet = new Set(succeededFiles);

  // Build state map: managed -> freshness entry
  const freshnessMap = new Map<string, FreshnessEntry>();
  for (const entry of freshness.files) {
    freshnessMap.set(entry.managed, entry);
  }

  // Map failed managed files to their specs
  const failedSpecs: string[] = [];
  for (const file of failedFiles) {
    // Try freshness map first
    const fe = freshnessMap.get(file);
    if (fe) {
      failedSpecs.push(fe.spec);
    } else {
      // Convention fallback: file.ext -> file.ext.spec.md
      const specRel = file.endsWith(".spec.md") ? file : `${file}.spec.md`;
      // Verify spec exists
      const absSpec = resolve(cwd, specRel);
      try {
        await stat(absSpec);
        failedSpecs.push(specRel);
      } catch (err: unknown) {
        if (!isEnoent(err)) throw err;
        // Spec doesn't exist -- skip
      }
    }
  }

  if (failedSpecs.length === 0) {
    return {
      resumedFrom: failedFiles,
      alreadyDone: succeededFiles.length,
      batches: [],
      skipped: [],
      collisions: [],
      stats: {
        totalStale: 0,
        totalBatches: 0,
        toRegenerate: 0,
        skippedNeedConfirm: 0,
        freshSkipped: 0,
      },
      buildOrder: [],
    };
  }

  // Build reverse dep graph and BFS from failed specs to find downstream closure
  const dag = await ensureDAG(cwd);
  const reverseDeps = new Map<string, string[]>();
  for (const [spec, deps] of Object.entries(dag.dag)) {
    for (const dep of deps) {
      if (!reverseDeps.has(dep)) reverseDeps.set(dep, []);
      reverseDeps.get(dep)!.push(spec);
    }
  }

  const failedSet = new Set(failedSpecs);
  const downstreamClosure = new Set(failedSpecs);
  const bfsQueue = [...failedSpecs];

  while (bfsQueue.length > 0) {
    const current = bfsQueue.shift()!;
    const dependents = reverseDeps.get(current) ?? [];
    for (const dep of dependents) {
      if (!downstreamClosure.has(dep)) {
        downstreamClosure.add(dep);
        bfsQueue.push(dep);
      }
    }
  }

  // Collect entries within downstream closure, excluding succeeded files
  const allEntries: SyncPlanEntry[] = [];

  for (const spec of downstreamClosure) {
    const managed = spec.replace(/\.spec\.md$/, "");

    // Skip succeeded files
    if (succeededSet.has(managed)) continue;

    const fe = freshnessMap.get(managed);
    const state = fe?.state ?? "stale";
    if (state === "fresh") continue;
    const cause = failedSet.has(spec) ? "retry" : "downstream";

    allEntries.push({
      managed,
      spec,
      state,
      cause,
    });
  }

  // Collision detection
  const preferSpec = options.preferSpec ?? {};
  const { collisions, blockedTargets, allowedClaimant } = detectCollisions(
    allEntries,
    preferSpec,
  );

  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedClaimant,
  );

  // Batch. Resume doesn't have a ripple result, so we compute one for its
  // failed specs to get concreteEdges.
  const resumeRipple = await rippleCheck(failedSpecs, cwd);
  const batches = computeParallelBatches(
    plan,
    dag.dag,
    resumeRipple.concreteEdges,
    maxBatchSize,
  );

  // Build order via topoSort on the downstream closure subgraph
  const subgraph: Record<string, string[]> = {};
  for (const spec of downstreamClosure) {
    subgraph[spec] = (dag.dag[spec] ?? []).filter((d) =>
      downstreamClosure.has(d),
    );
  }
  let buildOrder: string[];
  try {
    buildOrder = topoSort(subgraph);
  } catch (err: unknown) {
    if (err instanceof Error && err.message.startsWith("Cycle detected")) {
      buildOrder = [...downstreamClosure].sort();
    } else {
      throw err;
    }
  }

  return {
    resumedFrom: failedFiles,
    alreadyDone: succeededFiles.length,
    batches,
    skipped,
    collisions,
    stats: {
      totalStale: allEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: 0,
    },
    buildOrder,
  };
}
