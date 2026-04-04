# Phase 7: Inheritance Flattening + Collision Detection -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Archaeologist and Builder the resolved concrete spec view via on-demand inheritance flattening, and prevent sync plans from producing non-deterministic output when multiple concrete specs claim the same target file.

**Architecture:** New `inheritance.ts` module handles extends chain traversal and three-rule section merging (STRICT_CHILD_ONLY, additive, overridable). Collision detection lives in `sync.ts` via an extended `partitionPlan` that scans for target collisions and emits `CollisionEntry` records. `computeParallelBatches` is extended to include extends edges in its topological sort so parents build before children.

**Tech Stack:** TypeScript, vitest, SHA-256/12 (existing), temp directory fixtures

---

## File Structure

| File | Responsibility |
|------|---------------|
| `prunejuice/src/inheritance.ts` | **Create.** `resolveExtendsChain`, `flattenInheritanceChain`, section extraction, three merge rules, `InheritanceCycleError`, `MAX_EXTENDS_DEPTH=3`, `STRICT_CHILD_ONLY` set. |
| `prunejuice/src/sync.ts` | **Modify.** `partitionPlan` returns collisions. `bulkSyncPlan`/`deepSyncPlan`/`resumeSyncPlan` surface collisions in results. `computeParallelBatches` consumes extends edges from ripple. `DeepSyncOptions`/`BulkSyncOptions` gain `preferSpec?: Record<string, string>`. |
| `prunejuice/src/types.ts` | **Modify.** Add `CollisionEntry`, `FlattenedSection`, `FlattenedConcreteSpec`, `SectionMergeRule`. Add `collisions?: CollisionEntry[]` to `DeepSyncResult`/`BulkSyncResult`/`ResumeSyncResult`. |
| `prunejuice/src/ripple.ts` | **Modify.** Export `implMeta`-equivalent concrete edges (extends + concrete-dependencies) in `RippleResult` so `sync.ts` can feed them into `computeParallelBatches` without re-parsing. |
| `prunejuice/test/inheritance.test.ts` | **Create.** Contract tests for extends chain, section extraction, three merge rules, cycle/depth/missing-parent errors. |
| `prunejuice/test/collision.test.ts` | **Create.** Contract tests for collision detection, `preferSpec` resolution, blocked execution, audit trail. |
| `prunejuice/test/sync.test.ts` | **Modify.** Add tests for extends-aware build ordering in `computeParallelBatches`. |

---

### Task 1: Add Phase 7 types

**Files:**
- Modify: `prunejuice/src/types.ts`

- [ ] **Step 1: Add inheritance + collision types**

Add at the end of `prunejuice/src/types.ts`:

```typescript
// -- Inheritance flattening types --------------------------------------------

export type SectionMergeRule = "strict_child_only" | "additive" | "overridable";

export interface FlattenedSection {
  /** Resolved section content after merging. */
  readonly content: string;
  /**
   * Which spec in the chain provided this section.
   * For "overridable" sections, the most specific spec that defines the section.
   * For "additive" sections, the spec of the most specific contributor.
   * For "strict_child_only" sections, always the child.
   */
  readonly source: string;
  readonly rule: SectionMergeRule;
}

export interface FlattenedConcreteSpec {
  readonly specPath: string;
  /** Chain from child to root parent: [child, parent, grandparent, ...] */
  readonly chain: readonly string[];
  /** Resolved sections keyed by heading name (e.g. "Strategy", "Pattern"). */
  readonly sections: ReadonlyMap<string, FlattenedSection>;
}

// -- Collision detection types -----------------------------------------------

export interface CollisionEntry {
  readonly status: "collision";
  /** The target file path that multiple specs claim. */
  readonly targetPath: string;
  /** Concrete spec paths that claim this target (at least 2). */
  readonly claimants: readonly string[];
  /** When set (via preferSpec + force), names the winning claimant. */
  readonly preferSpec?: string;
  /** When preferSpec is set, the losing claimants logged for audit. */
  readonly skippedSpecs?: readonly string[];
}
```

Modify `DeepSyncResult`, `BulkSyncResult`, and `ResumeSyncResult` (around lines 292-321) to add a `collisions` field:

```typescript
export interface DeepSyncResult {
  trigger: string;
  plan: SyncPlanEntry[];
  skipped: SyncPlanEntry[];
  collisions: CollisionEntry[];
  stats: {
    totalAffected: number;
    toRegenerate: number;
    skippedNeedConfirm: number;
    freshSkipped: number;
  };
  buildOrder: string[];
}

export interface BulkSyncResult {
  batches: SyncBatch[];
  skipped: SyncPlanEntry[];
  collisions: CollisionEntry[];
  stats: {
    totalStale: number;
    totalBatches: number;
    toRegenerate: number;
    skippedNeedConfirm: number;
    freshSkipped: number;
  };
  buildOrder: string[];
}
```

