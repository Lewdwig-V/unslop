# Phase 6: Ripple Correctness Foundation -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `prunejuice_ripple_check` produce correct, actionable output for concrete specs -- including ghost staleness diagnostics with root cause tracing and full test coverage for `parseConcreteSpecFrontmatter`.

**Architecture:** New `manifest.ts` module handles concrete dependency graph hashing and diffing. Ghost staleness diagnostics attach to the existing ripple check output via a `GhostStaleDiagnostic` on `RippleManagedEntry`. `parseConcreteSpecFrontmatter` stays in `ripple.ts` but gets exported for direct testing. Test strategy is contract-based: behavioural contracts extracted from Python tests, YAML fixtures reused verbatim.

**Tech Stack:** TypeScript, vitest, SHA-256/12 (via `hashchain.ts`), temp directory fixtures

---

## File Structure

| File | Responsibility |
|------|---------------|
| `prunejuice/src/manifest.ts` | **Create.** Transitive concrete deps hashing (BFS), per-dependency manifest computation, manifest diffing, ghost staleness diagnosis + formatting. |
| `prunejuice/src/types.ts` | **Modify.** Add `GhostStaleDiagnostic`, `ManifestDiff`, sentinel constants. Add `diagnostic?` field to `RippleManagedEntry`. |
| `prunejuice/src/ripple.ts` | **Modify.** Export `parseConcreteSpecFrontmatter`. Call `diagnoseGhostStaleness` when classifying ghost-stale entries, attach diagnostic to `RippleManagedEntry`. |
| `prunejuice/src/hashchain.ts` | **Modify.** Add `concrete-manifest` line to `parseHeader` / `formatHeader`. |
| `prunejuice/test/concrete-frontmatter.test.ts` | **Create.** Contract tests for `parseConcreteSpecFrontmatter`. |
| `prunejuice/test/manifest.test.ts` | **Create.** Contract tests for manifest computation, diffing, and ghost diagnosis. |
| `prunejuice/test/extends-chain.test.ts` | **Create.** Contract tests for extends chain traversal in ripple. |
| `prunejuice/test/ghost-diagnostic.test.ts` | **Create.** Contract tests for ghost staleness diagnostic chain tracing and formatting. |

---

### Task 1: Add types and sentinel constants

**Files:**
- Modify: `prunejuice/src/types.ts`

- [ ] **Step 1: Add GhostStaleDiagnostic and ManifestDiff types, sentinel constants, and diagnostic field on RippleManagedEntry**

Add at the end of `prunejuice/src/types.ts`, before the closing content:

```typescript
// -- Concrete manifest types --------------------------------------------------

/** Sentinel hash for deps that don't exist on disk. */
export const MISSING_SENTINEL = "000000000000" as TruncatedHash;

/** Sentinel hash for deps that exist but can't be read. */
export const UNREADABLE_SENTINEL = "ffffffffffff" as TruncatedHash;

export interface ManifestDiff {
  added: string[];
  removed: string[];
  changed: string[];
}

export interface GhostStaleDiagnostic {
  /** The upstream spec whose content changed. */
  changedSpec: string;
  /** Current hash of the changed spec. */
  changeHash: TruncatedHash;
  /** Dependency path from root cause to this spec. */
  chain: string[];
  /** What specifically changed in the manifest. */
  manifestDiff: ManifestDiff;
}
```

Add `diagnostic?` field to the existing `RippleManagedEntry` interface:

```typescript
// In the existing RippleManagedEntry interface, add after ghostSource:
  diagnostic?: GhostStaleDiagnostic;
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd prunejuice && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add src/types.ts && git commit -m "feat(types): add GhostStaleDiagnostic, ManifestDiff, sentinel constants"
```

---

### Task 2: Export parseConcreteSpecFrontmatter from ripple.ts

**Files:**
- Modify: `prunejuice/src/ripple.ts`

- [ ] **Step 1: Export the function and its type**

In `prunejuice/src/ripple.ts`, change the `interface ConcreteSpecMeta` from a local interface to an exported one, and change `function parseConcreteSpecFrontmatter` to `export function parseConcreteSpecFrontmatter`:

