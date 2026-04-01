/**
 * Prunejuice Library API
 *
 * Five phases (standalone) + three orchestrators (composed).
 * Each phase is an async function that can be called independently.
 * This is the surface that unslop (or any other caller) imports.
 */

import { runArchitect } from "./agents/architect.js";
import {
  runArchaeologist,
  runDistiller,
  runWeeder,
} from "./agents/archaeologist.js";
import { runMason } from "./agents/mason.js";
import { runBuilder } from "./agents/builder.js";
import { runSaboteur } from "./agents/saboteur.js";
import {
  evaluateConvergence,
  validateSaboteurReport,
  routeSurvivors,
  MAX_CONVERGENCE_ITERATIONS,
} from "./pipeline.js";
import {
  ensureStore,
  savePipelineState,
  loadPipelineState,
  writeImplementationFiles,
  writeTestFiles,
  loadSpec,
  saveSpec,
  saveBehaviourContract,
  saveConcreteSpec,
  saveTests,
  saveSaboteurReport,
} from "./store.js";
import type {
  Spec,
  ConcreteSpec,
  BehaviourContract,
  GeneratedTests,
  Implementation,
  SaboteurReport,
  DriftReport,
  GenerateResult,
  CoverResult,
  PipelineState,
  PipelinePhase,
  MutationResult,
  DiscoveredItem,
  DiscoveryResolution,
  ResolvedDiscovery,
  VerifyResult,
} from "./types.js";

// -- Logging -----------------------------------------------------------------

export type LogFn = (stage: PipelinePhase, msg: string) => void;

export const defaultLog: LogFn = (stage, msg) => {
  const ts = new Date().toISOString().slice(11, 19);
  process.stderr.write(`[${ts}] [${stage}] ${msg}\n`);
};

// -- Pipeline invariant helper -----------------------------------------------

export function requireDefined<T>(
  value: T | undefined,
  name: string,
  phase: string,
): T {
  if (value === undefined) {
    throw new Error(`${phase} requires ${name}, but it is undefined.`);
  }
  return value;
}

function currentTimestamp(): string {
  return new Date().toISOString();
}

// -- Discovery handler (return-value protocol) -------------------------------

/**
 * Called when the Archaeologist surfaces discovered items.
 * Must return a resolution for each item.
 * Input is readonly — mutations are not observed.
 */
export type DiscoveryHandler = (
  discovered: ReadonlyArray<DiscoveredItem>,
) => Promise<ResolvedDiscovery[]>;

export const defaultDiscoveryHandler: DiscoveryHandler = async (discovered) => {
  return discovered.map((item) => {
    process.stderr.write(
      `[discovery-gate] WARNING: "${item.title}" auto-deferred (no discovery handler provided)\n`,
    );
    return { item, resolution: "deferred" as const };
  });
};

function applyDiscoveryResolutions(
  discovered: DiscoveredItem[],
  resolutions: ResolvedDiscovery[],
): void {
  for (const { item, resolution } of resolutions) {
    item.resolution = resolution;
  }
  // Validate all items were resolved
  for (const item of discovered) {
    if (item.resolution === undefined) {
      throw new Error(
        `Discovery item "${item.title}" was not resolved by the handler. ` +
          `Every discovered item must have a resolution.`,
      );
    }
  }
}

// -- Constants ---------------------------------------------------------------

export const COVER_KILL_RATE_THRESHOLD = 0.8;

// -- Phase 1: Distill --------------------------------------------------------

/**
 * Infer a spec from existing code.
 * Archaeologist reads the codebase and produces a Spec.
 */
export async function distill(
  cwd: string,
  options: { log?: LogFn } = {},
): Promise<Spec> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  log("distill", "Inferring specification from existing code...");
  const spec = await runDistiller(cwd);
  await saveSpec(cwd, spec);
  log(
    "distill",
    `Inferred spec with ${spec.requirements.length} requirements.`,
  );

  return spec;
}

// -- Phase 2: Elicit ---------------------------------------------------------

/**
 * Create or amend a spec via the Architect agent.
 *
 * For non-interactive use, pass a string intent. The Architect produces a
 * spec in a single pass. If existingSpec is provided, the Architect amends it.
 */
