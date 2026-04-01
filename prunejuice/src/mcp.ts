import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { checkFreshnessAll, type FreshnessReport } from "./freshness.js";

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