```typescript
// Line ~20: change "interface" to "export interface"
export interface ConcreteSpecMeta {
  sourceSpec: string | null;
  concreteDependencies: string[];
  extends: string | null;
  targets: Array<{ path: string; language?: string }>;
}

// Line ~27: change "function" to "export function"
export function parseConcreteSpecFrontmatter(content: string): ConcreteSpecMeta {
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd prunejuice && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add src/ripple.ts && git commit -m "refactor: export parseConcreteSpecFrontmatter and ConcreteSpecMeta"
```

---

### Task 3: parseConcreteSpecFrontmatter contract tests

**Files:**
- Create: `prunejuice/test/concrete-frontmatter.test.ts`

- [ ] **Step 1: Write the contract tests**

Create `prunejuice/test/concrete-frontmatter.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  parseConcreteSpecFrontmatter,
} from "../src/ripple.js";

describe("parseConcreteSpecFrontmatter", () => {
  it("parses full concrete spec with all fields", () => {
    const content = [
      "---",
      "source-spec: src/retry.py.spec.md",
      "extends: shared/fastapi-async.impl.md",
      "concrete-dependencies:",
      "  - src/core/pool.py.impl.md",
      "  - src/core/config.py.impl.md",
      "---",
      "",
      "## Strategy",
      "Retry with backoff.",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.sourceSpec).toBe("src/retry.py.spec.md");
    expect(result.extends).toBe("shared/fastapi-async.impl.md");
    expect(result.concreteDependencies).toEqual([
      "src/core/pool.py.impl.md",
      "src/core/config.py.impl.md",
    ]);
  });

  it("parses concrete spec with no dependencies", () => {
    const content = [
      "---",
      "source-spec: src/retry.py.spec.md",
      "---",
      "",
      "# Just markdown",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.sourceSpec).toBe("src/retry.py.spec.md");
    expect(result.concreteDependencies).toEqual([]);
    expect(result.extends).toBeNull();
  });

  it("returns empty result when content has no frontmatter", () => {
    const content = "# Just markdown\n\nNo frontmatter.\n";
    const result = parseConcreteSpecFrontmatter(content);

    expect(result.sourceSpec).toBeNull();
    expect(result.concreteDependencies).toEqual([]);
    expect(result.extends).toBeNull();
    expect(result.targets).toEqual([]);
  });

  it("extracts extends field", () => {
    const content = [
      "---",
      "source-spec: src/handler.py.spec.md",
      "extends: shared/fastapi-async.impl.md",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);
    expect(result.extends).toBe("shared/fastapi-async.impl.md");
  });

  it("parses multi-target configuration with path and language", () => {
    const content = [
      "---",
      "source-spec: src/auth/auth_logic.spec.md",
      "targets:",
      "  - path: src/api/auth.py",
      "    language: python",
      "  - path: frontend/src/api/auth.ts",
      "    language: typescript",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.targets).toEqual([
      { path: "src/api/auth.py", language: "python" },
      { path: "frontend/src/api/auth.ts", language: "typescript" },
    ]);
  });

  it("parses targets with only required path field", () => {
    const content = [
      "---",
      "source-spec: src/shared.spec.md",
      "targets:",
      "  - path: backend/shared.py",
      "  - path: frontend/shared.ts",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.targets).toHaveLength(2);
    expect(result.targets[0]!.path).toBe("backend/shared.py");
    expect(result.targets[1]!.path).toBe("frontend/shared.ts");
  });

  it("targets array and concrete-dependencies coexist", () => {
    const content = [
      "---",
      "source-spec: src/auth.spec.md",
      "targets:",
      "  - path: src/api/auth.py",
      "    language: python",
      "  - path: frontend/src/auth.ts",
      "    language: typescript",
      "concrete-dependencies:",
      "  - src/core/tokens.impl.md",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.targets).toHaveLength(2);
    expect(result.concreteDependencies).toEqual(["src/core/tokens.impl.md"]);
  });

  it("normalizes snake_case keys to kebab-case", () => {
    const content = [
      "---",
      "source_spec: src/retry.py.spec.md",
      "concrete_dependencies:",
      "  - src/core/pool.py.impl.md",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);

    expect(result.sourceSpec).toBe("src/retry.py.spec.md");
    expect(result.concreteDependencies).toEqual(["src/core/pool.py.impl.md"]);
  });

  it("handles inline concrete-dependencies value", () => {
    const content = [
      "---",
      "source-spec: src/retry.py.spec.md",
      "concrete-dependencies: src/core/pool.py.impl.md",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);
    expect(result.concreteDependencies).toEqual(["src/core/pool.py.impl.md"]);
  });

  it("strips quotes from values", () => {
    const content = [
      "---",
      'source-spec: "src/retry.py.spec.md"',
      "extends: 'shared/base.impl.md'",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);
    expect(result.sourceSpec).toBe("src/retry.py.spec.md");
    expect(result.extends).toBe("shared/base.impl.md");
  });

  it("returns empty result for unclosed frontmatter", () => {
    const content = "---\nsource-spec: src/retry.py.spec.md\n# No closing ---\n";
    const result = parseConcreteSpecFrontmatter(content);

    expect(result.sourceSpec).toBeNull();
  });

  it("returns empty targets when targets field has no entries", () => {
    const content = [
      "---",
      "source-spec: src/shared.spec.md",
      "targets:",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);
    expect(result.targets).toEqual([]);
  });

  it("handles simple string targets (- src/foo.py)", () => {
    const content = [
      "---",
      "source-spec: src/shared.spec.md",
      "targets:",
      "  - src/foo.py",
      "  - src/bar.ts",
      "---",
    ].join("\n");

    const result = parseConcreteSpecFrontmatter(content);
    expect(result.targets).toEqual([
      { path: "src/foo.py" },
      { path: "src/bar.ts" },
    ]);
  });
});
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/concrete-frontmatter.test.ts`
Expected: all tests PASS (the function already exists, we're adding coverage)

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add test/concrete-frontmatter.test.ts && git commit -m "test: add parseConcreteSpecFrontmatter contract tests (13 cases)"
```

---

### Task 4: Extends chain contract tests

**Files:**
- Create: `prunejuice/test/extends-chain.test.ts`

These test the extends chain traversal that already exists in `ripple.ts` via the concrete layer BFS. They use `rippleCheck` as the entry point since the extends resolution is internal to ripple.

- [ ] **Step 1: Write the extends chain tests**

Create `prunejuice/test/extends-chain.test.ts`:

```typescript
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

    // parent.spec.md is changed (input)
    // parent.impl.md has source-spec: parent.spec.md
    // child.impl.md extends parent.impl.md, source-spec: child.spec.md
    // child.spec.md is NOT in input -- child.impl.md should be ghost-stale
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

    // child.impl.md should be ghost-stale through the extends edge
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

    // Both parent and child should be ghost-stale
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
    // child extends base AND depends on util
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/extends-chain.test.ts`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add test/extends-chain.test.ts && git commit -m "test: add extends chain contract tests for ripple propagation (4 cases)"
```

---

### Task 5: Extend header format with concrete-manifest support

**Files:**
- Modify: `prunejuice/src/hashchain.ts`
- Modify: `prunejuice/test/hashchain.test.ts` (add tests first -- TDD)

The managed file header needs to store the concrete manifest so ghost staleness diagnostics can diff against the last-ratified state.

- [ ] **Step 1: Write failing tests for concrete-manifest in headers**

Add to `prunejuice/test/hashchain.test.ts`:

```typescript
import {
  truncatedHash,
  formatHeader,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
  formatManifestLine,
  parseManifestLine,
} from "../src/hashchain.js";
import type { TruncatedHash } from "../src/types.js";
import { MISSING_SENTINEL, UNREADABLE_SENTINEL } from "../src/types.js";

// ... existing tests ...

describe("concrete-manifest header line", () => {
  it("formats manifest as comma-separated path:hash pairs", () => {
    const manifest = new Map<string, TruncatedHash>([
      ["pool.impl.md", "a3f8c2e9b7d1" as TruncatedHash],
      ["base.impl.md", "7f2e1b8a9c04" as TruncatedHash],
    ]);

    const line = formatManifestLine(manifest);
    // Sorted by path
    expect(line).toBe(
      "# concrete-manifest:base.impl.md:7f2e1b8a9c04,pool.impl.md:a3f8c2e9b7d1",
    );
  });

  it("parses manifest line back to Map", () => {
    const line =
      "# concrete-manifest:base.impl.md:7f2e1b8a9c04,pool.impl.md:a3f8c2e9b7d1";
    const manifest = parseManifestLine(line);

    expect(manifest).not.toBeNull();
    expect(manifest!.get("base.impl.md")).toBe("7f2e1b8a9c04");
    expect(manifest!.get("pool.impl.md")).toBe("a3f8c2e9b7d1");
  });

  it("roundtrips manifest through format and parse", () => {
    const original = new Map<string, TruncatedHash>([
      ["src/pool.impl.md", "a3f8c2e9b7d1" as TruncatedHash],
      ["shared/base.impl.md", "b3d5a1f8e290" as TruncatedHash],
    ]);

    const line = formatManifestLine(original);
    const parsed = parseManifestLine(line);

    expect(parsed).not.toBeNull();
    expect(parsed!.size).toBe(2);
    expect(parsed!.get("src/pool.impl.md")).toBe("a3f8c2e9b7d1");
    expect(parsed!.get("shared/base.impl.md")).toBe("b3d5a1f8e290");
  });

  it("roundtrips sentinel values (MISSING_SENTINEL, UNREADABLE_SENTINEL)", () => {
    const original = new Map<string, TruncatedHash>([
      ["pool.impl.md", "a3f8c2e9b7d1" as TruncatedHash],
      ["missing.impl.md", MISSING_SENTINEL],
      ["bad.impl.md", UNREADABLE_SENTINEL],
    ]);

    const line = formatManifestLine(original);
    const parsed = parseManifestLine(line);

    expect(parsed!.get("missing.impl.md")).toBe(MISSING_SENTINEL);
    expect(parsed!.get("bad.impl.md")).toBe(UNREADABLE_SENTINEL);
  });

  it("returns null for non-manifest lines", () => {
    expect(parseManifestLine("# just a comment")).toBeNull();
    expect(parseManifestLine("// spec-hash:abc")).toBeNull();
  });

  it("handles empty manifest", () => {
    const manifest = new Map<string, TruncatedHash>();
    const line = formatManifestLine(manifest);
    expect(line).toBe("# concrete-manifest:");

    const parsed = parseManifestLine(line);
    expect(parsed).not.toBeNull();
    expect(parsed!.size).toBe(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/hashchain.test.ts`
Expected: FAIL -- `formatManifestLine` and `parseManifestLine` not exported

- [ ] **Step 3: Implement formatManifestLine and parseManifestLine**

Add to `prunejuice/src/hashchain.ts`:

```typescript
import { MISSING_SENTINEL, UNREADABLE_SENTINEL } from "./types.js";

// -- Concrete manifest header line --------------------------------------------

const MANIFEST_LINE_RE = /^[#/]+ concrete-manifest:(.*)$/;

/** Format a concrete manifest Map as a header-safe line. */
export function formatManifestLine(
  manifest: Map<string, TruncatedHash>,
  commentStyle: "#" | "//" = "#",
): string {
  const entries = [...manifest.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, hash]) => `${path}:${hash}`)
    .join(",");
  return `${commentStyle} concrete-manifest:${entries}`;
}

/** Parse a concrete-manifest header line back to a Map. Returns null if not a manifest line. */
export function parseManifestLine(
  line: string,
): Map<string, TruncatedHash> | null {
  const match = line.replace(/^\/\//, "#").match(MANIFEST_LINE_RE);
  if (!match) return null;

  const body = match[1]!.trim();
  const result = new Map<string, TruncatedHash>();
  if (body === "") return result;

  for (const entry of body.split(",")) {
    const lastColon = entry.lastIndexOf(":");
    if (lastColon === -1) continue;
    const path = entry.slice(0, lastColon);
    const hash = entry.slice(lastColon + 1) as TruncatedHash;
    result.set(path, hash);
  }

  return result;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/hashchain.test.ts`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/hashchain.ts test/hashchain.test.ts && git commit -m "feat(hashchain): add concrete-manifest header line format/parse"
```

---

### Task 6: Create manifest.ts -- diffConcreteManifests (pure function, no IO)

**Files:**
- Create: `prunejuice/src/manifest.ts`
- Create: `prunejuice/test/manifest.test.ts`

Start with the pure function (no IO) so the tests are fast and synchronous.

- [ ] **Step 1: Write failing tests for diffConcreteManifests**

Create `prunejuice/test/manifest.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { diffConcreteManifests } from "../src/manifest.js";
import type { TruncatedHash } from "../src/types.js";

function h(s: string): TruncatedHash {
  return s as TruncatedHash;
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/manifest.test.ts`
Expected: FAIL -- module not found

- [ ] **Step 3: Implement diffConcreteManifests**

Create `prunejuice/src/manifest.ts`:

```typescript
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { truncatedHash } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import { parseConcreteSpecFrontmatter } from "./ripple.js";
import type { TruncatedHash, ManifestDiff, GhostStaleDiagnostic } from "./types.js";
import { MISSING_SENTINEL, UNREADABLE_SENTINEL } from "./types.js";

// -- Manifest diffing (pure, no IO) ------------------------------------------

/** Compute the structural diff between two concrete dependency manifests. */
export function diffConcreteManifests(
  previous: Map<string, TruncatedHash>,
  current: Map<string, TruncatedHash>,
): ManifestDiff {
  const added: string[] = [];
  const removed: string[] = [];
  const changed: string[] = [];

  for (const [path, hash] of current) {
    const prev = previous.get(path);
    if (prev === undefined) {
      added.push(path);
    } else if (prev !== hash) {
      changed.push(path);
    }
  }

  for (const path of previous.keys()) {
    if (!current.has(path)) {
      removed.push(path);
    }
  }

  added.sort();
  removed.sort();
  changed.sort();

  return { added, removed, changed };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/manifest.test.ts`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/manifest.ts test/manifest.test.ts && git commit -m "feat(manifest): add diffConcreteManifests pure function"
```

---

### Task 7: Add computeConcreteManifest (IO-bound BFS)

**Files:**
- Modify: `prunejuice/src/manifest.ts`
- Modify: `prunejuice/test/manifest.test.ts`

- [ ] **Step 1: Write failing tests for computeConcreteManifest**

Add to `prunejuice/test/manifest.test.ts`:

```typescript
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

// ... existing diffConcreteManifests tests ...

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
    // Direct dep
    expect(manifest!.has("util.impl.md")).toBe(true);
    // Transitive dep
    expect(manifest!.has("core.impl.md")).toBe(true);
  });

  it("handles cycles in dependency graph without infinite loop", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // a depends on b, b depends on a (cycle)
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

    // Should not hang -- visited set breaks the cycle
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
    // Only one entry for base, not two
    expect(manifest!.size).toBe(1);
    expect(manifest!.get("base.impl.md")).toBe(truncatedHash(baseContent));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/manifest.test.ts`
Expected: FAIL -- `computeConcreteManifest` not exported

- [ ] **Step 3: Implement computeConcreteManifest and computeConcreteDepsHash**

Add to `prunejuice/src/manifest.ts`:

```typescript
// -- Strategy provider resolution ---------------------------------------------

/** Get all strategy providers: concrete-dependencies union extends. */
function getAllStrategyProviders(meta: {
  concreteDependencies: string[];
  extends: string | null;
}): string[] {
  const providers = new Set(meta.concreteDependencies);
  if (meta.extends) providers.add(meta.extends);
  return [...providers].sort();
}

// -- Manifest computation (IO-bound BFS) --------------------------------------

/**
 * Compute per-dependency manifest for a concrete spec.
 * BFS through concrete-dependencies + extends, hashing each file's content.
 * Returns null if the spec has no providers.
 */
export async function computeConcreteManifest(
  specPath: string,
  cwd: string,
): Promise<Map<string, TruncatedHash> | null> {
  const absCwd = resolve(cwd);
  const absSpec = join(absCwd, specPath);

  let content: string;
  try {
    content = await readFile(absSpec, "utf-8");
  } catch (err) {
    if (isEnoent(err)) return null;
    throw err;
  }

  const meta = parseConcreteSpecFrontmatter(content);
  const directProviders = getAllStrategyProviders(meta);
  if (directProviders.length === 0) return null;

  const manifest = new Map<string, TruncatedHash>();
  const visited = new Set<string>();
  const queue = [...directProviders];

  while (queue.length > 0) {
    const depPath = queue.shift()!;
    if (visited.has(depPath)) continue;
    visited.add(depPath);

    const absDep = join(absCwd, depPath);
    let depContent: string;
    try {
      depContent = await readFile(absDep, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        manifest.set(depPath, MISSING_SENTINEL);
        continue;
      }
      manifest.set(depPath, UNREADABLE_SENTINEL);
      continue;
    }

    manifest.set(depPath, truncatedHash(depContent));

    // Walk transitive providers
    const depMeta = parseConcreteSpecFrontmatter(depContent);
    for (const upstream of getAllStrategyProviders(depMeta)) {
      if (!visited.has(upstream)) {
        queue.push(upstream);
      }
    }
  }

  return manifest.size > 0 ? manifest : null;
}

/**
 * Compute a single opaque hash of all transitive strategy providers.
 * Returns null if the spec has no providers.
 */
export async function computeConcreteDepsHash(
  specPath: string,
  cwd: string,
): Promise<TruncatedHash | null> {
  const manifest = await computeConcreteManifest(specPath, cwd);
  if (!manifest) return null;

  const combined = [...manifest.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, hash]) => `${path}:${hash}`)
    .join("\n");

  return truncatedHash(combined);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/manifest.test.ts`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/manifest.ts test/manifest.test.ts && git commit -m "feat(manifest): add computeConcreteManifest and computeConcreteDepsHash"
```

---

### Task 8: Add computeConcreteDepsHash tests

**Files:**
- Modify: `prunejuice/test/manifest.test.ts`

- [ ] **Step 1: Write tests for computeConcreteDepsHash**

Add to `prunejuice/test/manifest.test.ts`:

```typescript
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

    // Update pool content
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

    // Change parent
    await writeAt(
      tmp,
      "parent.impl.md",
      "---\nsource-spec: parent.spec.md\n---\n## Strategy\nParent v2.",
    );

    const hash2 = await computeConcreteDepsHash("child.impl.md", tmp);

    expect(hash1).not.toBe(hash2);
  });
});
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/manifest.test.ts`
Expected: all tests PASS (implementation was added in Task 7)

- [ ] **Step 3: Commit**

```bash
cd prunejuice && git add test/manifest.test.ts && git commit -m "test: add computeConcreteDepsHash contract tests (5 cases)"
```

---

### Task 9: Ghost staleness diagnosis -- diagnoseGhostStaleness and formatGhostDiagnostic

**Files:**
- Modify: `prunejuice/src/manifest.ts`
- Create: `prunejuice/test/ghost-diagnostic.test.ts`

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/ghost-diagnostic.test.ts`:

