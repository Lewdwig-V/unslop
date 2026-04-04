# Prunejuice Phase 3: Sync Planning Tools -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the four remaining state management MCP tools (`prunejuice_deep_sync_plan`, `prunejuice_bulk_sync_plan`, `prunejuice_spec_diff`, `prunejuice_discover_files`) so that after this phase, Python state management is fully redundant.

**Architecture:** Three new source modules compose the Phase 1-2 building blocks (`checkFreshnessAll`, `rippleCheck`, `ensureDAG`, `topoSort`) into sync planning operations. `spec-diff.ts` and `discover.ts` are pure utilities with no DAG/freshness dependency. `sync.ts` implements deep sync, bulk sync, and resume -- all three share a common plan-entry model and the bulk/resume paths add parallel batching via Kahn's depth grouping. Four new MCP tool registrations in `mcp.ts`.

**Tech Stack:** TypeScript, vitest, `@modelcontextprotocol/sdk`, zod

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `prunejuice/src/spec-diff.ts` | Section-level markdown diff between two spec versions |
| **Create:** `prunejuice/src/discover.ts` | Source file discovery with test/build artifact exclusion |
| **Create:** `prunejuice/src/sync.ts` | Deep sync, bulk sync, resume sync -- compose freshness + DAG + ripple |
| **Modify:** `prunejuice/src/mcp.ts` | Register four new MCP tools |
| **Modify:** `prunejuice/src/types.ts` | Add sync plan result types |
| **Create:** `prunejuice/test/spec-diff.test.ts` | Unit tests for spec diff |
| **Create:** `prunejuice/test/discover.test.ts` | Unit tests for file discovery |
| **Create:** `prunejuice/test/sync.test.ts` | Unit tests for sync planning |
| **Create:** `prunejuice/test/sync-mcp.test.ts` | MCP handler tests for new tools |

---

### Task 1: Add Sync Planning Types to `types.ts`

**Files:**
- Modify: `prunejuice/src/types.ts`

- [ ] **Step 1: Add type definitions at the end of types.ts**

```typescript
// -- Sync planning results ----------------------------------------------------

export interface SyncPlanEntry {
  managed: string;
  spec: string;
  state: string;
  cause: "direct" | "transitive" | "ghost-stale" | "retry" | "downstream";
  concrete?: string;
}

export interface SyncBatch {
  batchIndex: number;
  files: SyncPlanEntry[];
  size: number;
}

export interface DeepSyncResult {
  trigger: string;
  plan: SyncPlanEntry[];
  skipped: SyncPlanEntry[];
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
  stats: {
    totalStale: number;
    totalBatches: number;
    toRegenerate: number;
    skippedNeedConfirm: number;
    freshSkipped: number;
  };
  buildOrder: string[];
}

export interface ResumeSyncResult extends BulkSyncResult {
  resumedFrom: string[];
  alreadyDone: number;
}

export interface SpecDiffResult {
  changedSections: string[];
  unchangedSections: string[];
}
```

- [ ] **Step 2: Run tests to verify nothing broke**

Run: `cd prunejuice && npm run test`
Expected: All 155 existing tests pass

- [ ] **Step 3: Commit**

```bash
git add prunejuice/src/types.ts
git commit -m "feat(prunejuice): add sync planning types for Phase 3"
```

---

### Task 2: Implement Spec Diff (`spec-diff.ts`)

**Files:**
- Create: `prunejuice/test/spec-diff.test.ts`
- Create: `prunejuice/src/spec-diff.ts`

This is a pure utility -- no DAG, no freshness, no I/O. Parses markdown by `## ` headings and compares sections.

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/spec-diff.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { computeSpecDiff } from "../src/spec-diff.js";

