import { query } from "@anthropic-ai/claude-agent-sdk";
// SDK expects Record<string, unknown> for schema; we alias for clarity
type JsonSchema = Record<string, unknown>;
import type {
  PipelineState,
  PipelineStage,
  CoordinatorDecision,
  SurvivorClassification,
  SurvivorRouting,
  SaboteurReport,
  MutationResult,
} from "./types.js";
import {
  classifyFreshness,
  actionForState,
  type FreshnessInput,
} from "./hashchain.js";

// -- Agent execution helper --------------------------------------------------

interface AgentQuery {
  systemPrompt: string;
  prompt: string;
  tools: string[];
  cwd: string;
  outputSchema: JsonSchema;
  model?: string;
  maxTurns?: number;
}

export async function queryAgent(params: AgentQuery): Promise<unknown> {
  let result: unknown = undefined;

  for await (const message of query({
    prompt: params.prompt,
    options: {
      systemPrompt: params.systemPrompt,
      allowedTools: params.tools,
      disallowedTools: ["Task", "Agent"],
      cwd: params.cwd,
      model: params.model ?? "claude-sonnet-4-6",
      maxTurns: params.maxTurns ?? 20,
      permissionMode: "bypassPermissions",
      allowDangerouslySkipPermissions: true,
      outputFormat: {
        type: "json_schema",
        schema: params.outputSchema,
      },
      settingSources: [],
      persistSession: false,
    },
  })) {
    if (message.type === "result") {
      if (message.subtype !== "success") {
        const errors =
          "errors" in message ? (message as { errors: string[] }).errors : [];
        throw new Error(
          `Agent failed (${message.subtype}): ${errors.join(", ")}`,
        );
      }
      const success = message as {
        result: string;
        structured_output?: unknown;
      };
      if (success.structured_output !== undefined) {
        result = success.structured_output;
      } else {
        try {
          result = JSON.parse(success.result);
        } catch {
          throw new Error(
            `Agent returned non-JSON output. Raw result (first 500 chars): ${success.result.slice(0, 500)}`,
          );
        }
      }
    }
  }

  if (result === undefined) {
    throw new Error("Agent produced no result");
  }
  return result;
}

// -- Kill rate recomputation (never trust LLM-computed metrics) --------------

export function recomputeKillRate(mutationResults: MutationResult[]): number {
  const killed = mutationResults.filter((m) => m.killed).length;
  const equivalent = mutationResults.filter(
    (m) => !m.killed && m.classification === "equivalent",
  ).length;
  const nonEquivalent = mutationResults.length - equivalent;
  if (nonEquivalent === 0) return 1; // no non-equivalent mutations → vacuously passing
  return killed / nonEquivalent;
}

export function validateSaboteurReport(raw: SaboteurReport): SaboteurReport {
  // Validate: every survivor must have a classification
  for (const m of raw.mutationResults) {
    if (!m.killed && !("classification" in m && m.classification)) {
      throw new Error(
        `Saboteur returned survivor without classification: "${m.mutation}". ` +
          `Every non-killed mutation must be classified as weak_test, spec_gap, or equivalent.`,
      );
    }
  }
  // Recompute kill rate — never trust the LLM's arithmetic
  const recomputed = recomputeKillRate(raw.mutationResults);
  if (Math.abs(recomputed - raw.killRate) > 0.01) {
    process.stderr.write(
      `[pipeline] WARNING: Saboteur reported killRate ${raw.killRate.toFixed(3)} but recomputed ${recomputed.toFixed(3)} — using recomputed value\n`,
    );
  }
  return { ...raw, killRate: recomputed };
}

// -- Survivor routing (pure function, exhaustive switch) --------------------

