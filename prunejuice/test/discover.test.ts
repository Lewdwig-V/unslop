import { describe, it, expect, afterEach } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { discoverFiles } from "../src/discover.js";

// -- Helpers ------------------------------------------------------------------

async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "discover-test-"));
}

async function writeAt(base: string, rel: string, content: string): Promise<void> {
  const full = join(base, rel);
  const parent = full.substring(0, full.lastIndexOf("/"));
  await mkdir(parent, { recursive: true });
  await writeFile(full, content, "utf-8");
}

// -- Tests --------------------------------------------------------------------

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

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "src/lib/util.ts", "export const y = 2;");

    const files = await discoverFiles(tmp);

    expect(files).toContain("src/main.ts");
    expect(files).toContain("src/lib/util.ts");
    expect(files).toHaveLength(2);
  });

  it("excludes test files by pattern", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "src/main.test.ts", "// test");
    await writeAt(tmp, "src/test_util.py", "# test");

    const files = await discoverFiles(tmp);

    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("src/main.test.ts");
    expect(files).not.toContain("src/test_util.py");
  });

  it("excludes test directories", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "tests/util.test.ts", "// test");
    await writeAt(tmp, "__tests__/helper.ts", "// helper");

    const files = await discoverFiles(tmp);

    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("tests/util.test.ts");
    expect(files).not.toContain("__tests__/helper.ts");
  });

  it("excludes build artifact directories", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "node_modules/lodash/index.js", "module.exports = {};");
    await writeAt(tmp, "dist/main.js", "const x = 1;");

    const files = await discoverFiles(tmp);

    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("node_modules/lodash/index.js");
    expect(files).not.toContain("dist/main.js");
  });

  it("filters by extensions when provided", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "src/styles.css", "body { margin: 0; }");

    const files = await discoverFiles(tmp, { extensions: [".ts"] });

    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("src/styles.css");
  });

  it("applies extra excludes", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/main.ts", "export const x = 1;");
    await writeAt(tmp, "vendor/lib/util.ts", "export const z = 3;");

    const files = await discoverFiles(tmp, { extraExcludes: ["vendor"] });

    expect(files).toContain("src/main.ts");
    expect(files).not.toContain("vendor/lib/util.ts");
  });

  it("returns sorted paths relative to directory", async () => {
    const tmp = await makeTmp();
    dirs.push(tmp);

    await writeAt(tmp, "src/z.ts", "");
    await writeAt(tmp, "src/a.ts", "");
    await writeAt(tmp, "lib/b.ts", "");

    const files = await discoverFiles(tmp);

    expect(files).toEqual([...files].sort());
    expect(files[0]).toBe("lib/b.ts");
    expect(files[1]).toBe("src/a.ts");
    expect(files[2]).toBe("src/z.ts");
  });

  it("throws on non-existent directory", async () => {
    await expect(discoverFiles("/tmp/does-not-exist-prunejuice-discover-test")).rejects.toThrow(
      /does not exist/,
    );
  });
});