describe("computeSpecDiff", () => {
  it("reports changed and unchanged sections", () => {
    const old = [
      "## Intent",
      "Build a widget",
      "## Requirements",
      "- Must be fast",
    ].join("\n");
    const updated = [
      "## Intent",
      "Build a widget",
      "## Requirements",
      "- Must be fast",
      "- Must be reliable",
    ].join("\n");

    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toEqual(["Requirements"]);
    expect(diff.unchangedSections).toEqual(["Intent"]);
  });

  it("detects added sections", () => {
    const old = "## Intent\nBuild a widget";
    const updated = "## Intent\nBuild a widget\n## Constraints\nNone";

    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toContain("Constraints");
    expect(diff.unchangedSections).toContain("Intent");
  });

  it("detects removed sections", () => {
    const old = "## Intent\nBuild a widget\n## Deprecated\nOld stuff";
    const updated = "## Intent\nBuild a widget";

    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toContain("Deprecated");
  });

  it("returns empty arrays for identical specs", () => {
    const spec = "## Intent\nSame\n## Requirements\nSame";
    const diff = computeSpecDiff(spec, spec);
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual(["Intent", "Requirements"]);
  });

  it("handles specs with no sections", () => {
    const diff = computeSpecDiff("Just text", "Different text");
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual([]);
  });

  it("handles empty inputs", () => {
    const diff = computeSpecDiff("", "");
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/spec-diff.test.ts`
Expected: FAIL -- cannot resolve `../src/spec-diff.js`

- [ ] **Step 3: Implement spec diff**

Create `prunejuice/src/spec-diff.ts`:

```typescript
import type { SpecDiffResult } from "./types.js";

/**
 * Parse markdown into {heading: content} by `## ` boundaries.
 * Content before the first `## ` heading is ignored.
 */
function parseMdSections(text: string): Record<string, string> {
  const sections: Record<string, string> = {};
  let currentHeading: string | null = null;
  const currentLines: string[] = [];

  for (const line of text.split("\n")) {
    if (line.startsWith("## ")) {
      if (currentHeading !== null) {
        sections[currentHeading] = currentLines.join("\n").trim();
      }
      currentHeading = line.slice(3).trim();
      currentLines.length = 0;
    } else {
      currentLines.push(line);
    }
  }

  if (currentHeading !== null) {
    sections[currentHeading] = currentLines.join("\n").trim();
  }

  return sections;
}

/**
 * Section-level markdown diff between two spec versions.
 * Compares content under each `## ` heading.
 */
export function computeSpecDiff(
  oldSpec: string,
  newSpec: string,
): SpecDiffResult {
  const oldSections = parseMdSections(oldSpec);
  const newSections = parseMdSections(newSpec);

  const allHeadings = new Set([
    ...Object.keys(oldSections),
    ...Object.keys(newSections),
  ]);

  const changedSections: string[] = [];
  const unchangedSections: string[] = [];

  for (const heading of [...allHeadings].sort()) {
    const oldContent = oldSections[heading];
    const newContent = newSections[heading];
    if (oldContent === newContent) {
      unchangedSections.push(heading);
    } else {
      changedSections.push(heading);
    }
  }

  return { changedSections, unchangedSections };
}
```

- [ ] **Step 4: Run tests**

Run: `cd prunejuice && npx vitest run test/spec-diff.test.ts`
Expected: All 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add prunejuice/src/spec-diff.ts prunejuice/test/spec-diff.test.ts
git commit -m "feat(prunejuice): section-level spec diff"
```

---

### Task 3: Implement File Discovery (`discover.ts`)

**Files:**
- Create: `prunejuice/test/discover.test.ts`
- Create: `prunejuice/src/discover.ts`

Source file discovery that excludes tests, build artifacts, and common noise directories. Matches Python's `discover_files()` in `spec_discovery.py`.

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/discover.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { discoverFiles } from "../src/discover.js";

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "discover-test-"));
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

describe("discoverFiles", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("discovers source files recursively", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "src/lib/util.ts", "export {}");

    const files = await discoverFiles(tmp);
    expect(files).toContain("src/main.ts");
    expect(files).toContain("src/lib/util.ts");
  });

  it("excludes test files by pattern", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "src/main.test.ts", "test");
    await writeAt(tmp, "src/test_util.py", "test");

    const files = await discoverFiles(tmp);
    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("src/main.test.ts");
    expect(files).not.toContain("src/test_util.py");
  });

  it("excludes test directories", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "tests/test_main.py", "test");
    await writeAt(tmp, "__tests__/main.test.ts", "test");

    const files = await discoverFiles(tmp);
    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("tests/test_main.py");
    expect(files).not.toContain("__tests__/main.test.ts");
  });

  it("excludes build artifact directories", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "node_modules/dep/index.js", "module");
    await writeAt(tmp, "dist/main.js", "built");

    const files = await discoverFiles(tmp);
    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("node_modules/dep/index.js");
    expect(files).not.toContain("dist/main.js");
  });

  it("filters by extensions when provided", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "src/style.css", "body {}");

    const files = await discoverFiles(tmp, { extensions: [".ts"] });
    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("src/style.css");
  });

  it("applies extra excludes", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");
    await writeAt(tmp, "vendor/lib.ts", "export {}");

    const files = await discoverFiles(tmp, { extraExcludes: ["vendor"] });
    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("vendor/lib.ts");
  });

  it("returns sorted paths relative to directory", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/b.ts", "");
    await writeAt(tmp, "src/a.ts", "");

    const files = await discoverFiles(tmp);
    expect(files).toEqual(["src/a.ts", "src/b.ts"]);
  });

  it("throws on non-existent directory", async () => {
    await expect(discoverFiles("/nonexistent/path")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/discover.test.ts`
Expected: FAIL -- cannot resolve `../src/discover.js`

- [ ] **Step 3: Implement file discovery**

Create `prunejuice/src/discover.ts`:

```typescript
import { readdir, stat } from "node:fs/promises";
import { join, relative, extname, resolve } from "node:path";
import { isEnoent } from "./fs-utils.js";

const EXCLUDED_DIRS = new Set([
  "__pycache__",
  "node_modules",
  "target",
  ".git",
  ".venv",
  "venv",
  "dist",
  "build",
  ".tox",
  "vendor",
  ".mypy_cache",
  ".pytest_cache",
  ".eggs",
  ".prunejuice",
  ".unslop",
]);

const TEST_DIR_NAMES = new Set(["__tests__", "tests", "spec"]);

const TEST_FILE_PATTERNS = [
  /^test_/,
  /_test\./,
  /\.test\./,
  /\.spec\.(ts|js)$/,
];

export interface DiscoverOptions {
  extensions?: string[];
  extraExcludes?: string[];
}

/**
 * Discover source files in a directory, excluding tests and build artifacts.
 * Returns sorted list of file paths relative to the scanned directory.
 */
export async function discoverFiles(
  directory: string,
  options?: DiscoverOptions,
): Promise<string[]> {
  const root = resolve(directory);
  const rootStat = await stat(root);
  if (!rootStat.isDirectory()) {
    throw new Error(`Directory does not exist: ${directory}`);
  }

  const excluded = new Set(EXCLUDED_DIRS);
  if (options?.extraExcludes) {
    for (const e of options.extraExcludes) excluded.add(e);
  }

  const extensionSet = options?.extensions
    ? new Set(options.extensions)
    : null;

  const results: string[] = [];
  const stack = [root];

  while (stack.length > 0) {
    const dir = stack.pop()!;
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch (err: unknown) {
      if (isEnoent(err)) continue;
      throw err;
    }

    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (!excluded.has(entry.name) && !TEST_DIR_NAMES.has(entry.name)) {
          stack.push(join(dir, entry.name));
        }
      } else if (entry.isFile()) {
        const rel = relative(root, join(dir, entry.name));
        const parts = rel.split("/");

        // Skip if any parent dir is excluded or a test dir
        if (parts.slice(0, -1).some((p) => excluded.has(p) || TEST_DIR_NAMES.has(p))) {
          continue;
        }

        // Skip if extension doesn't match filter
        if (extensionSet && !extensionSet.has(extname(entry.name))) {
          continue;
        }

        // Skip test files by name pattern
        if (TEST_FILE_PATTERNS.some((pat) => pat.test(entry.name))) {
          continue;
        }

        results.push(rel);
      }
    }
  }

  return results.sort();
}
```

- [ ] **Step 4: Run tests**

Run: `cd prunejuice && npx vitest run test/discover.test.ts`
Expected: All 8 tests pass

- [ ] **Step 5: Commit**

```bash
git add prunejuice/src/discover.ts prunejuice/test/discover.test.ts
git commit -m "feat(prunejuice): source file discovery with test/artifact exclusion"
```

---

### Task 4: Implement Sync Planning (`sync.ts`)

**Files:**
- Create: `prunejuice/test/sync.test.ts`
- Create: `prunejuice/src/sync.ts`

This is the most complex task. Three functions compose freshness + DAG + ripple into sync plans.

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/sync.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { deepSyncPlan, bulkSyncPlan, resumeSyncPlan } from "../src/sync.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "sync-test-"));
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

function managedFile(specContent: string, bodyContent: string): string {
  const specHash = truncatedHash(specContent);
  const bodyHash = truncatedHash(bodyContent);
  const header = formatHeader("test.spec.md", {
    specHash,
    outputHash: bodyHash,
    generated: "2026-04-01T00:00:00Z",
  });
  return `${header}\n\n${bodyContent}`;
}

// -- deepSyncPlan -------------------------------------------------------------

describe("deepSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns plan for a single stale spec and its dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specA = "---\n---\n# A";
    const specB = "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B";
    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    // a.ts is stale (spec hash doesn't match)
    await writeAt(tmp, "a.ts", managedFile("---\n---\n# OLD A", "code a"));
    await writeAt(tmp, "b.ts", managedFile(specB, "code b"));

    const result = await deepSyncPlan("a.ts.spec.md", tmp);
    expect(result.trigger).toBe("a.ts.spec.md");
    expect(result.plan.length).toBeGreaterThanOrEqual(1);
    expect(result.plan.some((e) => e.managed === "a.ts")).toBe(true);
    expect(result.buildOrder.length).toBeGreaterThanOrEqual(1);
  });

  it("accepts managed file path and resolves to spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget";
    await writeAt(tmp, "widget.ts.spec.md", specContent);
    // No managed file yet -> pending
    const result = await deepSyncPlan("widget.ts", tmp);
    expect(result.trigger).toBe("widget.ts.spec.md");
  });

  it("skips modified files into skipped list when force=false", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Widget";
    const origBody = "original code";
    await writeAt(tmp, "widget.ts.spec.md", specContent);
    // Managed file has correct spec hash but body was edited (modified state)
    const managed = managedFile(specContent, origBody);
    const editedManaged = managed.replace(origBody, "user edited code");
    await writeAt(tmp, "widget.ts", editedManaged);

    const result = await deepSyncPlan("widget.ts.spec.md", tmp, { force: false });
    expect(result.skipped.length).toBeGreaterThanOrEqual(1);
    expect(result.skipped.some((e) => e.managed === "widget.ts")).toBe(true);
  });

  it("returns error for nonexistent spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await expect(
      deepSyncPlan("nonexistent.spec.md", tmp),
    ).rejects.toThrow();
  });
});

// -- bulkSyncPlan -------------------------------------------------------------

describe("bulkSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns batched plan for all stale files", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Two stale specs
    const specA = "---\n---\n# A";
    const specB = "---\n---\n# B";
    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "a.ts", managedFile("---\n---\n# OLD A", "code a"));
    await writeAt(tmp, "b.ts", managedFile("---\n---\n# OLD B", "code b"));

    const result = await bulkSyncPlan(tmp);
    expect(result.batches.length).toBeGreaterThanOrEqual(1);
    expect(result.stats.toRegenerate).toBeGreaterThanOrEqual(2);
    expect(result.buildOrder.length).toBeGreaterThanOrEqual(2);
  });

  it("returns empty batches when everything is fresh", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "---\n---\n# Fresh";
    const bodyContent = "fresh code";
    await writeAt(tmp, "x.ts.spec.md", specContent);
    await writeAt(tmp, "x.ts", managedFile(specContent, bodyContent));

    const result = await bulkSyncPlan(tmp);
    expect(result.batches).toEqual([]);
    expect(result.stats.toRegenerate).toBe(0);
  });

  it("groups independent specs into parallel batches", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // Three independent stale specs (no deps between them)
    for (const name of ["a", "b", "c"]) {
      const spec = `---\n---\n# ${name}`;
      await writeAt(tmp, `${name}.ts.spec.md`, spec);
      await writeAt(tmp, `${name}.ts`, managedFile(`---\n---\n# OLD ${name}`, `code ${name}`));
    }

    const result = await bulkSyncPlan(tmp, { maxBatchSize: 2 });
    // 3 independent files with maxBatchSize=2 -> at least 2 batches
    expect(result.batches.length).toBeGreaterThanOrEqual(2);
    expect(result.batches.every((b) => b.size <= 2)).toBe(true);
  });

  it("respects dependency ordering across batches", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // b depends on a, both stale
    const specA = "---\n---\n# A";
    const specB = "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B";
    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "a.ts", managedFile("---\n---\n# OLD A", "code a"));
    await writeAt(tmp, "b.ts", managedFile("---\n---\n# OLD B", "code b"));

    const result = await bulkSyncPlan(tmp);
    // a should be in an earlier batch than b
    const aBatchIdx = result.batches.findIndex((b) =>
      b.files.some((f) => f.managed === "a.ts"),
    );
    const bBatchIdx = result.batches.findIndex((b) =>
      b.files.some((f) => f.managed === "b.ts"),
    );
    expect(aBatchIdx).toBeLessThanOrEqual(bBatchIdx);
  });
});

