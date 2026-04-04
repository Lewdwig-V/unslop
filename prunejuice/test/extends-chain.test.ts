import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { rippleCheck } from "../src/ripple.js";
import { clearDAGCache } from "../src/dag.js";

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "extends-test-"));
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

describe("extends chain in ripple", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("extends edge propagates ripple: parent change affects child", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "parent.spec.md", "---\n---\n# Parent");
    await writeAt(tmp, "child.spec.md", "---\n---\n# Child");
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nBase strategy.",
    );
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: parent.impl.md",
        "---",
        "## Strategy",
        "Child strategy.",
      ].join("\n"),
    );

    const result = await rippleCheck(["parent.spec.md"], tmp);
    expect(result.layers.concrete.ghostStaleImpls).toContain("child.impl.md");
  });

  it("two-level extends chain: grandchild affected by grandparent change", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "gp.spec.md", "---\n---\n# Grandparent");
    await writeAt(tmp, "parent.spec.md", "---\n---\n# Parent");
    await writeAt(tmp, "child.spec.md", "---\n---\n# Child");

    await writeAt(
      tmp,
      "gp.impl.md",
      "---\nsource-spec: gp.spec.md\n---\n## Strategy\nGP strategy.",
    );
    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "extends: gp.impl.md",
        "---",
        "## Strategy",
        "Parent strategy.",
      ].join("\n"),
    );
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: parent.impl.md",
        "---",
        "## Strategy",
        "Child strategy.",
      ].join("\n"),
    );

    const result = await rippleCheck(["gp.spec.md"], tmp);
    expect(result.layers.concrete.ghostStaleImpls).toContain("parent.impl.md");
    expect(result.layers.concrete.ghostStaleImpls).toContain("child.impl.md");
  });

  it("extends combined with concrete-dependencies: both edge types propagate", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "base.spec.md", "---\n---\n# Base");
    await writeAt(tmp, "util.spec.md", "---\n---\n# Util");
    await writeAt(tmp, "child.spec.md", "---\n---\n# Child");

    await writeAt(
      tmp,
      "base.impl.md",
      "---\nsource-spec: base.spec.md\n---\n## Strategy\nBase.",
    );
    await writeAt(
      tmp,
      "util.impl.md",
      "---\nsource-spec: util.spec.md\n---\n## Strategy\nUtil.",
    );
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: base.impl.md",
        "concrete-dependencies:",
        "  - util.impl.md",
        "---",
        "## Strategy",
        "Child.",
      ].join("\n"),
    );

    // Change base -- child should be ghost-stale via extends
    const result1 = await rippleCheck(["base.spec.md"], tmp);
    expect(result1.layers.concrete.ghostStaleImpls).toContain("child.impl.md");

    clearDAGCache();

    // Change util -- child should be ghost-stale via concrete-dependency
    const result2 = await rippleCheck(["util.spec.md"], tmp);
    expect(result2.layers.concrete.ghostStaleImpls).toContain("child.impl.md");
  });

  it("no extends: single impl with no chain is not ghost-stale", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\n---\n## Strategy\nA.",
    );

    const result = await rippleCheck(["a.spec.md"], tmp);
    expect(result.layers.concrete.ghostStaleImpls).toEqual([]);
    expect(result.layers.concrete.affectedImpls).toContain("a.impl.md");
  });
});