export async function elicit(
  intent: string,
  cwd: string,
  options: {
    existingSpec?: Spec;
    log?: LogFn;
  } = {},
): Promise<Spec> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  log("elicit", `Eliciting specification from intent: "${intent}"`);

  const prompt = options.existingSpec
    ? `Amend the following specification based on this new intent: "${intent}"\n\nExisting spec:\n${JSON.stringify(options.existingSpec, null, 2)}`
    : intent;

  const spec = await runArchitect(prompt, cwd);
  await saveSpec(cwd, spec);
  log("elicit", `Produced spec with ${spec.requirements.length} requirements.`);

  return spec;
}

// -- Phase 3: Generate -------------------------------------------------------

/**
 * Tests-then-implementation from spec, with convergence loop.
 * Clones the spec before mutation — the caller's original is never modified.
 */
export async function generate(
  spec: Spec,
  cwd: string,
  options: {
    log?: LogFn;
    onDiscovery?: DiscoveryHandler;
    /** Pre-resolved discoveries from a prior generate call (keyed by title). */
    priorResolutions?: Map<string, DiscoveryResolution>;
  } = {},
): Promise<GenerateResult> {
  const log = options.log ?? defaultLog;
  const onDiscovery = options.onDiscovery ?? defaultDiscoveryHandler;
  const priorResolutions = options.priorResolutions;
  await ensureStore(cwd);

  // Clone spec to avoid mutating the caller's object during convergence
  const workingSpec = structuredClone(spec);

  const state: PipelineState = {
    userIntent: workingSpec.intent,
    cwd,
    spec: workingSpec,
    convergenceIteration: 0,
    killRateHistory: [],
    radicalHardeningAttempted: false,
  };

  // Stage 0: Archaeologist → concrete spec + behaviour contract
  log("generate", "Archaeologist analyzing codebase...");
  state.concreteSpec = await runArchaeologist(workingSpec, cwd);
  state.behaviourContract = structuredClone(
    state.concreteSpec.behaviourContract,
  );
  log(
    "generate",
    `Strategy targets ${state.concreteSpec.fileTargets.length} files. Contract: ${state.concreteSpec.behaviourContract.name}`,
  );

  // Stage 0b: Discovery gate
  if (state.concreteSpec.discovered.length > 0) {
    // Auto-resolve discoveries that have prior resolutions
    if (priorResolutions && priorResolutions.size > 0) {
      const unresolved: DiscoveredItem[] = [];
      for (const item of state.concreteSpec.discovered) {
        const prior = priorResolutions.get(item.title);
        if (prior) {
          item.resolution = prior;
          log(
            "discovery-gate",
            `"${item.title}" auto-resolved as ${prior} (prior resolution)`,
          );
        } else {
          unresolved.push(item);
        }
      }

      // Only invoke handler for genuinely new discoveries
      if (unresolved.length > 0) {
        log(
          "generate",
          `${unresolved.length} new discovered item(s) — invoking discovery handler.`,
        );
        const resolutions = await onDiscovery(unresolved);
        applyDiscoveryResolutions(unresolved, resolutions);
      }
    } else {
      log(
        "generate",
        `${state.concreteSpec.discovered.length} discovered item(s) — invoking discovery handler.`,
      );
      const resolutions = await onDiscovery(state.concreteSpec.discovered);
      applyDiscoveryResolutions(state.concreteSpec.discovered, resolutions);
    }
  }

  // Run Mason → Builder → Saboteur
  await runTestBuildVerify(state, log);

  // Convergence loop (flat — no recursion)
  let converged = false;
  while (true) {
    const convergence = evaluateConvergence(state);
    log("convergence", `${convergence.action} — ${convergence.reason}`);

    if (convergence.converged) {
      converged = true;
      break;
    }

    if (convergence.action === "abort") {
      throw new Error(`Convergence failed: ${convergence.reason}`);
    }

    state.convergenceIteration++;

    if (convergence.action === "radical-harden") {
      state.radicalHardeningAttempted = true;
      log(
        "convergence",
        "Radical spec hardening — re-running with mutation feedback.",
      );
      if (state.saboteurReport) {
        const survivorSummary = state.saboteurReport.mutationResults
          .filter((m) => !m.killed)
          .map(
            (m) =>
              `- ${m.mutation}: ${m.details} (${!m.killed ? m.classification : "killed"})`,
          )
          .join("\n");
        workingSpec.constraints.push(
          `[MUTATION FEEDBACK] Survivors:\n${survivorSummary}`,
        );
      }
      // Re-run Archaeologist → Mason → Builder → Saboteur
      state.concreteSpec = await runArchaeologist(workingSpec, cwd);
      state.behaviourContract = structuredClone(
        state.concreteSpec.behaviourContract,
      );
      await runTestBuildVerify(state, log);
      continue;
    }

    if (convergence.action === "retry-architect") {
      log(
        "convergence",
        `Re-running from Archaeologist (iteration ${state.convergenceIteration}/${MAX_CONVERGENCE_ITERATIONS})`,
      );
      if (convergence.routing) {
        workingSpec.constraints.push(
          `[SPEC GAP FEEDBACK] Under-constrained:\n- ${convergence.routing.architectTargets.join("\n- ")}`,
        );
      }
      // Re-run Archaeologist → Mason → Builder → Saboteur
      state.concreteSpec = await runArchaeologist(workingSpec, cwd);
      state.behaviourContract = structuredClone(
        state.concreteSpec.behaviourContract,
      );
      await runTestBuildVerify(state, log);
      continue;
    }

    if (convergence.action === "retry-mason") {
      log(
        "convergence",
        `Re-running from Mason (iteration ${state.convergenceIteration}/${MAX_CONVERGENCE_ITERATIONS})`,
      );
      if (convergence.routing) {
        const bc = requireDefined(
          state.behaviourContract,
          "behaviourContract",
          "retry-mason",
        );
        bc.invariants.push(
          ...convergence.routing.masonTargets.map(
            (t) => `[STRENGTHEN] Test gap: ${t}`,
          ),
        );
      }
      // Re-run Mason → Builder → Saboteur (reads current state.concreteSpec, no stale closure)
      await runTestBuildVerify(state, log);
      continue;
    }
  }

  return {
    spec: workingSpec,
    concreteSpec: requireDefined(
      state.concreteSpec,
      "concreteSpec",
      "generate",
    ),
    tests: requireDefined(state.tests, "tests", "generate"),
    implementation: requireDefined(
      state.implementation,
      "implementation",
      "generate",
    ),
    saboteurReport: requireDefined(
      state.saboteurReport,
      "saboteurReport",
      "generate",
    ),
    converged,
    convergenceIterations: state.convergenceIteration,
    killRateHistory: state.killRateHistory,
  };
}