`ResumeSyncResult` extends `BulkSyncResult` so it inherits the field automatically.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd prunejuice && npx tsc --noEmit`

Expected: errors in `sync.ts` (existing code doesn't construct the new `collisions` field yet). This is expected -- we'll fix it in Task 6.

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add src/types.ts && git commit -m "feat(types): add CollisionEntry, FlattenedConcreteSpec, SectionMergeRule"
```

Note: this commit intentionally leaves the project in a broken state (sync.ts doesn't compile). The next tasks add inheritance.ts while sync.ts is untouched, and Task 6 fixes sync.ts. If you need an atomically-green tree, complete Tasks 1-6 before pushing.

---

### Task 2: Create inheritance.ts with resolveExtendsChain

**Files:**
- Create: `prunejuice/src/inheritance.ts`
- Create: `prunejuice/test/inheritance.test.ts`

- [ ] **Step 1: Write failing tests for resolveExtendsChain**

Create `prunejuice/test/inheritance.test.ts`:

```typescript
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

    // No file written. The Python behavior is: if the starting impl is missing,
    // return [impl_path] without error (consumers decide how to handle).
    const chain = await resolveExtendsChain("ghost.impl.md", tmp);
    expect(chain).toEqual(["ghost.impl.md"]);
  });

  it("exports MAX_EXTENDS_DEPTH=3", () => {
    expect(MAX_EXTENDS_DEPTH).toBe(3);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: FAIL -- module not found.

- [ ] **Step 3: Create inheritance.ts with resolveExtendsChain**

Create `prunejuice/src/inheritance.ts`:

```typescript
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { isEnoent } from "./fs-utils.js";
import { parseConcreteSpecFrontmatter } from "./ripple.js";

// -- Constants ---------------------------------------------------------------

export const MAX_EXTENDS_DEPTH = 3;

/** Sections that always come from the child, never merged from parents. */
export const STRICT_CHILD_ONLY: ReadonlySet<string> = new Set([
  "Strategy",
  "Type Sketch",
  "Representation Invariants",
  "Safety Contracts",
  "Concurrency Model",
  "State Machine",
  "Migration Notes",
  "Error Taxonomy",
  "Test Seams",
]);

// -- Errors ------------------------------------------------------------------

export class InheritanceCycleError extends Error {
  constructor(cycle: string[]) {
    super(`Cycle detected in extends chain: ${cycle.join(" -> ")}`);
    this.name = "InheritanceCycleError";
  }
}

// -- Extends chain resolution -------------------------------------------------

/**
 * Resolve the extends chain for a concrete spec.
 *
 * Returns a list of impl paths starting from `specPath` (most specific, the
 * child) and walking up to the root parent (most general). `specPath` is
 * always the first element.
 *
 * Throws:
 *   - `InheritanceCycleError` on a cycle in the extends graph
 *   - Error with "exceeds maximum depth" message when chain > MAX_EXTENDS_DEPTH
 *   - Error with "Missing parent" message when an extends target doesn't exist
 *
 * If `specPath` itself does not exist, returns `[specPath]` without error --
 * callers decide how to handle missing starting points.
 */
export async function resolveExtendsChain(
  specPath: string,
  cwd: string,
): Promise<string[]> {
  const absCwd = resolve(cwd);
  const chain: string[] = [];
  const visited = new Set<string>();
  let current: string | null = specPath;

  while (current !== null) {
    const absPath = resolve(absCwd, current);

    if (visited.has(absPath)) {
      throw new InheritanceCycleError([...chain, current]);
    }

    chain.push(current);
    visited.add(absPath);

    if (chain.length > MAX_EXTENDS_DEPTH) {
      throw new Error(
        `Extends chain exceeds maximum depth of ${MAX_EXTENDS_DEPTH}: ${chain.join(" -> ")}. Flatten the hierarchy.`,
      );
    }

    let content: string;
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        if (chain.length === 1) {
          // Starting impl doesn't exist -- return chain as-is
          return chain;
        }
        throw new Error(
          `Missing parent concrete spec in extends chain: ${current}`,
        );
      }
      throw err;
    }

    const meta = parseConcreteSpecFrontmatter(content);
    current = meta.extends;
  }

  return chain;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/inheritance.ts test/inheritance.test.ts && git commit -m "feat(inheritance): add resolveExtendsChain with cycle/depth detection"
```

---

### Task 3: Section extraction + merge rules

**Files:**
- Modify: `prunejuice/src/inheritance.ts`
- Modify: `prunejuice/test/inheritance.test.ts`

- [ ] **Step 1: Write failing tests for section extraction and merge rules**

Add to `prunejuice/test/inheritance.test.ts` (at the end of the file):

```typescript
import {
  extractSections,
  mergePatternSections,
  mergeLoweringNotes,
} from "../src/inheritance.js";

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: the new describe blocks FAIL -- functions not exported.

- [ ] **Step 3: Implement extractSections and merge functions**

