import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { rippleCheck } from "../src/ripple.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader, formatManifestLine } from "../src/hashchain.js";
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

  it("traces concrete layer through impl files with source-spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Abstract spec a, concrete impl points to a
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\n---\n# Impl A",
    );

    const result = await rippleCheck(["a.spec.md"], tmp);
    expect(result.layers.concrete.affectedImpls).toContain("a.impl.md");
    expect(result.layers.concrete.total).toBeGreaterThanOrEqual(1);
  });

  it("detects ghost-stale impls through concrete-dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // a.spec.md is changed (input spec)
    // a.impl.md has source-spec: a.spec.md (directly affected)
    // b.impl.md has concrete-dependencies pointing to a.impl.md but source-spec: b.spec.md
    // b.spec.md is NOT in the input -- so b.impl.md is ghost-stale
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\n---\n# Impl A",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\nconcrete-dependencies:\n  - a.impl.md\n---\n# Impl B",
    );

    const result = await rippleCheck(["a.spec.md"], tmp);
    expect(result.layers.concrete.ghostStaleImpls).toContain("b.impl.md");
    expect(result.layers.code.ghostStale.length).toBeGreaterThanOrEqual(1);
    const ghostEntry = result.layers.code.ghostStale.find(
      (e) => e.concrete === "b.impl.md",
    );
    expect(ghostEntry).toBeDefined();
    expect(ghostEntry!.cause).toBe("ghost-stale");
    expect(ghostEntry!.ghostSource).toBe("b.impl.md");
  });

  it("classifies stale managed files correctly", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const oldSpecContent = "---\n---\n# Original spec";
    const bodyContent = "export function widget() {}";
    // Write managed file with hashes from OLD spec
    await writeAt(tmp, "widget.ts", managedFile(oldSpecContent, bodyContent));
    // But spec has been updated (different content)
    const newSpecContent = "---\n---\n# Updated spec with changes";
    await writeAt(tmp, "widget.ts.spec.md", newSpecContent);

    const result = await rippleCheck(["widget.ts.spec.md"], tmp);
    const entry = result.layers.code.regenerate[0]!;
    expect(entry.exists).toBe(true);
    expect(entry.currentState).toBe("stale");
  });

  it("attaches GhostStaleDiagnostic to ghost-stale managed entries", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Setup: a.spec.md changed, a.impl.md is directly affected
    // b.impl.md depends on a.impl.md (concrete-dependency) but b.spec.md is not in input
    // b.impl.md should be ghost-stale WITH a diagnostic

    const aImplContent =
      "---\nsource-spec: a.spec.md\n---\n## Strategy\nA strategy.";
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(tmp, "a.impl.md", aImplContent);

    await writeAt(
      tmp,
      "b.impl.md",
      [
        "---",
        "source-spec: b.spec.md",
        "concrete-dependencies:",
        "  - a.impl.md",
        "---",
        "",
        "## Strategy",
        "B strategy.",
      ].join("\n"),
    );

    // Create a managed file for b with a stored manifest containing OLD a.impl.md hash
    const oldAImplContent =
      "---\nsource-spec: a.spec.md\n---\n## Strategy\nOLD A strategy.";
    const bBody = "console.log('b')";
    const bSpecContent = "---\n---\n# B";
    const bSpecHash = truncatedHash(bSpecContent);
    const bOutputHash = truncatedHash(bBody);
    const bHeader = formatHeader("b.spec.md", {
      specHash: bSpecHash,
      outputHash: bOutputHash,
      generated: "2026-01-01T00:00:00Z",
    });
    const oldManifest = new Map([
      ["a.impl.md", truncatedHash(oldAImplContent)],
    ]);
    const manifestLine = formatManifestLine(oldManifest);

    await writeAt(tmp, "b", `${bHeader}\n${manifestLine}\n\n${bBody}`);

    const result = await rippleCheck(["a.spec.md"], tmp);

    const ghostEntry = result.layers.code.ghostStale.find(
      (e) => e.concrete === "b.impl.md",
    );
    expect(ghostEntry).toBeDefined();
    expect(ghostEntry!.diagnostic).toBeDefined();
    expect(ghostEntry!.diagnostic!.changedSpec).toBe("a.impl.md");
  });
});
