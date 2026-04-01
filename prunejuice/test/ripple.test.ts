import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { rippleCheck } from "../src/ripple.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";
import type { TruncatedHash } from "../src/types.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "ripple-test-"));
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

describe("rippleCheck", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("traces abstract layer: directly changed + transitively affected", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Chain: b depends on a, c depends on b → ripple from a hits b and c
    await writeAt(tmp, "a.spec.md", "---\ntitle: A\n---\n# A");
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# B",
    );
    await writeAt(
      tmp,
      "c.spec.md",
      "---\ndepends-on:\n  - b.spec.md\n---\n# C",
    );

    const result = await rippleCheck(["a.spec.md"], tmp);

    expect(result.layers.abstract.directlyChanged).toEqual(["a.spec.md"]);
    expect(result.layers.abstract.transitivelyAffected).toContain("b.spec.md");
    expect(result.layers.abstract.transitivelyAffected).toContain("c.spec.md");
    expect(result.layers.abstract.total).toBe(3);
  });

  it("populates code layer with managed file entries", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Create spec in src/ subdir, no managed file
    await writeAt(
      tmp,
      "src/x.ts.spec.md",
      "---\ntitle: X\n---\n# X implementation",
    );

    const result = await rippleCheck(["src/x.ts.spec.md"], tmp);

    expect(result.layers.code.regenerate.length).toBe(1);
    const entry = result.layers.code.regenerate[0]!;
    expect(entry.managed).toBe("src/x.ts");
    expect(entry.exists).toBe(false);
    expect(entry.currentState).toBe("new");
    expect(entry.cause).toBe("direct");
  });

  it("includes build order for affected specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // b depends on a → ripple from a. Build order: a first (leaf), then b
    await writeAt(tmp, "a.spec.md", "---\ntitle: A\n---\n# A");
    await writeAt(
      tmp,
      "b.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# B",
    );

    const result = await rippleCheck(["a.spec.md"], tmp);

    expect(result.buildOrder).toEqual(["a.spec.md", "b.spec.md"]);
  });

  it("returns empty layers when spec has no dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "leaf.spec.md", "---\ntitle: Leaf\n---\n# Leaf");

    const result = await rippleCheck(["leaf.spec.md"], tmp);

    expect(result.layers.abstract.directlyChanged).toEqual(["leaf.spec.md"]);
    expect(result.layers.abstract.transitivelyAffected).toEqual([]);
    expect(result.layers.abstract.total).toBe(1);
  });

  it("handles multiple input specs", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.spec.md", "---\ntitle: A\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\ntitle: B\n---\n# B");
    await writeAt(
      tmp,
      "c.spec.md",
      "---\ndepends-on:\n  - a.spec.md\n---\n# C",
    );

    const result = await rippleCheck(["a.spec.md", "b.spec.md"], tmp);

    expect(result.inputSpecs).toContain("a.spec.md");
    expect(result.inputSpecs).toContain("b.spec.md");
    expect(result.layers.abstract.directlyChanged).toContain("a.spec.md");
    expect(result.layers.abstract.directlyChanged).toContain("b.spec.md");
  });

  it("classifies existing managed files by freshness state", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\ntitle: Fresh\n---\n# Fresh spec";
    const bodyContent = "console.log('hello');";

    await writeAt(tmp, "app.ts.spec.md", specContent);
    await writeAt(tmp, "app.ts", managedFile(specContent, bodyContent));

    const result = await rippleCheck(["app.ts.spec.md"], tmp);

    expect(result.layers.code.regenerate.length).toBe(1);
    const entry = result.layers.code.regenerate[0]!;
    expect(entry.exists).toBe(true);
    expect(entry.currentState).toBe("fresh");
  });
});