// -- resumeSyncPlan -----------------------------------------------------------

describe("resumeSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("includes failed files and their downstream dependents", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // a -> b -> c chain, all stale. a failed, b and c are downstream.
    const specA = "---\n---\n# A";
    const specB = "---\ndepends-on:\n  - a.ts.spec.md\n---\n# B";
    const specC = "---\ndepends-on:\n  - b.ts.spec.md\n---\n# C";
    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "c.ts.spec.md", specC);
    await writeAt(tmp, "a.ts", managedFile("---\n---\n# OLD A", "code a"));
    await writeAt(tmp, "b.ts", managedFile("---\n---\n# OLD B", "code b"));
    await writeAt(tmp, "c.ts", managedFile("---\n---\n# OLD C", "code c"));

    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["a.ts"],
      succeededFiles: [],
    });
    expect(result.resumedFrom).toEqual(["a.ts"]);
    // All three should be in the plan (a is retry, b and c are downstream)
    const allManaged = result.batches.flatMap((b) => b.files.map((f) => f.managed));
    expect(allManaged).toContain("a.ts");
    expect(allManaged).toContain("b.ts");
    expect(allManaged).toContain("c.ts");
  });

  it("excludes succeeded files", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specA = "---\n---\n# A";
    const specB = "---\n---\n# B";
    await writeAt(tmp, "a.ts.spec.md", specA);
    await writeAt(tmp, "b.ts.spec.md", specB);
    await writeAt(tmp, "a.ts", managedFile("---\n---\n# OLD A", "code a"));
    await writeAt(tmp, "b.ts", managedFile("---\n---\n# OLD B", "code b"));

    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["a.ts"],
      succeededFiles: ["b.ts"],
    });
    const allManaged = result.batches.flatMap((b) => b.files.map((f) => f.managed));
    expect(allManaged).toContain("a.ts");
    expect(allManaged).not.toContain("b.ts");
    expect(result.alreadyDone).toBe(1);
  });

  it("returns empty plan when no failed specs found", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.ts.spec.md", "---\n---\n# A");

    const result = await resumeSyncPlan(tmp, {
      failedFiles: ["nonexistent.ts"],
      succeededFiles: [],
    });
    expect(result.batches).toEqual([]);
    expect(result.resumedFrom).toEqual(["nonexistent.ts"]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/sync.test.ts`
Expected: FAIL -- cannot resolve `../src/sync.js`

- [ ] **Step 3: Implement sync planning**

Create `prunejuice/src/sync.ts`:

```typescript
import { readFile, stat } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { checkFreshnessAll, type FreshnessEntry } from "./freshness.js";
import { ensureDAG, topoSort } from "./dag.js";
import { rippleCheck } from "./ripple.js";
import { parseHeader } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import type {
  DeepSyncResult,
  BulkSyncResult,
  ResumeSyncResult,
  SyncPlanEntry,
  SyncBatch,
} from "./types.js";

// -- Shared helpers -----------------------------------------------------------

const NEEDS_CONFIRM = new Set(["modified", "conflict"]);

function partitionPlan(
  entries: SyncPlanEntry[],
  force: boolean,
): { plan: SyncPlanEntry[]; skipped: SyncPlanEntry[] } {
  if (force) return { plan: entries, skipped: [] };
  const plan: SyncPlanEntry[] = [];
  const skipped: SyncPlanEntry[] = [];
  for (const e of entries) {
    if (NEEDS_CONFIRM.has(e.state)) {
      skipped.push(e);
    } else {
      plan.push(e);
    }
  }
  return { plan, skipped };
}

/**
 * Compute parallel-safe batches using Kahn's algorithm with depth grouping.
 * Files at the same topological depth can run in parallel.
 */
function computeParallelBatches(
  entries: SyncPlanEntry[],
  graph: Record<string, string[]>,
  maxBatchSize: number,
): SyncBatch[] {
  // Build subgraph restricted to specs in plan
  const planSpecs = new Set(entries.map((e) => e.spec));
  const subgraph: Record<string, string[]> = {};
  for (const spec of planSpecs) {
    subgraph[spec] = (graph[spec] ?? []).filter((d) => planSpecs.has(d));
  }

  // Kahn's with depth grouping
  const inDegree = new Map<string, number>();
  const successors = new Map<string, string[]>();

  for (const spec of planSpecs) {
    if (!inDegree.has(spec)) inDegree.set(spec, 0);
    if (!successors.has(spec)) successors.set(spec, []);
  }
  for (const [spec, deps] of Object.entries(subgraph)) {
    for (const dep of deps) {
      if (!successors.has(dep)) successors.set(dep, []);
      successors.get(dep)!.push(spec);
      inDegree.set(spec, (inDegree.get(spec) ?? 0) + 1);
    }
  }

  // Build spec -> entries map
  const specToEntries = new Map<string, SyncPlanEntry[]>();
  for (const entry of entries) {
    if (!specToEntries.has(entry.spec)) specToEntries.set(entry.spec, []);
    specToEntries.get(entry.spec)!.push(entry);
  }

  const batches: SyncBatch[] = [];
  let batchIndex = 0;

  // Process waves (each wave = one topological depth)
  let queue = [...inDegree.entries()]
    .filter(([, deg]) => deg === 0)
    .map(([spec]) => spec)
    .sort();

  while (queue.length > 0) {
    // Collect all entries for this wave
    const waveEntries: SyncPlanEntry[] = [];
    for (const spec of queue) {
      const entries = specToEntries.get(spec) ?? [];
      waveEntries.push(...entries);
    }

    // Split into chunks of maxBatchSize
    for (let i = 0; i < waveEntries.length; i += maxBatchSize) {
      const chunk = waveEntries.slice(i, i + maxBatchSize);
      batches.push({
        batchIndex,
        files: chunk,
        size: chunk.length,
      });
      batchIndex++;
    }

    // Advance: decrement successors, collect next wave
    const nextQueue: string[] = [];
    for (const spec of queue) {
      for (const succ of successors.get(spec) ?? []) {
        const newDeg = inDegree.get(succ)! - 1;
        inDegree.set(succ, newDeg);
        if (newDeg === 0) nextQueue.push(succ);
      }
    }
    queue = nextQueue.sort();
  }

  // Cycle fallback: emit any remaining entries
  const emitted = new Set(batches.flatMap((b) => b.files.map((f) => f.spec)));
  const remaining = entries.filter((e) => !emitted.has(e.spec));
  if (remaining.length > 0) {
    for (let i = 0; i < remaining.length; i += maxBatchSize) {
      const chunk = remaining.slice(i, i + maxBatchSize);
      batches.push({ batchIndex, files: chunk, size: chunk.length });
      batchIndex++;
    }
  }

  return batches;
}

// -- Deep sync ----------------------------------------------------------------

export interface DeepSyncOptions {
  force?: boolean;
}

/**
 * Compute a sync plan for a single file with dependency ordering.
 * Accepts either a spec path or a managed file path.
 */
export async function deepSyncPlan(
  filePath: string,
  cwd: string,
  options?: DeepSyncOptions,
): Promise<DeepSyncResult> {
  const absCwd = resolve(cwd);
  const force = options?.force ?? false;

  // Resolve to spec path
  let triggerSpec: string;
  if (filePath.endsWith(".spec.md")) {
    triggerSpec = filePath;
  } else {
    // Try to find spec from managed file header
    const absFile = resolve(absCwd, filePath);
    let found = false;
    try {
      const content = await readFile(absFile, "utf-8");
      const header = parseHeader(content);
      if (header) {
        // Header exists but doesn't contain spec path directly.
        // Fall back to convention: file.ext -> file.ext.spec.md
        triggerSpec = filePath + ".spec.md";
        found = true;
      }
    } catch (err: unknown) {
      if (!isEnoent(err)) throw err;
    }
    if (!found) {
      triggerSpec = filePath + ".spec.md";
    }
  }

  // Verify spec exists
  const absSpec = resolve(absCwd, triggerSpec);
  try {
    await stat(absSpec);
  } catch (err: unknown) {
    if (isEnoent(err)) {
      throw new Error(`Spec file not found: ${triggerSpec}`);
    }
    throw err;
  }

  // Get freshness and ripple check
  const freshness = await checkFreshnessAll(cwd);
  const ripple = await rippleCheck([triggerSpec], cwd);

  // Build state map from freshness
  const stateMap = new Map<string, FreshnessEntry>();
  for (const f of freshness.files) {
    stateMap.set(f.managed, f);
  }

  // Collect plan entries from ripple result
  const allEntries: SyncPlanEntry[] = [];

  for (const entry of ripple.layers.code.regenerate) {
    const freshEntry = stateMap.get(entry.managed);
    const state = freshEntry?.state ?? entry.currentState;
    if (state === "fresh") continue;
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state,
      cause: entry.cause,
      concrete: entry.concrete,
    });
  }

  for (const entry of ripple.layers.code.ghostStale) {
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state: "ghost-stale",
      cause: "ghost-stale",
      concrete: entry.concrete,
    });
  }

  const { plan, skipped } = partitionPlan(allEntries, force);

  // Sort plan by build order
  const specOrder = new Map<string, number>();
  for (let i = 0; i < ripple.buildOrder.length; i++) {
    specOrder.set(ripple.buildOrder[i]!, i);
  }
  plan.sort((a, b) => (specOrder.get(a.spec) ?? 999999) - (specOrder.get(b.spec) ?? 999999));

  return {
    trigger: triggerSpec,
    plan,
    skipped,
    stats: {
      totalAffected: plan.length + skipped.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: ripple.layers.code.regenerate.filter(
        (e) => (stateMap.get(e.managed)?.state ?? e.currentState) === "fresh",
      ).length,
    },
    buildOrder: ripple.buildOrder,
  };
}

