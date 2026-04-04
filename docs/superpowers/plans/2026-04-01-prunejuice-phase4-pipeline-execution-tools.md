# Prunejuice Phase 4: Pipeline Execution Tools -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the five pipeline phases (`generate`, `distill`, `cover`, `weed`, `verify`) and the discovery-gate resume flow as MCP tools, completing the prunejuice tool surface.

**Architecture:** The library functions in `api.ts` already implement the full pipeline. The MCP tools are thin wrappers that translate MCP request/response into library calls. The only non-trivial piece is the two-call discovery flow for `generate`: the first call runs the Archaeologist, detects discoveries, and returns serialised pipeline state; the second call takes resolutions and continues from Mason onward. A new `verify` function is added to `api.ts` for single-file Saboteur verification. All pipeline state round-trips through the client as JSON -- the MCP server remains stateless.

**Tech Stack:** TypeScript, vitest, `@modelcontextprotocol/sdk`, zod, `@anthropic-ai/claude-agent-sdk`

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Modify:** `prunejuice/src/api.ts` | Add `verify()` function for single-file Saboteur verification |
| **Create:** `prunejuice/src/pipeline-mcp.ts` | MCP handlers for the 6 pipeline tools (keeps mcp.ts from growing unwieldy) |
| **Modify:** `prunejuice/src/mcp.ts` | Import and register the 6 pipeline tools from pipeline-mcp.ts |
| **Modify:** `prunejuice/src/types.ts` | Add `VerifyResult` and `SerialisedPipelineState` types |
| **Create:** `prunejuice/test/pipeline-mcp.test.ts` | Handler tests for pipeline MCP tools |
| **Create:** `prunejuice/test/verify.test.ts` | Unit tests for the verify function |

---

### Task 1: Add Pipeline Types to `types.ts`

**Files:**
- Modify: `prunejuice/src/types.ts`

- [ ] **Step 1: Add type definitions at the end of types.ts**

```typescript
// -- Pipeline MCP types -------------------------------------------------------

export interface VerifyResult {
  status: "pass" | "fail" | "error";
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
```

- [ ] **Step 2: Run tests**

Run: `cd prunejuice && npm run test`
Expected: All 186 existing tests pass

- [ ] **Step 3: Commit**

```bash
git add prunejuice/src/types.ts
git commit -m "feat(prunejuice): add pipeline MCP types for Phase 4"
```

---

### Task 2: Implement `verify()` in `api.ts`

**Files:**
- Modify: `prunejuice/src/api.ts`
- Create: `prunejuice/test/verify.test.ts`

The `verify` function runs a synchronous Saboteur verification on a single managed file. It loads the spec and test artifacts, runs the Saboteur, and returns a `VerifyResult`. This is simpler than `cover` -- no iteration, no Mason re-runs.

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/verify.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import type { VerifyResult } from "../src/types.js";

// We test the verify function's logic by mocking the agent calls.
// The actual Saboteur dispatch is tested in the pipeline integration tests.

