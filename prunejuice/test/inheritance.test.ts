import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  resolveExtendsChain,
  InheritanceCycleError,
  MAX_EXTENDS_DEPTH,
  extractSections,
  mergePatternSections,
  mergeLoweringNotes,
} from "../src/inheritance.js";
import { flattenInheritanceChain } from "../src/inheritance.js";

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

describe("extractSections", () => {
  it("extracts sections under ## headings", () => {
    const content = [
      "---",
      "source-spec: a.spec.md",
      "---",
      "",
      "## Strategy",
      "Use connection pooling.",
      "",
      "## Pattern",
      "- **Concurrency**: async",
    ].join("\n");

    const sections = extractSections(content);
    expect(sections.get("Strategy")).toBe("Use connection pooling.");
    expect(sections.get("Pattern")).toBe("- **Concurrency**: async");
  });

  it("returns empty map when no sections present", () => {
    const content = "---\nsource-spec: a.spec.md\n---\n\nJust prose.";
    const sections = extractSections(content);
    expect(sections.size).toBe(0);
  });

  it("strips frontmatter before extracting", () => {
    const content = [
      "---",
      "source-spec: a.spec.md",
      "## not-a-section-heading-in-frontmatter",
      "---",
      "",
      "## Real Section",
      "Content.",
    ].join("\n");

    const sections = extractSections(content);
    expect(sections.size).toBe(1);
    expect(sections.get("Real Section")).toBe("Content.");
  });

  it("handles content without frontmatter", () => {
    const content = "## Strategy\nPool.\n\n## Pattern\n- **Key**: Value";
    const sections = extractSections(content);
    expect(sections.get("Strategy")).toBe("Pool.");
    expect(sections.get("Pattern")).toBe("- **Key**: Value");
  });
});

describe("mergePatternSections", () => {
  it("child overrides parent keys by name", () => {
    const parent = "- **Concurrency**: async\n- **DI**: annotated";
    const child = "- **Concurrency**: threaded";
    const merged = mergePatternSections(parent, child);
    expect(merged).toContain("- **Concurrency**: threaded");
    expect(merged).toContain("- **DI**: annotated");
  });

  it("parent keys preserved when child omits them", () => {
    const parent = "- **Concurrency**: async\n- **Backpressure**: bounded";
    const child = "- **Concurrency**: threaded";
    const merged = mergePatternSections(parent, child);
    expect(merged).toContain("- **Backpressure**: bounded");
  });

  it("handles empty child (all parent preserved)", () => {
    const parent = "- **A**: 1\n- **B**: 2";
    const child = "";
    const merged = mergePatternSections(parent, child);
    expect(merged).toContain("- **A**: 1");
    expect(merged).toContain("- **B**: 2");
  });
});

describe("mergeLoweringNotes", () => {
  it("merges language blocks, child overrides matching languages", () => {
    const parent = [
      "### Python",
      "Use asyncio",
      "",
      "### Go",
      "Use goroutines",
    ].join("\n");
    const child = ["### Python", "Use trio instead"].join("\n");

    const merged = mergeLoweringNotes(parent, child);
    expect(merged).toContain("### Python");
    expect(merged).toContain("Use trio instead");
    expect(merged).not.toContain("Use asyncio");
    expect(merged).toContain("### Go");
    expect(merged).toContain("Use goroutines");
  });

  it("child adds new language blocks", () => {
    const parent = "### Python\nUse asyncio";
    const child = "### TypeScript\nUse Promises";
    const merged = mergeLoweringNotes(parent, child);
    expect(merged).toContain("### Python");
    expect(merged).toContain("Use asyncio");
    expect(merged).toContain("### TypeScript");
    expect(merged).toContain("Use Promises");
  });
});

