# Prunejuice Phase 1: MCP Server + Freshness Tool -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the prunejuice MCP server with `prunejuice_check_freshness` as the first tool, running alongside the existing Python MCP server.

**Architecture:** An MCP server in `prunejuice/src/mcp.ts` exposes tools via the `@modelcontextprotocol/sdk` MCP server primitives. The server is registered in the unslop plugin's `.mcp.json` alongside the Python server. The freshness tool wraps the existing `classifyFreshness()` from `hashchain.ts`, adding file discovery (scan for `*.spec.md`, derive managed paths, read headers, compute current hashes).

**Tech Stack:** TypeScript, `@modelcontextprotocol/sdk` (MCP server), vitest

**Task order:** Task 4 (install deps) must run before Task 2 (MCP server uses those deps). Recommended execution order: 4 → 1 → 2 → 3 → 5 → 6. Tasks 1 and 4 can run in parallel since they touch different files.

**Reference files:**
- Spec: `docs/superpowers/specs/2026-03-31-prunejuice-integration-design.md`
- Existing hashchain: `prunejuice/src/hashchain.ts`
- Existing store: `prunejuice/src/store.ts`
- Python MCP server (compatibility target): `unslop/scripts/mcp_server.py`
- Plugin MCP config: `unslop/.claude-plugin/.mcp.json`

---

### Task 1: Add freshness scanning module

**Files:**
- Create: `prunejuice/src/freshness.ts`
- Test: `prunejuice/test/freshness.test.ts`

This module bridges the single-file `classifyFreshness()` in `hashchain.ts` to project-wide scanning -- discovering all spec files, deriving managed paths, reading headers, and computing current hashes.

- [ ] **Step 1: Write the test file with initial tests**

