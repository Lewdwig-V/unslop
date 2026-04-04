import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  diffConcreteManifests,
  computeConcreteManifest,
  computeConcreteDepsHash,
} from "../src/manifest.js";
import type { TruncatedHash } from "../src/types.js";
import { MISSING_SENTINEL } from "../src/types.js";
import { truncatedHash } from "../src/hashchain.js";

function h(s: string): TruncatedHash {
  return s as TruncatedHash;
}

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "manifest-test-"));
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

describe("diffConcreteManifests", () => {
  it("detects added dependencies", () => {
    const previous = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const current = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
      ["auth.impl.md", h("bbbbbbbbbbbb")],
    ]);
    const diff = diffConcreteManifests(previous, current);
    expect(diff.added).toEqual(["auth.impl.md"]);
    expect(diff.removed).toEqual([]);
    expect(diff.changed).toEqual([]);
  });

  it("detects removed dependencies", () => {
    const previous = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
      ["auth.impl.md", h("bbbbbbbbbbbb")],
    ]);
    const current = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const diff = diffConcreteManifests(previous, current);
    expect(diff.added).toEqual([]);
    expect(diff.removed).toEqual(["auth.impl.md"]);
    expect(diff.changed).toEqual([]);
  });

  it("detects changed dependencies", () => {
    const previous = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const current = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("bbbbbbbbbbbb")],
    ]);
    const diff = diffConcreteManifests(previous, current);
    expect(diff.added).toEqual([]);
    expect(diff.removed).toEqual([]);
    expect(diff.changed).toEqual(["pool.impl.md"]);
  });

  it("returns empty diff for identical manifests", () => {
    const manifest = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const diff = diffConcreteManifests(manifest, manifest);
    expect(diff.added).toEqual([]);
    expect(diff.removed).toEqual([]);
    expect(diff.changed).toEqual([]);
  });

  it("handles empty previous (all added)", () => {
    const previous = new Map<string, TruncatedHash>();
    const current = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const diff = diffConcreteManifests(previous, current);
    expect(diff.added).toEqual(["pool.impl.md"]);
  });

  it("handles empty current (all removed)", () => {
    const previous = new Map<string, TruncatedHash>([
      ["pool.impl.md", h("aaaaaaaaaaaa")],
    ]);
    const current = new Map<string, TruncatedHash>();
    const diff = diffConcreteManifests(previous, current);
    expect(diff.removed).toEqual(["pool.impl.md"]);
  });

  it("sorts output arrays alphabetically", () => {
    const previous = new Map<string, TruncatedHash>([
      ["z.impl.md", h("aaaaaaaaaaaa")],
      ["a.impl.md", h("bbbbbbbbbbbb")],
    ]);
    const current = new Map<string, TruncatedHash>([
      ["z.impl.md", h("cccccccccccc")],
      ["a.impl.md", h("dddddddddddd")],
    ]);
    const diff = diffConcreteManifests(previous, current);
    expect(diff.changed).toEqual(["a.impl.md", "z.impl.md"]);
  });
});

