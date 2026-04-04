import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  resolveExtendsChain,
  InheritanceCycleError,
  MAX_EXTENDS_DEPTH,
} from "../src/inheritance.js";

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "inheritance-test-"));
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

describe("resolveExtendsChain", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns single-element chain for spec with no extends", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\n---\n## Strategy\nA.",
    );

    const chain = await resolveExtendsChain("a.impl.md", tmp);
    expect(chain).toEqual(["a.impl.md"]);
  });

  it("returns two-element chain for single extends", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nParent.",
    );
    await writeAt(
      tmp,
      "child.impl.md",
      "---\nsource-spec: child.spec.md\nextends: parent.impl.md\n---\n## Strategy\nChild.",
    );

    const chain = await resolveExtendsChain("child.impl.md", tmp);
    expect(chain).toEqual(["child.impl.md", "parent.impl.md"]);
  });

  it("returns three-element chain for two-level extends", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "gp.impl.md",
      "---\nsource-spec: gp.spec.md\n---\n## Strategy\nGP.",
    );
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\nextends: gp.impl.md\n---\n## Strategy\nParent.",
    );
    await writeAt(
      tmp,
      "child.impl.md",
      "---\nsource-spec: child.spec.md\nextends: parent.impl.md\n---\n## Strategy\nChild.",
    );

    const chain = await resolveExtendsChain("child.impl.md", tmp);
    expect(chain).toEqual(["child.impl.md", "parent.impl.md", "gp.impl.md"]);
  });

  it("throws InheritanceCycleError on a extends b extends a", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\nextends: b.impl.md\n---\n## Strategy\nA.",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\nextends: a.impl.md\n---\n## Strategy\nB.",
    );

    await expect(resolveExtendsChain("a.impl.md", tmp)).rejects.toThrow(
      InheritanceCycleError,
    );
  });

  it("throws on chain exceeding MAX_EXTENDS_DEPTH", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Chain of 4: a -> b -> c -> d (exceeds depth=3)
    await writeAt(tmp, "d.impl.md", "---\nsource-spec: d.spec.md\n---\n");
    await writeAt(
      tmp,
      "c.impl.md",
      "---\nsource-spec: c.spec.md\nextends: d.impl.md\n---\n",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\nextends: c.impl.md\n---\n",
    );
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\nextends: b.impl.md\n---\n",
    );

    await expect(resolveExtendsChain("a.impl.md", tmp)).rejects.toThrow(
      /exceeds maximum depth/,
    );
  });

  it("throws when parent in extends chain does not exist", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "child.impl.md",
      "---\nsource-spec: child.spec.md\nextends: missing.impl.md\n---\n",
    );

    await expect(resolveExtendsChain("child.impl.md", tmp)).rejects.toThrow(
      /Missing parent/,
    );
  });

  it("returns single-element chain when impl file itself does not exist", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const chain = await resolveExtendsChain("ghost.impl.md", tmp);
    expect(chain).toEqual(["ghost.impl.md"]);
  });

  it("exports MAX_EXTENDS_DEPTH=3", () => {
    expect(MAX_EXTENDS_DEPTH).toBe(3);
  });
});