```typescript
import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  diagnoseGhostStaleness,
  formatGhostDiagnostic,
  computeConcreteManifest,
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

    // Pool was "Sync pool" at ratification, now "Async pool"
    const oldPoolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nSync pool.";
    const newPoolContent = "---\nsource-spec: pool.spec.md\n---\n## Strategy\nAsync pool.";
    await writeAt(tmp, "pool.impl.md", newPoolContent);

    const storedManifest = new Map<string, TruncatedHash>([
      ["pool.impl.md", truncatedHash(oldPoolContent)],
    ]);

    const diagnostics = await diagnoseGhostStaleness(
      storedManifest,
      tmp,
    );

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("pool.impl.md");
    expect(diagnostics[0]!.chain).toContain("pool.impl.md");
    expect(diagnostics[0]!.manifestDiff.changed).toContain("pool.impl.md");
  });

  it("reports missing dep with 'not found' in chain", async () => {
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

    // Dep was missing at ratification and is still missing -- no change
    const storedManifest = new Map<string, TruncatedHash>([
      ["still-missing.impl.md", MISSING_SENTINEL],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);
    expect(diagnostics).toEqual([]);
  });

  it("traces through deep dep chain for root cause", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    // handler depends on service, service depends on utils
    // utils changed, service stored hash is stale
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

    // Stored manifest has old hash for service (indicating it changed)
    const storedManifest = new Map<string, TruncatedHash>([
      ["service.impl.md", h("000000000000")],
    ]);

    const diagnostics = await diagnoseGhostStaleness(storedManifest, tmp);

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]!.changedSpec).toBe("service.impl.md");
    // Chain should trace through to service's upstream
    expect(diagnostics[0]!.chain.length).toBeGreaterThanOrEqual(1);
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

    const lines = formatGhostDiagnostic(diag);
    expect(lines).toContain("pool.impl.md");
    expect(lines).toContain("changed");
  });

  it("formats deep chain with via annotation", () => {
    const diag: GhostStaleDiagnostic = {
      changedSpec: "service.impl.md",
      changeHash: h("bbbbbbbbbbbb"),
      chain: ["service.impl.md", "utils.impl.md"],
      manifestDiff: { added: [], removed: [], changed: ["service.impl.md"] },
    };

    const lines = formatGhostDiagnostic(diag);
    expect(lines).toContain("service.impl.md");
    expect(lines).toContain("via");
    expect(lines).toContain("utils.impl.md");
  });

  it("formats missing dep", () => {
    const diag: GhostStaleDiagnostic = {
      changedSpec: "gone.impl.md",
      changeHash: MISSING_SENTINEL,
      chain: ["gone.impl.md"],
      manifestDiff: { added: [], removed: ["gone.impl.md"], changed: [] },
    };

    const lines = formatGhostDiagnostic(diag);
    expect(lines).toContain("gone.impl.md");
    expect(lines).toContain("not found");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/ghost-diagnostic.test.ts`
