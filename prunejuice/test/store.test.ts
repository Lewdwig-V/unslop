import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, readFile, readdir, writeFile, chmod, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { commentStyleForPath, atomicWriteFile } from "../src/store.js";

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

  it("preserves previous target content when write fails", async () => {
    const tmp = await makeTmp();
    const target = join(tmp, "out.txt");
    await writeFile(target, "original", "utf-8");

    // Make the directory read-only so the temp file write fails.
    await chmod(tmp, 0o555);

    try {
      await expect(
        atomicWriteFile(target, "should not replace"),
      ).rejects.toThrow();
    } finally {
      // Restore permissions so cleanup can run.
      await chmod(tmp, 0o755);
    }

    // Original content is still there (target was never touched).
    expect(await readFile(target, "utf-8")).toBe("original");
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
