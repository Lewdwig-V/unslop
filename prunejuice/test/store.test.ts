import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, readFile, readdir, writeFile, mkdir, chmod, stat, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  commentStyleForPath,
  atomicWriteFile,
  writeManagedFile,
  writeImplementationFiles,
  ensureStore,
  saveConcreteSpec,
} from "../src/store.js";
import {
  truncatedHash,
  parseHeader,
  getBodyBelowHeader,
} from "../src/hashchain.js";
import type { ConcreteSpec, Implementation, TruncatedHash } from "../src/types.js";

describe("commentStyleForPath", () => {
  it("returns # for Python files", () => {
    expect(commentStyleForPath("src/main.py")).toBe("#");
  });

  it("returns # for shell scripts", () => {
    expect(commentStyleForPath("scripts/deploy.sh")).toBe("#");
  });

  it("returns # for Ruby files", () => {
    expect(commentStyleForPath("lib/config.rb")).toBe("#");
  });

  it("returns # for YAML files (.yaml)", () => {
    expect(commentStyleForPath("config.yaml")).toBe("#");
  });

  it("returns # for YAML files (.yml)", () => {
    expect(commentStyleForPath("docker-compose.yml")).toBe("#");
  });

  it("returns # for TOML files", () => {
    expect(commentStyleForPath("Cargo.toml")).toBe("#");
  });

  it("returns # for Perl files", () => {
    expect(commentStyleForPath("script.pl")).toBe("#");
  });

  it("returns # for R files", () => {
    expect(commentStyleForPath("analysis.r")).toBe("#");
  });

  it("returns # for Julia files", () => {
    expect(commentStyleForPath("sim.jl")).toBe("#");
  });

  it("returns // for TypeScript files", () => {
    expect(commentStyleForPath("src/index.ts")).toBe("//");
  });

  it("returns // for JavaScript files", () => {
    expect(commentStyleForPath("app.js")).toBe("//");
  });

  it("returns // for Go files", () => {
    expect(commentStyleForPath("main.go")).toBe("//");
  });

  it("returns // for Rust files", () => {
    expect(commentStyleForPath("lib.rs")).toBe("//");
  });

  it("returns // for Java files", () => {
    expect(commentStyleForPath("Main.java")).toBe("//");
  });

  it("handles uppercase extensions", () => {
    expect(commentStyleForPath("script.PY")).toBe("#");
    expect(commentStyleForPath("module.TS")).toBe("//");
  });

  it("handles deeply nested paths", () => {
    expect(commentStyleForPath("a/b/c/d/e/f.py")).toBe("#");
  });
});

