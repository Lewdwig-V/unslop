import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { handleBuildOrder, handleResolveDeps, handleRippleCheck } from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dag-compat-test-"));
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

// -- build_order compatibility ------------------------------------------------

describe("build_order compatibility", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("output has 'order' field as string array", async () => {
    tmpDir = await makeTmp();

    await writeAt(tmpDir, "a.spec.md", "---\ntitle: A\n---\n# A\n");

    const result = await handleBuildOrder({ cwd: tmpDir });

    expect(Array.isArray(result.order)).toBe(true);
    expect(result.order.every((item) => typeof item === "string")).toBe(true);
  });

  it("cycle output has 'cycles' field as array of arrays", async () => {
    tmpDir = await makeTmp();

    // Mutual dependency creates a cycle: a depends on b, b depends on a
    await writeAt(
      tmpDir,
      "a.spec.md",
      "---\ntitle: A\ndepends-on:\n  - b.spec.md\n---\n# A\n",
    );
    await writeAt(
      tmpDir,
      "b.spec.md",
      "---\ntitle: B\ndepends-on:\n  - a.spec.md\n---\n# B\n",
    );

    const result = await handleBuildOrder({ cwd: tmpDir });

    expect(result.cycles).toBeDefined();
    expect(Array.isArray(result.cycles)).toBe(true);
    expect(
      result.cycles!.every((cycle) => Array.isArray(cycle)),
    ).toBe(true);
  });

  it("matches Python output for diamond dependency graph", async () => {
    tmpDir = await makeTmp();

    // Diamond: d depends on b and c; b depends on a; c depends on a
    await writeAt(tmpDir, "a.spec.md", "---\ntitle: A\n---\n# A\n");
    await writeAt(
      tmpDir,
      "b.spec.md",
      "---\ntitle: B\ndepends-on:\n  - a.spec.md\n---\n# B\n",
    );
    await writeAt(
      tmpDir,
      "c.spec.md",
      "---\ntitle: C\ndepends-on:\n  - a.spec.md\n---\n# C\n",
    );
    await writeAt(
      tmpDir,
      "d.spec.md",
      "---\ntitle: D\ndepends-on:\n  - b.spec.md\n  - c.spec.md\n---\n# D\n",
    );

    const result = await handleBuildOrder({ cwd: tmpDir });

    expect(result.order).toHaveLength(4);
    expect(result.order[0]).toBe("a.spec.md");
    expect(result.order[result.order.length - 1]).toBe("d.spec.md");
  });
});

// -- resolve_deps compatibility -----------------------------------------------

describe("resolve_deps compatibility", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns string array", async () => {
    tmpDir = await makeTmp();

    await writeAt(tmpDir, "a.spec.md", "---\ntitle: A\n---\n# A\n");
    await writeAt(
      tmpDir,
      "b.spec.md",
      "---\ntitle: B\ndepends-on:\n  - a.spec.md\n---\n# B\n",
    );

    const result = await handleResolveDeps({ specPath: "b.spec.md", cwd: tmpDir });

    expect(Array.isArray(result)).toBe(true);
    expect(result).toContain("a.spec.md");
    expect(result.every((item) => typeof item === "string")).toBe(true);
  });

  it("does NOT include the input spec (matches Python behavior)", async () => {
    tmpDir = await makeTmp();

    await writeAt(
      tmpDir,
      "standalone.spec.md",
      "---\ntitle: Standalone\n---\n# Standalone\n",
    );

    const result = await handleResolveDeps({
      specPath: "standalone.spec.md",
      cwd: tmpDir,
    });

    expect(result).not.toContain("standalone.spec.md");
  });
});

// -- ripple_check compatibility -----------------------------------------------

describe("ripple_check compatibility", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("output has required top-level fields matching Python format", async () => {
    tmpDir = await makeTmp();

    await writeAt(tmpDir, "a.spec.md", "---\ntitle: A\n---\n# A\n");

    const result = await handleRippleCheck({ specPaths: ["a.spec.md"], cwd: tmpDir });

    // Top-level fields
    expect(result).toHaveProperty("inputSpecs");
    expect(result).toHaveProperty("layers");
    expect(result).toHaveProperty("buildOrder");

    // Abstract layer
    expect(result.layers).toHaveProperty("abstract");
    expect(result.layers.abstract).toHaveProperty("directlyChanged");
    expect(result.layers.abstract).toHaveProperty("transitivelyAffected");
    expect(result.layers.abstract).toHaveProperty("total");

    // Concrete layer
    expect(result.layers).toHaveProperty("concrete");
    expect(result.layers.concrete).toHaveProperty("affectedImpls");
    expect(result.layers.concrete).toHaveProperty("ghostStaleImpls");
    expect(result.layers.concrete).toHaveProperty("total");

    // Code layer
    expect(result.layers).toHaveProperty("code");
    expect(result.layers.code).toHaveProperty("regenerate");
    expect(result.layers.code).toHaveProperty("ghostStale");
    expect(result.layers.code).toHaveProperty("totalFiles");

    // buildOrder is a string array
    expect(Array.isArray(result.buildOrder)).toBe(true);
  });

  it("inputSpecs field contains the specs passed in", async () => {
    tmpDir = await makeTmp();

    await writeAt(tmpDir, "x.spec.md", "---\ntitle: X\n---\n# X\n");
    await writeAt(tmpDir, "y.spec.md", "---\ntitle: Y\n---\n# Y\n");

    const result = await handleRippleCheck({
      specPaths: ["x.spec.md", "y.spec.md"],
      cwd: tmpDir,
    });

    expect(Array.isArray(result.inputSpecs)).toBe(true);
    expect(result.inputSpecs).toContain("x.spec.md");
    expect(result.inputSpecs).toContain("y.spec.md");
  });

  it("code layer entries have required fields matching Python format", async () => {
    tmpDir = await makeTmp();

    // Spec with a managed file target (src/widget.ts.spec.md -> src/widget.ts)
    await writeAt(
      tmpDir,
      "src/widget.ts.spec.md",
      "---\ntitle: Widget\n---\n# Widget\n",
    );

    const result = await handleRippleCheck({
      specPaths: ["src/widget.ts.spec.md"],
      cwd: tmpDir,
    });

    expect(result.layers.code.regenerate.length).toBeGreaterThan(0);
    const entry = result.layers.code.regenerate[0]!;

    // Required fields matching Python format
    expect(entry).toHaveProperty("managed");
    expect(entry.managed).toBe("src/widget.ts");
    expect(entry).toHaveProperty("spec");
    expect(entry).toHaveProperty("exists");
    expect(typeof entry.exists).toBe("boolean");
    expect(entry).toHaveProperty("currentState");
    expect(entry).toHaveProperty("cause");
  });
});
