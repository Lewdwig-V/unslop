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

  // -- Regression guards for subtle branches ---------------------------------

  it("does not treat // inside a string literal as a comment delimiter", () => {
    // If maskStrings() regresses, the // in "https://..." would be treated
    // as a comment, truncating the line and skipping downstream checks.
    // The correct behaviour: the string is masked, so // is not a comment,
    // and the line parses as a valid assignment with ←.
    const content = [
      "```pseudocode",
      'SET url ← "https://example.com/api"',
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("FOR/INCREMENT assignment context emits specific message", () => {
    // ASSIGNMENT_REQUIRED branch produces a message mentioning FOR/SET/INCREMENT
    // headers specifically, distinct from the generic bare assignment fallback.
    const forContent = [
      "```pseudocode",
      "FOR i = 0 TO 10",
      "  RETURN i",
      "```",
    ].join("\n");
    const forResult = validatePseudocode(forContent, "test.impl.md");
    expect(forResult.status).toBe("fail");
    const forViolation = forResult.violations?.find(
      (v) => v.check === "bare_assignment",
    );
    expect(forViolation).toBeDefined();
    expect(forViolation!.message).toMatch(/FOR\/SET\/INCREMENT/);

    const incContent = [
      "```pseudocode",
      "INCREMENT count = count + 1",
      "```",
    ].join("\n");
    const incResult = validatePseudocode(incContent, "test.impl.md");
    expect(incResult.status).toBe("fail");
    const incViolation = incResult.violations?.find(
      (v) => v.check === "bare_assignment",
    );
    expect(incViolation).toBeDefined();
    expect(incViolation!.message).toMatch(/FOR\/SET\/INCREMENT/);
  });

  it("CASE/WHEN: comparison in condition passes, assignment in action passes", () => {
    // The condition part before `:` allows bare `=` as comparison.
    // The action part after `:` must use ← or :=.
    const content = [
      "```pseudocode",
      "CASE status",
      "  WHEN x = 5: SET result ← ready",
      "  WHEN x = 10: SET result ← done",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("CASE/WHEN: bare assignment in action part is flagged", () => {
    // Action part after `:` must use ← or :=; bare = is a violation.
    const content = [
      "```pseudocode",
      "CASE status",
      "  WHEN x = 5: result = ready",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    const violation = result.violations?.find((v) => v.check === "bare_assignment");
    expect(violation).toBeDefined();
    expect(violation!.message).toMatch(/CASE\/WHEN/);
  });

  it("END FUNCTION without matching FUNCTION is unmatched_end_function", () => {
    // Distinct from unclosed_function -- this is extra END FUNCTION.
    const content = [
      "```pseudocode",
      "END FUNCTION",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    const violation = result.violations?.find(
      (v) => v.check === "unmatched_end_function",
    );
    expect(violation).toBeDefined();
  });

  it("per-block FUNCTION stack isolation: block A unclosed, block B balanced", () => {
    // If functionStack hoists outside the per-block loop, block A's
    // unclosed FUNCTION would be matched by block B's END FUNCTION.
    // Correct behaviour: each block has its own stack, so block A
    // reports unclosed_function and block B passes.
    const content = [
      "```pseudocode",
      "FUNCTION blockA()",
      "  SET x ← 1",
      "```",
      "",
      "Some prose between blocks.",
      "",
      "```pseudocode",
      "FUNCTION blockB()",
      "  SET y ← 2",
      "END FUNCTION",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    const unclosed = result.violations?.filter(
      (v) => v.check === "unclosed_function",
    );
    // Exactly one unclosed (from block A). Block B balanced.
    expect(unclosed).toHaveLength(1);
    expect(unclosed![0]!.text).toMatch(/FUNCTION opened at line/);
  });
});
