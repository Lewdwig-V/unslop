import { describe, it, expect } from "vitest";
import {
  truncatedHash,
  formatHeader,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
  actionForState,
  type FreshnessInput,
  type FreshnessState,
} from "../src/hashchain.js";
import type { TruncatedHash } from "../src/types.js";

const hash = (s: string) => truncatedHash(s);

// -- truncatedHash -----------------------------------------------------------

describe("truncatedHash", () => {
  it("returns exactly 12 hex characters", () => {
    const h = truncatedHash("hello world");
    expect(h).toMatch(/^[0-9a-f]{12}$/);
    expect(h).toHaveLength(12);
  });

  it("is deterministic", () => {
    expect(truncatedHash("test")).toBe(truncatedHash("test"));
  });

  it("produces different hashes for different inputs", () => {
    expect(truncatedHash("a")).not.toBe(truncatedHash("b"));
  });

  it("handles empty string", () => {
    const h = truncatedHash("");
    expect(h).toMatch(/^[0-9a-f]{12}$/);
  });
});

// -- formatHeader / parseHeader roundtrip ------------------------------------

describe("formatHeader + parseHeader", () => {
  const header = {
    specHash: hash("spec content"),
    outputHash: hash("code content"),
    generated: "2026-03-28T00:00:00Z",
  };

  it("roundtrips with # comment style", () => {
    const formatted = formatHeader("foo.spec.md", header, "#");
    const parsed = parseHeader(formatted);
    expect(parsed).toEqual(header);
  });

  it("roundtrips with // comment style", () => {
    const formatted = formatHeader("foo.spec.md", header, "//");
    const parsed = parseHeader(formatted);
    expect(parsed).toEqual(header);
  });

  it("includes spec path in the first line", () => {
    const formatted = formatHeader("src/utils.spec.md", header, "#");
    expect(formatted).toContain("Edit src/utils.spec.md instead");
  });

  it("returns null for non-managed content", () => {
    expect(parseHeader("just some code\nno header here")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseHeader("")).toBeNull();
  });

  it("parses header even with code below", () => {
    const formatted = formatHeader("spec.md", header, "#");
    const fullFile = `${formatted}\n\nfunction hello() {}\n`;
    const parsed = parseHeader(fullFile);
    expect(parsed).toEqual(header);
  });
});

// -- getBodyBelowHeader ------------------------------------------------------

describe("getBodyBelowHeader", () => {
  const header = {
    specHash: hash("spec"),
    outputHash: hash("code"),
    generated: "2026-03-28T00:00:00Z",
  };

  it("extracts body below a # header", () => {
    const formatted = formatHeader("spec.md", header, "#");
    const fullFile = `${formatted}\n\nconst x = 1;\nconst y = 2;`;
    expect(getBodyBelowHeader(fullFile)).toBe("const x = 1;\nconst y = 2;");
  });

  it("extracts body below a // header", () => {
    const formatted = formatHeader("spec.md", header, "//");
    const fullFile = `${formatted}\n\nconst x = 1;`;
    expect(getBodyBelowHeader(fullFile)).toBe("const x = 1;");
  });

  it("returns full content for non-managed files", () => {
    const content = "just code\nno header";
    expect(getBodyBelowHeader(content)).toBe(content);
  });
});

// -- classifyFreshness -------------------------------------------------------

describe("classifyFreshness", () => {
  const base: FreshnessInput = {
    currentSpecHash: hash("spec"),
    headerSpecHash: hash("spec"),
    currentOutputHash: hash("code"),
    headerOutputHash: hash("code"),
    codeFileExists: true,
    upstreamChanged: false,
    specChangedSinceTests: false,
  };

  it("returns fresh when all hashes match", () => {
    expect(classifyFreshness(base)).toBe("fresh");
  });

  it("returns stale when spec changed but code unchanged", () => {
    expect(
      classifyFreshness({
        ...base,
        currentSpecHash: hash("new spec"),
      }),
    ).toBe("stale");
  });

  it("returns modified when code changed but spec unchanged", () => {
    expect(
      classifyFreshness({
        ...base,
        currentOutputHash: hash("edited code"),
      }),
    ).toBe("modified");
  });

  it("returns conflict when both changed", () => {
    expect(
      classifyFreshness({
        ...base,
        currentSpecHash: hash("new spec"),
        currentOutputHash: hash("edited code"),
      }),
    ).toBe("conflict");
  });

  it("returns pending when no code file exists and no provenance", () => {
    expect(
      classifyFreshness({
        ...base,
        codeFileExists: false,
        headerSpecHash: null,
        headerOutputHash: null,
      }),
    ).toBe("pending");
  });

  it("returns structural when code vanished but had provenance", () => {
    expect(
      classifyFreshness({
        ...base,
        codeFileExists: false,
        // headerSpecHash is still set — had provenance
      }),
    ).toBe("structural");
  });

  it("returns ghost-stale when upstream changed (takes priority)", () => {
    expect(
      classifyFreshness({
        ...base,
        upstreamChanged: true,
      }),
    ).toBe("ghost-stale");
  });

  it("returns test-drifted when spec changed since tests", () => {
    expect(
      classifyFreshness({
        ...base,
        specChangedSinceTests: true,
      }),
    ).toBe("test-drifted");
  });

  it("returns pending when no header hashes (unmanaged file)", () => {
    expect(
      classifyFreshness({
        ...base,
        headerSpecHash: null,
        headerOutputHash: null,
      }),
    ).toBe("pending");
  });

  it("upstream changed takes priority over spec/code changes", () => {
    expect(
      classifyFreshness({
        ...base,
        currentSpecHash: hash("new spec"),
        currentOutputHash: hash("edited code"),
        upstreamChanged: true,
      }),
    ).toBe("ghost-stale");
  });
});

// -- actionForState ----------------------------------------------------------

describe("actionForState", () => {
  const allStates: FreshnessState[] = [
    "fresh",
    "stale",
    "modified",
    "conflict",
    "pending",
    "structural",
    "ghost-stale",
    "test-drifted",
  ];

  it("handles every state (exhaustive)", () => {
    for (const state of allStates) {
      const action = actionForState(state);
      expect(action).toHaveProperty("kind");
      expect(action).toHaveProperty("description");
      expect(action.description.length).toBeGreaterThan(0);
    }
  });

  it("maps fresh to skip", () => {
    expect(actionForState("fresh").kind).toBe("skip");
  });

  it("maps stale, pending, test-drifted to regenerate", () => {
    expect(actionForState("stale").kind).toBe("regenerate");
    expect(actionForState("pending").kind).toBe("regenerate");
    expect(actionForState("test-drifted").kind).toBe("regenerate");
  });

  it("maps modified, conflict, ghost-stale to coordinate", () => {
    expect(actionForState("modified").kind).toBe("coordinate");
    expect(actionForState("conflict").kind).toBe("coordinate");
    expect(actionForState("ghost-stale").kind).toBe("coordinate");
  });

  it("maps structural to error", () => {
    expect(actionForState("structural").kind).toBe("error");
  });
});
