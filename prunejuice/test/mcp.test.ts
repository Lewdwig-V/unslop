import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { handleCheckFreshness } from "../src/mcp.js";
import { truncatedHash, formatHeader } from "../src/hashchain.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "mcp-test-"));
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
    generated: "2026-03-31T00:00:00Z",
  });
  return `${header}\n\n${bodyContent}`;
}

// -- Tests --------------------------------------------------------------------

describe("handleCheckFreshness", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("returns a valid report for an empty project (no spec files)", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const report = await handleCheckFreshness({ cwd: tmp });

    expect(report.status).toBe("ok");
    expect(report.files).toHaveLength(0);
    expect(report.summary).toMatchObject({
      fresh: 0,
      stale: 0,
      modified: 0,
      conflict: 0,
      pending: 0,
      structural: 0,
      "ghost-stale": 0,
      "test-drifted": 0,
    });
  });

  it("detects a pending spec when the managed file does not exist", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "# My spec\nDo something useful.";
    await writeAt(tmp, "src/widget.ts.spec.md", specContent);
    // Deliberately do NOT create src/widget.ts

    const report = await handleCheckFreshness({ cwd: tmp });

    expect(report.files).toHaveLength(1);
    const entry = report.files[0];
    expect(entry.spec).toBe("src/widget.ts.spec.md");
    expect(entry.managed).toBe("src/widget.ts");
    expect(entry.state).toBe("pending");
    expect(entry.hint).toContain("generate");
    expect(report.status).toBe("ok"); // pending is not a fail state
    expect(report.summary.pending).toBe(1);
  });

  it("passes excludePatterns through to skip matching directories", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "# Spec to exclude\nShould be skipped.";
    // Place spec inside a directory that will be excluded
    await writeAt(tmp, "vendor/lib/util.ts.spec.md", specContent);

    // Without excludePatterns, the spec is found
    const reportWithout = await handleCheckFreshness({ cwd: tmp });
    expect(reportWithout.files).toHaveLength(1);

    // With excludePatterns including "vendor", the spec is skipped
    const reportWith = await handleCheckFreshness({
      cwd: tmp,
      excludePatterns: ["vendor"],
    });
    expect(reportWith.files).toHaveLength(0);
    expect(reportWith.status).toBe("ok");
  });

  it("returns fresh when managed file matches spec and output hashes", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    const specContent = "# Stable spec\nDefined behavior.";
    const bodyContent = "export function stable() { return 42; }";
    const managed = managedFile(specContent, bodyContent);

    await writeAt(tmp, "lib/stable.ts.spec.md", specContent);
    await writeAt(tmp, "lib/stable.ts", managed);

    const report = await handleCheckFreshness({ cwd: tmp });

    expect(report.files).toHaveLength(1);
    expect(report.files[0].state).toBe("fresh");
    expect(report.status).toBe("ok");
    expect(report.summary.fresh).toBe(1);
  });
});
