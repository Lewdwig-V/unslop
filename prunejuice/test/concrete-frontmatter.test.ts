import { describe, it, expect } from "vitest";
import { parseConcreteSpecFrontmatter } from "../src/ripple.js";

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
    const content = ["---", "source-spec: src/retry.py.spec.md", "---", "", "# Just markdown"].join("\n");
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
    const content = ["---", "source-spec: src/handler.py.spec.md", "extends: shared/fastapi-async.impl.md", "---"].join("\n");
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
    const content = ["---", "source-spec: src/retry.py.spec.md", "concrete-dependencies: src/core/pool.py.impl.md", "---"].join("\n");
    const result = parseConcreteSpecFrontmatter(content);
    expect(result.concreteDependencies).toEqual(["src/core/pool.py.impl.md"]);
  });

  it("strips quotes from values", () => {
    const content = ["---", 'source-spec: "src/retry.py.spec.md"', "extends: 'shared/base.impl.md'", "---"].join("\n");
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
    const content = ["---", "source-spec: src/shared.spec.md", "targets:", "---"].join("\n");
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
