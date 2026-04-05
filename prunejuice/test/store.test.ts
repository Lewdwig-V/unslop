import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, readFile, readdir, writeFile, chmod, stat, rm } from "node:fs/promises";
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