// -- Mason → Builder → Saboteur helper (shared by generate and convergence) --

async function runTestBuildVerify(
  state: PipelineState,
  log: LogFn,
): Promise<void> {
  const ts = currentTimestamp();
  const behaviourContract = requireDefined(
    state.behaviourContract,
    "behaviourContract",
    "runTestBuildVerify",
  );
  // Always read concreteSpec from state — never from a closure capture
  const concreteSpec = requireDefined(
    state.concreteSpec,
    "concreteSpec",
    "runTestBuildVerify",
  );

  // Persist artifacts before writing managed files (managed file headers
  // hash the stored artifact, so the artifact must exist on disk first).
  await saveBehaviourContract(state.cwd, behaviourContract);
  await saveConcreteSpec(state.cwd, concreteSpec);

  // Mason → tests (Chinese Wall)
  log("generate", "Mason generating tests from behaviour contract...");
  state.tests = await runMason(behaviourContract);
  await writeTestFiles(state.cwd, state.tests, ts);
  log(
    "generate",
    `Generated ${state.tests.testFilePaths.length} test file(s).`,
  );

  // Builder → implementation
  log("generate", "Builder implementing from spec + tests...");
  state.implementation = await runBuilder(
    concreteSpec.refinedSpec,
    concreteSpec,
    state.tests,
    state.cwd,
  );
  await writeImplementationFiles(state.cwd, state.implementation, ts);
  log(
    "generate",
    `Wrote ${state.implementation.files.length} file(s): ${state.implementation.summary}`,
  );

  // Saboteur → mutation testing
  log("generate", "Saboteur running mutation testing...");
  const rawReport = await runSaboteur(
    concreteSpec.refinedSpec,
    state.tests,
    state.implementation,
    state.cwd,
  );
  state.saboteurReport = validateSaboteurReport(rawReport);
  state.killRateHistory.push(state.saboteurReport.killRate);
  log(
    "generate",
    `Kill rate: ${(state.saboteurReport.killRate * 100).toFixed(1)}%`,
  );

  await savePipelineState(state.cwd, state);
}

// -- Phase 4: Cover ----------------------------------------------------------

/**
 * Find and fill gaps in test coverage via targeted mutation testing.
 * Runs Saboteur to find weak tests, then Mason to strengthen them.
 * Persists updated tests, contract, and reports after each iteration.
 */
