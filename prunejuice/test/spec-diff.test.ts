import { describe, it, expect } from "vitest";
import { computeSpecDiff } from "../src/spec-diff.js";

describe("computeSpecDiff", () => {
  it("reports changed and unchanged sections", () => {
    const old = "## Intent\nBuild a widget\n## Requirements\n- Must be fast";
    const updated = "## Intent\nBuild a widget\n## Requirements\n- Must be fast\n- Must be reliable";
    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toEqual(["Requirements"]);
    expect(diff.unchangedSections).toEqual(["Intent"]);
  });

  it("detects added sections", () => {
    const old = "## Intent\nBuild a widget";
    const updated = "## Intent\nBuild a widget\n## Constraints\nNone";
    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toContain("Constraints");
    expect(diff.unchangedSections).toContain("Intent");
  });

  it("detects removed sections", () => {
    const old = "## Intent\nBuild a widget\n## Deprecated\nOld stuff";
    const updated = "## Intent\nBuild a widget";
    const diff = computeSpecDiff(old, updated);
    expect(diff.changedSections).toContain("Deprecated");
  });

  it("returns empty arrays for identical specs", () => {
    const spec = "## Intent\nSame\n## Requirements\nSame";
    const diff = computeSpecDiff(spec, spec);
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual(["Intent", "Requirements"]);
  });

  it("handles specs with no sections", () => {
    const diff = computeSpecDiff("Just text", "Different text");
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual([]);
  });

  it("handles empty inputs", () => {
    const diff = computeSpecDiff("", "");
    expect(diff.changedSections).toEqual([]);
    expect(diff.unchangedSections).toEqual([]);
  });
});
