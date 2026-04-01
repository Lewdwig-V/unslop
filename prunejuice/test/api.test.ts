import { describe, it, expect } from "vitest";
import {
  requireDefined,
  defaultDiscoveryHandler,
  COVER_KILL_RATE_THRESHOLD,
} from "../src/api.js";
import type { DiscoveredItem } from "../src/types.js";

// -- requireDefined ----------------------------------------------------------

describe("requireDefined", () => {
  it("returns the value when defined", () => {
    expect(requireDefined(42, "count", "test")).toBe(42);
  });

  it("returns the value when falsy but defined", () => {
    expect(requireDefined(0, "count", "test")).toBe(0);
    expect(requireDefined("", "name", "test")).toBe("");
    expect(requireDefined(false, "flag", "test")).toBe(false);
  });

  it("throws with descriptive message when undefined", () => {
    expect(() => requireDefined(undefined, "spec", "Architect")).toThrow(
      "Architect requires spec, but it is undefined.",
    );
  });

  it("includes both name and phase in error message", () => {
    try {
      requireDefined(undefined, "behaviourContract", "Mason");
    } catch (e) {
      expect((e as Error).message).toContain("Mason");
      expect((e as Error).message).toContain("behaviourContract");
    }
  });
});

// -- defaultDiscoveryHandler -------------------------------------------------

describe("defaultDiscoveryHandler", () => {
  it("returns deferred resolution for all items", async () => {
    const items: DiscoveredItem[] = [
      {
        title: "Missing validation",
        observation: "No input check",
        question: "Add validation?",
      },
      {
        title: "Edge case",
        observation: "Null not handled",
        question: "Throw or return?",
      },
    ];

    const resolutions = await defaultDiscoveryHandler(items);
    expect(resolutions).toHaveLength(2);
    expect(resolutions[0]!.resolution).toBe("deferred");
    expect(resolutions[1]!.resolution).toBe("deferred");
    expect(resolutions[0]!.item).toBe(items[0]);
    expect(resolutions[1]!.item).toBe(items[1]);
  });

  it("returns empty array for empty input", async () => {
    const resolutions = await defaultDiscoveryHandler([]);
    expect(resolutions).toEqual([]);
  });
});

// -- COVER_KILL_RATE_THRESHOLD -----------------------------------------------

describe("COVER_KILL_RATE_THRESHOLD", () => {
  it("is 0.8 (80%)", () => {
    expect(COVER_KILL_RATE_THRESHOLD).toBe(0.8);
  });
});

// -- Module exports ----------------------------------------------------------

describe("api exports", () => {
  it("exports all five phases", async () => {
    const api = await import("../src/api.js");
    expect(typeof api.distill).toBe("function");
    expect(typeof api.elicit).toBe("function");
    expect(typeof api.generate).toBe("function");
    expect(typeof api.cover).toBe("function");
    expect(typeof api.weed).toBe("function");
  });

  it("exports all three orchestrators", async () => {
    const api = await import("../src/api.js");
    expect(typeof api.takeover).toBe("function");
    expect(typeof api.change).toBe("function");
    expect(typeof api.sync).toBe("function");
  });

  it("exports defaultLog and requireDefined", async () => {
    const api = await import("../src/api.js");
    expect(typeof api.defaultLog).toBe("function");
    expect(typeof api.requireDefined).toBe("function");
  });
});

// -- Agent entry points ------------------------------------------------------

describe("agent entry points", () => {
  it("exports runDistiller from archaeologist module", async () => {
    const { runDistiller } = await import("../src/agents/archaeologist.js");
    expect(typeof runDistiller).toBe("function");
  });

  it("exports runWeeder from archaeologist module", async () => {
    const { runWeeder } = await import("../src/agents/archaeologist.js");
    expect(typeof runWeeder).toBe("function");
  });
});
