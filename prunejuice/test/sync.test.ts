import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm, readFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { deepSyncPlan, bulkSyncPlan, resumeSyncPlan } from "../src/sync.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "sync-test-"));
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

/** Create a managed file with correct hash headers. */
function managedFile(specContent: string, bodyContent: string): string {
  const specHash = truncatedHash(specContent);
  const outputHash = truncatedHash(bodyContent);
  const header = formatHeader("test.spec.md", {
    specHash,
    outputHash,
    generated: "2026-01-01T00:00:00Z",
  });
  return `${header}\n\n${bodyContent}`;
}

// -- Tests --------------------------------------------------------------------

describe("deepSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns plan for a single stale spec and its dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const oldSpecA = "---\n---\n# OLD content A";
    const newSpecA = "---\n---\n# NEW content A";
    const specB =
      "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B content";

    // a.ts is stale: managed file has old spec hash, spec has new content
    await writeAt(tmp, "a.ts.spec.md", newSpecA);
    await writeAt(tmp, "a.ts", managedFile(oldSpecA, "code a"));

    // b.ts depends on a.ts
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "b.ts", managedFile(specB, "code b"));

    const result = await deepSyncPlan("a.ts.spec.md", tmp);

    expect(result.trigger).toBe("a.ts.spec.md");
    // a.ts should be in plan (stale)
    const managedPaths = result.plan.map((e) => e.managed);
    expect(managedPaths).toContain("a.ts");
    expect(result.stats.toRegenerate).toBeGreaterThanOrEqual(1);
  });

  it("accepts managed file path and resolves to spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget spec";
    await writeAt(tmp, "widget.ts.spec.md", specContent);
    // No managed file -> pending state
    const result = await deepSyncPlan("widget.ts", tmp);

    expect(result.trigger).toBe("widget.ts.spec.md");
    const managedPaths = result.plan.map((e) => e.managed);
    expect(managedPaths).toContain("widget.ts");
  });

  it("skips modified files into skipped list when force=false", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget spec";
    const origBody = "original code";

    // Create managed file with matching spec hash but edited body
    const managed = managedFile(specContent, origBody);
    // Replace body while keeping header
    const lines = managed.split("\n");
    const headerLines = lines.slice(0, 2);
    const modifiedManaged = headerLines.join("\n") + "\n\nMANUALLY EDITED CODE";

    await writeAt(tmp, "widget.ts.spec.md", specContent);
    await writeAt(tmp, "widget.ts", modifiedManaged);

    const result = await deepSyncPlan("widget.ts.spec.md", tmp, {
      force: false,
    });

    // modified file should be in skipped, not plan
    const skippedPaths = result.skipped.map((e) => e.managed);
    expect(skippedPaths).toContain("widget.ts");
    expect(result.stats.skippedNeedConfirm).toBe(1);
  });

  it("includes modified files in plan when force=true", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget";
    const origBody = "original code";
    await writeAt(tmp, "widget.ts.spec.md", specContent);
    const managed = managedFile(specContent, origBody);
    const editedManaged = managed.replace(origBody, "user edited code");
    await writeAt(tmp, "widget.ts", editedManaged);

    const result = await deepSyncPlan("widget.ts.spec.md", tmp, { force: true });
    expect(result.plan.some((e) => e.managed === "widget.ts")).toBe(true);
    expect(result.skipped).toEqual([]);
  });

  it("throws for nonexistent spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await expect(
      deepSyncPlan("nonexistent.ts.spec.md", tmp),
    ).rejects.toThrow(/Spec not found/);
  });
});

