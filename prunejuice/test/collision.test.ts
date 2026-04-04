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
});