Add to `prunejuice/src/inheritance.ts`:

```typescript
// -- Section extraction ------------------------------------------------------

/**
 * Extract `## ` sections from a markdown file into a Map.
 * Strips frontmatter before scanning for headings. The map key is the heading
 * text (trimmed); the value is the section body joined with newlines and
 * stripped of leading/trailing whitespace.
 */
export function extractSections(content: string): Map<string, string> {
  const sections = new Map<string, string>();
  const lines = content.split("\n");

  // Skip frontmatter
  let bodyStart = 0;
  if (lines.length > 0 && lines[0]!.trim() === "---") {
    for (let i = 1; i < lines.length; i++) {
      if (lines[i]!.trim() === "---") {
        bodyStart = i + 1;
        break;
      }
    }
  }

  let currentName: string | null = null;
  let currentLines: string[] = [];

  for (let i = bodyStart; i < lines.length; i++) {
    const line = lines[i]!;
    const match = line.match(/^## (.+)$/);
    if (match) {
      if (currentName !== null) {
        sections.set(currentName, currentLines.join("\n").trim());
      }
      currentName = match[1]!.trim();
      currentLines = [];
    } else if (currentName !== null) {
      currentLines.push(line);
    }
  }

  if (currentName !== null) {
    sections.set(currentName, currentLines.join("\n").trim());
  }

  return sections;
}

// -- Merge rules -------------------------------------------------------------

/** Parse `- **Key**: Value` bullet lines into a Map. */
function parsePatternEntries(content: string): Map<string, string> {
  const entries = new Map<string, string>();
  for (const line of content.split("\n")) {
    const match = line.match(/^\s*-\s+\*\*(.+?)\*\*:\s*(.+)$/);
    if (match) {
      entries.set(match[1]!.trim(), match[2]!.trim());
    }
  }
  return entries;
}

/**
 * Merge two Pattern sections. Child keys override parent keys with the same name.
 * Keys only in parent are preserved.
 */
export function mergePatternSections(parent: string, child: string): string {
  const parentEntries = parsePatternEntries(parent);
  const childEntries = parsePatternEntries(child);
  const merged = new Map([...parentEntries, ...childEntries]);
  return [...merged.entries()].map(([k, v]) => `- **${k}**: ${v}`).join("\n");
}

/** Parse `### Language` blocks into a Map. */
function parseLanguageBlocks(content: string): Map<string, string> {
  const blocks = new Map<string, string>();
  let currentLang: string | null = null;
  let currentLines: string[] = [];

  for (const line of content.split("\n")) {
    const match = line.match(/^### (.+)$/);
    if (match) {
      if (currentLang !== null) {
        blocks.set(currentLang, currentLines.join("\n").trim());
      }
      currentLang = match[1]!.trim();
      currentLines = [];
    } else if (currentLang !== null) {
      currentLines.push(line);
    }
  }

  if (currentLang !== null) {
    blocks.set(currentLang, currentLines.join("\n").trim());
  }

  return blocks;
}

/**
 * Merge two Lowering Notes sections. Child language blocks override matching
 * parent language blocks by heading name.
 */
export function mergeLoweringNotes(parent: string, child: string): string {
  const parentLangs = parseLanguageBlocks(parent);
  const childLangs = parseLanguageBlocks(child);
  const merged = new Map([...parentLangs, ...childLangs]);
  const parts: string[] = [];
  for (const [lang, langContent] of merged) {
    parts.push(`### ${lang}`);
    parts.push(langContent);
  }
  return parts.join("\n\n");
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: all tests PASS (8 from Task 2 + new describe blocks).

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/inheritance.ts test/inheritance.test.ts && git commit -m "feat(inheritance): add extractSections and pattern/lowering-notes merge rules"
```

---

### Task 4: flattenInheritanceChain -- the public API

**Files:**
- Modify: `prunejuice/src/inheritance.ts`
- Modify: `prunejuice/test/inheritance.test.ts`

- [ ] **Step 1: Write failing tests for flattenInheritanceChain**

Add to `prunejuice/test/inheritance.test.ts`:

```typescript
import { flattenInheritanceChain } from "../src/inheritance.js";

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: new tests FAIL -- `flattenInheritanceChain` not exported.

- [ ] **Step 3: Implement flattenInheritanceChain**

Add to `prunejuice/src/inheritance.ts`:

```typescript
import type {
  FlattenedConcreteSpec,
  FlattenedSection,
  SectionMergeRule,
} from "./types.js";

// -- Inheritance flattening --------------------------------------------------

/** Determine the merge rule for a given section name. */
function ruleFor(sectionName: string): SectionMergeRule {
  if (STRICT_CHILD_ONLY.has(sectionName)) return "strict_child_only";
  if (sectionName === "Pattern") return "overridable";
  if (sectionName === "Lowering Notes") return "additive";
  return "overridable";
}

/**
 * Flatten the inheritance chain for a concrete spec. Reads each spec in the
 * extends chain, merges sections according to three rules:
 *   - STRICT_CHILD_ONLY: child's section wins; parent's is purged even if child omits
 *   - Pattern (overridable): parent keys preserved, child keys override by name
 *   - Lowering Notes (additive): merged by language heading, child wins matching languages
 *   - Other sections: child overrides parent (overridable)
 *
 * Returns a `FlattenedConcreteSpec` with the chain, the resolved sections, and
 * per-section attribution indicating which spec provided each section's content.
 *
 * Throws:
 *   - `InheritanceCycleError` on a cycle
 *   - Error on depth > MAX_EXTENDS_DEPTH
 *   - Error on missing parent
 */
export async function flattenInheritanceChain(
  specPath: string,
  cwd: string,
): Promise<FlattenedConcreteSpec> {
  const absCwd = resolve(cwd);
  const chain = await resolveExtendsChain(specPath, cwd);

  // Single-element chain: just return the child's own sections
  if (chain.length <= 1) {
    const absPath = resolve(absCwd, specPath);
    let content = "";
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err) {
      if (!isEnoent(err)) throw err;
    }

    const childSections = extractSections(content);
    const sections = new Map<string, FlattenedSection>();
    for (const [name, sectionContent] of childSections) {
      sections.set(name, {
        content: sectionContent,
        source: specPath,
        rule: ruleFor(name),
      });
    }
    return { specPath, chain, sections };
  }

  // Read each level of the chain. chain is [child, parent, grandparent, ...]
  // We process in reversed order (root -> child) so parent sections build up first.
  type Level = { path: string; sections: Map<string, string> };
  const levels: Level[] = [];
  for (const path of [...chain].reverse()) {
    const absPath = resolve(absCwd, path);
    let content = "";
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err) {
      if (!isEnoent(err)) throw err;
    }
    levels.push({ path, sections: extractSections(content) });
  }

  // levels is now [root, ..., parent, child] (general -> specific)
  const parentLevels = levels.slice(0, -1);
  const childLevel = levels[levels.length - 1]!;

  // Step 1: build parent_resolved by merging all parent levels
  // Track source attribution for each section.
  const parentResolved = new Map<string, { content: string; source: string }>();
  for (const level of parentLevels) {
    for (const [name, content] of level.sections) {
      if (name === "Pattern" && parentResolved.has(name)) {
        const existing = parentResolved.get(name)!;
        parentResolved.set(name, {
          content: mergePatternSections(existing.content, content),
          source: level.path, // most specific contributor
        });
      } else if (name === "Lowering Notes" && parentResolved.has(name)) {
        const existing = parentResolved.get(name)!;
        parentResolved.set(name, {
          content: mergeLoweringNotes(existing.content, content),
          source: level.path,
        });
      } else {
        parentResolved.set(name, { content, source: level.path });
      }
    }
  }

  // Step 2: purge STRICT_CHILD_ONLY sections from parent_resolved
  for (const name of STRICT_CHILD_ONLY) {
    parentResolved.delete(name);
  }

  // Step 3: apply child sections, merging where appropriate
  const resolved = new Map(parentResolved);
  for (const [name, content] of childLevel.sections) {
    if (name === "Lowering Notes" && resolved.has(name)) {
      const existing = resolved.get(name)!;
      resolved.set(name, {
        content: mergeLoweringNotes(existing.content, content),
        source: childLevel.path,
      });
    } else if (name === "Pattern" && resolved.has(name)) {
      const existing = resolved.get(name)!;
      resolved.set(name, {
        content: mergePatternSections(existing.content, content),
        source: childLevel.path,
      });
    } else {
      resolved.set(name, { content, source: childLevel.path });
    }
  }

  // Build FlattenedSection entries with the right rule
  const sections = new Map<string, FlattenedSection>();
  for (const [name, { content, source }] of resolved) {
    sections.set(name, {
      content,
      source,
      rule: ruleFor(name),
    });
  }

  return { specPath, chain, sections };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/inheritance.test.ts`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/inheritance.ts test/inheritance.test.ts && git commit -m "feat(inheritance): add flattenInheritanceChain with STRICT_CHILD_ONLY/additive/overridable rules"
```

---

### Task 5: Ripple exposes concrete edges for sync ordering

**Files:**
- Modify: `prunejuice/src/ripple.ts`
- Modify: `prunejuice/src/types.ts`

This task exposes the extends+concrete-dependencies edge set from ripple so `computeParallelBatches` can include them in topological sort without re-parsing every impl file.

- [ ] **Step 1: Add concreteEdges field to RippleResult**

In `prunejuice/src/types.ts`, modify `RippleResult` (around line 265):

```typescript
export interface RippleResult {
  inputSpecs: string[];
  layers: {
    abstract: RippleAbstractLayer;
    concrete: RippleConcreteLayer;
    code: RippleCodeLayer;
  };
  buildOrder: string[];
  /**
   * Concrete spec edges projected to spec space for batch ordering.
   * Key: spec path. Value: list of spec paths it depends on via extends or
   * concrete-dependencies (resolved through its impl's source-spec).
   */
  concreteEdges: Record<string, string[]>;
}
```

- [ ] **Step 2: Populate concreteEdges in rippleCheck**

In `prunejuice/src/ripple.ts`, locate the existing `concreteSpecEdges` Map (around line 503). Currently it only covers `concreteDependencies`. Extend it to also include `extends` edges, then convert to a plain object for the result.

Find this block (around lines 503-515):

```typescript
  const concreteSpecEdges = new Map<string, string[]>();
  // Project concrete edges to spec space
  for (const [implRel, meta] of implMeta) {
    if (!meta.sourceSpec) continue;
    for (const dep of meta.concreteDependencies) {
      const depMeta = implMeta.get(dep);
      if (depMeta?.sourceSpec) {
        if (!concreteSpecEdges.has(meta.sourceSpec))
          concreteSpecEdges.set(meta.sourceSpec, []);
        concreteSpecEdges.get(meta.sourceSpec)!.push(depMeta.sourceSpec);
      }
    }
  }
```

Replace with:

```typescript
  const concreteSpecEdges = new Map<string, string[]>();
  // Project concrete edges (concrete-dependencies + extends) to spec space.
  // Both edge types mean "parent impl must build before child impl", so they
  // translate to "parent source-spec must build before child source-spec".
  for (const [, meta] of implMeta) {
    if (!meta.sourceSpec) continue;

    const upstreamImpls: string[] = [...meta.concreteDependencies];
    if (meta.extends) upstreamImpls.push(meta.extends);

    for (const dep of upstreamImpls) {
      const depMeta = implMeta.get(dep);
      if (depMeta?.sourceSpec && depMeta.sourceSpec !== meta.sourceSpec) {
        if (!concreteSpecEdges.has(meta.sourceSpec))
          concreteSpecEdges.set(meta.sourceSpec, []);
        const existing = concreteSpecEdges.get(meta.sourceSpec)!;
        if (!existing.includes(depMeta.sourceSpec)) {
          existing.push(depMeta.sourceSpec);
        }
      }
    }
  }
```

Then, in the return statement at the bottom of `rippleCheck` (around line 531), add `concreteEdges`:

Find:
```typescript
  return {
    inputSpecs: [...specPaths],
    layers: {
      abstract: abstractLayer,
      concrete: concreteLayer,
      code: codeLayer,
    },
    buildOrder,
  };
}
```

Replace with:
```typescript
  // Convert concreteSpecEdges Map to a plain Record for the result.
  const concreteEdgesObj: Record<string, string[]> = {};
  for (const [spec, deps] of concreteSpecEdges) {
    concreteEdgesObj[spec] = deps;
  }

  return {
    inputSpecs: [...specPaths],
    layers: {
      abstract: abstractLayer,
      concrete: concreteLayer,
      code: codeLayer,
    },
    buildOrder,
    concreteEdges: concreteEdgesObj,
  };
}
```

- [ ] **Step 3: Run existing tests to check for regressions**

Run: `cd prunejuice && npx vitest run test/ripple.test.ts`

Expected: all existing tests still pass. The new field is additive.

- [ ] **Step 4: Add a test asserting concreteEdges contains extends edges**

Add to the existing `describe("rippleCheck", ...)` block in `prunejuice/test/ripple.test.ts`:

```typescript
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
```

- [ ] **Step 5: Run tests**

Run: `cd prunejuice && npx vitest run test/ripple.test.ts`

Expected: all tests PASS including the new one.

- [ ] **Step 6: Commit**

```bash
cd prunejuice && git add src/ripple.ts src/types.ts test/ripple.test.ts && git commit -m "feat(ripple): expose concreteEdges including extends relationships in RippleResult"
```

---

### Task 6: Wire concreteEdges into computeParallelBatches

**Files:**
- Modify: `prunejuice/src/sync.ts`
- Modify: `prunejuice/test/sync.test.ts`

- [ ] **Step 1: Write failing tests for extends-aware batch ordering**

Add to `prunejuice/test/sync.test.ts` (inside the existing describe block for `bulkSyncPlan` or create a new one):

```typescript
  it("extends edge enforces parent-before-child in batch ordering", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // parent.spec.md and child.spec.md are both stale
    // child.impl.md extends parent.impl.md -> parent must batch before child
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
      ].join("\n"),
    );

    // Pre-create managed files as stale so bulkSyncPlan picks them up
    // (both missing = "new" state, which is stale-equivalent)
    // Actually we just need freshness to classify them as non-fresh.
    // Since there are no managed files, they'll be classified as new/stale.

    const result = await bulkSyncPlan(tmp);

    // Find the batch index for each spec
    const parentBatch = result.batches.findIndex((b) =>
      b.files.some((f) => f.spec === "parent.spec.md"),
    );
    const childBatch = result.batches.findIndex((b) =>
      b.files.some((f) => f.spec === "child.spec.md"),
    );

    expect(parentBatch).toBeGreaterThanOrEqual(0);
    expect(childBatch).toBeGreaterThanOrEqual(0);
    // parent must come before child
    expect(parentBatch).toBeLessThan(childBatch);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prunejuice && npx vitest run test/sync.test.ts`

Expected: the new test FAILS -- `computeParallelBatches` currently only uses `dag.dag` (abstract depends-on), not concrete edges.

- [ ] **Step 3: Extend computeParallelBatches to accept concrete edges**

Modify `prunejuice/src/sync.ts`. Update `computeParallelBatches` signature and logic to merge `concreteEdges` into the graph:

Find:
```typescript
function computeParallelBatches(
  entries: SyncPlanEntry[],
  graph: Record<string, string[]>,
  maxBatchSize: number,
): SyncBatch[] {
```

Replace with:
```typescript
function computeParallelBatches(
  entries: SyncPlanEntry[],
  graph: Record<string, string[]>,
  concreteEdges: Record<string, string[]>,
  maxBatchSize: number,
): SyncBatch[] {
```

Then, inside the function, replace the subgraph construction to merge both edge sources:

Find:
```typescript
  // Build subgraph of only entries' specs
  const specSet = new Set(entries.map((e) => e.spec));
  const subgraph: Record<string, string[]> = {};
  for (const spec of specSet) {
    subgraph[spec] = (graph[spec] ?? []).filter((d) => specSet.has(d));
  }
```

Replace with:
```typescript
  // Build subgraph of only entries' specs, merging abstract depends-on edges
  // with concrete extends/concrete-dependencies edges projected to spec space.
  const specSet = new Set(entries.map((e) => e.spec));
  const subgraph: Record<string, string[]> = {};
  for (const spec of specSet) {
    const abstractDeps = (graph[spec] ?? []).filter((d) => specSet.has(d));
    const concreteDeps = (concreteEdges[spec] ?? []).filter((d) =>
      specSet.has(d),
    );
    // Deduplicate
    subgraph[spec] = [...new Set([...abstractDeps, ...concreteDeps])];
  }
```

- [ ] **Step 4: Update all call sites of computeParallelBatches to pass concreteEdges**

In `bulkSyncPlan` (around line 325):

Find:
```typescript
  const dag = await ensureDAG(cwd);
  const batches = computeParallelBatches(plan, dag.dag, maxBatchSize);
```

Replace with:
```typescript
  const dag = await ensureDAG(cwd);
  const batches = computeParallelBatches(
    plan,
    dag.dag,
    ripple.concreteEdges,
    maxBatchSize,
  );
```

In `resumeSyncPlan` (around line 455):

Find:
```typescript
  // Batch
  const batches = computeParallelBatches(plan, dag.dag, maxBatchSize);
```

Replace with:
```typescript
  // Batch. Resume doesn't have a ripple result, so we compute one for its
  // failed specs to get concreteEdges. If this is expensive, we could cache,
  // but resume is an interactive path and runs once per retry.
  const resumeRipple = await rippleCheck(failedSpecs, cwd);
  const batches = computeParallelBatches(
    plan,
    dag.dag,
    resumeRipple.concreteEdges,
    maxBatchSize,
  );
```

- [ ] **Step 5: Run tests**

Run: `cd prunejuice && npx vitest run test/sync.test.ts`

Expected: the new test PASSES and all existing sync tests still pass.

- [ ] **Step 6: Commit**

```bash
cd prunejuice && git add src/sync.ts test/sync.test.ts && git commit -m "feat(sync): extends-aware batch ordering via ripple concreteEdges"
```

---

### Task 7: Collision detection in partitionPlan

**Files:**
- Modify: `prunejuice/src/sync.ts`
- Create: `prunejuice/test/collision.test.ts`

- [ ] **Step 1: Write failing tests for collision detection**

Create `prunejuice/test/collision.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { bulkSyncPlan, deepSyncPlan } from "../src/sync.js";
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

    // a.impl.md and b.impl.md both target src/shared.ts
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/collision.test.ts`

Expected: FAIL -- `collisions` field doesn't exist on result, `preferSpec` option doesn't exist.

- [ ] **Step 3: Add preferSpec to options types**

In `prunejuice/src/sync.ts`, update the option interfaces at the top of the file:

```typescript
export interface DeepSyncOptions {
  force?: boolean;
  /** Map from target path to the concrete spec that should win a collision. */
  preferSpec?: Record<string, string>;
}

export interface BulkSyncOptions {
  force?: boolean;
  maxBatchSize?: number;
  preferSpec?: Record<string, string>;
}

export interface ResumeSyncOptions {
  failedFiles: string[];
  succeededFiles: string[];
  force?: boolean;
  maxBatchSize?: number;
  preferSpec?: Record<string, string>;
}
```

- [ ] **Step 4: Add detectCollisions helper and integrate into partitionPlan**

In `prunejuice/src/sync.ts`, import `CollisionEntry`:

Find the existing import:
```typescript
import type {
  DeepSyncResult,
  BulkSyncResult,
  ResumeSyncResult,
  SyncPlanEntry,
  SyncBatch,
} from "./types.js";
```

Add `CollisionEntry`:
```typescript
import type {
  DeepSyncResult,
  BulkSyncResult,
  ResumeSyncResult,
  SyncPlanEntry,
  SyncBatch,
  CollisionEntry,
} from "./types.js";
```

Add a new helper function near `partitionPlan` (before it):

```typescript
/**
 * Detect target collisions across concrete specs.
 *
 * Scans all plan entries and groups them by managed target path. Any target
 * claimed by more than one concrete spec produces a CollisionEntry. If
 * `preferSpec` names a winner for a given target, the collision is marked
 * resolved -- the winner proceeds normally and losers are skipped with audit.
 *
 * Returns:
 *   - `collisions`: list of collision records (one per conflicting target)
 *   - `allowedTargets`: set of (targetPath) that should proceed to the plan;
 *     entries for colliding targets are either all blocked (no preferSpec) or
 *     only the winner is allowed.
 *   - `allowedByConcrete`: for collisions with preferSpec, maps target ->
 *     winning concrete spec so we can filter plan entries correctly.
 */
function detectCollisions(
  entries: SyncPlanEntry[],
  preferSpec: Record<string, string>,
): {
  collisions: CollisionEntry[];
  blockedTargets: Set<string>;
  allowedByConcrete: Map<string, string>; // targetPath -> winning concrete
} {
  // Group entries by target path, tracking unique concrete specs per target
  const byTarget = new Map<string, Set<string>>();
  for (const entry of entries) {
    if (!entry.concrete) continue; // only collisions between concrete specs
    if (!byTarget.has(entry.managed)) byTarget.set(entry.managed, new Set());
    byTarget.get(entry.managed)!.add(entry.concrete);
  }

  const collisions: CollisionEntry[] = [];
  const blockedTargets = new Set<string>();
  const allowedByConcrete = new Map<string, string>();

  for (const [targetPath, claimantSet] of byTarget) {
    if (claimantSet.size < 2) continue; // no collision

    const claimants = [...claimantSet].sort();
    const winner = preferSpec[targetPath];

    if (winner && claimants.includes(winner)) {
      // Resolved: winner proceeds, losers skipped
      const skipped = claimants.filter((c) => c !== winner);
      collisions.push({
        status: "collision",
        targetPath,
        claimants,
        preferSpec: winner,
        skippedSpecs: skipped,
      });
      allowedByConcrete.set(targetPath, winner);
    } else {
      // Unresolved: block all claimants
      collisions.push({
        status: "collision",
        targetPath,
        claimants,
      });
      blockedTargets.add(targetPath);
    }
  }

  return { collisions, blockedTargets, allowedByConcrete };
}
```

Update `partitionPlan` to accept collisions and filter entries:

Find:
```typescript
function partitionPlan(
  entries: SyncPlanEntry[],
  force: boolean,
): { plan: SyncPlanEntry[]; skipped: SyncPlanEntry[] } {
  if (force) {
    return { plan: entries, skipped: [] };
  }
  const plan: SyncPlanEntry[] = [];
  const skipped: SyncPlanEntry[] = [];
  for (const entry of entries) {
    if (entry.state === "modified" || entry.state === "conflict") {
      skipped.push(entry);
    } else {
      plan.push(entry);
    }
  }
  return { plan, skipped };
}
```

Replace with:
```typescript
function partitionPlan(
  entries: SyncPlanEntry[],
  force: boolean,
  blockedTargets: Set<string>,
  allowedByConcrete: Map<string, string>,
): { plan: SyncPlanEntry[]; skipped: SyncPlanEntry[] } {
  const plan: SyncPlanEntry[] = [];
  const skipped: SyncPlanEntry[] = [];

  for (const entry of entries) {
    // Collision filtering: applies regardless of force
    if (blockedTargets.has(entry.managed)) {
      // Unresolved collision -- block this entry
      continue;
    }
    const winner = allowedByConcrete.get(entry.managed);
    if (winner !== undefined && entry.concrete !== winner) {
      // Resolved collision, this entry is the loser -- skip it
      continue;
    }

    // Standard partitioning: modified/conflict need coordinator confirmation
    if (!force && (entry.state === "modified" || entry.state === "conflict")) {
      skipped.push(entry);
    } else {
      plan.push(entry);
    }
  }

  return { plan, skipped };
}
```

- [ ] **Step 5: Update bulkSyncPlan to compute collisions and populate result**

In `bulkSyncPlan`, after the `allEntries` array is built and before `partitionPlan` is called, add:

Find:
```typescript
  // Partition
  const { plan, skipped } = partitionPlan(allEntries, force);
```

Replace with:
```typescript
  // Collision detection
  const preferSpec = options?.preferSpec ?? {};
  const { collisions, blockedTargets, allowedByConcrete } = detectCollisions(
    allEntries,
    preferSpec,
  );

  // Partition (applies collision filtering inside)
  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedByConcrete,
  );
```

Find the return statement:
```typescript
  return {
    batches,
    skipped,
    stats: {
      totalStale: staleEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: freshness.files.filter((f) => f.state === "fresh").length,
    },
    buildOrder,
  };
```

Replace with:
```typescript
  return {
    batches,
    skipped,
    collisions,
    stats: {
      totalStale: staleEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: freshness.files.filter((f) => f.state === "fresh").length,
    },
    buildOrder,
  };
```

- [ ] **Step 6: Update deepSyncPlan similarly**

In `deepSyncPlan`, find:
```typescript
  // Partition
  const { plan, skipped } = partitionPlan(allEntries, force);
```

Replace with:
```typescript
  // Collision detection
  const preferSpec = options?.preferSpec ?? {};
  const { collisions, blockedTargets, allowedByConcrete } = detectCollisions(
    allEntries,
    preferSpec,
  );

  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedByConcrete,
  );
