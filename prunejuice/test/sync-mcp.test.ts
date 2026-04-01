import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { handleDeepSyncPlan, handleBulkSyncPlan, handleSpecDiff, handleDiscoverFiles } from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "sync-mcp-test-"));
}

async function writeAt(
  base: string,
  rel: string,
  content: string,
): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

// -- Tests --------------------------------------------------------------------

describe("handleDeepSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns result with trigger and plan for a pending spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget spec\nDo something useful.";
    await writeAt(tmp, "src/widget.ts.spec.md", specContent);
    // No managed file -- state will be "pending"

    const result = await handleDeepSyncPlan({
      filePath: "src/widget.ts.spec.md",
      cwd: tmp,
    });

    expect(result).toHaveProperty("trigger");
    expect(result).toHaveProperty("plan");
    expect(result.trigger).toBe("src/widget.ts.spec.md");
    expect(Array.isArray(result.plan)).toBe(true);
    // pending state file should be in the plan
    expect(result.plan.length).toBeGreaterThanOrEqual(1);
    expect(result.plan[0].managed).toBe("src/widget.ts");
  });
});

describe("handleBulkSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns result with batches and stats for a pending spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Service spec\nDo something.";
    await writeAt(tmp, "src/service.ts.spec.md", specContent);
    // No managed file -- stale/pending

    const result = await handleBulkSyncPlan({ cwd: tmp });

    expect(result).toHaveProperty("batches");
    expect(result).toHaveProperty("stats");
    expect(Array.isArray(result.batches)).toBe(true);
    expect(typeof result.stats).toBe("object");
    expect(result.stats.totalStale).toBeGreaterThanOrEqual(1);
  });
});

describe("handleSpecDiff", () => {
  it("returns changedSections and unchangedSections for two spec texts", async () => {
    const oldSpec = [
      "## Overview",
      "This is the overview.",
      "",
      "## Behaviour",
      "Original behaviour.",
    ].join("\n");

    const newSpec = [
      "## Overview",
      "This is the overview.",
      "",
      "## Behaviour",
      "Updated behaviour.",
      "",
      "## Error Handling",
      "New section.",
    ].join("\n");

    const result = await handleSpecDiff({ oldSpec, newSpec });

    expect(result).toHaveProperty("changedSections");
    expect(result).toHaveProperty("unchangedSections");
    expect(result.unchangedSections).toContain("Overview");
    expect(result.changedSections).toContain("Behaviour");
    expect(result.changedSections).toContain("Error Handling");
  });
});

describe("handleDiscoverFiles", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns src/main.ts in results when it exists", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export function main() {}");
    // Also write a test file that should be excluded
    await writeAt(tmp, "src/main.test.ts", "test('main', () => {})");

    const result = await handleDiscoverFiles({ directory: tmp });

    expect(Array.isArray(result)).toBe(true);
    expect(result).toContain("src/main.ts");
    // Test file should be excluded
    expect(result).not.toContain("src/main.test.ts");
  });
});