export async function cover(
  cwd: string,
  options: {
    spec?: Spec;
    log?: LogFn;
    maxIterations?: number;
  } = {},
): Promise<CoverResult> {
  const log = options.log ?? defaultLog;
  const maxIterations = options.maxIterations ?? MAX_CONVERGENCE_ITERATIONS;
  await ensureStore(cwd);

  // Load existing state
  const existing = await loadPipelineState(cwd);
  const spec =
    options.spec ??
    requireDefined(
      existing.spec,
      "spec",
      "cover (load from store or pass explicitly)",
    );
  const concreteSpec = requireDefined(
    existing.concreteSpec,
    "concreteSpec",
    "cover",
  );
  let tests = requireDefined(existing.tests, "tests", "cover");
  const implementation = requireDefined(
    existing.implementation,
    "implementation",
    "cover",
  );

  // Clone behaviour contract to avoid mutating loaded state
  let behaviourContract = structuredClone(
    requireDefined(existing.behaviourContract, "behaviourContract", "cover"),
  );

  // Initial Saboteur run
  log("cover", "Running Saboteur to find test coverage gaps...");
  let rawReport = await runSaboteur(
    concreteSpec.refinedSpec,
    tests,
    implementation,
    cwd,
  );
  let report = validateSaboteurReport(rawReport);
  const originalKillRate = report.killRate;
  const killRateHistory = [report.killRate];
  log("cover", `Initial kill rate: ${(originalKillRate * 100).toFixed(1)}%`);

  let iterations = 0;

  while (
    report.killRate < COVER_KILL_RATE_THRESHOLD &&
    iterations < maxIterations
  ) {
    const survivors = report.mutationResults
      .filter((m): m is Extract<MutationResult, { killed: false }> => !m.killed)
      .map((m) => ({ mutation: m.mutation, classification: m.classification }));

    const routing = routeSurvivors(survivors);

    if (routing.masonTargets.length === 0) {
      log(
        "cover",
        "No weak_test survivors — cannot improve further via test strengthening alone.",
      );
      break;
    }

    iterations++;
    log(
      "cover",
      `Iteration ${iterations}: strengthening ${routing.masonTargets.length} weak tests.`,
    );

    // Enrich behaviour contract with feedback
    behaviourContract.invariants.push(
      ...routing.masonTargets.map((t) => `[STRENGTHEN] Test gap: ${t}`),
    );

    // Persist enriched contract BEFORE writing test files (test headers
    // hash the stored contract artifact, so it must be current on disk).
    await saveBehaviourContract(cwd, behaviourContract);

    // Re-run Mason
    const ts = currentTimestamp();
    tests = await runMason(behaviourContract);
    await writeTestFiles(cwd, tests, ts);
    await saveTests(cwd, tests);

    // Re-run Saboteur
    rawReport = await runSaboteur(spec, tests, implementation, cwd);
    report = validateSaboteurReport(rawReport);
    killRateHistory.push(report.killRate);
    await saveSaboteurReport(cwd, report);

    log("cover", `Kill rate: ${(report.killRate * 100).toFixed(1)}%`);
  }

  return {
    originalKillRate,
    finalKillRate: report.killRate,
    strengtheningIterations: iterations,
    killRateHistory,
    tests,
    report,
  };
}

// -- Phase 5: Weed -----------------------------------------------------------

/**
 * Detect intent drift between spec and code.
 */
export async function weed(
  cwd: string,
  options: {
    spec?: Spec;
    log?: LogFn;
  } = {},
): Promise<DriftReport> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  const spec = options.spec ?? (await loadSpec(cwd));
  if (!spec) {
    throw new Error(
      "weed requires a spec. Run distill or elicit first, or pass spec explicitly.",
    );
  }

  log("weed", "Detecting intent drift between spec and code...");
  const report = await runWeeder(spec, cwd);
  log(
    "weed",
    `Found ${report.findings.length} drift finding(s). Assessment: ${report.overallAssessment}`,
  );

  return report;
}

// -- Verify (single-file Saboteur) -------------------------------------------

/**
 * Run Saboteur verification on a single managed file.
 * Loads existing pipeline artifacts (spec, tests, implementation) from the store.
 * Returns a VerifyResult with kill rate, mutation results, and compliance violations.
 */