```

Find the return statement:
```typescript
  return {
    trigger: specRel,
    plan,
    skipped,
    stats: {
      totalAffected: allEntries.length + freshSkipped,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped,
    },
    buildOrder: ripple.buildOrder,
  };
```

Replace with:
```typescript
  return {
    trigger: specRel,
    plan,
    skipped,
    collisions,
    stats: {
      totalAffected: allEntries.length + freshSkipped,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped,
    },
    buildOrder: ripple.buildOrder,
  };
```

- [ ] **Step 7: Update resumeSyncPlan similarly**

In `resumeSyncPlan`, find:
```typescript
  // Partition
  const { plan, skipped } = partitionPlan(allEntries, force);
```

Replace with:
```typescript
  // Collision detection
  const preferSpec = options.preferSpec ?? {};
  const { collisions, blockedTargets, allowedByConcrete } = detectCollisions(
    allEntries,
    preferSpec,
  );

  const { plan, skipped } = partitionPlan(
    allEntries,
    force,
    blockedTargets,
    allowedByConcrete,
  );
```

Find the return statement:
```typescript
  return {
    resumedFrom: failedFiles,
    alreadyDone: succeededFiles.length,
    batches,
    skipped,
    stats: {
      totalStale: allEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: 0,
    },
    buildOrder,
  };