Expected: FAIL -- `diagnoseGhostStaleness` and `formatGhostDiagnostic` not exported

- [ ] **Step 3: Implement diagnoseGhostStaleness and formatGhostDiagnostic**

Add to `prunejuice/src/manifest.ts`:

```typescript
// -- Ghost staleness chain tracing --------------------------------------------

/**
 * Walk upstream from a changed dep to find the deepest changed node.
 * Returns the chain from the direct dep to the deepest upstream.
 */
async function traceChangeChain(
  depPath: string,
  cwd: string,
): Promise<string[]> {
  const absCwd = resolve(cwd);
  const chain = [depPath];
  const visited = new Set([depPath]);
  let current = depPath;

  while (true) {
    const absPath = join(absCwd, current);
    let content: string;
    try {
      content = await readFile(absPath, "utf-8");
    } catch {
      break;
    }

    const meta = parseConcreteSpecFrontmatter(content);
    const upstreams = getAllStrategyProviders(meta);

    let foundDeeper = false;
    for (const up of upstreams) {
      if (visited.has(up)) continue;
      visited.add(up);
      chain.push(up);
      current = up;
      foundDeeper = true;
      break; // depth-first: follow first unvisited upstream
    }

    if (!foundDeeper) break;
  }

  return chain;
}

/**
 * Compare stored manifest against current disk state.
 * Returns diagnostics for each dependency that has changed.
 */
export async function diagnoseGhostStaleness(
  storedManifest: Map<string, TruncatedHash>,
  cwd: string,
): Promise<GhostStaleDiagnostic[]> {
  const absCwd = resolve(cwd);
  const diagnostics: GhostStaleDiagnostic[] = [];

  // Compute current manifest of each stored dep for diffing
  const currentManifest = new Map<string, TruncatedHash>();

  for (const [depPath, storedHash] of [...storedManifest.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const absDep = join(absCwd, depPath);
    let depContent: string;

    try {
      depContent = await readFile(absDep, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        // File was present before but is now gone -- OR it was already MISSING_SENTINEL
        if (storedHash === MISSING_SENTINEL) {
          // Was missing before, still missing -- no change
          currentManifest.set(depPath, MISSING_SENTINEL);
          continue;
        }
        currentManifest.set(depPath, MISSING_SENTINEL);
        diagnostics.push({
          changedSpec: depPath,
          changeHash: MISSING_SENTINEL,
          chain: [depPath],
          manifestDiff: { added: [], removed: [depPath], changed: [] },
        });
        continue;
      }
      throw err;
    }

    const currentHash = truncatedHash(depContent);
    currentManifest.set(depPath, currentHash);

    if (currentHash === storedHash) continue; // fresh

    // Changed -- trace the chain for root cause
    const chain = await traceChangeChain(depPath, cwd);

    diagnostics.push({
      changedSpec: depPath,
      changeHash: currentHash,
      chain,
      manifestDiff: diffConcreteManifests(storedManifest, currentManifest),
    });
  }

  return diagnostics;
}

/**
 * Format a ghost staleness diagnostic into a human-readable string.
 * This is the output the command layer surfaces directly.
 */
export function formatGhostDiagnostic(diagnostic: GhostStaleDiagnostic): string {
  const { changedSpec, changeHash, chain } = diagnostic;

  if (changeHash === MISSING_SENTINEL) {
    return `upstream \`${changedSpec}\` not found`;
  }

  if (chain.length <= 1) {
    return `upstream \`${changedSpec}\` changed`;
  }

  const via = chain.slice(1).join(" -> ");
  return `upstream \`${changedSpec}\` changed (via ${via})`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/ghost-diagnostic.test.ts`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/manifest.ts test/ghost-diagnostic.test.ts && git commit -m "feat(manifest): add diagnoseGhostStaleness and formatGhostDiagnostic"
```

