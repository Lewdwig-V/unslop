import { describe, it, expect } from "vitest";
import { commentStyleForPath } from "../src/store.js";

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