describe("computeConcreteManifest", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns per-dependency hash map for direct deps", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const poolContent = [
      "---",
      "source-spec: pool.spec.md",
      "---",
      "",
      "## Strategy",
      "Connection pooling.",
    ].join("\n");

    await writeAt(tmp, "pool.impl.md", poolContent);
    await writeAt(
      tmp,
      "handler.impl.md",
      [
        "---",
        "source-spec: handler.spec.md",
        "concrete-dependencies:",
        "  - pool.impl.md",
        "---",
      ].join("\n"),
    );

    const manifest = await computeConcreteManifest("handler.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.size).toBe(1);
    expect(manifest!.get("pool.impl.md")).toBe(truncatedHash(poolContent));
  });

  it("returns null when spec has no dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "simple.impl.md",
      "---\nsource-spec: simple.spec.md\n---\n",
    );

    const manifest = await computeConcreteManifest("simple.impl.md", tmp);
    expect(manifest).toBeNull();
  });

  it("uses MISSING_SENTINEL for nonexistent deps", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "handler.impl.md",
      [
        "---",
        "source-spec: handler.spec.md",
        "concrete-dependencies:",
        "  - nonexistent.impl.md",
        "---",
      ].join("\n"),
    );

    const manifest = await computeConcreteManifest("handler.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.get("nonexistent.impl.md")).toBe(MISSING_SENTINEL);
  });

  it("includes extends parent in manifest", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const parentContent = [
      "---",
      "source-spec: parent.spec.md",
      "---",
      "",
      "## Strategy",
      "Base strategy v1.",
    ].join("\n");

    await writeAt(tmp, "parent.impl.md", parentContent);
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: parent.impl.md",
        "---",
      ].join("\n"),
    );

    const manifest = await computeConcreteManifest("child.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.get("parent.impl.md")).toBe(truncatedHash(parentContent));
  });

  it("walks transitive dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const coreContent = "---\nsource-spec: core.spec.md\n---\n## Strategy\nCore.";
    const utilContent = [
      "---",
      "source-spec: util.spec.md",
      "concrete-dependencies:",
      "  - core.impl.md",
      "---",
      "",
      "## Strategy",
      "Util.",
    ].join("\n");

    await writeAt(tmp, "core.impl.md", coreContent);
    await writeAt(tmp, "util.impl.md", utilContent);
    await writeAt(
      tmp,
      "handler.impl.md",
      [
        "---",
        "source-spec: handler.spec.md",
        "concrete-dependencies:",
        "  - util.impl.md",
        "---",
      ].join("\n"),
    );

    const manifest = await computeConcreteManifest("handler.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.has("util.impl.md")).toBe(true);
    expect(manifest!.has("core.impl.md")).toBe(true);
  });

  it("handles cycles in dependency graph without infinite loop", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "a.impl.md",
      [
        "---",
        "source-spec: a.spec.md",
        "concrete-dependencies:",
        "  - b.impl.md",
        "---",
      ].join("\n"),
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

    const manifest = await computeConcreteManifest("a.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.has("b.impl.md")).toBe(true);
  });

  it("deduplicates when same dep appears via extends and concrete-dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const baseContent = "---\nsource-spec: base.spec.md\n---\n## Strategy\nBase.";
    await writeAt(tmp, "base.impl.md", baseContent);
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: base.impl.md",
        "concrete-dependencies:",
        "  - base.impl.md",
        "---",
      ].join("\n"),
    );

    const manifest = await computeConcreteManifest("child.impl.md", tmp);
    expect(manifest).not.toBeNull();
    expect(manifest!.size).toBe(1);
    expect(manifest!.get("base.impl.md")).toBe(truncatedHash(baseContent));
  });
});

describe("computeConcreteDepsHash", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("changes when upstream impl content changes", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const poolV1 = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nSync pool.";
    await writeAt(tmp, "pool.impl.md", poolV1);
    await writeAt(
      tmp,
      "handler.impl.md",
      "---\nsource-spec: handler.spec.md\nconcrete-dependencies:\n  - pool.impl.md\n---",
    );

    const hash1 = await computeConcreteDepsHash("handler.impl.md", tmp);
    const poolV2 = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nAsync pool.";
    await writeAt(tmp, "pool.impl.md", poolV2);
    const hash2 = await computeConcreteDepsHash("handler.impl.md", tmp);

    expect(hash1).not.toBeNull();
    expect(hash2).not.toBeNull();
    expect(hash1).not.toBe(hash2);
  });

  it("returns null when spec has no dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "simple.impl.md",
      "---\nsource-spec: simple.spec.md\n---\n",
    );

    const hash = await computeConcreteDepsHash("simple.impl.md", tmp);
    expect(hash).toBeNull();
  });

  it("still produces hash when declared dep is missing", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(
      tmp,
      "handler.impl.md",
      "---\nsource-spec: handler.spec.md\nconcrete-dependencies:\n  - nonexistent.impl.md\n---",
    );

    const hash = await computeConcreteDepsHash("handler.impl.md", tmp);
    expect(hash).not.toBeNull();
  });

  it("changes when extends parent content changes", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const parentV1 = "---\nsource-spec: parent.spec.md\n---\n## Strategy\nBase v1.";
    await writeAt(tmp, "parent.impl.md", parentV1);
    await writeAt(
      tmp,
      "child.impl.md",
      "---\nsource-spec: child.spec.md\nextends: parent.impl.md\n---",
    );

    const hash1 = await computeConcreteDepsHash("child.impl.md", tmp);
    const parentV2 = "---\nsource-spec: parent.spec.md\n---\n## Strategy\nBase v2.";
    await writeAt(tmp, "parent.impl.md", parentV2);
    const hash2 = await computeConcreteDepsHash("child.impl.md", tmp);

    expect(hash1).not.toBe(hash2);
  });

  it("incorporates both extends and concrete-dependencies", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const parentContent = "---\nsource-spec: parent.spec.md\n---\n## Strategy\nParent.";
    const poolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nPool.";

    await writeAt(tmp, "parent.impl.md", parentContent);
    await writeAt(tmp, "pool.impl.md", poolContent);
    await writeAt(
      tmp,
      "child.impl.md",
      [
        "---",
        "source-spec: child.spec.md",
        "extends: parent.impl.md",
        "concrete-dependencies:",
        "  - pool.impl.md",
        "---",
      ].join("\n"),
    );

    const hash1 = await computeConcreteDepsHash("child.impl.md", tmp);
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nParent v2.",
    );
    const hash2 = await computeConcreteDepsHash("child.impl.md", tmp);

    expect(hash1).not.toBe(hash2);
  });
});