// -- Bulk sync ----------------------------------------------------------------

export interface BulkSyncOptions {
  force?: boolean;
  maxBatchSize?: number;
}

/**
 * Compute a sync plan for all stale files with parallel batch grouping.
 */
export async function bulkSyncPlan(
  cwd: string,
  options?: BulkSyncOptions,
): Promise<BulkSyncResult> {
  const force = options?.force ?? false;
  const maxBatchSize = options?.maxBatchSize ?? 8;

  // Get freshness
  const freshness = await checkFreshnessAll(cwd);
  const staleEntries = freshness.files.filter((f) => f.state !== "fresh");

  if (staleEntries.length === 0) {
    return {
      batches: [],
      skipped: [],
      stats: {
        totalStale: 0,
        totalBatches: 0,
        toRegenerate: 0,
        skippedNeedConfirm: 0,
        freshSkipped: freshness.files.filter((f) => f.state === "fresh").length,
      },
      buildOrder: [],
    };
  }

  // Ripple check on all stale specs at once
  const staleSpecs = [...new Set(staleEntries.map((e) => e.spec))];
  const ripple = await rippleCheck(staleSpecs, cwd);

  // Build state map
  const stateMap = new Map<string, FreshnessEntry>();
  for (const f of freshness.files) {
    stateMap.set(f.managed, f);
  }

  // Collect entries from ripple, deduplicating
  const seen = new Set<string>();
  const allEntries: SyncPlanEntry[] = [];

  for (const entry of ripple.layers.code.regenerate) {
    if (seen.has(entry.managed)) continue;
    seen.add(entry.managed);
    const freshEntry = stateMap.get(entry.managed);
    const state = freshEntry?.state ?? entry.currentState;
    if (state === "fresh") continue;
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state,
      cause: entry.cause,
      concrete: entry.concrete,
    });
  }

  for (const entry of ripple.layers.code.ghostStale) {
    if (seen.has(entry.managed)) continue;
    seen.add(entry.managed);
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state: "ghost-stale",
      cause: "ghost-stale",
      concrete: entry.concrete,
    });
  }

  const { plan, skipped } = partitionPlan(allEntries, force);

  // Get DAG for batching
  const cache = await ensureDAG(cwd);
  const batches = computeParallelBatches(plan, cache.dag, maxBatchSize);

  return {
    batches,
    skipped,
    stats: {
      totalStale: plan.length + skipped.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: freshness.files.filter((f) => f.state === "fresh").length,
    },
    buildOrder: ripple.buildOrder,
  };
}