describe("flattenInheritanceChain", () => {
  const dirs2: string[] = [];

  afterEach(async () => {
    for (const d of dirs2.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns child-only sections when no extends", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "a.impl.md",
      [
        "---",
        "source-spec: a.spec.md",
        "---",
        "",
        "## Strategy",
        "Direct strategy.",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("a.impl.md", tmp);

    expect(result.chain).toEqual(["a.impl.md"]);
    expect(result.sections.get("Strategy")?.content).toBe("Direct strategy.");
    expect(result.sections.get("Strategy")?.source).toBe("a.impl.md");
    expect(result.sections.get("Strategy")?.rule).toBe("strict_child_only");
  });

  it("STRICT_CHILD_ONLY: child Strategy completely replaces parent Strategy", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "---",
        "",
        "## Strategy",
        "Parent strategy -- should NOT appear.",
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
        "",
        "## Strategy",
        "Child strategy -- wins.",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);

    const strategy = result.sections.get("Strategy");
    expect(strategy?.content).toBe("Child strategy -- wins.");
    expect(strategy?.source).toBe("child.impl.md");
    expect(strategy?.rule).toBe("strict_child_only");
  });

  it("STRICT_CHILD_ONLY: parent Strategy purged even when child has no Strategy", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "---",
        "",
        "## Strategy",
        "Parent strategy -- should be purged.",
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
        "",
        "## Pattern",
        "- **Key**: Value",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);

    // Strategy is STRICT_CHILD_ONLY: since child doesn't define it, it's absent from resolved
    expect(result.sections.has("Strategy")).toBe(false);
    // Pattern comes from child
    expect(result.sections.get("Pattern")?.content).toBe("- **Key**: Value");
  });

  it("Overridable: child Pattern merges with parent Pattern by key", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "---",
        "",
        "## Pattern",
        "- **Concurrency**: async",
        "- **Backpressure**: bounded",
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
        "",
        "## Pattern",
        "- **Concurrency**: threaded",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);
    const pattern = result.sections.get("Pattern")!;
    expect(pattern.content).toContain("- **Concurrency**: threaded");
    expect(pattern.content).toContain("- **Backpressure**: bounded");
    expect(pattern.rule).toBe("overridable");
  });

  it("Overridable: Pattern inherited unchanged when child omits it", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "---",
        "",
        "## Pattern",
        "- **Key**: Value",
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
        "",
        "## Strategy",
        "Child strategy.",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);
    const pattern = result.sections.get("Pattern")!;
    expect(pattern.content).toBe("- **Key**: Value");
    expect(pattern.source).toBe("parent.impl.md");
  });

  it("Additive: Lowering Notes from child + parent merged with child language winning", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "---",
        "",
        "## Lowering Notes",
        "",
        "### Python",
        "Use asyncio",
        "",
        "### Go",
        "Use goroutines",
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
        "",
        "## Lowering Notes",
        "",
        "### Python",
        "Use trio",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);
    const notes = result.sections.get("Lowering Notes")!;
    // Child's Python wins
    expect(notes.content).toContain("Use trio");
    expect(notes.content).not.toContain("Use asyncio");
    // Parent's Go preserved
    expect(notes.content).toContain("Use goroutines");
    expect(notes.rule).toBe("additive");
  });

  it("two-level chain: grandparent Pattern inherited to child through parent", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "gp.impl.md",
      [
        "---",
        "source-spec: gp.spec.md",
        "---",
        "",
        "## Pattern",
        "- **Base**: value",
      ].join("\n"),
    );
    await writeAt(
      tmp,
      "parent.impl.md",
      [
        "---",
        "source-spec: parent.spec.md",
        "extends: gp.impl.md",
        "---",
        "",
        "## Pattern",
        "- **Middle**: value",
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
        "",
        "## Strategy",
        "Child.",
      ].join("\n"),
    );

    const result = await flattenInheritanceChain("child.impl.md", tmp);
    expect(result.chain).toEqual(["child.impl.md", "parent.impl.md", "gp.impl.md"]);
    const pattern = result.sections.get("Pattern")!;
    expect(pattern.content).toContain("- **Base**: value");
    expect(pattern.content).toContain("- **Middle**: value");
  });

  it("throws InheritanceCycleError on cyclic extends", async () => {
    const tmp = await makeTmp();
    dirs2.push(tmp);

    await writeAt(
      tmp,
      "a.impl.md",
      "---\nsource-spec: a.spec.md\nextends: b.impl.md\n---\n",
    );
    await writeAt(
      tmp,
      "b.impl.md",
      "---\nsource-spec: b.spec.md\nextends: a.impl.md\n---\n",
    );

    await expect(flattenInheritanceChain("a.impl.md", tmp)).rejects.toThrow(
      InheritanceCycleError,
    );
  });
});