export function routeSurvivors(
  survivors: Array<{
    mutation: string;
    classification: SurvivorClassification;
  }>,
): SurvivorRouting {
  const masonTargets: string[] = [];
  const architectTargets: string[] = [];
  const skipped: string[] = [];

  for (const { mutation, classification } of survivors) {
    switch (classification) {
      case "weak_test":
        masonTargets.push(mutation);
        break;
      case "spec_gap":
        architectTargets.push(mutation);
        break;
      case "equivalent":
        skipped.push(mutation);
        break;
      default: {
        const _exhaustive: never = classification;
        throw new Error(`Unknown survivor classification: ${_exhaustive}`);
      }
    }
  }

  const totalRouted =
    masonTargets.length + architectTargets.length + skipped.length;
  if (totalRouted !== survivors.length) {
    throw new Error(
      `Routing partition invariant violated: routed ${totalRouted} but received ${survivors.length}`,
    );
  }

  return { masonTargets, architectTargets, skipped };
}

// -- Convergence loop --------------------------------------------------------

export const MAX_CONVERGENCE_ITERATIONS = 3;
const KILL_RATE_THRESHOLD = 0.8;
const ENTROPY_IMPROVEMENT_THRESHOLD = 0.05;

export interface ConvergenceResult {
  converged: boolean;
  action:
    | "proceed"
    | "retry-mason"
    | "retry-architect"
    | "radical-harden"
    | "abort";
  reason: string;
  routing?: SurvivorRouting;
}

export function evaluateConvergence(state: PipelineState): ConvergenceResult {
  const report = state.saboteurReport;
  if (!report) {
    return {
      converged: false,
      action: "abort",
      reason: "No Saboteur report available",
    };
  }

  // Pass: kill rate above threshold and no compliance violations
  if (
    report.killRate >= KILL_RATE_THRESHOLD &&
    report.complianceViolations.length === 0
  ) {
    return {
      converged: true,
      action: "proceed",
      reason: `Kill rate ${(report.killRate * 100).toFixed(1)}% >= ${KILL_RATE_THRESHOLD * 100}%`,
    };
  }

  // Compliance violations with acceptable kill rate — route to Architect (spec-level concern)
  if (
    report.complianceViolations.length > 0 &&
    report.killRate >= KILL_RATE_THRESHOLD
  ) {
    return {
      converged: false,
      action: "retry-architect",
      reason: `${report.complianceViolations.length} compliance violation(s) with kill rate ${(report.killRate * 100).toFixed(1)}%: ${report.complianceViolations.join("; ")}`,
    };
  }

  // Radical hardening already attempted — abort
  if (state.radicalHardeningAttempted) {
    return {
      converged: false,
      action: "abort",
      reason: `Radical hardening already attempted. Final kill rate: ${(report.killRate * 100).toFixed(1)}%`,
    };
  }

  // Max iterations exceeded — one last shot via radical hardening
  if (state.convergenceIteration >= MAX_CONVERGENCE_ITERATIONS) {
    return {
      converged: false,
      action: "radical-harden",
      reason: `${MAX_CONVERGENCE_ITERATIONS} iterations exhausted, attempting radical spec hardening`,
    };
  }

  // Kill rate regression detection: if rate got worse, abort immediately
  if (state.killRateHistory.length >= 2) {
    const prev = state.killRateHistory[state.killRateHistory.length - 2]!;
    const curr = state.killRateHistory[state.killRateHistory.length - 1]!;
    const delta = curr - prev;

    if (delta < 0) {
      return {
        converged: false,
        action: "abort",
        reason: `Kill rate regressed from ${(prev * 100).toFixed(1)}% to ${(curr * 100).toFixed(1)}% — convergence loop is diverging`,
      };
    }

    // Entropy stall: less than 5% improvement
    if (delta < ENTROPY_IMPROVEMENT_THRESHOLD) {
      return {
        converged: false,
        action: "radical-harden",
        reason: `Entropy stall: kill rate improved only ${(delta * 100).toFixed(1)}% (< ${ENTROPY_IMPROVEMENT_THRESHOLD * 100}% threshold)`,
      };
    }
  }

  // Route survivors to responsible agents
  const survivors = report.mutationResults
    .filter((m): m is Extract<MutationResult, { killed: false }> => !m.killed)
    .map((m) => ({ mutation: m.mutation, classification: m.classification }));

  const routing = routeSurvivors(survivors);

  // Decide which agent to retry based on routing
  if (routing.architectTargets.length > 0) {
    return {
      converged: false,
      action: "retry-architect",
      reason: `${routing.architectTargets.length} spec gaps${routing.masonTargets.length > 0 ? ` + ${routing.masonTargets.length} weak tests` : ""}`,
      routing,
    };
  }
  if (routing.masonTargets.length > 0) {
    return {
      converged: false,
      action: "retry-mason",
      reason: `${routing.masonTargets.length} weak tests to strengthen`,
      routing,
    };
  }

  // All survivors are equivalent but kill rate still below threshold
  return {
    converged: false,
    action: "abort",
    reason: `Kill rate ${(report.killRate * 100).toFixed(1)}% below threshold but all survivors classified equivalent — Saboteur classification may be drifting`,
  };
}