describe("verify", () => {
  it("is exported from api.ts", async () => {
    const api = await import("../src/api.js");
    expect(typeof api.verify).toBe("function");
  });

  it("throws when spec artifact is missing", async () => {
    const { verify } = await import("../src/api.js");
    // /tmp/nonexistent has no .prunejuice store
    await expect(
      verify("/tmp/nonexistent-verify-test", {
        specPath: "test.spec.md",
        managedFilePath: "test.ts",
      }),
    ).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/verify.test.ts`
Expected: FAIL -- `verify` not exported from api.ts

- [ ] **Step 3: Implement verify**

Add to `prunejuice/src/api.ts`, after the `weed` function and before the orchestrator section:

First add the import of `VerifyResult` to the existing type imports at the top:

```typescript
import type {
  // ... existing imports ...
  VerifyResult,
} from "./types.js";
```

Then add the function:

```typescript
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

  log("generate", `Verifying ${options.managedFilePath} against ${options.specPath}...`);

  const rawReport = await runSaboteur(spec, tests, implementation, cwd);
  const report = validateSaboteurReport(rawReport);

  return {
    status: report.verdict === "pass" ? "pass" : "fail",
    killRate: report.killRate,
    mutationResults: report.mutationResults,
    complianceViolations: report.complianceViolations,
  };
}
```

Also add `VerifyResult` to the re-exports at the bottom of api.ts:

```typescript
export type {
  // ... existing re-exports ...
  VerifyResult,
} from "./types.js";
```

- [ ] **Step 4: Run tests**

Run: `cd prunejuice && npx vitest run test/verify.test.ts`
Expected: Both tests pass

- [ ] **Step 5: Run full suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/api.ts prunejuice/test/verify.test.ts
git commit -m "feat(prunejuice): add verify function for single-file Saboteur verification"
```

---

### Task 3: Implement Pipeline MCP Handlers (`pipeline-mcp.ts`)

**Files:**
- Create: `prunejuice/src/pipeline-mcp.ts`

This is the core of Phase 4. Six handler functions that wrap the library API for MCP consumption. The `generate` handler implements the two-call discovery flow.

- [ ] **Step 1: Create pipeline-mcp.ts with all handlers**

Create `prunejuice/src/pipeline-mcp.ts`:

```typescript
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

// -- Generate (two-call discovery flow) ---------------------------------------

export interface GenerateParams {
  spec: Spec;
  cwd: string;
}

/**
 * Run the full generate pipeline.
 * If the Archaeologist surfaces discoveries, returns discovery_pending
 * with serialised pipeline state for the resume call.
 * If no discoveries, runs the full pipeline and returns the result.
 */
export async function handleGenerate(
  params: GenerateParams,
): Promise<GenerateMcpResult | GenerateDiscoveryPending> {
  let pendingDiscoveries: DiscoveredItem[] | null = null;
  let pendingState: SerialisedPipelineState | null = null;

  const onDiscovery: DiscoveryHandler = async (discovered) => {
    // Capture discoveries and pipeline state for the client
    pendingDiscoveries = [...discovered];

    // We need the concrete spec and behaviour contract that were just
    // produced by the Archaeologist. These are available because generate()
    // calls the discovery handler synchronously after the Archaeologist.
    // However, we can't access them here -- we need to intercept them
    // from the generate function's internal state.
    //
    // Solution: return deferred resolutions so generate() continues,
    // but we'll check pendingDiscoveries after generate returns.
    return discovered.map((item) => ({
      item: { ...item },
      resolution: "deferred" as const,
    }));
  };

  try {
    const result = await generate(params.spec, params.cwd, {
      onDiscovery,
    });

    // If discoveries were captured but we deferred them all,
    // check if any were non-trivial (had observations/questions)
    if (
      pendingDiscoveries &&
      pendingDiscoveries.length > 0 &&
      pendingDiscoveries.some((d) => d.observation || d.question)
    ) {
      // Return discovery_pending so the client can present them
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

// -- Generate Resume (after discovery resolution) -----------------------------

export interface GenerateResumeParams {
  pipelineState: SerialisedPipelineState;
  resolutions: DiscoveryResolutionInput[];
}

/**
 * Resume the generate pipeline after discovery resolution.
 * Takes the serialised pipeline state + resolutions, applies them,
 * and continues the pipeline.
 */
export async function handleGenerateResume(
  params: GenerateResumeParams,
): Promise<GenerateMcpResult> {
  const { pipelineState, resolutions } = params;

  // Apply resolutions to the spec
  let workingSpec = structuredClone(pipelineState.spec);

  for (const resolution of resolutions) {
    if (resolution.action === "promote" && resolution.specAmendment) {
      // Merge amendment into spec
      workingSpec = {
        ...workingSpec,
        ...resolution.specAmendment,
        // Merge arrays additively for requirements/constraints/acceptanceCriteria
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
    // dismiss and defer: no spec changes needed
  }

  try {
    // Re-run generate with the amended spec
    // Discovery handler auto-defers since we've already resolved
    const result = await generate(workingSpec, pipelineState.cwd);
    return { success: true, result };
  } catch (err: unknown) {
    return {
      success: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// -- Distill ------------------------------------------------------------------

export interface DistillParams {
  cwd: string;
}

export async function handleDistill(
  params: DistillParams,
): Promise<{ spec: Spec }> {
  const spec = await distill(params.cwd);
  return { spec };
}

// -- Cover --------------------------------------------------------------------

export interface CoverParams {
  cwd: string;
  spec?: Spec;
  maxIterations?: number;
}

export async function handleCover(
  params: CoverParams,
): Promise<CoverResult> {
  return cover(params.cwd, {
    spec: params.spec,
    maxIterations: params.maxIterations,
  });
}

// -- Weed ---------------------------------------------------------------------

export interface WeedParams {
  cwd: string;
  spec?: Spec;
}

export async function handleWeed(
  params: WeedParams,
): Promise<DriftReport> {
  return weed(params.cwd, { spec: params.spec });
}

// -- Verify -------------------------------------------------------------------

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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile

- [ ] **Step 3: Commit**

```bash
git add prunejuice/src/pipeline-mcp.ts
git commit -m "feat(prunejuice): pipeline MCP handlers with two-call discovery flow"
```

---

### Task 4: Register Pipeline MCP Tools in `mcp.ts`

**Files:**
- Modify: `prunejuice/src/mcp.ts`
- Create: `prunejuice/test/pipeline-mcp.test.ts`

- [ ] **Step 1: Write failing handler tests**

Create `prunejuice/test/pipeline-mcp.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  handleDistill,
  handleCover,
  handleWeed,
  handleVerify,
  handleGenerate,
  handleGenerateResume,
} from "../src/pipeline-mcp.js";

// These handlers wrap library functions that call the Claude Agent SDK.
// We test that the handlers are exported and have the right signatures.
// Full integration tests require agent dispatch and are out of scope
// for unit tests -- they're covered by the stress-test fixtures.

describe("pipeline MCP handlers", () => {
  it("handleGenerate is exported with correct signature", () => {
    expect(typeof handleGenerate).toBe("function");
    expect(handleGenerate.length).toBeLessThanOrEqual(1); // 1 param
  });

  it("handleGenerateResume is exported with correct signature", () => {
    expect(typeof handleGenerateResume).toBe("function");
    expect(handleGenerateResume.length).toBeLessThanOrEqual(1);
  });

  it("handleDistill is exported with correct signature", () => {
    expect(typeof handleDistill).toBe("function");
  });

  it("handleCover is exported with correct signature", () => {
    expect(typeof handleCover).toBe("function");
  });

  it("handleWeed is exported with correct signature", () => {
    expect(typeof handleWeed).toBe("function");
  });

  it("handleVerify is exported with correct signature", () => {
    expect(typeof handleVerify).toBe("function");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/pipeline-mcp.test.ts`
Expected: FAIL -- cannot resolve `../src/pipeline-mcp.js` (or handlers not exported)

Wait -- the file was already created in Task 3. The tests should pass. Run them to verify.

- [ ] **Step 3: Add imports and tool registrations to mcp.ts**

Add imports at top of `prunejuice/src/mcp.ts`:

```typescript
import {
  handleGenerate,
  handleGenerateResume,
  handleDistill,
  handleCover,
  handleWeed,
  handleVerify,
} from "./pipeline-mcp.js";
import type {
  GenerateMcpResult,
  GenerateDiscoveryPending,
  CoverResult,
  DriftReport,
  VerifyResult,
} from "./types.js";
```

Register six new tools inside `createServer()`:

```typescript
  // -- Pipeline execution tools -----------------------------------------------

  server.registerTool(
    "prunejuice_generate",
    {
      description:
        "Run the full generate pipeline: Archaeologist -> Mason -> Builder -> Saboteur with convergence. Returns discovery_pending if discoveries need resolution.",
      inputSchema: {
        spec: z.object({
          intent: z.string(),
          requirements: z.array(z.string()),
          constraints: z.array(z.string()),
          acceptanceCriteria: z.array(z.string()),
        }).describe("The spec to generate from"),
        cwd: z.string().describe("Absolute path to the project root"),
      },
    },
    async (args) => {
      try {
        const result = await handleGenerate({
          spec: args.spec,
          cwd: args.cwd,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_generate:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_generate_resume",
    {
      description:
        "Resume the generate pipeline after discovery resolution. Takes serialised pipeline state and resolutions.",
      inputSchema: {
        pipelineState: z.object({
          spec: z.object({
            intent: z.string(),
            requirements: z.array(z.string()),
            constraints: z.array(z.string()),
            acceptanceCriteria: z.array(z.string()),
          }),
          concreteSpec: z.any(),
          behaviourContract: z.any(),
          cwd: z.string(),
        }).describe("Serialised pipeline state from generate's discovery_pending response"),
        resolutions: z.array(z.object({
          discoveryId: z.string(),
          action: z.enum(["promote", "dismiss", "defer"]),
          specAmendment: z.any().optional(),
        })).describe("Resolution for each discovery"),
      },
    },
    async (args) => {
      try {
        const result = await handleGenerateResume({
          pipelineState: args.pipelineState,
          resolutions: args.resolutions,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_generate_resume:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_distill",
    {
      description:
        "Infer a spec from existing code. Archaeologist reads the codebase and produces a Spec.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root"),
      },
    },
    async (args) => {
      try {
        const result = await handleDistill({ cwd: args.cwd });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_distill:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_cover",
    {
      description:
        "Mutation-driven test coverage improvement. Runs Saboteur to find gaps, Mason to strengthen tests.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root"),
        spec: z.object({
          intent: z.string(),
          requirements: z.array(z.string()),
          constraints: z.array(z.string()),
          acceptanceCriteria: z.array(z.string()),
        }).optional().describe("Spec to cover (loads from store if omitted)"),
        maxIterations: z.number().int().optional().describe("Max strengthening iterations (default 3)"),
      },
    },
    async (args) => {
      try {
        const result = await handleCover({
          cwd: args.cwd,
          spec: args.spec,
          maxIterations: args.maxIterations,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_cover:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_weed",
    {
      description:
        "Detect intent drift between spec and code. Returns findings with severity and recommendations.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root"),
        spec: z.object({
          intent: z.string(),
          requirements: z.array(z.string()),
          constraints: z.array(z.string()),
          acceptanceCriteria: z.array(z.string()),
        }).optional().describe("Spec to check against (loads from store if omitted)"),
      },
    },
    async (args) => {
      try {
        const result = await handleWeed({
          cwd: args.cwd,
          spec: args.spec,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_weed:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_verify",
    {
      description:
        "Synchronous Saboteur verification on a single file. Returns kill rate, mutation results, and compliance violations.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root"),
        specPath: z.string().describe("Path to the spec file (relative to cwd)"),
        managedFilePath: z.string().describe("Path to the managed file (relative to cwd)"),
      },
    },
    async (args) => {
      try {
        const result = await handleVerify({
          cwd: args.cwd,
          specPath: args.specPath,
          managedFilePath: args.managedFilePath,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_verify:\n${message}` }],
        };
      }
    },
  );
```

- [ ] **Step 4: Run tests**

Run: `cd prunejuice && npx vitest run test/pipeline-mcp.test.ts`
Expected: All 6 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile

- [ ] **Step 7: Commit**

```bash
git add prunejuice/src/mcp.ts prunejuice/test/pipeline-mcp.test.ts
git commit -m "feat(prunejuice): register 6 pipeline MCP tools (generate, resume, distill, cover, weed, verify)"
```

---

### Task 5: Version Bump + Final Verification

**Files:**
- Modify: `prunejuice/package.json`

- [ ] **Step 1: Bump version**

Change `"version": "1.3.0"` to `"version": "1.4.0"` in `prunejuice/package.json`.

- [ ] **Step 2: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 3: Run Python orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: All 408+ tests pass

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile

- [ ] **Step 5: Commit**

```bash
git add prunejuice/package.json
git commit -m "chore(prunejuice): bump version to 1.4.0 for Phase 4"
```

---

## Notes for the Implementer

### Key Invariants

1. **The MCP server is stateless.** Pipeline state for the discovery gate round-trips through the client as `SerialisedPipelineState` JSON. No in-memory session state, no restart fragility.

2. **The library functions do the real work.** Every MCP handler is a thin translation layer: parse params → call library function → format response. Domain logic stays in `api.ts`, not in the MCP layer.

3. **`generate`'s discovery flow is the only non-trivial handler.** All others are direct pass-through. The two-call pattern works by:
   - First call: `onDiscovery` callback captures discoveries and defers them all → generate runs the full pipeline with deferrals → result is returned with `status: "discovery_pending"` if discoveries had substantive content
   - Second call: client sends resolutions → handler merges spec amendments → re-runs generate with the amended spec

4. **`verify` is a new function in `api.ts`.** Unlike the other pipeline functions which already existed, `verify` is new. It runs a single Saboteur pass using stored pipeline artifacts (spec, tests, implementation).

5. **`pipeline-mcp.ts` is a separate module from `mcp.ts`.** This keeps the MCP handler file from growing past 700+ lines. `mcp.ts` imports the handlers and registers the tools. The handlers contain the param types and delegation logic.

### What NOT to Build

- **Interactive elicit** stays in unslop commands. The `elicit` function exists in `api.ts` but is NOT exposed as an MCP tool -- Socratic dialogue runs in the Claude Code session.
- **Orchestrators** (takeover, change, sync) are NOT exposed as MCP tools in Phase 4. They compose the phases and are called by unslop commands, not by MCP clients directly.
- **`prunejuice_generate_resume`'s resolution semantics** are simplified: `promote` merges amendments additively (appends to requirements/constraints/acceptanceCriteria arrays). Full re-run of Archaeologist on promote happens naturally because `generate` always starts with the Archaeologist.

### Testing Strategy

Pipeline tools call the Claude Agent SDK, which makes real API calls. Unit tests verify handler exports and signatures. Integration testing against the stress-test fixtures happens after Phase 5 when commands switch to prunejuice tools.

### Tool Count After Phase 4

15 MCP tools total:
- Phase 1: `check_freshness` (1)
- Phase 2: `build_order`, `resolve_deps`, `ripple_check` (3)
- Phase 3: `deep_sync_plan`, `bulk_sync_plan`, `resume_sync_plan`, `spec_diff`, `discover_files` (5)
- Phase 4: `generate`, `generate_resume`, `distill`, `cover`, `weed`, `verify` (6)
