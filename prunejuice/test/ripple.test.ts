import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm, readFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { rippleCheck } from "../src/ripple.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader, formatManifestLine } from "../src/hashchain.js";
import {
  writeImplementationFiles,
  ensureStore,
  saveConcreteSpec,
} from "../src/store.js";
import type {
  TruncatedHash,
  ConcreteSpec,
  Implementation,
} from "../src/types.js";

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
    // Diagnostic content must reflect what actually changed, not just exist
    expect(ghostEntry!.diagnostic!.changedSpec).toBe("a.impl.md");
    expect(ghostEntry!.diagnostic!.changeHash).toBe(truncatedHash(aImplContent));
    expect(ghostEntry!.diagnostic!.chain).toContain("a.impl.md");
    expect(ghostEntry!.diagnostic!.manifestDiff.changed).toEqual(["a.impl.md"]);
  });

  it("ghost-stale managed entry without stored manifest has undefined diagnostic", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Same setup as above but no managed file, so no stored manifest to diff against
    await writeAt(tmp, "a.spec.md", "---\n---\n# A");
    await writeAt(tmp, "b.spec.md", "---\n---\n# B");
    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\n---\n## Strategy\nA.",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      [
        "---",
        "source-spec: b.spec.md",
        "concrete-dependencies:",
        "  - a.impl.md",
        "---",
      ].join("\n"),
    );

    const result = await rippleCheck(["a.spec.md"], tmp);
    const ghostEntry = result.layers.code.ghostStale.find(
      (e) => e.concrete === "b.impl.md",
    );
    expect(ghostEntry).toBeDefined();
    expect(ghostEntry!.diagnostic).toBeUndefined();
  });

  it("exposes concreteEdges including extends relationships", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "parent.spec.md", "---\n---\n# Parent");
    await writeAt(tmp, "child.spec.md", "---\n---\n# Child");
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nP.",
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
        "C.",
      ].join("\n"),
    );

    const result = await rippleCheck(["parent.spec.md"], tmp);

    // child.spec.md depends on parent.spec.md via the extends edge on the impl files
    expect(result.concreteEdges["child.spec.md"]).toContain("parent.spec.md");
  });

  it("concreteEdges deduplicates when extends and concrete-dependencies point to same parent", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "parent.spec.md", "---\n---\n# Parent");
    await writeAt(tmp, "child.spec.md", "---\n---\n# Child");
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nP.",
    );
    // child extends parent.impl.md AND lists it in concrete-dependencies
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: parent.impl.md",
        "concrete-dependencies:",
        "  - parent.impl.md",
        "---",
        "## Strategy",
        "C.",
      ].join("\n"),
    );

    const result = await rippleCheck(["parent.spec.md"], tmp);

    // Should appear exactly once, not twice
    const childDeps = result.concreteEdges["child.spec.md"];
    expect(childDeps).toBeDefined();
    expect(childDeps!.filter((d) => d === "parent.spec.md")).toHaveLength(1);
  });

  // -- End-to-end ghost staleness regression -------------------------------
  //
  // This test goes through the REAL write pipeline (writeImplementationFiles)
  // rather than simulating the header via formatManifestLine directly. It
  // would have caught the Phase 6 gap where writeManagedFile never wrote the
  // concrete-manifest line, leaving diagnoseGhostStaleness with no stored
  // manifest to diff against in production.
  //
  // Flow:
  //   1. Seed a managed store
  //   2. Create upstream `base.impl.md` with some content
  //   3. Create downstream `retry.py.impl.md` with concrete-dependencies: [base]
  //   4. writeImplementationFiles('retry.py') -- the REAL write path
  //   5. Mutate the upstream base.impl.md content
  //   6. rippleCheck(['base.spec.md'])
  //   7. Assert the ghost-stale entry for retry.py has a populated diagnostic
  //
  // If writeImplementationFiles doesn't wire the concrete-manifest line,
  // step 7 fails with diagnostic === undefined (the gap).

  it("populates ghost diagnostic end-to-end through writeImplementationFiles", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // 1. Seed the prunejuice store with a ConcreteSpec artifact so
    //    writeManagedFile can compute specHash.
    await ensureStore(tmp);
    const concreteSpec: ConcreteSpec = {
      existingPatterns: [],
      integrationPoints: [],
      fileTargets: ["src/retry.py"],
      strategyProjection: "retry wrapping base",
      refinedSpec: {
        intent: "retry wraps base",
        requirements: [],
        constraints: [],
        acceptanceCriteria: [],
      },
      behaviourContract: {
        name: "retry",
        preconditions: [],
        postconditions: [],
        invariants: [],
        scenarios: [],
      },
      discovered: [],
    };
    await saveConcreteSpec(tmp, concreteSpec);

    // 2. Create abstract spec files so rippleCheck can find them
    await writeAt(tmp, "src/base.spec.md", "---\n---\n# Base spec");
    await writeAt(tmp, "src/retry.py.spec.md", "---\n---\n# Retry spec");

    // 3. Create upstream .impl.md file with initial content.
    //    Note: source-spec is resolved relative to the impl file's directory
    //    (not cwd), so an impl at src/base.impl.md uses source-spec: base.spec.md
    //    to reference src/base.spec.md.
    const baseImplContentV1 =
      "---\nsource-spec: base.spec.md\n---\n## Strategy\nBase strategy v1.";
    await writeAt(tmp, "src/base.impl.md", baseImplContentV1);

    // 4. Create downstream .impl.md declaring a concrete-dependency on base.
    //    concrete-dependencies, unlike source-spec, are cwd-relative paths.
    await writeAt(
      tmp,
      "src/retry.py.impl.md",
      [
        "---",
        "source-spec: retry.py.spec.md",
        "concrete-dependencies:",
        "  - src/base.impl.md",
        "---",
        "",
        "## Strategy",
        "Retry wraps base.",
      ].join("\n"),
    );

    // 5. Write the managed file via the REAL write pipeline.
    //    writeImplementationFiles should auto-discover src/retry.py.impl.md
    //    via the conventional <managed-file>.impl.md lookup and emit a
    //    concrete-manifest line in the header.
    const implementation: Implementation = {
      files: [
        { path: "src/retry.py", content: "def retry(): pass\n" },
      ],
      summary: "retry impl",
    };
    await writeImplementationFiles(tmp, implementation, "2026-04-05T00:00:00Z");

    // Sanity check: the written header actually contains a concrete-manifest
    // line pointing at base.impl.md. If this fails, the write path is broken.
    const writtenRetry = await readFile(join(tmp, "src/retry.py"), "utf-8");
    expect(writtenRetry).toContain("concrete-manifest:");
    expect(writtenRetry).toContain(
      `src/base.impl.md:${truncatedHash(baseImplContentV1)}`,
    );

    // 6. Mutate the upstream -- ghost staleness trigger.
    //    Keep source-spec consistent with V1 (relative to impl's dir).
    const baseImplContentV2 =
      "---\nsource-spec: base.spec.md\n---\n## Strategy\nBase strategy v2 (changed).";
    await writeAt(tmp, "src/base.impl.md", baseImplContentV2);

    // 7. Run ripple check from the changed upstream. retry.py should be
    //    ghost-stale AND its entry should carry a populated diagnostic.
    clearDAGCache();
    const result = await rippleCheck(["src/base.spec.md"], tmp);

    const ghostEntry = result.layers.code.ghostStale.find(
      (e) => e.managed === "src/retry.py",
    );
    expect(ghostEntry).toBeDefined();
    expect(ghostEntry!.currentState).toBe("ghost-stale");

    // THE CRITICAL ASSERTION: diagnostic must be populated, not undefined.
    // This is what fails if the write path doesn't emit concrete-manifest.
    expect(ghostEntry!.diagnostic).toBeDefined();
    expect(ghostEntry!.diagnostic!.changedSpec).toBe("src/base.impl.md");
    expect(ghostEntry!.diagnostic!.chain).toContain("src/base.impl.md");
  });
});
