import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm, readFile, unlink } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  parseDependsOn,
  topoSort,
  ensureDAG,
  clearDAGCache,
  buildOrder,
  resolveDeps,
} from "../src/dag.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dag-test-"));
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

// -- parseDependsOn -----------------------------------------------------------

describe("parseDependsOn", () => {
  it("extracts depends-on list from frontmatter", () => {
    const content = [
      "---",
      "title: My Spec",
      "depends-on:",
      "  - auth.spec.md",
      "  - db.spec.md",
      "---",
      "# Body",
    ].join("\n");

    expect(parseDependsOn(content)).toEqual(["auth.spec.md", "db.spec.md"]);
  });

  it("returns empty array when no frontmatter", () => {
    expect(parseDependsOn("# Just a heading\nSome text.")).toEqual([]);
  });

  it("returns empty array when no depends-on field", () => {
    const content = ["---", "title: No deps", "---", "# Body"].join("\n");
    expect(parseDependsOn(content)).toEqual([]);
  });

  it("normalizes depends_on (snake_case) to depends-on", () => {
    const content = [
      "---",
      "depends_on:",
      "  - core.spec.md",
      "---",
      "# Body",
    ].join("\n");

    expect(parseDependsOn(content)).toEqual(["core.spec.md"]);
  });

  it("stops reading deps at next field", () => {
    const content = [
      "---",
      "depends-on:",
      "  - first.spec.md",
      "status: draft",
      "---",
      "# Body",
    ].join("\n");

    expect(parseDependsOn(content)).toEqual(["first.spec.md"]);
  });

  it("handles unclosed frontmatter by returning empty", () => {
    const content = [
      "---",
      "depends-on:",
      "  - orphan.spec.md",
      "# Never closed",
    ].join("\n");

    expect(parseDependsOn(content)).toEqual([]);
  });
});

// -- ensureDAG ----------------------------------------------------------------

describe("ensureDAG", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("builds DAG from scratch when no cache exists (cold start)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "a.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n---\n# A",
    );
    await writeAt(tmp, "b.spec.md", "---\ntitle: B\n---\n# B");

    const cache = await ensureDAG(tmp);

    expect(cache.dag["a.spec.md"]).toEqual(["b.spec.md"]);
    expect(cache.dag["b.spec.md"]).toEqual([]);
    expect(cache.manifest["a.spec.md"]).toBeDefined();
    expect(cache.manifest["b.spec.md"]).toBeDefined();
    expect(cache.builtAt).toBeDefined();
  });

  it("returns cached DAG when spec content is unchanged (warm path)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "x.spec.md", "---\ntitle: X\n---\n# X");

    const first = await ensureDAG(tmp);
    const firstBuiltAt = first.builtAt;

    const second = await ensureDAG(tmp);
    expect(second.builtAt).toBe(firstBuiltAt);
  });

  it("detects new spec files added after cache was built", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "existing.spec.md", "# Existing");
    await ensureDAG(tmp);

    // Add a new spec
    await writeAt(tmp, "added.spec.md", "# Added");
    const cache = await ensureDAG(tmp);

    expect(cache.manifest["added.spec.md"]).toBeDefined();
    expect(cache.dag["added.spec.md"]).toEqual([]);
  });

  it("updates DAG when spec content changes (hash differs)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "c.spec.md", "# Version 1");
    const first = await ensureDAG(tmp);
    const firstHash = first.manifest["c.spec.md"];

    // Modify the spec
    await writeAt(
      tmp,
      "c.spec.md",
      "---\ndepends-on:\n  - d.spec.md\n---\n# Version 2",
    );
    const second = await ensureDAG(tmp);

    expect(second.manifest["c.spec.md"]).not.toBe(firstHash);
    expect(second.dag["c.spec.md"]).toEqual(["d.spec.md"]);
  });

  it("prunes deleted specs from DAG and manifest", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "# A");
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# B",
    );
    await ensureDAG(tmp);

    // Delete a.spec.md -- b.spec.md still lists it as a dep
    await unlink(join(tmp, "a.spec.md"));
    clearDAGCache();
    const cache = await ensureDAG(tmp);

    expect(cache.manifest["a.spec.md"]).toBeUndefined();
    expect(cache.dag["a.spec.md"]).toBeUndefined();
    // b.spec.md survives but its edge to the deleted spec must be removed
    expect(cache.dag["b.spec.md"]).toEqual([]);
  });

  it("persists cache to .prunejuice/dag-cache.json", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "p.spec.md", "# Persist test");
    await ensureDAG(tmp);

    const raw = await readFile(
      join(tmp, ".prunejuice", "dag-cache.json"),
      "utf-8",
    );
    const parsed = JSON.parse(raw);
    expect(parsed.dag).toBeDefined();
    expect(parsed.manifest).toBeDefined();
    expect(parsed.builtAt).toBeDefined();
    expect(parsed.manifest["p.spec.md"]).toBeDefined();
  });

  it("excludes default directories (.prunejuice, node_modules, .git)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "real.spec.md", "# Real");
    await writeAt(tmp, ".prunejuice/hidden.spec.md", "# Hidden");
    await writeAt(tmp, "node_modules/pkg/mod.spec.md", "# Module");
    await writeAt(tmp, ".git/objects/obj.spec.md", "# Git");

    const cache = await ensureDAG(tmp);

    expect(Object.keys(cache.manifest)).toEqual(["real.spec.md"]);
  });
});

