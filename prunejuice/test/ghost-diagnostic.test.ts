import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  diagnoseGhostStaleness,
  formatGhostDiagnostic,
} from "../src/manifest.js";
import { truncatedHash } from "../src/hashchain.js";
import type { TruncatedHash, GhostStaleDiagnostic } from "../src/types.js";
import { MISSING_SENTINEL } from "../src/types.js";

function h(s: string): TruncatedHash {
  return s as TruncatedHash;
}

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "ghost-diag-test-"));
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

describe("diagnoseGhostStaleness", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("detects changed dep by comparing manifest hash vs current content", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const oldPoolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nSync pool.";
    const newPoolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nAsync pool.";
    await writeAt(tmp, "pool.impl.md", newPoolContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["pool.impl.md", truncatedHash(oldPoolContent)],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("pool.impl.md");
    expect(diagnostics[0]!.chain).toContain("pool.impl.md");
    expect(diagnostics[0]!.manifestDiff.changed).toContain("pool.impl.md");
  });

  it("reports missing dep", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const storedManifest = new Map<string, TruncatedHash>([
      ["nonexistent.impl.md", h("a3f8c2e9b7d1")],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("nonexistent.impl.md");
    expect(diagnostics[0]!.chain).toEqual(["nonexistent.impl.md"]);
  });

  it("returns empty diagnostics when all deps are fresh", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const poolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nPool.";
    await writeAt(tmp, "pool.impl.md", poolContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["pool.impl.md", truncatedHash(poolContent)],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);
    expect(diagnostics).toEqual([]);
  });

  it("missing sentinel in stored manifest: dep now exists reports changed", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const revivedContent = "---\nsource-spec: revived.spec.md\n---\n## Strategy\nRevived.";
    await writeAt(tmp, "revived.impl.md", revivedContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["revived.impl.md", MISSING_SENTINEL],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("revived.impl.md");
  });

  it("missing sentinel in stored manifest: dep still missing reports no change", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const storedManifest = new Map<string, TruncatedHash>([
      ["still-missing.impl.md", MISSING_SENTINEL],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);
    expect(diagnostics).toEqual([]);
  });

  it("traces through deep dep chain for root cause", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const utilsContent = "---\nsource-spec: utils.spec.md\n---\n## Strategy\nUtils v2.";
    const serviceContent = [
      "---",
      "source-spec: service.spec.md",
      "concrete-dependencies:",
      "  - utils.impl.md",
      "---",
      "",
      "## Strategy",
      "Service.",
    ].join("\n");

    await writeAt(tmp, "utils.impl.md", utilsContent);
    await writeAt(tmp, "service.impl.md", serviceContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["service.impl.md", h("000000000000")],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("service.impl.md");
    expect(diagnostics[0]!.chain.length).toBeGreaterThanOrEqual(1);
  });

  it("manifest diff is computed against full current state, not partial", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Two deps: a changed, b unchanged. The manifestDiff must not report b as removed.
    const aContentOld = "---\nsource-spec: a.spec.md\n---\n## Strategy\nA v1.";
    const aContentNew = "---\nsource-spec: a.spec.md\n---\n## Strategy\nA v2.";
    const bContent = "---\nsource-spec: b.spec.md\n---\n## Strategy\nB.";

    await writeAt(tmp, "a.impl.md", aContentNew);
    await writeAt(tmp, "b.impl.md", bContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["a.impl.md", truncatedHash(aContentOld)],
      ["b.impl.md", truncatedHash(bContent)],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("a.impl.md");
    // The key assertion: b.impl.md must NOT appear in removed
    expect(diagnostics[0]!.manifestDiff.removed).toEqual([]);
    expect(diagnostics[0]!.manifestDiff.changed).toEqual(["a.impl.md"]);
  });
});

describe("formatGhostDiagnostic", () => {
  it("formats single changed dep", () => {
    const diag: GhostStaleDiagnostic = {
      changedSpec: "pool.impl.md",
      changeHash: h("bbbbbbbbbbbb"),
      chain: ["pool.impl.md"],
      manifestDiff: { added: [], removed: [], changed: ["pool.impl.md"] },
    };

    const line = formatGhostDiagnostic(diag);
    expect(line).toContain("pool.impl.md");
    expect(line).toContain("changed");
  });

  it("formats deep chain with via annotation", () => {
    const diag: GhostStaleDiagnostic = {
      changedSpec: "service.impl.md",
      changeHash: h("bbbbbbbbbbbb"),
      chain: ["service.impl.md", "utils.impl.md"],
      manifestDiff: { added: [], removed: [], changed: ["service.impl.md"] },
    };

    const line = formatGhostDiagnostic(diag);
    expect(line).toContain("service.impl.md");
    expect(line).toContain("via");
    expect(line).toContain("utils.impl.md");
  });

  it("formats missing dep", () => {
    const diag: GhostStaleDiagnostic = {
      changedSpec: "gone.impl.md",
      changeHash: MISSING_SENTINEL,
      chain: ["gone.impl.md"],
      manifestDiff: { added: [], removed: ["gone.impl.md"], changed: [] },
    };

    const line = formatGhostDiagnostic(diag);
    expect(line).toContain("gone.impl.md");
    expect(line).toContain("not found");
  });
});