// -- Resume sync --------------------------------------------------------------

export interface ResumeSyncOptions {
  failedFiles: string[];
  succeededFiles: string[];
  force?: boolean;
  maxBatchSize?: number;
}

/**
 * Compute a plan to resume a partial sync after failure.
 * Includes failed files + their downstream dependents, excludes succeeded files.
 */
export async function resumeSyncPlan(
  cwd: string,
  options: ResumeSyncOptions,
): Promise<ResumeSyncResult> {
  const absCwd = resolve(cwd);
  const force = options.force ?? false;
  const maxBatchSize = options.maxBatchSize ?? 8;
  const succeededSet = new Set(options.succeededFiles);

  // Get freshness
  const freshness = await checkFreshnessAll(cwd);
  const stateMap = new Map<string, FreshnessEntry>();
  for (const f of freshness.files) {
    stateMap.set(f.managed, f);
  }

  // Identify specs of failed files
  const failedSpecs = new Set<string>();
  for (const managed of options.failedFiles) {
    const entry = stateMap.get(managed);
    if (entry) {
      failedSpecs.add(entry.spec);
    } else {
      // Convention fallback
      const candidate = managed + ".spec.md";
      try {
        await stat(resolve(absCwd, candidate));
        failedSpecs.add(candidate);
      } catch {
        // Not found -- skip
      }
    }
  }

  if (failedSpecs.size === 0) {
    return {
      batches: [],
      skipped: [],
      resumedFrom: options.failedFiles,
      alreadyDone: options.succeededFiles.length,
      stats: {
        totalStale: 0,
        totalBatches: 0,
        toRegenerate: 0,
        skippedNeedConfirm: 0,
        freshSkipped: 0,
      },
      buildOrder: [],
    };
  }

  // Build unified DAG and find downstream closure via BFS
  const cache = await ensureDAG(cwd);
  const graph = cache.dag;

  // Build reverse graph
  const reverse = new Map<string, string[]>();
  for (const [spec, deps] of Object.entries(graph)) {
    for (const dep of deps) {
      if (!reverse.has(dep)) reverse.set(dep, []);
      reverse.get(dep)!.push(spec);
    }
  }

  // BFS from failed specs
  const downstream = new Set(failedSpecs);
  const queue = [...failedSpecs];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const dependent of reverse.get(current) ?? []) {
      if (!downstream.has(dependent)) {
        downstream.add(dependent);
        queue.push(dependent);
      }
    }
  }

  // Collect stale entries in downstream closure, excluding succeeded
  const allEntries: SyncPlanEntry[] = [];
  for (const entry of freshness.files) {
    if (entry.state === "fresh") continue;
    if (succeededSet.has(entry.managed)) continue;
    if (!downstream.has(entry.spec)) continue;
    allEntries.push({
      managed: entry.managed,
      spec: entry.spec,
      state: entry.state,
      cause: failedSpecs.has(entry.spec) ? "retry" : "downstream",
    });
  }

  const { plan, skipped } = partitionPlan(allEntries, force);
  const batches = computeParallelBatches(plan, graph, maxBatchSize);

  // Build order for affected specs
  const planSpecs = new Set(plan.map((e) => e.spec));
  const subgraph: Record<string, string[]> = {};
  for (const spec of planSpecs) {
    subgraph[spec] = (graph[spec] ?? []).filter((d) => planSpecs.has(d));
  }
  let buildOrderResult: string[];
  try {
    buildOrderResult = topoSort(subgraph);
  } catch {
    buildOrderResult = [...planSpecs].sort();
  }

  return {
    batches,
    skipped,
    resumedFrom: options.failedFiles,
    alreadyDone: options.succeededFiles.length,
    stats: {
      totalStale: plan.length + skipped.length,
      totalBatches: batches.length,
      toRegenerate: plan.length,
      skippedNeedConfirm: skipped.length,
      freshSkipped: 0,
    },
    buildOrder: buildOrderResult,
  };
}
```

- [ ] **Step 4: Run tests**

Run: `cd prunejuice && npx vitest run test/sync.test.ts`
Expected: All 10 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/sync.ts prunejuice/test/sync.test.ts
git commit -m "feat(prunejuice): deep sync, bulk sync, resume sync planning"
```

