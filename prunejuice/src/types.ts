/**
 * Artifacts produced and consumed by pipeline stages.
 * Each agent sees only the artifacts listed in its StageInput type.
 */

// -- Branded types for hash strings ------------------------------------------

declare const __brand: unique symbol;
type Brand<T, B extends string> = T & { readonly [__brand]: B };

/** SHA-256 truncated to 12 hex characters. Prevents accidental string interchange. */
export type TruncatedHash = Brand<string, "TruncatedHash">;

// -- Core artifacts ----------------------------------------------------------

export interface Spec {
  intent: string;
  requirements: string[];
  constraints: string[];
  acceptanceCriteria: string[];
}

export interface ConcreteSpec {
  existingPatterns: string[];
  integrationPoints: string[];
  fileTargets: string[];
  strategyProjection: string;
  refinedSpec: Spec;
  behaviourContract: BehaviourContract;
  discovered: DiscoveredItem[]; // correctness requirements the spec doesn't cover
}

export interface BehaviourContract {
  name: string;
  preconditions: string[];
  postconditions: string[];
  invariants: string[];
  scenarios: Array<{
    given: string;
    when: string;
    then: string;
  }>;
}

export interface GeneratedTests {
  testCode: string;
  testFilePaths: string[];
  coverageTargets: string[];
}

export interface Implementation {
  files: Array<{
    path: string;
    content: string;
  }>;
  summary: string;
}

// -- Mutation results (discriminated union) -----------------------------------

export type SurvivorClassification = "weak_test" | "spec_gap" | "equivalent";

export type MutationResult =
  | { mutation: string; killed: true; details: string }
  | {
      mutation: string;
      killed: false;
      details: string;
      classification: SurvivorClassification;
    };

export interface SaboteurReport {
  mutationResults: MutationResult[];
  complianceViolations: string[];
  verdict: "pass" | "fail";
  recommendations: string[];
  killRate: number; // 0-1, adjusted (excluding equivalent) — recomputed by pipeline, not trusted from LLM
}

// -- Discovery gate ----------------------------------------------------------

export type DiscoveryResolution = "promoted" | "dismissed" | "deferred";

export interface DiscoveredItem {
  title: string;
  observation: string;
  question: string;
  resolution?: DiscoveryResolution; // populated after discovery gate
}

export interface ResolvedDiscovery {
  item: DiscoveredItem;
  resolution: DiscoveryResolution;
}

// -- Convergence loop routing ------------------------------------------------

export interface SurvivorRouting {
  masonTargets: string[]; // weak_test → Mason strengthens assertions
  architectTargets: string[]; // spec_gap → Architect enriches behaviour contract
  skipped: string[]; // equivalent → no action
}

// -- Pipeline phase names (typed union for LogFn) ----------------------------

export type PipelinePhase =
  | "distill"
  | "elicit"
  | "generate"
  | "convergence"
  | "cover"
  | "weed"
  | "verify"
  | "takeover"
  | "change"
  | "sync"
  | "discovery-gate";

// -- Phase result types ------------------------------------------------------

export interface DriftLocation {
  filePath: string;
  detail?: string; // function name, line range, etc.
}

export interface DriftFinding {
  location: DriftLocation;
  specIntent: string;
  codeReality: string;
  severity: "high" | "medium" | "low";
  recommendation: string;
}

export interface DriftReport {
  findings: DriftFinding[];
  specPath: string;
  filesChecked: string[];
  overallAssessment: string;
  hasDrift: boolean; // derived: findings.length > 0
}

export interface GenerateResult {
  spec: Spec;
  concreteSpec: ConcreteSpec;
  tests: GeneratedTests;
  implementation: Implementation;
  saboteurReport: SaboteurReport;
  converged: boolean;
  convergenceIterations: number;
  killRateHistory: number[];
}

export interface CoverResult {
  originalKillRate: number;
  finalKillRate: number;
  strengtheningIterations: number;
  killRateHistory: number[];
  tests: GeneratedTests;
  report: SaboteurReport;
}

// -- Information boundary types (what each agent receives) -------------------

export interface ArchitectInput {
  userIntent: string;
}

export interface ArchaeologistInput {
  spec: Spec;
  cwd: string;
}

export interface MasonInput {
  behaviourContract: BehaviourContract;
}

export interface BuilderInput {
  spec: Spec;
  concreteSpec: ConcreteSpec;
  tests: GeneratedTests;
  cwd: string;
}

export interface SaboteurInput {
  spec: Spec;
  tests: GeneratedTests;
  implementation: Implementation;
  cwd: string;
}

// -- Pipeline state accumulator ----------------------------------------------

export interface PipelineState {
  userIntent: string;
  cwd: string;
  spec?: Spec;
  concreteSpec?: ConcreteSpec;
  behaviourContract?: BehaviourContract;
  tests?: GeneratedTests;
  implementation?: Implementation;
  saboteurReport?: SaboteurReport;
  // Convergence loop tracking
  convergenceIteration: number;
  killRateHistory: number[];
  radicalHardeningAttempted: boolean;
}

export type PipelineStage =
  | "architect"
  | "archaeologist"
  | "discovery-gate"
  | "mason"
  | "builder"
  | "saboteur";

export interface CoordinatorDecision {
  action: "proceed" | "retry" | "abort";
  retryFrom?: PipelineStage;
  reason: string;
}

// -- DAG cache ----------------------------------------------------------------

