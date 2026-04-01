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