export async function verify(
  cwd: string,
  options: {
    specPath: string;
    managedFilePath: string;
    log?: LogFn;
  },
): Promise<VerifyResult> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  const existing = await loadPipelineState(cwd);
  const spec = requireDefined(existing.spec, "spec", "verify");
  const tests = requireDefined(existing.tests, "tests", "verify");
  const implementation = requireDefined(
    existing.implementation,
    "implementation",
    "verify",
  );

  log("verify", `Verifying ${options.managedFilePath} against ${options.specPath}...`);

  const rawReport = await runSaboteur(spec, tests, implementation, cwd);
  const report = validateSaboteurReport(rawReport);

  return {
    status: report.verdict === "pass" ? "pass" : "fail",
    killRate: report.killRate,
    mutationResults: report.mutationResults,
    complianceViolations: report.complianceViolations,
  };
}

// -- Archaeologist-only phase (for MCP two-call discovery flow) ---------------

/**
 * Run just the Archaeologist stage and return the ConcreteSpec.
 * Used by the MCP generate handler to check for discoveries before
 * committing to the full pipeline.
 */
export async function archaeologistPhase(
  spec: Spec,
  cwd: string,
  options: { log?: LogFn } = {},
): Promise<ConcreteSpec> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  log("generate", "Archaeologist analyzing codebase...");
  const concreteSpec = await runArchaeologist(spec, cwd);
  await saveConcreteSpec(cwd, concreteSpec);
  await saveBehaviourContract(cwd, concreteSpec.behaviourContract);
  return concreteSpec;
}

// -- Orchestrator: Takeover --------------------------------------------------

/**
 * Bring existing code under management.
 * distill → elicit (optional, if intent provided) → generate
 */
export async function takeover(
  cwd: string,
  options: {
    intent?: string;
    log?: LogFn;
    onDiscovery?: DiscoveryHandler;
  } = {},
): Promise<GenerateResult> {
  const log = options.log ?? defaultLog;

  log("takeover", "Phase 1: Distilling spec from existing code...");
  let spec = await distill(cwd, { log });

  if (options.intent) {
    log("takeover", "Phase 2: Refining spec with user intent...");
    spec = await elicit(options.intent, cwd, { existingSpec: spec, log });
  }

  log("takeover", "Phase 3: Generating tests + implementation from spec...");
  return generate(spec, cwd, { log, onDiscovery: options.onDiscovery });
}

// -- Orchestrator: Change ----------------------------------------------------

/**
 * Record a change and regenerate.
 * elicit (amend existing spec) → generate
 */
export async function change(
  intent: string,
  cwd: string,
  options: {
    log?: LogFn;
    onDiscovery?: DiscoveryHandler;
  } = {},
): Promise<GenerateResult> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  const existingSpec = await loadSpec(cwd);

  if (!existingSpec) {
    log(
      "change",
      "WARNING: No existing spec found. Creating a new spec instead of amending. Run 'distill' first to infer a spec from existing code.",
    );
  }

  log("change", `Amending spec with intent: "${intent}"`);
  const spec = await elicit(intent, cwd, {
    existingSpec: existingSpec ?? undefined,
    log,
  });

  log("change", "Generating from amended spec...");
  return generate(spec, cwd, { log, onDiscovery: options.onDiscovery });
}

// -- Orchestrator: Sync ------------------------------------------------------

/**
 * Regenerate stale files.
 * Loads existing spec and state, runs generate if anything is stale.
 */
export async function sync(
  cwd: string,
  options: {
    log?: LogFn;
    onDiscovery?: DiscoveryHandler;
  } = {},
): Promise<GenerateResult> {
  const log = options.log ?? defaultLog;
  await ensureStore(cwd);

  const spec = await loadSpec(cwd);
  if (!spec) {
    throw new Error(
      "sync requires an existing spec. Run distill, elicit, or takeover first.",
    );
  }

  log("sync", "Regenerating from existing spec...");
  return generate(spec, cwd, { log, onDiscovery: options.onDiscovery });
}

// -- Re-exports for library consumers ----------------------------------------

export type {
  Spec,
  ConcreteSpec,
  BehaviourContract,
  GeneratedTests,
  Implementation,
  SaboteurReport,
  DriftReport,
  DriftFinding,
  DriftLocation,
  GenerateResult,
  CoverResult,
  DiscoveredItem,
  DiscoveryResolution,
  ResolvedDiscovery,
  MutationResult,
  SurvivorClassification,
  TruncatedHash,
  PipelinePhase,
  VerifyResult,
} from "./types.js";