describe("atomicWriteFile", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  async function makeTmp(): Promise<string> {
    const d = await mkdtemp(join(tmpdir(), "atomic-write-test-"));
    dirs.push(d);
    return d;
  }

  it("writes content to the target path", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "out.txt");

    await atomicWriteFile(target, "hello world");

    expect(await readFile(target, "utf-8")).toBe("hello world");
  });

  it("does not leave a .tmp- sibling after successful write", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "out.txt");

    await atomicWriteFile(target, "content");

    const entries = await readdir(tmp);
    expect(entries).toEqual(["out.txt"]);
    expect(entries.every((e) => !e.includes(".tmp-"))).toBe(true);
  });

  it("creates parent directories if they don't exist", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "nested", "deeply", "out.txt");

    await atomicWriteFile(target, "nested content");

    expect(await readFile(target, "utf-8")).toBe("nested content");
  });

  it("overwrites an existing file atomically", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "out.txt");

    await writeFile(target, "old content", "utf-8");
    await atomicWriteFile(target, "new content");

    expect(await readFile(target, "utf-8")).toBe("new content");
    // No temp files left behind
    const entries = await readdir(tmp);
    expect(entries).toEqual(["out.txt"]);
  });

  it("preserves existing file when a neighboring atomic write fails", async () => {
    const tmp = await makeTmp();
    // Create an existing file with known content. We want to verify that
    // a FAILING atomic write nearby does not touch this file.
    const preserved = join(tmp, "preserved.txt");
    await writeFile(preserved, "original content", "utf-8");

    // Trigger a UID-independent failure: try to atomic-write to a path
    // whose parent component is a file, not a directory. This fails with
    // ENOTDIR during mkdir -- a filesystem type constraint that holds for
    // all users including root, so the test is stable in containerized CI.
    const badTarget = join(preserved, "child.txt");
    await expect(atomicWriteFile(badTarget, "new content")).rejects.toThrow();

    // The existing file was never touched.
    expect(await readFile(preserved, "utf-8")).toBe("original content");
  });

  it("preserves file mode when overwriting an existing executable", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "script.sh");
    await writeFile(target, "#!/bin/sh\necho original\n", "utf-8");
    // Mark the existing file executable (the mode bits atomicWriteFile must preserve).
    await chmod(target, 0o755);

    await atomicWriteFile(target, "#!/bin/sh\necho regenerated\n");

    const st = await stat(target);
    // Mask to just the permission bits (strip file-type bits).
    // The executable bit for owner (0o100) must still be set.
    expect(st.mode & 0o777).toBe(0o755);
    expect(await readFile(target, "utf-8")).toBe(
      "#!/bin/sh\necho regenerated\n",
    );
  });

  it("cleans up temp file on write failure", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "out.txt");

    // Create a directory at the target path so the final rename fails
    // (rename onto a non-empty directory is an error).
    await writeFile(join(tmp, "blocker"), "x", "utf-8");

    // Use a target where the parent exists but we can trigger a rename failure
    // by pointing at a path whose parent component is a file, not a dir.
    const badTarget = join(tmp, "blocker", "cannot-write-here.txt");

    await expect(atomicWriteFile(badTarget, "content")).rejects.toThrow();

    // No .tmp- sibling should remain at the top level
    const entries = await readdir(tmp);
    const tmpSiblings = entries.filter((e) => e.includes(".tmp-"));
    expect(tmpSiblings).toEqual([]);
  });

  it("uses a unique temp filename per call (no collision)", async () => {
    const tmp = await makeTmp();
    const targetA = join(tmp, "a.txt");
    const targetB = join(tmp, "b.txt");

    // Concurrent writes must not collide on temp filenames.
    await Promise.all([
      atomicWriteFile(targetA, "content A"),
      atomicWriteFile(targetB, "content B"),
    ]);

    expect(await readFile(targetA, "utf-8")).toBe("content A");
    expect(await readFile(targetB, "utf-8")).toBe("content B");
    const entries = await readdir(tmp);
    expect(entries.sort()).toEqual(["a.txt", "b.txt"]);
  });

  it("handles large content without truncation", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "large.txt");
    // 1 MB of deterministic content
    const large = "abcdefghij".repeat(100_000);

    await atomicWriteFile(target, large);

    const result = await readFile(target, "utf-8");
    expect(result.length).toBe(large.length);
    expect(result).toBe(large);
  });
});

// Helper: seed a minimal ConcreteSpec artifact so writeManagedFile can
// compute its specHash during tests.
async function seedConcreteSpec(cwd: string): Promise<void> {
  await ensureStore(cwd);
  const concreteSpec: ConcreteSpec = {
    existingPatterns: [],
    integrationPoints: [],
    fileTargets: [],
    strategyProjection: "test",
    refinedSpec: {
      intent: "test",
      requirements: [],
      constraints: [],
      acceptanceCriteria: [],
    },
    behaviourContract: {
      name: "test",
      preconditions: [],
      postconditions: [],
      invariants: [],
      scenarios: [],
    },
    discovered: [],
  };
  await saveConcreteSpec(cwd, concreteSpec);
}