export interface DAGCache {
  /** spec_path (relative to cwd) -> list of spec paths it depends on */
  dag: Record<string, string[]>;
  /** spec_path -> content hash of the spec file */
  manifest: Record<string, TruncatedHash>;
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
  currentState: "fresh" | "stale" | "modified" | "conflict" | "pending" | "structural" | "ghost-stale" | "test-drifted" | "new" | "error";
  cause: "direct" | "transitive" | "ghost-stale";
  language?: string;
  error?: string;
  ghostSource?: string;
  diagnostic?: GhostStaleDiagnostic;
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

// -- Sync planning results ----------------------------------------------------

export interface SyncPlanEntry {
  managed: string;
  spec: string;
  state: string;
  cause: "direct" | "transitive" | "ghost-stale" | "retry" | "downstream";
  concrete?: string;
}

export interface SyncBatch {
  batchIndex: number;
  files: SyncPlanEntry[];
  size: number;
}

export interface DeepSyncResult {
  trigger: string;
  plan: SyncPlanEntry[];
  skipped: SyncPlanEntry[];
  collisions: CollisionEntry[];
  stats: {
    totalAffected: number;
    toRegenerate: number;
    skippedNeedConfirm: number;
    freshSkipped: number;
  };
  buildOrder: string[];
}

export interface BulkSyncResult {
  batches: SyncBatch[];
  skipped: SyncPlanEntry[];
  collisions: CollisionEntry[];
  stats: {
    totalStale: number;
    totalBatches: number;
    toRegenerate: number;
    skippedNeedConfirm: number;
    freshSkipped: number;
  };
  buildOrder: string[];
}

export interface ResumeSyncResult extends BulkSyncResult {
  resumedFrom: string[];
  alreadyDone: number;
}

export interface SpecDiffResult {
  changedSections: string[];
  unchangedSections: string[];
}

// -- Pipeline MCP types -------------------------------------------------------

export interface VerifyResult {
  status: "pass" | "fail";
  killRate: number;
  mutationResults: MutationResult[];
  complianceViolations: string[];
}

/**
 * Serialised pipeline state for the two-call discovery flow.
 * Round-trips through the MCP client as JSON.
 * Contains everything needed to resume from Mason onward.
 */
export interface SerialisedPipelineState {
  spec: Spec;
  concreteSpec: ConcreteSpec;
  behaviourContract: BehaviourContract;
  cwd: string;
}

export interface GenerateMcpResult {
  success: boolean;
  result?: GenerateResult;
  error?: string;
}

export interface GenerateDiscoveryPending {
  status: "discovery_pending";
  pipelineState: SerialisedPipelineState;
  discoveries: DiscoveredItem[];
}

export interface DiscoveryResolutionInput {
  discoveryId: string;
  action: "promote" | "dismiss" | "defer";
  specAmendment?: Partial<Spec>;
}

// -- Concrete manifest types --------------------------------------------------

/**
 * Sentinel hash indicating a dep that didn't exist on disk at manifest
 * computation time. Distinguishable from real hashes because SHA-256/12
 * collision with all-zeros is astronomically unlikely (~2^-48).
 */
export const MISSING_SENTINEL = "000000000000" as TruncatedHash;

export interface ManifestDiff {
  readonly added: readonly string[];
  readonly removed: readonly string[];
  readonly changed: readonly string[];
}

export interface GhostStaleDiagnostic {
  /** The dep whose hash changed between stored manifest and current disk state. */
  readonly changedSpec: string;
  /** Current hash of the changed spec (MISSING_SENTINEL if the file was deleted). */
  readonly changeHash: TruncatedHash;
  /**
   * Chain from `changedSpec` to the deepest changed upstream (the root cause).
   * chain[0] === changedSpec. chain[chain.length-1] is the root cause.
   * Only contains deps that actually changed -- unchanged intermediaries are skipped.
   */
  readonly chain: readonly string[];
  /** Full structural diff of the manifest (same instance shared across all diagnostics from one call). */
  readonly manifestDiff: ManifestDiff;
}

// -- Inheritance flattening types --------------------------------------------

export type SectionMergeRule = "strict_child_only" | "additive" | "overridable";

export interface FlattenedSection {
  /** Resolved section content after merging. */
  readonly content: string;
  /**
   * Which spec in the chain provided this section.
   * For "overridable" sections, the most specific spec that defines the section.
   * For "additive" sections, the spec of the most specific contributor.
   * For "strict_child_only" sections, always the child.
   */
  readonly source: string;
  readonly rule: SectionMergeRule;
}

export interface FlattenedConcreteSpec {
  readonly specPath: string;
  /** Chain from child to root parent: [child, parent, grandparent, ...] */
  readonly chain: readonly string[];
  /** Resolved sections keyed by heading name (e.g. "Strategy", "Pattern"). */
  readonly sections: ReadonlyMap<string, FlattenedSection>;
}

// -- Collision detection types -----------------------------------------------

export interface CollisionEntry {
  readonly status: "collision";
  /** The target file path that multiple specs claim. */
  readonly targetPath: string;
  /** Concrete spec paths that claim this target (at least 2). */
  readonly claimants: readonly string[];
  /** When set (via preferSpec + force), names the winning claimant. */
  readonly preferSpec?: string;
  /** When preferSpec is set, the losing claimants logged for audit. */
  readonly skippedSpecs?: readonly string[];
}
