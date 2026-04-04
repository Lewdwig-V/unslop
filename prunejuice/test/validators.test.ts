import { describe, it, expect } from "vitest";
import { validatePseudocode } from "../src/validators.js";

describe("validatePseudocode", () => {
  it("returns warn when no pseudocode blocks present", () => {
    const content = "## Strategy\nUse connection pooling.";
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("warn");
    expect(result.warnings?.[0]?.check).toBe("no_pseudocode");
  });

  it("passes valid pseudocode with ← assignment", () => {
    const content = [
      "## Pseudocode",
      "",
      "```pseudocode",
      "FUNCTION retry(operation, maxAttempts)",
      "  SET attempts ← 0",
      "  WHILE attempts < maxAttempts",
      "    IF operation() = SUCCESS THEN",
      "      RETURN SUCCESS",
      "    SET attempts ← attempts + 1",
      "  RETURN FAILURE",
      "END FUNCTION",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("flags bare assignment without ← or :=", () => {
    const content = [
      "```pseudocode",
      "SET x = 5",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("bare_assignment");
  });

  it("allows = as comparison in IF/WHILE/ASSERT", () => {
    const content = [
      "```pseudocode",
      "IF x = 5 THEN",
      "  RETURN true",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("flags language-specific keywords like def, fn, let", () => {
    const content = [
      "```pseudocode",
      "def foo()",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("language_keyword");
  });

  it("flags arrow operators => and ->", () => {
    const content = [
      "```pseudocode",
      "SET handler ← (x) => x + 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "language_keyword")).toBe(true);
  });

  it("flags library calls like time.sleep()", () => {
    const content = [
      "```pseudocode",
      "CALL time.sleep(5)",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("library_call");
  });

  it("flags multi-statement lines with semicolons", () => {
    const content = [
      "```pseudocode",
      "SET x ← 1; SET y ← 2",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("multi_statement");
  });

  it("flags FUNCTION without matching END FUNCTION", () => {
    const content = [
      "```pseudocode",
      "FUNCTION foo()",
      "  SET x ← 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "unclosed_function")).toBe(true);
  });

  it("flags unclosed pseudocode fence", () => {
    const content = [
      "```pseudocode",
      "FUNCTION foo()",
      "END FUNCTION",
      // No closing ```
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "unclosed_fence")).toBe(true);
  });

  it("ignores // comments inside pseudocode", () => {
    const content = [
      "```pseudocode",
      "// this is a comment",
      "SET x ← 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("advises on single-char variable names (not loop counters)", () => {
    const content = [
      "```pseudocode",
      "SET z ← 5",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    // Single-char vars outside {i,j,k,n,m,x,y} are advisories, not violations
    expect(result.status).toBe("warn");
    expect(result.advisories?.[0]?.check).toBe("abbreviated_name");
  });

  it("extracts multiple pseudocode blocks", () => {
    const content = [
      "```pseudocode",
      "SET x ← 1",
      "```",
      "",
      "Some prose.",
      "",
      "```pseudocode",
      "SET y = 2",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    // Second block has bare assignment
    expect(result.status).toBe("fail");
  });
});