describe("writeManagedFile concrete-manifest option", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  async function makeTmp(): Promise<string> {
    const d = await mkdtemp(join(tmpdir(), "manifest-write-test-"));
    dirs.push(d);
    return d;
  }

  it("emits concrete-manifest line when option is provided", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    const manifest = new Map<string, TruncatedHash>([
      ["src/base.impl.md", "a3f8c2e9b7d1" as TruncatedHash],
      ["shared/util.impl.md", "7f2e1b8a9c04" as TruncatedHash],
    ]);

    await writeManagedFile(
      tmp,
      "src/retry.py",
      "def retry(): pass\n",
      "concrete-spec",
      "2026-04-05T00:00:00Z",
      { concreteManifest: manifest },
    );

    const written = await readFile(join(tmp, "src/retry.py"), "utf-8");
    expect(written).toContain("# concrete-manifest:");
    expect(written).toContain("src/base.impl.md:a3f8c2e9b7d1");
    expect(written).toContain("shared/util.impl.md:7f2e1b8a9c04");
    // Manifest line must come BEFORE the body (inside the header block).
    const manifestIdx = written.indexOf("concrete-manifest:");
    const bodyIdx = written.indexOf("def retry():");
    expect(manifestIdx).toBeLessThan(bodyIdx);
  });

  it("does NOT emit concrete-manifest line when option is absent", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    await writeManagedFile(
      tmp,
      "src/simple.py",
      "def simple(): pass\n",
      "concrete-spec",
      "2026-04-05T00:00:00Z",
    );

    const written = await readFile(join(tmp, "src/simple.py"), "utf-8");
    expect(written).not.toContain("concrete-manifest:");
  });

  it("does NOT emit concrete-manifest line when manifest is empty", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    await writeManagedFile(
      tmp,
      "src/empty.py",
      "def empty(): pass\n",
      "concrete-spec",
      "2026-04-05T00:00:00Z",
      { concreteManifest: new Map() },
    );

    const written = await readFile(join(tmp, "src/empty.py"), "utf-8");
    expect(written).not.toContain("concrete-manifest:");
  });

  it("uses the comment style of the target file (// for TypeScript)", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    const manifest = new Map<string, TruncatedHash>([
      ["src/base.impl.md", "a3f8c2e9b7d1" as TruncatedHash],
    ]);

    await writeManagedFile(
      tmp,
      "src/retry.ts",
      "export function retry() {}\n",
      "concrete-spec",
      "2026-04-05T00:00:00Z",
      { concreteManifest: manifest },
    );

    const written = await readFile(join(tmp, "src/retry.ts"), "utf-8");
    // TypeScript uses // comment style, so the manifest line should too.
    expect(written).toContain("// concrete-manifest:");
    expect(written).not.toContain("# concrete-manifest:");
  });
});

