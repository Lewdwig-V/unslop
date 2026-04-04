import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { bulkSyncPlan } from "../src/sync.js";
import { clearDAGCache } from "../src/dag.js";

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "collision-test-"));
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

describe("collision detection", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("detects two specs claiming the same target", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      [
        "---",
        "source-spec: a.spec.md",
        "targets:",
        "  - path: src/shared.ts",
        "    language: typescript",
        "---",
      ].join("\n"),
    );
    await writeAt(
      tmp,
      "b.impl.md",
      [
        "---",
        "source-spec: b.spec.md",
        "targets:",
        "  - path: src/shared.ts",
        "    language: typescript",
        "---",
      ].join("\n"),
    );

    const result = await bulkSyncPlan(tmp);

    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.targetPath).toBe("src/shared.ts");
    expect(result.collisions[0]!.claimants).toHaveLength(2);
    expect(result.collisions[0]!.claimants).toContain("a.impl.md");
    expect(result.collisions[0]!.claimants).toContain("b.impl.md");
  });

  it("colliding specs are blocked from plan without force", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );

    const result = await bulkSyncPlan(tmp);

    // The colliding target should not be in any batch
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(0);
  });

  it("force without preferSpec still blocks collisions", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );

    const result = await bulkSyncPlan(tmp, { force: true });

    // Even with force, collision is still recorded and the target is not in plan
    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.preferSpec).toBeUndefined();
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(0);
  });

  it("force with preferSpec proceeds with winner and skips loser", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );

    const result = await bulkSyncPlan(tmp, {
      force: true,
      preferSpec: { "src/shared.ts": "a.impl.md" },
    });

    // The collision entry records the resolution
    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.preferSpec).toBe("a.impl.md");
    expect(result.collisions[0]!.skippedSpecs).toContain("b.impl.md");

    // The target IS in a batch now, via the winning spec
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(1);
    expect(sharedEntries[0]!.concrete).toBe("a.impl.md");
  });

  it("no collision when targets are distinct", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\ntargets:\n  - path: src/a.ts\n    language: typescript\n---",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/b.ts\n    language: typescript\n---",
    );

    const result = await bulkSyncPlan(tmp);
    expect(result.collisions).toEqual([]);
  });

  it("three-way collision: three specs claim the same target", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    for (const name of ["a", "b", "c"]) {
      await writeAt(tmp, `${name}.spec.md`, "---\n---\n# X");
      await writeAt(
        tmp,
        `${name}.impl.md`,
        `---\nsource-spec: ${name}.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---`,
      );
    }

    const result = await bulkSyncPlan(tmp);
    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.claimants).toHaveLength(3);
  });

  it("detects collision between abstract single-target and concrete multi-target", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Abstract spec A uses default single-target convention: src/shared.ts.spec.md -> src/shared.ts
    // No impl file for A -- pure abstract single-target.
    await writeAt(tmp, "src/shared.ts.spec.md", "---\n---\n# A");

    // Concrete spec B explicitly targets the same file via its impl
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "b.impl.md",
      [
        "---",
        "source-spec: b.spec.md",
        "targets:",
        "  - path: src/shared.ts",
        "    language: typescript",
        "---",
      ].join("\n"),
    );

    const result = await bulkSyncPlan(tmp);

    // Both should be detected as claiming src/shared.ts
    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.targetPath).toBe("src/shared.ts");
    expect(result.collisions[0]!.claimants).toContain("src/shared.ts.spec.md");
    expect(result.collisions[0]!.claimants).toContain("b.impl.md");

    // Neither entry should be in the plan (unresolved collision blocks both)
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(0);
  });

  it("preferSpec resolves abstract-vs-concrete collision when winner is the abstract spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/shared.ts.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );

    const result = await bulkSyncPlan(tmp, {
      force: true,
      preferSpec: { "src/shared.ts": "src/shared.ts.spec.md" },
    });

    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.preferSpec).toBe("src/shared.ts.spec.md");
    expect(result.collisions[0]!.skippedSpecs).toContain("b.impl.md");

    // The abstract spec's entry should proceed
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(1);
    // The winner is the abstract spec (no concrete field)
    expect(sharedEntries[0]!.concrete).toBeUndefined();
  });

  it("accumulates multiple independent collisions in one plan", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Two independent collisions on different targets
    for (const name of ["a1", "a2"]) {
      await writeAt(tmp, `${name}.spec.md`, "---\n---\n# X");
      await writeAt(
        tmp,
        `${name}.impl.md`,
        `---\nsource-spec: ${name}.spec.md\ntargets:\n  - path: src/shared1.ts\n    language: typescript\n---`,
      );
    }
    for (const name of ["b1", "b2"]) {
      await writeAt(tmp, `${name}.spec.md`, "---\n---\n# X");
      await writeAt(
        tmp,
        `${name}.impl.md`,
        `---\nsource-spec: ${name}.spec.md\ntargets:\n  - path: src/shared2.ts\n    language: typescript\n---`,
      );
    }

    const result = await bulkSyncPlan(tmp);

    // Both collisions recorded
    expect(result.collisions).toHaveLength(2);
    const paths = result.collisions.map((c) => c.targetPath).sort();
    expect(paths).toEqual(["src/shared1.ts", "src/shared2.ts"]);

    // Both targets blocked from plan
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    expect(
      allPlanEntries.filter((e) => e.managed === "src/shared1.ts"),
    ).toHaveLength(0);
    expect(
      allPlanEntries.filter((e) => e.managed === "src/shared2.ts"),
    ).toHaveLength(0);
  });

  it("preferSpec with claimant not in the set falls through to unresolved", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\ntargets:\n  - path: src/shared.ts\n    language: typescript\n---",
    );

    // User typo'd the winner -- "c.impl.md" isn't in the claimants
    const result = await bulkSyncPlan(tmp, {
      force: true,
      preferSpec: { "src/shared.ts": "c.impl.md" },
    });

    // Must fall through to unresolved (safe default) -- not silently accept the typo
    expect(result.collisions).toHaveLength(1);
    expect(result.collisions[0]!.status).toBe("unresolved");
    expect(result.collisions[0]!.preferSpec).toBeUndefined();

    // Both entries still blocked
    const allPlanEntries = result.batches.flatMap((b) => b.files);
    const sharedEntries = allPlanEntries.filter(
      (e) => e.managed === "src/shared.ts",
    );
    expect(sharedEntries).toHaveLength(0);
  });
});