---

### Task 5: Register MCP Tools in `mcp.ts`

**Files:**
- Modify: `prunejuice/src/mcp.ts`
- Create: `prunejuice/test/sync-mcp.test.ts`

- [ ] **Step 1: Write failing MCP handler tests**

Create `prunejuice/test/sync-mcp.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  handleDeepSyncPlan,
  handleBulkSyncPlan,
  handleSpecDiff,
  handleDiscoverFiles,
} from "../src/mcp.js";
import { clearDAGCache } from "../src/dag.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "sync-mcp-test-"));
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

describe("handleDeepSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns a deep sync result for a pending spec", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "x.ts.spec.md", "---\n---\n# X");

    const result = await handleDeepSyncPlan({ filePath: "x.ts.spec.md", cwd: tmp });
    expect(result.trigger).toBe("x.ts.spec.md");
    expect(result.plan.length).toBeGreaterThanOrEqual(1);
  });
});

describe("handleBulkSyncPlan", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    clearDAGCache();
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns batches for stale project", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "a.ts.spec.md", "---\n---\n# A");

    const result = await handleBulkSyncPlan({ cwd: tmp });
    expect(result.batches).toBeDefined();
    expect(result.stats).toBeDefined();
  });
});

describe("handleSpecDiff", () => {
  it("returns diff result", async () => {
    const result = await handleSpecDiff({
      oldSpec: "## Intent\nBuild widget",
      newSpec: "## Intent\nBuild widget\n## Constraints\nNone",
    });
    expect(result.changedSections).toContain("Constraints");
    expect(result.unchangedSections).toContain("Intent");
  });
});

describe("handleDiscoverFiles", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns discovered source files", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export {}");

    const result = await handleDiscoverFiles({ directory: tmp });
    expect(result).toContain("src/main.ts");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/sync-mcp.test.ts`