describe("bulkSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns batched plan for all stale files", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const oldSpec1 = "---\n---\n# OLD 1";
    const newSpec1 = "---\n---\n# NEW 1";
    const oldSpec2 = "---\n---\n# OLD 2";
    const newSpec2 = "---\n---\n# NEW 2";

    await writeAt(tmp, "a.ts.spec.md", newSpec1);
    await writeAt(tmp, "a.ts", managedFile(oldSpec1, "code a"));
    await writeAt(tmp, "b.ts.spec.md", newSpec2);
    await writeAt(tmp, "b.ts", managedFile(oldSpec2, "code b"));

    const result = await bulkSyncPlan(tmp);

    expect(result.stats.totalStale).toBe(2);
    expect(result.batches.length).toBeGreaterThanOrEqual(1);
    expect(result.stats.toRegenerate).toBe(2);
  });

  it("returns empty batches when everything is fresh", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Fresh spec";
    await writeAt(tmp, "fresh.ts.spec.md", specContent);
    await writeAt(tmp, "fresh.ts", managedFile(specContent, "fresh code"));

    const result = await bulkSyncPlan(tmp);

    expect(result.batches).toEqual([]);
    expect(result.stats.totalStale).toBe(0);
  });

  it("groups independent specs into parallel batches", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Three independent stale specs
    for (const name of ["x", "y", "z"]) {
      const oldSpec = `---\n---\n# OLD ${name}`;
      const newSpec = `---\n---\n# NEW ${name}`;
      await writeAt(tmp, `${name}.ts.spec.md`, newSpec);
      await writeAt(tmp, `${name}.ts`, managedFile(oldSpec, `code ${name}`));
    }

    const result = await bulkSyncPlan(tmp, { maxBatchSize: 2 });

    // 3 items with maxBatchSize=2 -> at least 2 batches
    expect(result.batches.length).toBeGreaterThanOrEqual(2);
    const totalFiles = result.batches.reduce((sum, b) => sum + b.size, 0);
    expect(totalFiles).toBe(3);
  });

  it("respects dependency ordering across batches", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // b depends on a, both stale
    const oldSpecA = "---\n---\n# OLD A";
    const newSpecA = "---\n---\n# NEW A";
    const oldSpecB = "---\ndepends-on:\n  - a.ts.spec.md\n---\n# OLD B";
    const newSpecB = "---\ndepends-on:\n  - a.ts.spec.md\n---\n# NEW B";

    await writeAt(tmp, "a.ts.spec.md", newSpecA);
    await writeAt(tmp, "a.ts", managedFile(oldSpecA, "code a"));
    await writeAt(tmp, "b.ts.spec.md", newSpecB);
    await writeAt(tmp, "b.ts", managedFile(oldSpecB, "code b"));

    const result = await bulkSyncPlan(tmp, { maxBatchSize: 1 });

    // Find batch indices for a and b
    let aBatchIdx = -1;
    let bBatchIdx = -1;
    for (const batch of result.batches) {
      for (const file of batch.files) {
        if (file.spec === "a.ts.spec.md") aBatchIdx = batch.batchIndex;
        if (file.spec === "b.ts.spec.md") bBatchIdx = batch.batchIndex;
      }
    }

    expect(aBatchIdx).toBeGreaterThanOrEqual(0);
    expect(bBatchIdx).toBeGreaterThanOrEqual(0);
    expect(aBatchIdx).toBeLessThan(bBatchIdx);
  });
});

describe("resumeSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("includes failed files and their downstream dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Chain: a -> b -> c
    const specA = "---\n---\n# A";
    const specB =
      "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B";
    const specC =
      "---\ndepends-on:\n  - b.ts.spec.md\n---\n# C";

    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "c.ts.spec.md", specC);

    // All pending (no managed files)
    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["a.ts"],
      succeededFiles: [],
    });

    // Flatten batches to get all plan entries
    const plan = result.batches.flatMap((b) => b.files);
    const allEntries = [...plan, ...result.skipped];
    const managedPaths = allEntries.map((e) => e.managed);
    expect(managedPaths).toContain("a.ts");
    expect(managedPaths).toContain("b.ts");
    expect(managedPaths).toContain("c.ts");

    // Check causes
    const aEntry = allEntries.find((e) => e.managed === "a.ts");
    const bEntry = allEntries.find((e) => e.managed === "b.ts");
    const cEntry = allEntries.find((e) => e.managed === "c.ts");
    expect(aEntry?.cause).toBe("retry");
    expect(bEntry?.cause).toBe("downstream");
    expect(cEntry?.cause).toBe("downstream");

    expect(result.resumedFrom).toEqual(["a.ts"]);
  });

  it("excludes succeeded files", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // a -> b, a failed, b succeeded
    const specA = "---\n---\n# A";
    const specB =
      "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B";

    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);

    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["a.ts"],
      succeededFiles: ["b.ts"],
    });

    const plan = result.batches.flatMap((b) => b.files);
    const allEntries = [...plan, ...result.skipped];
    const managedPaths = allEntries.map((e) => e.managed);
    expect(managedPaths).toContain("a.ts");
    expect(managedPaths).not.toContain("b.ts");
    expect(result.alreadyDone).toBe(1);
  });

  it("returns empty plan when no failed specs found", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["nonexistent.ts"],
      succeededFiles: [],
    });

    const plan = result.batches.flatMap((b) => b.files);
    expect(plan).toEqual([]);
    expect(result.batches).toEqual([]);
    expect(result.resumedFrom).toEqual(["nonexistent.ts"]);
  });
});