```typescript
// prunejuice/test/freshness.test.ts
import { describe, it, expect, beforeEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { checkFreshnessAll, type FreshnessEntry } from "../src/freshness.js";

let cwd: string;

beforeEach(async () => {
  cwd = await mkdtemp(join(tmpdir(), "pj-freshness-"));
});

describe("checkFreshnessAll", () => {
  it("returns empty files array when no specs exist", async () => {
    const result = await checkFreshnessAll(cwd);
    expect(result.status).toBe("ok");
    expect(result.files).toEqual([]);
    expect(result.summary).toContain("0");
  });

  it("returns pending for a spec with no managed file", async () => {
    await mkdir(join(cwd, "src"), { recursive: true });
    await writeFile(
      join(cwd, "src", "utils.py.spec.md"),
      "---\nintent: Do something\n---\n## Purpose\nUtility functions",
    );

    const result = await checkFreshnessAll(cwd);
    expect(result.status).toBe("ok");
    expect(result.files).toHaveLength(1);
    expect(result.files[0]!.state).toBe("pending");
    expect(result.files[0]!.managed).toBe("src/utils.py");
    expect(result.files[0]!.spec).toBe("src/utils.py.spec.md");
  });

  it("returns fresh for a managed file with matching hashes", async () => {
    await mkdir(join(cwd, "src"), { recursive: true });

    const specContent = "---\nintent: Hash things\n---\n## Purpose\nHashing";
    await writeFile(join(cwd, "src", "hash.py.spec.md"), specContent);

    // Compute the hashes that would match
    const { truncatedHash } = await import("../src/hashchain.js");
    const specHash = truncatedHash(specContent);
    const codeBody = "def hash(x): return x";
    const outputHash = truncatedHash(codeBody);

    await writeFile(
      join(cwd, "src", "hash.py"),
      `# @prunejuice-managed -- Edit src/hash.py.spec.md instead\n# spec-hash:${specHash} output-hash:${outputHash} generated:2026-03-28T00:00:00Z\n\n${codeBody}`,
    );

    const result = await checkFreshnessAll(cwd);
    expect(result.files).toHaveLength(1);
    expect(result.files[0]!.state).toBe("fresh");
  });

  it("returns stale when spec content changed", async () => {
    await mkdir(join(cwd, "src"), { recursive: true });

    const oldSpecContent = "---\nintent: Old intent\n---\n## Purpose\nOld";
    const { truncatedHash } = await import("../src/hashchain.js");
    const oldSpecHash = truncatedHash(oldSpecContent);
    const codeBody = "def old(): pass";
    const outputHash = truncatedHash(codeBody);

    // Write the managed file with the OLD spec hash
    await writeFile(
      join(cwd, "src", "mod.py"),
      `# @prunejuice-managed -- Edit src/mod.py.spec.md instead\n# spec-hash:${oldSpecHash} output-hash:${outputHash} generated:2026-03-28T00:00:00Z\n\n${codeBody}`,
    );

    // Write the NEW spec (different content, different hash)
    await writeFile(
      join(cwd, "src", "mod.py.spec.md"),
      "---\nintent: New intent\n---\n## Purpose\nNew",
    );

    const result = await checkFreshnessAll(cwd);
    expect(result.files).toHaveLength(1);
    expect(result.files[0]!.state).toBe("stale");
  });

  it("excludes .prunejuice and node_modules directories", async () => {
    await mkdir(join(cwd, ".prunejuice", "artifacts"), { recursive: true });
    await mkdir(join(cwd, "node_modules", "pkg"), { recursive: true });
    await writeFile(
      join(cwd, ".prunejuice", "internal.spec.md"),
      "---\n---\nshould be excluded",
    );
    await writeFile(
      join(cwd, "node_modules", "pkg", "index.js.spec.md"),
      "---\n---\nshould be excluded",
    );

    const result = await checkFreshnessAll(cwd);
    expect(result.files).toEqual([]);
  });

  it("respects custom excludePatterns", async () => {
    await mkdir(join(cwd, "vendor"), { recursive: true });
    await writeFile(
      join(cwd, "vendor", "lib.py.spec.md"),
      "---\nintent: Vendored\n---\n",
    );

    const result = await checkFreshnessAll(cwd, {
      excludePatterns: ["vendor"],
    });
    expect(result.files).toEqual([]);
  });

  it("returns fail status when any file is conflict", async () => {
    await mkdir(join(cwd, "src"), { recursive: true });

    const { truncatedHash } = await import("../src/hashchain.js");
    const codeBody = "def changed(): pass";
    // Deliberately mismatched hashes for both spec and output
    await writeFile(
      join(cwd, "src", "conflict.py"),
      `# @prunejuice-managed -- Edit src/conflict.py.spec.md instead\n# spec-hash:000000000000 output-hash:000000000000 generated:2026-03-28T00:00:00Z\n\n${codeBody}`,
    );
    await writeFile(
      join(cwd, "src", "conflict.py.spec.md"),
      "---\nintent: Different\n---\n",
    );

    const result = await checkFreshnessAll(cwd);
    expect(result.status).toBe("fail");
    expect(result.files[0]!.state).toBe("conflict");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prunejuice && npx vitest run test/freshness.test.ts`
Expected: FAIL -- `checkFreshnessAll` does not exist yet.

- [ ] **Step 3: Implement the freshness scanning module**

```typescript
// prunejuice/src/freshness.ts
import { readFile, readdir, stat } from "node:fs/promises";
import { join, relative } from "node:path";
import {
  truncatedHash,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
  type FreshnessState,
} from "./hashchain.js";

export interface FreshnessEntry {
  managed: string; // relative path to managed file
  spec: string; // relative path to spec file
  state: FreshnessState;
  hint?: string;
}

export interface FreshnessReport {
  status: "ok" | "fail";
  files: FreshnessEntry[];
  summary: string;
}

const DEFAULT_EXCLUDES = [
  ".prunejuice",
  ".unslop",
  "node_modules",
  ".git",
  "__pycache__",
  "dist",
  "build",
  ".venv",
  "venv",
];

const HINTS: Record<string, string> = {
  fresh: "Up to date.",
  stale:
    "Spec changed, code unchanged. Regenerate with prunejuice generate.",
  modified: "Code was edited directly while spec is unchanged.",
  conflict:
    "Spec and code have both diverged. Resolve manually or use --force to overwrite edits.",
  pending: "Spec exists but no managed code yet. Run generate.",
  structural: "Code disappeared -- lifecycle issue (absorb/exude needed).",
  "ghost-stale": "Upstream dependency changed.",
  "test-drifted": "Spec changed since tests were generated.",
};

async function findSpecFiles(
  dir: string,
  root: string,
  excludes: string[],
): Promise<string[]> {
  const specs: string[] = [];

  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return specs;
  }

  for (const entry of entries) {
    if (excludes.includes(entry.name)) continue;

    const fullPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      specs.push(...(await findSpecFiles(fullPath, root, excludes)));
    } else if (entry.name.endsWith(".spec.md")) {
      specs.push(relative(root, fullPath));
    }
  }

  return specs.sort();
}

