import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { checkFreshnessAll, type FreshnessReport } from "./freshness.js";
import { buildOrder, resolveDeps, type BuildOrderResult } from "./dag.js";
import { rippleCheck } from "./ripple.js";
import { deepSyncPlan, bulkSyncPlan, resumeSyncPlan } from "./sync.js";
import { computeSpecDiff } from "./spec-diff.js";
import { discoverFiles } from "./discover.js";
import type { RippleResult, DeepSyncResult, BulkSyncResult, ResumeSyncResult, SpecDiffResult } from "./types.js";

// -- Tool handler (exported for direct testing) --------------------------------

export interface CheckFreshnessParams {
  cwd: string;
  excludePatterns?: string[];
}

export async function handleCheckFreshness(
  params: CheckFreshnessParams,
): Promise<FreshnessReport> {
  return checkFreshnessAll(params.cwd, {
    excludePatterns: params.excludePatterns,
  });
}

// -- Tool handlers (exported for direct testing) -------------------------------

export async function handleBuildOrder({
  cwd,
}: {
  cwd: string;
}): Promise<BuildOrderResult> {
  return buildOrder(cwd);
}

export async function handleResolveDeps({
  specPath,
  cwd,
}: {
  specPath: string;
  cwd: string;
}): Promise<string[]> {
  return resolveDeps(specPath, cwd);
}

export async function handleRippleCheck({
  specPaths,
  cwd,
}: {
  specPaths: string[];
  cwd: string;
}): Promise<RippleResult> {
  return rippleCheck(specPaths, cwd);
}

export interface DeepSyncPlanParams { filePath: string; cwd: string; force?: boolean; }
export async function handleDeepSyncPlan(params: DeepSyncPlanParams): Promise<DeepSyncResult> {
  return deepSyncPlan(params.filePath, params.cwd, { force: params.force });
}

export interface BulkSyncPlanParams { cwd: string; force?: boolean; maxBatchSize?: number; }
export async function handleBulkSyncPlan(params: BulkSyncPlanParams): Promise<BulkSyncResult> {
  return bulkSyncPlan(params.cwd, { force: params.force, maxBatchSize: params.maxBatchSize });
}

export interface SpecDiffParams { oldSpec: string; newSpec: string; }
export async function handleSpecDiff(params: SpecDiffParams): Promise<SpecDiffResult> {
  return computeSpecDiff(params.oldSpec, params.newSpec);
}

export interface DiscoverFilesParams { directory: string; extensions?: string[]; extraExcludes?: string[]; }
export async function handleDiscoverFiles(params: DiscoverFilesParams): Promise<string[]> {
  return discoverFiles(params.directory, { extensions: params.extensions, extraExcludes: params.extraExcludes });
}

// -- Server factory ------------------------------------------------------------

export function createServer(): McpServer {
  const server = new McpServer({
    name: "prunejuice",
    version: "1.0.0",
  });

  server.registerTool(
    "prunejuice_check_freshness",
    {
      description:
        "Check freshness of all managed files. Returns eight-state classification for each spec/managed-file pair.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root to scan"),
        excludePatterns: z
          .array(z.string())
          .optional()
          .describe("Additional directory names to exclude from scanning"),
      },
    },
    async (args) => {
      // Two-tier error handling:
      // - Domain errors (bad cwd, no specs, etc.) return clean JSON in content
      // - Unexpected errors (invariant violations) surface traceback
      let report: FreshnessReport;
      try {
        report = await handleCheckFreshness({
          cwd: args.cwd,
          excludePatterns: args.excludePatterns,
        });
      } catch (err: unknown) {
        // Unexpected error -- surface traceback
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_check_freshness:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(report, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_build_order",
    {
      description:
        "Topological sort of spec dependency DAG. Returns specs in build order (leaves first).",
      inputSchema: {
        cwd: z.string(),
      },
    },
    async (args) => {
      let result: BuildOrderResult;
      try {
        result = await handleBuildOrder({ cwd: args.cwd });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_build_order:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_resolve_deps",
    {
      description:
        "Resolve transitive dependencies of a single spec file. Returns dependency specs in build order (leaves first), excluding the input spec.",
      inputSchema: {
        specPath: z.string(),
        cwd: z.string(),
      },
    },
    async (args) => {
      let result: string[];
      try {
        result = await handleResolveDeps({
          specPath: args.specPath,
          cwd: args.cwd,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_resolve_deps:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_ripple_check",
    {
      description:
        "Compute blast radius of spec changes across abstract, concrete, and code layers. Returns affected specs, impls, managed files, and build order.",
      inputSchema: {
        specPaths: z.array(z.string()),
        cwd: z.string(),
      },
    },
    async (args) => {
      let result: RippleResult;
      try {
        result = await handleRippleCheck({
          specPaths: args.specPaths,
          cwd: args.cwd,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_ripple_check:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_deep_sync_plan",
    {
      description:
        "Compute a sync plan for a single file with dependency ordering. Accepts spec or managed file path.",
      inputSchema: {
        filePath: z.string(),
        cwd: z.string(),
        force: z.boolean().optional(),
      },
    },
    async (args) => {
      let result: DeepSyncResult;
      try {
        result = await handleDeepSyncPlan({
          filePath: args.filePath,
          cwd: args.cwd,
          force: args.force,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_deep_sync_plan:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_bulk_sync_plan",
    {
      description:
        "Compute a sync plan for all stale files with parallel batch grouping.",
      inputSchema: {
        cwd: z.string(),
        force: z.boolean().optional(),
        maxBatchSize: z.number().int().optional(),
      },
    },
    async (args) => {
      let result: BulkSyncResult;
      try {
        result = await handleBulkSyncPlan({
          cwd: args.cwd,
          force: args.force,
          maxBatchSize: args.maxBatchSize,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_bulk_sync_plan:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_spec_diff",
    {
      description:
        "Compute section-level diff between two spec versions. Returns changed and unchanged section headings.",
      inputSchema: {
        oldSpec: z.string(),
        newSpec: z.string(),
      },
    },
    async (args) => {
      let result: SpecDiffResult;
      try {
        result = await handleSpecDiff({
          oldSpec: args.oldSpec,
          newSpec: args.newSpec,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_spec_diff:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.registerTool(
    "prunejuice_discover_files",
    {
      description:
        "Find source files in a directory, excluding tests and build artifacts.",
      inputSchema: {
        directory: z.string(),
        extensions: z.array(z.string()).optional(),
        extraExcludes: z.array(z.string()).optional(),
      },
    },
    async (args) => {
      let result: string[];
      try {
        result = await handleDiscoverFiles({
          directory: args.directory,
          extensions: args.extensions,
          extraExcludes: args.extraExcludes,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? `${err.message}\n${err.stack ?? ""}`
            : String(err);
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: `Unexpected error in prunejuice_discover_files:\n${message}`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  return server;
}

// -- Entry point ---------------------------------------------------------------

async function main(): Promise<void> {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

// Only run when executed directly (not when imported)
const isMain =
  process.argv[1] !== undefined &&
  fileURLToPath(import.meta.url) === process.argv[1];

if (isMain) {
  main().catch((err: unknown) => {
    process.stderr.write(
      `Fatal: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`,
    );
    process.exit(1);
  });
}
