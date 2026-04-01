import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { handleBuildOrder, handleResolveDeps, handleRippleCheck } from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";

// -- handleBuildOrder ----------------------------------------------------------

describe("handleBuildOrder", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns topologically sorted spec list", async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "pj-mcp-build-order-"));

    const specA = "a.spec.md";
    const specB = "b.spec.md";

    await writeFile(
      join(tmpDir, specA),
      "---\ntitle: A\n---\n# A\n",
      "utf-8",
    );
    await writeFile(
      join(tmpDir, specB),
      `---\ntitle: B\ndepends-on:\n  - ${specA}\n---\n# B\n`,
      "utf-8",
    );

    const result = await handleBuildOrder({ cwd: tmpDir });

    expect(result.order).toEqual([specA, specB]);
    expect(result.cycles).toBeUndefined();
  });

  it("returns empty order for project with no specs", async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "pj-mcp-build-order-empty-"));

    const result = await handleBuildOrder({ cwd: tmpDir });

    expect(result.order).toEqual([]);
    expect(result.cycles).toBeUndefined();
  });
});

// -- handleResolveDeps ---------------------------------------------------------

describe("handleResolveDeps", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns transitive deps excluding the spec itself", async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "pj-mcp-resolve-deps-"));

    const specA = "a.spec.md";
    const specB = "b.spec.md";
    const specC = "c.spec.md";

    await writeFile(
      join(tmpDir, specA),
      "---\ntitle: A\n---\n# A\n",
      "utf-8",
    );
    await writeFile(
      join(tmpDir, specB),
      `---\ntitle: B\ndepends-on:\n  - ${specA}\n---\n# B\n`,
      "utf-8",
    );
    await writeFile(
      join(tmpDir, specC),
      `---\ntitle: C\ndepends-on:\n  - ${specB}\n---\n# C\n`,
      "utf-8",
    );

    const result = await handleResolveDeps({ specPath: specC, cwd: tmpDir });

    // C depends on B depends on A -- result should be [a, b] (leaves first, C excluded)
    expect(result).toEqual([specA, specB]);
  });
});

// -- handleRippleCheck ---------------------------------------------------------

describe("handleRippleCheck", () => {
  let tmpDir: string;

  afterEach(async () => {
    clearDAGCache();
    if (tmpDir) await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns structured ripple result", async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "pj-mcp-ripple-"));

    const specA = "a.spec.md";
    const specB = "b.spec.md";

    await writeFile(
      join(tmpDir, specA),
      "---\ntitle: A\n---\n# A\n",
      "utf-8",
    );
    await writeFile(
      join(tmpDir, specB),
      `---\ntitle: B\ndepends-on:\n  - ${specA}\n---\n# B\n`,
      "utf-8",
    );

    const result = await handleRippleCheck({ specPaths: [specA], cwd: tmpDir });

    // Should have the expected shape
    expect(result).toHaveProperty("inputSpecs");
    expect(result).toHaveProperty("layers");
    expect(result).toHaveProperty("buildOrder");
    expect(result.layers).toHaveProperty("abstract");
    expect(result.layers).toHaveProperty("concrete");
    expect(result.layers).toHaveProperty("code");

    // A is directly changed; B is transitively affected
    expect(result.layers.abstract.directlyChanged).toContain(specA);
    expect(result.layers.abstract.transitivelyAffected).toContain(specB);

    // Build order should include both
    expect(result.buildOrder).toContain(specA);
    expect(result.buildOrder).toContain(specB);
    // A must come before B in build order (leaves first)
    expect(result.buildOrder.indexOf(specA)).toBeLessThan(
      result.buildOrder.indexOf(specB),
    );
  });
});