function deriveManagedPath(specPath: string): string {
  // src/utils.py.spec.md -> src/utils.py
  return specPath.replace(/\.spec\.md$/, "");
}

async function safeReadFile(path: string): Promise<string | null> {
  try {
    return await readFile(path, "utf-8");
  } catch {
    return null;
  }
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

export async function checkFreshnessAll(
  cwd: string,
  options: { excludePatterns?: string[] } = {},
): Promise<FreshnessReport> {
  const excludes = [
    ...DEFAULT_EXCLUDES,
    ...(options.excludePatterns ?? []),
  ];

  const specPaths = await findSpecFiles(cwd, cwd, excludes);
  const files: FreshnessEntry[] = [];

  for (const specRel of specPaths) {
    const managedRel = deriveManagedPath(specRel);
    const specAbs = join(cwd, specRel);
    const managedAbs = join(cwd, managedRel);

    const specContent = await safeReadFile(specAbs);
    if (!specContent) continue; // shouldn't happen, but be safe

    const codeExists = await fileExists(managedAbs);
    const codeContent = codeExists
      ? await safeReadFile(managedAbs)
      : null;

    const header =
      codeContent !== null ? parseHeader(codeContent) : null;

    const currentSpecHash = truncatedHash(specContent);
    const currentOutputHash =
      codeContent !== null
        ? truncatedHash(getBodyBelowHeader(codeContent))
        : null;

    const state = classifyFreshness({
      currentSpecHash,
      headerSpecHash: header?.specHash ?? null,
      currentOutputHash,
      headerOutputHash: header?.outputHash ?? null,
      codeFileExists: codeExists,
      upstreamChanged: false, // no DAG in Phase 1
      specChangedSinceTests: false, // no test tracking in Phase 1
    });

    const entry: FreshnessEntry = {
      managed: managedRel,
      spec: specRel,
      state,
    };

    const hint = HINTS[state];
    if (hint && state !== "fresh") {
      entry.hint = hint;
    }

    files.push(entry);
  }

  const hasFail = files.some((f) =>
    ["conflict", "structural"].includes(f.state),
  );
  const stateCounts = files.reduce(
    (acc, f) => {
      acc[f.state] = (acc[f.state] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );
  const summary = Object.entries(stateCounts)
    .map(([state, count]) => `${count} ${state}`)
    .join(", ") || "0 managed files";

  return {
    status: hasFail ? "fail" : "ok",
    files,
    summary,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/freshness.test.ts`
Expected: All 7 tests PASS.

- [ ] **Step 5: Run full test suite to check nothing broke**

Run: `cd prunejuice && npx vitest run`
Expected: All tests pass (84 existing + 7 new = 91).

- [ ] **Step 6: Commit**

```bash
git add prunejuice/src/freshness.ts prunejuice/test/freshness.test.ts
git commit -m "feat(prunejuice): add freshness scanning module

Bridges single-file classifyFreshness() to project-wide scanning.
Discovers *.spec.md files, derives managed paths, reads headers,
computes current hashes, returns FreshnessReport."
```

---

### Task 2: Create the MCP server

**Files:**
- Create: `prunejuice/src/mcp.ts`
- Test: `prunejuice/test/mcp.test.ts`

The MCP server uses the `@anthropic-ai/sdk` MCP primitives to expose tools. Phase 1 has one tool: `prunejuice_check_freshness`.

- [ ] **Step 1: Check what MCP server primitives the SDK provides**

Read the Claude Agent SDK docs to find the MCP server API. We need the server-side primitives for registering tools and handling requests.

Run: Use the context7 MCP to fetch `@anthropic-ai/claude-agent-sdk` docs for MCP server creation.

If the Agent SDK doesn't include MCP server primitives (it's a client SDK, not a server SDK), we'll use the `@modelcontextprotocol/sdk` package instead. Check:

```bash
cd prunejuice && npm info @modelcontextprotocol/sdk version 2>/dev/null || echo "not installed"
```

- [ ] **Step 2: Install MCP server dependency**

```bash
cd prunejuice && npm install @modelcontextprotocol/sdk
```

- [ ] **Step 3: Write the test file**

```typescript
// prunejuice/test/mcp.test.ts
import { describe, it, expect } from "vitest";
import { mkdtemp, writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { handleCheckFreshness } from "../src/mcp.js";

let cwd: string;

describe("handleCheckFreshness", () => {
  it("returns valid FreshnessReport JSON", async () => {
    cwd = await mkdtemp(join(tmpdir(), "pj-mcp-"));
    const result = await handleCheckFreshness({ cwd });
    expect(result).toHaveProperty("status", "ok");
    expect(result).toHaveProperty("files");
    expect(result).toHaveProperty("summary");
  });

  it("detects a pending spec", async () => {
    cwd = await mkdtemp(join(tmpdir(), "pj-mcp-"));
    await mkdir(join(cwd, "src"), { recursive: true });
    await writeFile(
      join(cwd, "src", "foo.py.spec.md"),
      "---\nintent: Foo things\n---\n## Purpose\nFoo",
    );

    const result = await handleCheckFreshness({ cwd });
    expect(result.files).toHaveLength(1);
    expect(result.files[0]!.state).toBe("pending");
  });

  it("passes excludePatterns through", async () => {
    cwd = await mkdtemp(join(tmpdir(), "pj-mcp-"));
    await mkdir(join(cwd, "vendor"), { recursive: true });
    await writeFile(
      join(cwd, "vendor", "lib.py.spec.md"),
      "---\n---\n",
    );

    const result = await handleCheckFreshness({
      cwd,
      excludePatterns: ["vendor"],
    });
    expect(result.files).toEqual([]);
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd prunejuice && npx vitest run test/mcp.test.ts`
Expected: FAIL -- `handleCheckFreshness` does not exist.

- [ ] **Step 5: Implement the MCP server**

```typescript
// prunejuice/src/mcp.ts
/**
 * Prunejuice MCP server.
 *
 * Exposes pipeline and state management tools via MCP protocol.
 * Phase 1: prunejuice_check_freshness only.
 *
 * Run as: node dist/mcp.js
 * Or auto-started by Claude Code via .mcp.json
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  checkFreshnessAll,
  type FreshnessReport,
} from "./freshness.js";

// -- Tool handlers (exported for direct testing) -----------------------------

export async function handleCheckFreshness(params: {
  cwd: string;
  excludePatterns?: string[];
}): Promise<FreshnessReport> {
  return checkFreshnessAll(params.cwd, {
    excludePatterns: params.excludePatterns,
  });
}

// -- MCP server wiring -------------------------------------------------------

export function createServer(): McpServer {
  const server = new McpServer({
    name: "prunejuice",
    version: "1.0.0",
  });

  server.tool(
    "prunejuice_check_freshness",
    "Check freshness of all managed files. Returns eight-state classification (fresh, stale, modified, conflict, pending, structural, ghost-stale, test-drifted) for each spec/managed-file pair.",
    {
      cwd: z.string().describe("Project root directory"),
      excludePatterns: z
        .array(z.string())
        .optional()
        .describe("Directory names to exclude from scanning"),
    },
    async ({ cwd, excludePatterns }) => {
      try {
        const report = await handleCheckFreshness({
          cwd,
          excludePatterns,
        });
        return {
          content: [
            { type: "text" as const, text: JSON.stringify(report, null, 2) },
          ],
        };
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : String(err);
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                { error: msg, error_type: "internal", tool: "prunejuice_check_freshness" },
                null,
                2,
              ),
            },
          ],
          isError: true,
        };
      }
    },
  );

  return server;
}

// -- Entry point (stdio transport) -------------------------------------------

async function main(): Promise<void> {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

// Only run if this is the entry point
const isMain =
  typeof process !== "undefined" &&
  process.argv[1] &&
  (process.argv[1].endsWith("/mcp.js") ||
    process.argv[1].endsWith("/mcp.ts"));

if (isMain) {
  main().catch((err) => {
    process.stderr.write(`prunejuice MCP server fatal: ${err}\n`);
    process.exit(1);
  });
}
```

**Note:** The `@modelcontextprotocol/sdk` import paths may differ depending on the version installed. Check the installed package's exports after `npm install` and adjust if needed. If it doesn't export `McpServer` / `StdioServerTransport`, use the context7 MCP to fetch current docs for `@modelcontextprotocol/sdk`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/mcp.test.ts`
Expected: All 3 tests PASS.

- [ ] **Step 7: Run full test suite**

Run: `cd prunejuice && npx vitest run`
Expected: All tests pass (91 + 3 = 94).

- [ ] **Step 8: Commit**

```bash
git add prunejuice/src/mcp.ts prunejuice/test/mcp.test.ts
git commit -m "feat(prunejuice): MCP server with prunejuice_check_freshness

Phase 1 of prunejuice integration. MCP server exposes freshness
checking via stdio transport. Tool handlers exported for testing."
```

---

### Task 3: Register the MCP server in unslop's plugin config

**Files:**
- Modify: `unslop/.claude-plugin/.mcp.json`

- [ ] **Step 1: Update .mcp.json to add prunejuice server**

The prunejuice MCP server runs alongside the existing Python server. Both are registered in the same `.mcp.json`. The prunejuice server runs via `node` on the compiled output.

```json
{
  "mcpServers": {
    "unslop": {
      "command": "python3",
      "args": ["-m", "unslop.scripts.mcp_server"],
      "cwd": "${PROJECT_ROOT}",
      "env": {
        "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/.."
      }
    },
    "prunejuice": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/../prunejuice/dist/mcp.js"],
      "cwd": "${PROJECT_ROOT}"
    }
  }
}
```

- [ ] **Step 2: Build prunejuice to generate dist/mcp.js**

Run: `cd prunejuice && npm run build`
Expected: `dist/mcp.js` exists.

- [ ] **Step 3: Verify the MCP server starts**

Run: `echo '{}' | node prunejuice/dist/mcp.js 2>&1 | head -5`
Expected: Server starts and waits for stdin (or outputs MCP protocol init).

- [ ] **Step 4: Commit**

```bash
git add unslop/.claude-plugin/.mcp.json
git commit -m "feat: register prunejuice MCP server alongside Python server

Both servers run in parallel during migration. Commands can call
either prunejuice_* or unslop_* tools."
```

---

### Task 4: Add npm dependency for MCP SDK and verify zod is available

**Files:**
- Modify: `prunejuice/package.json`

- [ ] **Step 1: Install dependencies**

```bash
cd prunejuice && npm install @modelcontextprotocol/sdk zod
```

**Note:** The `@modelcontextprotocol/sdk` package typically includes `zod` as a dependency. Check after install:

```bash
cd prunejuice && node -e "require('zod')" 2>&1 && echo "zod OK" || echo "zod missing"
```

If zod is already available transitively, skip the explicit install. If not, install it as a direct dependency.

- [ ] **Step 2: Verify build still works**

Run: `cd prunejuice && npm run build`
Expected: Clean build, no errors.

- [ ] **Step 3: Verify all tests still pass**

Run: `cd prunejuice && npx vitest run`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add prunejuice/package.json prunejuice/package-lock.json
git commit -m "chore(prunejuice): add @modelcontextprotocol/sdk dependency"
```

---

### Task 5: Compatibility integration test

**Files:**
- Create: `prunejuice/test/freshness-compat.test.ts`

This test verifies that prunejuice's freshness output matches the Python orchestrator's output format for the same inputs. It uses the adversarial-hashing stress test fixture as a real-world input.

- [ ] **Step 1: Write the compatibility test**

```typescript
// prunejuice/test/freshness-compat.test.ts
import { describe, it, expect } from "vitest";
import { resolve } from "node:path";
import { checkFreshnessAll } from "../src/freshness.js";

describe("freshness compatibility with Python orchestrator", () => {
  const stressTestDir = resolve(
    import.meta.dirname,
    "../../stress-tests/adversarial-hashing",
  );

  it("produces a valid FreshnessReport for the stress test fixture", async () => {
    const result = await checkFreshnessAll(stressTestDir);

    // The report structure matches what Python returns
    expect(result).toHaveProperty("status");
    expect(result).toHaveProperty("files");
    expect(result).toHaveProperty("summary");
    expect(["ok", "fail"]).toContain(result.status);

    // Should find at least the hashing.py spec
    expect(result.files.length).toBeGreaterThanOrEqual(1);

    // Each entry has the required fields
    for (const entry of result.files) {
      expect(entry).toHaveProperty("managed");
      expect(entry).toHaveProperty("spec");
      expect(entry).toHaveProperty("state");
      expect(typeof entry.managed).toBe("string");
      expect(typeof entry.spec).toBe("string");
      expect(typeof entry.state).toBe("string");
    }
  });

  it("finds the hashing.py spec and classifies it", async () => {
    const result = await checkFreshnessAll(stressTestDir);
    const hashing = result.files.find((f) =>
      f.spec.includes("hashing.py.spec.md"),
    );
    expect(hashing).toBeDefined();
    expect(hashing!.managed).toContain("hashing.py");
    // Should be fresh if hashes are current, or stale/conflict if not
    expect([
      "fresh",
      "stale",
      "modified",
      "conflict",
    ]).toContain(hashing!.state);
  });

  it("output matches Python format field names", async () => {
    const result = await checkFreshnessAll(stressTestDir);
    // Python returns: { status, files: [{ managed, spec, state, hint? }], summary }
    // These exact field names must match for the compatibility rule
    const keys = Object.keys(result);
    expect(keys).toContain("status");
    expect(keys).toContain("files");
    expect(keys).toContain("summary");

    if (result.files.length > 0) {
      const entryKeys = Object.keys(result.files[0]!);
      expect(entryKeys).toContain("managed");
      expect(entryKeys).toContain("spec");
      expect(entryKeys).toContain("state");
    }
  });
});
```

- [ ] **Step 2: Run the compatibility test**

Run: `cd prunejuice && npx vitest run test/freshness-compat.test.ts`
Expected: All 3 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd prunejuice && npx vitest run`
Expected: All tests pass (94 + 3 = 97).

- [ ] **Step 4: Commit**

```bash
git add prunejuice/test/freshness-compat.test.ts
git commit -m "test(prunejuice): add freshness compatibility test against stress fixture

Verifies prunejuice's freshness output matches the Python orchestrator's
field names and structure using the adversarial-hashing stress test."
```

---

### Task 6: Version bump and final verification

**Files:**
- Modify: `prunejuice/package.json` (version field)

- [ ] **Step 1: Bump prunejuice version**

Update `prunejuice/package.json` version from `"1.0.0"` to `"1.1.0"`.

- [ ] **Step 2: Run full test suite**

Run: `cd prunejuice && npx vitest run`
Expected: All 97 tests pass.

- [ ] **Step 3: Build and verify MCP server binary**

Run: `cd prunejuice && npm run build && ls dist/mcp.js`
Expected: `dist/mcp.js` exists.

- [ ] **Step 4: Verify existing unslop tests unaffected**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: 408 passed.

- [ ] **Step 5: Commit**

```bash
git add prunejuice/package.json
git commit -m "chore(prunejuice): bump to v1.1.0 (MCP server + freshness)"
```