describe("writeImplementationFiles .impl.md lookup", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    for (const d of dirs.splice(0)) {
      await rm(d, { recursive: true, force: true });
    }
  });

  async function makeTmp(): Promise<string> {
    const d = await mkdtemp(join(tmpdir(), "impl-lookup-test-"));
    dirs.push(d);
    return d;
  }

  it("includes concrete-manifest when a conventional .impl.md exists with deps", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    // Create an upstream impl file
    const basePath = join(tmp, "src", "base.impl.md");
    await mkdir(join(tmp, "src"), { recursive: true });
    const baseContent =
      "---\nsource-spec: src/base.spec.md\n---\n## Strategy\nBase strategy.";
    await writeFile(basePath, baseContent, "utf-8");

    // Create the downstream .impl.md with a concrete-dependency on base
    const retryImplPath = join(tmp, "src", "retry.py.impl.md");
    await writeFile(
      retryImplPath,
      [
        "---",
        "source-spec: src/retry.py.spec.md",
        "concrete-dependencies:",
        "  - src/base.impl.md",
        "---",
        "",
        "## Strategy",
        "Retry wraps base.",
      ].join("\n"),
      "utf-8",
    );

    // Now write the implementation -- writeImplementationFiles should find
    // the .impl.md file conventionally at src/retry.py.impl.md and compute
    // the manifest from it.
    const implementation: Implementation = {
      files: [{ path: "src/retry.py", content: "def retry(): pass\n" }],
      summary: "test",
    };
    await writeImplementationFiles(tmp, implementation, "2026-04-05T00:00:00Z");

    const written = await readFile(join(tmp, "src/retry.py"), "utf-8");
    expect(written).toContain("# concrete-manifest:");
    expect(written).toContain(`src/base.impl.md:${truncatedHash(baseContent)}`);
  });

  it("omits concrete-manifest when no .impl.md file exists (prunejuice-pure workflow)", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    const implementation: Implementation = {
      files: [{ path: "src/alone.py", content: "def alone(): pass\n" }],
      summary: "test",
    };
    await writeImplementationFiles(tmp, implementation, "2026-04-05T00:00:00Z");

    const written = await readFile(join(tmp, "src/alone.py"), "utf-8");
    expect(written).not.toContain("concrete-manifest:");
  });

  it("omits concrete-manifest when .impl.md exists but declares no deps", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    await mkdir(join(tmp, "src"), { recursive: true });
    await writeFile(
      join(tmp, "src", "noDeps.py.impl.md"),
      "---\nsource-spec: src/noDeps.py.spec.md\n---\n## Strategy\nStandalone.",
      "utf-8",
    );

    const implementation: Implementation = {
      files: [{ path: "src/noDeps.py", content: "def no_deps(): pass\n" }],
      summary: "test",
    };
    await writeImplementationFiles(tmp, implementation, "2026-04-05T00:00:00Z");

    const written = await readFile(join(tmp, "src/noDeps.py"), "utf-8");
    expect(written).not.toContain("concrete-manifest:");
  });

  // -- Round-trip regression guard -----------------------------------------
  //
  // When writeImplementationFiles emits a concrete-manifest line, the
  // output-hash in the header is computed from the BODY only (not body +
  // manifest line). getBodyBelowHeader must recognize the manifest line as
  // part of the header so the rehash on readback matches the stored hash;
  // otherwise every affected file reports as "modified" on the next
  // freshness check.
  //
  // This test writes via the real writeImplementationFiles pipeline, reads
  // the file back, and asserts that:
  //   - parseHeader extracts the stored output-hash
  //   - truncatedHash(getBodyBelowHeader(written)) === headerOutputHash
  //
  // If they don't match, the freshness classifier will mark the file as
  // modified immediately after it was written -- a false drift regression.

  it("round-trips: output-hash in header matches rehash of body after writeImplementationFiles with manifest", async () => {
    const tmp = await makeTmp();
    await seedConcreteSpec(tmp);

    await mkdir(join(tmp, "src"), { recursive: true });
    await writeFile(
      join(tmp, "src", "base.impl.md"),
      "---\nsource-spec: src/base.spec.md\n---\n## Strategy\nBase.",
      "utf-8",
    );
    await writeFile(
      join(tmp, "src", "retry.py.impl.md"),
      [
        "---",
        "source-spec: src/retry.py.spec.md",
        "concrete-dependencies:",
        "  - src/base.impl.md",
        "---",
        "",
        "## Strategy",
        "Retry wraps base.",
      ].join("\n"),
      "utf-8",
    );

    const originalBody = "def retry(): pass\n";
    const implementation: Implementation = {
      files: [{ path: "src/retry.py", content: originalBody }],
      summary: "test",
    };
    await writeImplementationFiles(tmp, implementation, "2026-04-05T00:00:00Z");

    // Read the written file back and verify it actually has a manifest line
    // (if not, this test isn't exercising the regression path).
    const written = await readFile(join(tmp, "src/retry.py"), "utf-8");
    expect(written).toContain("concrete-manifest:");

    // Parse the header to get the stored output-hash
    const header = parseHeader(written);
    expect(header).not.toBeNull();

    // THE CRITICAL ASSERTION: getBodyBelowHeader must strip ALL header lines
    // (including concrete-manifest) so the rehashed body matches the stored
    // output-hash. If this fails, files are marked modified immediately
    // after being written.
    const extractedBody = getBodyBelowHeader(written);
    expect(extractedBody).toBe(originalBody);
    expect(truncatedHash(extractedBody)).toBe(header!.outputHash);
  });
});