```

Replace with:
```typescript
  return {
    resumedFrom: failedFiles,
    alreadyDone: succeededFiles.length,
    batches,
    skipped,
    collisions,
    stats: {
      totalStale: allEntries.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: 0,
    },
    buildOrder,
  };
```

- [ ] **Step 8: Run all sync and collision tests**

Run: `cd prunejuice && npx vitest run test/sync.test.ts test/collision.test.ts`

Expected: all tests PASS.

- [ ] **Step 9: Run full suite to check for regressions**

Run: `cd prunejuice && npx vitest run`

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
cd prunejuice && git add src/sync.ts test/collision.test.ts && git commit -m "feat(sync): multi-target collision detection with preferSpec resolution"
```

---

### Task 8: Full verification + TypeScript check

**Files:**
- None (verification only)

- [ ] **Step 1: TypeScript compiles clean**

Run: `cd prunejuice && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 2: Full test suite passes**

Run: `cd prunejuice && npx vitest run`

Expected: all tests pass. New test counts:
- `test/inheritance.test.ts` (~23 tests: 8 resolveExtendsChain + 4 extractSections + 3 mergePatternSections + 2 mergeLoweringNotes + 6 flattenInheritanceChain)
- `test/collision.test.ts` (6 tests)
- `test/ripple.test.ts` (+1 concreteEdges test)
- `test/sync.test.ts` (+1 extends batch ordering test)

Approximately 31 new tests, bringing total from ~255 to ~286.

- [ ] **Step 3: Verify exports are accessible**

Run: `cd prunejuice && npx tsc && node -e "import('./dist/inheritance.js').then(m => console.log(Object.keys(m)))"`

Expected: `['MAX_EXTENDS_DEPTH', 'STRICT_CHILD_ONLY', 'InheritanceCycleError', 'resolveExtendsChain', 'extractSections', 'mergePatternSections', 'mergeLoweringNotes', 'flattenInheritanceChain']`

- [ ] **Step 4: Final commit if cleanup needed**

Only commit if there are uncommitted changes:

```bash
cd prunejuice && git status
# if changes: git add -A && git commit -m "chore: phase 7 verification cleanup"
```