// -- Coordinator (hybrid LLM judgment for ambiguous freshness states) --------

const COORDINATOR_PROMPT = `You are the Coordinator — a pipeline supervisor for a multi-agent code generation system.

You are called when the pipeline encounters an ambiguous state that requires judgment:
- A generated file was manually edited ("modified" state)
- Both the spec and code changed independently ("conflict" state)
- An upstream dependency changed ("ghost-stale" state)

Your job is to decide what happens next:
- "proceed": accept the current state and continue
- "retry": re-run from a specific stage
- "abort": stop the pipeline

You MUST respond with a single JSON object:
{
  "action": "proceed" | "retry" | "abort",
  "retryFrom": "architect" | "archaeologist" | "mason" | "builder" | "saboteur" (only if action is "retry"),
  "reason": "brief explanation"
}`;

export async function coordinatorDecision(
  state: PipelineState,
  context: string,
): Promise<CoordinatorDecision> {
  const result = await queryAgent({
    systemPrompt: COORDINATOR_PROMPT,
    prompt: context,
    tools: [],
    cwd: state.cwd,
    model: "claude-sonnet-4-6",
    maxTurns: 1,
    outputSchema: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["proceed", "retry", "abort"] },
        retryFrom: {
          type: "string",
          enum: [
            "architect",
            "archaeologist",
            "discovery-gate",
            "mason",
            "builder",
            "saboteur",
          ],
        },
        reason: { type: "string" },
      },
      required: ["action", "reason"],
    },
  });

  return result as CoordinatorDecision;
}

// -- Freshness check (wires classifier into pipeline decisions) ---------------

export async function checkFreshness(
  input: FreshnessInput,
  state: PipelineState,
): Promise<"skip" | "regenerate" | "abort"> {
  const freshnessState = classifyFreshness(input);
  const action = actionForState(freshnessState);

  switch (action.kind) {
    case "skip":
      return "skip";
    case "regenerate":
      return "regenerate";
    case "error":
      throw new Error(`Freshness error: ${action.description}`);
    case "coordinate": {
      const decision = await coordinatorDecision(
        state,
        `Freshness state: ${freshnessState}. ${action.description}`,
      );
      if (decision.action === "abort") {
        return "abort";
      }
      // Coordinator says proceed or retry — either way, regenerate
      return "regenerate";
    }
  }
}

// -- Pipeline stages (ordered) -----------------------------------------------

export const STAGE_ORDER: PipelineStage[] = [
  "architect",
  "archaeologist",
  "discovery-gate",
  "mason",
  "builder",
  "saboteur",
];

export function nextStage(current: PipelineStage): PipelineStage | null {
  const idx = STAGE_ORDER.indexOf(current);
  return idx < STAGE_ORDER.length - 1 ? STAGE_ORDER[idx + 1]! : null;
}

// -- Stage-running helper (shared by forward pass and convergence retries) ---

export async function runStagesFrom(
  start: PipelineStage,
  state: PipelineState,
  runStage: (stage: PipelineStage, state: PipelineState) => Promise<void>,
): Promise<void> {
  const startIdx = STAGE_ORDER.indexOf(start);
  for (const stage of STAGE_ORDER.slice(startIdx)) {
    await runStage(stage, state);
  }
}