Expected: FAIL

- [ ] **Step 3: Add imports, handlers, and tool registrations to mcp.ts**

Add imports at the top of `mcp.ts`:

```typescript
import { deepSyncPlan, bulkSyncPlan, resumeSyncPlan } from "./sync.js";
import { computeSpecDiff } from "./spec-diff.js";
import { discoverFiles } from "./discover.js";
import type {
  DeepSyncResult,
  BulkSyncResult,
  ResumeSyncResult,
  SpecDiffResult,
} from "./types.js";
```

Add handler functions:

```typescript
// -- Deep sync handler --------------------------------------------------------

export interface DeepSyncPlanParams {
  filePath: string;
  cwd: string;
  force?: boolean;
}

export async function handleDeepSyncPlan(
  params: DeepSyncPlanParams,
): Promise<DeepSyncResult> {
  return deepSyncPlan(params.filePath, params.cwd, { force: params.force });
}

// -- Bulk sync handler --------------------------------------------------------

export interface BulkSyncPlanParams {
  cwd: string;
  force?: boolean;
  maxBatchSize?: number;
}

export async function handleBulkSyncPlan(
  params: BulkSyncPlanParams,
): Promise<BulkSyncResult> {
  return bulkSyncPlan(params.cwd, {
    force: params.force,
    maxBatchSize: params.maxBatchSize,
  });
}

// -- Spec diff handler --------------------------------------------------------

export interface SpecDiffParams {
  oldSpec: string;
  newSpec: string;
}

export async function handleSpecDiff(
  params: SpecDiffParams,
): Promise<SpecDiffResult> {
  return computeSpecDiff(params.oldSpec, params.newSpec);
}

// -- Discover files handler ---------------------------------------------------

export interface DiscoverFilesParams {
  directory: string;
  extensions?: string[];
  extraExcludes?: string[];
}

export async function handleDiscoverFiles(
  params: DiscoverFilesParams,
): Promise<string[]> {
  return discoverFiles(params.directory, {
    extensions: params.extensions,
    extraExcludes: params.extraExcludes,
  });
}
```