// -- buildOrder ---------------------------------------------------------------

describe("buildOrder", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns specs in topological order (leaves first)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Chain: a depends on b, b depends on c
    await writeAt(
      tmp,
      "a.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n---\n# A",
    );
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - c.spec.md\n---\n# B",
    );
    await writeAt(tmp, "c.spec.md", "---\ntitle: C\n---\n# C");

    const result = await buildOrder(tmp);

    expect(result.order).toEqual(["c.spec.md", "b.spec.md", "a.spec.md"]);
    expect(result.cycles).toBeUndefined();
  });

  it("reports cycles instead of throwing", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Mutual dependency: a depends on b, b depends on a
    await writeAt(
      tmp,
      "a.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n---\n# A",
    );
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# B",
    );

    const result = await buildOrder(tmp);

    expect(result.cycles).toBeDefined();
    expect(result.cycles!.length).toBeGreaterThan(0);
    // Fallback should be alphabetical
    expect(result.order).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty order for projects with no specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const result = await buildOrder(tmp);

    expect(result.order).toEqual([]);
    expect(result.cycles).toBeUndefined();
  });
});

// -- resolveDeps --------------------------------------------------------------

describe("resolveDeps", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns transitive deps in build order, excluding the spec itself", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Chain: a depends on b, b depends on c
    await writeAt(
      tmp,
      "a.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n---\n# A",
    );
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - c.spec.md\n---\n# B",
    );
    await writeAt(tmp, "c.spec.md", "---\ntitle: C\n---\n# C");

    const deps = await resolveDeps("a.spec.md", tmp);

    // Should include b and c but not a, in build order (c first)
    expect(deps).toEqual(["c.spec.md", "b.spec.md"]);
  });

  it("returns empty array for spec with no deps", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "solo.spec.md", "# No deps");

    const deps = await resolveDeps("solo.spec.md", tmp);
    expect(deps).toEqual([]);
  });

  it("handles diamond dependencies without false cycle detection", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Diamond: d depends on b and c, both depend on a
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(tmp, "c.spec.md", "---\ndepends-on:\n  - a.spec.md\n---\n");
    await writeAt(
      tmp,
      "d.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n  - c.spec.md\n---\n",
    );

    const deps = await resolveDeps("d.spec.md", tmp);
    expect(deps).toContain("a.spec.md");
    expect(deps).toContain("b.spec.md");
    expect(deps).toContain("c.spec.md");
    expect(deps).not.toContain("d.spec.md");
  });

  it("throws on cycle", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "x.spec.md",
      "---\ndepends-on:\n  - y.spec.md\n---\n# X",
    );
    await writeAt(
      tmp,
      "y.spec.md",
      "---\ndepends-on:\n  - x.spec.md\n---\n# Y",
    );

    await expect(resolveDeps("x.spec.md", tmp)).rejects.toThrow(/Cycle/);
  });
});