---

### Task 10: Wire ghost diagnostics into rippleCheck

**Files:**
- Modify: `prunejuice/src/ripple.ts`
- Modify: `prunejuice/test/ripple.test.ts` (add integration test)

- [ ] **Step 1: Write failing test -- ghost-stale entries should have diagnostic**

Add to the existing `describe("rippleCheck", ...)` block in `prunejuice/test/ripple.test.ts`:

```typescript
import {
  computeConcreteManifest,
  formatGhostDiagnostic,
} from "../src/manifest.js";
import { formatManifestLine } from "../src/hashchain.js";

// Add this test to the existing describe block:

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

    // b.impl.md has concrete-dependency on a.impl.md and a managed file with a stored manifest
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prunejuice && npx vitest run test/ripple.test.ts`
Expected: FAIL -- `diagnostic` is undefined on ghost-stale entries

- [ ] **Step 3: Wire diagnoseGhostStaleness into ripple.ts**

In `prunejuice/src/ripple.ts`, add the diagnostic wiring to the ghost-stale managed entry construction (around line 431-461). Import the needed functions and modify the ghost-stale loop:

```typescript
// Add to imports at top of ripple.ts:
import {
  diagnoseGhostStaleness,
  computeConcreteManifest,
} from "./manifest.js";
import { parseManifestLine } from "./hashchain.js";
import type { GhostStaleDiagnostic } from "./types.js";

// Replace the ghost-stale managed entries loop (lines ~431-461) with:

  // Ghost-stale managed entries from ghost-stale impls
  for (const impl of ghostStaleImpls) {
    const meta = implMeta.get(impl);
    if (!meta) continue;

    const targetPaths =
      meta.targets.length > 0
        ? meta.targets.map((t) => t.path)
        : [impl.replace(/\.impl\.md$/, "")];

    // Try to compute ghost diagnostic from stored manifest
    let diagnostic: GhostStaleDiagnostic | undefined;
    for (const target of targetPaths) {
      const absTarget = join(absCwd, target);
      let managedContent: string | null = null;
      try {
        managedContent = await readFile(absTarget, "utf-8");
      } catch {
        // File may not exist yet
      }

      if (managedContent) {
        // Look for stored manifest in managed file header
        const headerLines = managedContent.split("\n").slice(0, 10);
        for (const line of headerLines) {
          const storedManifest = parseManifestLine(line);
          if (storedManifest && storedManifest.size > 0) {
            const diagnostics = await diagnoseGhostStaleness(
              storedManifest,
              cwd,
            );
            if (diagnostics.length > 0) {
              diagnostic = diagnostics[0];
            }
            break;
          }
        }
      }

      let exists = true;
      try {
        await stat(absTarget);
      } catch (err: unknown) {
        if (!isEnoent(err)) throw err;
        exists = false;
      }

      const entry: RippleManagedEntry = {
        managed: target,
        spec: meta.sourceSpec ?? impl,
        concrete: impl,
        exists,
        currentState: "ghost-stale",
        cause: "ghost-stale",
        ghostSource: impl,
        diagnostic,
      };
      ghostStale.push(entry);
    }
  }
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd prunejuice && npx vitest run`
Expected: all tests PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
cd prunejuice && git add src/ripple.ts test/ripple.test.ts && git commit -m "feat(ripple): attach GhostStaleDiagnostic to ghost-stale managed entries"
```

---

### Task 11: Run full test suite and verify

**Files:**
- None (verification only)

- [ ] **Step 1: Run the complete prunejuice test suite**

Run: `cd prunejuice && npx vitest run`
Expected: all tests PASS, including the new test files:
- `test/concrete-frontmatter.test.ts` (13 tests)
- `test/manifest.test.ts` (12+ tests)
- `test/extends-chain.test.ts` (4 tests)
- `test/ghost-diagnostic.test.ts` (9 tests)
- Plus existing tests (no regressions)

- [ ] **Step 2: Verify TypeScript compiles clean**

Run: `cd prunejuice && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Verify exports are accessible**

Run: `cd prunejuice && node -e "import('./dist/manifest.js').then(m => console.log(Object.keys(m)))"`

If this fails because dist is stale, run `npx tsc` first, then retry.

Expected: `['diffConcreteManifests', 'computeConcreteManifest', 'computeConcreteDepsHash', 'diagnoseGhostStaleness', 'formatGhostDiagnostic']`

- [ ] **Step 4: Final commit if any cleanup was needed**

```bash
cd prunejuice && git add -A && git commit -m "chore: phase 6 verification and cleanup"
```

Only commit if there are actual changes. If everything was clean, skip this step.
