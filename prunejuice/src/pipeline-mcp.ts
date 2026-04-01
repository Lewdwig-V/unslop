/**
 * Pipeline MCP Handlers
 *
 * Six handler functions that wrap the library API for MCP consumption.
 * Implements the two-call discovery flow for generate (handleGenerate + handleGenerateResume).
 */

import {
  generate,
  distill,
  cover,
  weed,
  verify,
  type DiscoveryHandler,
} from "./api.js";
import type {
  Spec,
  GenerateResult,
  GenerateMcpResult,
  GenerateDiscoveryPending,
  SerialisedPipelineState,
  DiscoveryResolutionInput,
  DiscoveredItem,
  CoverResult,
  DriftReport,
  VerifyResult,
} from "./types.js";

// -- Handler 1: Generate (first call of two-call discovery flow) -------------

export interface GenerateParams {
  spec: Spec;
  cwd: string;
}

export async function handleGenerate(
  params: GenerateParams,
): Promise<GenerateMcpResult | GenerateDiscoveryPending> {
  // eslint-disable-next-line prefer-const -- assigned inside async callback
  let pendingDiscoveries: DiscoveredItem[] | undefined;

  const onDiscovery: DiscoveryHandler = async (discovered) => {
    pendingDiscoveries = [...discovered];
    // Defer all -- client will resolve in the resume call
    return discovered.map((item) => ({
      item: { ...item },
      resolution: "deferred" as const,
    }));
  };

  try {
    const result = await generate(params.spec, params.cwd, { onDiscovery });

    if (
      pendingDiscoveries !== undefined &&
      pendingDiscoveries.length > 0 &&
      pendingDiscoveries.some((d: DiscoveredItem) => d.observation || d.question)
    ) {
      return {
        status: "discovery_pending",
        pipelineState: {
          spec: result.spec,
          concreteSpec: result.concreteSpec,
          behaviourContract: result.concreteSpec.behaviourContract,
          cwd: params.cwd,
        },
        discoveries: pendingDiscoveries,
      };
    }

    return { success: true, result };
  } catch (err: unknown) {
    return {
      success: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// -- Handler 2: Generate Resume (second call of two-call discovery flow) -----

export interface GenerateResumeParams {
  pipelineState: SerialisedPipelineState;
  resolutions: DiscoveryResolutionInput[];
}

export async function handleGenerateResume(
  params: GenerateResumeParams,
): Promise<GenerateMcpResult> {
  const { pipelineState, resolutions } = params;
  let workingSpec = structuredClone(pipelineState.spec);

  for (const resolution of resolutions) {
    if (resolution.action === "promote" && resolution.specAmendment) {
      workingSpec = {
        ...workingSpec,
        ...resolution.specAmendment,
        requirements: [
          ...workingSpec.requirements,
          ...(resolution.specAmendment.requirements ?? []),
        ],
        constraints: [
          ...workingSpec.constraints,
          ...(resolution.specAmendment.constraints ?? []),
        ],
        acceptanceCriteria: [
          ...workingSpec.acceptanceCriteria,
          ...(resolution.specAmendment.acceptanceCriteria ?? []),
        ],
      };
    }
  }

  try {
    const result = await generate(workingSpec, pipelineState.cwd);
    return { success: true, result };
  } catch (err: unknown) {
    return {
      success: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// -- Handler 3: Distill ------------------------------------------------------

export interface DistillParams {
  cwd: string;
}

export async function handleDistill(
  params: DistillParams,
): Promise<{ spec: Spec }> {
  const spec = await distill(params.cwd);
  return { spec };
}

// -- Handler 4: Cover --------------------------------------------------------

export interface CoverParams {
  cwd: string;
  spec?: Spec;
  maxIterations?: number;
}

export async function handleCover(params: CoverParams): Promise<CoverResult> {
  return cover(params.cwd, {
    spec: params.spec,
    maxIterations: params.maxIterations,
  });
}

// -- Handler 5: Weed ---------------------------------------------------------

export interface WeedParams {
  cwd: string;
  spec?: Spec;
}

export async function handleWeed(params: WeedParams): Promise<DriftReport> {
  return weed(params.cwd, { spec: params.spec });
}

// -- Handler 6: Verify -------------------------------------------------------

export interface VerifyParams {
  cwd: string;
  specPath: string;
  managedFilePath: string;
}

export async function handleVerify(
  params: VerifyParams,
): Promise<VerifyResult> {
  return verify(params.cwd, {
    specPath: params.specPath,
    managedFilePath: params.managedFilePath,
  });
}