Register four new tools in `createServer()`:

```typescript
  server.registerTool(
    "prunejuice_deep_sync_plan",
    {
      description:
        "Compute a sync plan for a single file with dependency ordering. Accepts spec or managed file path.",
      inputSchema: {
        filePath: z.string().describe("Path to spec or managed file (relative to cwd)"),
        cwd: z.string().describe("Absolute path to the project root"),
        force: z.boolean().optional().describe("Include modified/conflict files without confirmation"),
      },
    },
    async (args) => {
      try {
        const result = await handleDeepSyncPlan({
          filePath: args.filePath,
          cwd: args.cwd,
          force: args.force,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message =
          err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_deep_sync_plan:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_bulk_sync_plan",
    {
      description:
        "Compute a sync plan for all stale files with parallel batch grouping.",
      inputSchema: {
        cwd: z.string().describe("Absolute path to the project root"),
        force: z.boolean().optional().describe("Include modified/conflict files"),
        maxBatchSize: z.number().int().optional().describe("Max files per batch (default 8)"),
      },
    },
    async (args) => {
      try {
        const result = await handleBulkSyncPlan({
          cwd: args.cwd,
          force: args.force,
          maxBatchSize: args.maxBatchSize,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message =
          err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_bulk_sync_plan:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_spec_diff",
    {
      description:
        "Compute section-level diff between two spec versions. Returns changed and unchanged section headings.",
      inputSchema: {
        oldSpec: z.string().describe("Old spec markdown text"),
        newSpec: z.string().describe("New spec markdown text"),
      },
    },
    async (args) => {
      try {
        const result = await handleSpecDiff({
          oldSpec: args.oldSpec,
          newSpec: args.newSpec,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message =
          err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_spec_diff:\n${message}` }],
        };
      }
    },
  );

  server.registerTool(
    "prunejuice_discover_files",
    {
      description:
        "Find source files in a directory, excluding tests and build artifacts.",
      inputSchema: {
        directory: z.string().describe("Directory to scan"),
        extensions: z.array(z.string()).optional().describe("File extensions to include (e.g. ['.py', '.ts'])"),
        extraExcludes: z.array(z.string()).optional().describe("Additional directory names to exclude"),
      },
    },
    async (args) => {
      try {
        const result = await handleDiscoverFiles({
          directory: args.directory,
          extensions: args.extensions,
          extraExcludes: args.extraExcludes,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err: unknown) {
        const message =
          err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
        return {
          isError: true,
          content: [{ type: "text", text: `Unexpected error in prunejuice_discover_files:\n${message}` }],
        };
      }
    },
  );
```

- [ ] **Step 4: Run MCP handler tests**

Run: `cd prunejuice && npx vitest run test/sync-mcp.test.ts`
Expected: All 4 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/mcp.ts prunejuice/test/sync-mcp.test.ts
git commit -m "feat(prunejuice): register deep_sync, bulk_sync, spec_diff, discover_files MCP tools"
```

---

### Task 6: Version Bump + Final Verification

**Files:**
- Modify: `prunejuice/package.json`

- [ ] **Step 1: Bump version**

Change `"version": "1.2.0"` to `"version": "1.3.0"` in `prunejuice/package.json`.

- [ ] **Step 2: Run full test suite**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 3: Run Python orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: All 408+ tests pass

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile

- [ ] **Step 5: Commit**

```bash
git add prunejuice/package.json
git commit -m "chore(prunejuice): bump version to 1.3.0 for Phase 3"
```

---

## Notes for the Implementer

### Key Invariants

1. **Sync plans compose Phase 1-2 building blocks.** `deepSyncPlan` = freshness + ripple. `bulkSyncPlan` = freshness + ripple + batching. `resumeSyncPlan` = freshness + DAG closure + batching. No new filesystem scanning logic -- everything goes through `checkFreshnessAll`, `rippleCheck`, and `ensureDAG`.

2. **Partition before batch.** Always split into `plan` (actionable) and `skipped` (modified/conflict needing confirmation) BEFORE computing parallel batches. The `force` flag bypasses this split.

3. **Kahn's depth grouping for batches.** All specs at the same topological depth share no dependency edges and can safely run in parallel. The `maxBatchSize` cap splits large waves into smaller chunks. This is the same algorithm as Python's `_compute_parallel_batches`.

4. **Resume closure is BFS through reverse edges.** Failed specs → find all specs that transitively depend on them → include only stale files within that closure. Succeeded files are excluded by managed-file path (not by spec).

5. **`specDiff` operates on raw markdown text, not file paths.** The MCP tool receives the text directly. The caller reads the files.

### What NOT to Build

- **`prunejuice_resume_sync_plan`** is not listed in the design spec's tool surface. Resume planning is available as a library function but is NOT exposed as an MCP tool in Phase 3. It can be added later if needed.
- **Python state management removal** happens at Phase 5, not now. Both MCP servers continue running in parallel.

### Compatibility Notes

The design spec's compatibility rule says: "Where the Python tools return a field, the prunejuice tools return the same field with the same name and type." The TypeScript types use camelCase (`changedSections`, `buildOrder`), while Python uses snake_case (`changed_sections`, `build_order`). Since these tools have the `prunejuice_*` prefix and won't be called by existing commands until Phase 5, camelCase is acceptable. A transform layer can be added at Phase 5 if needed.
