import { describe, it, expect } from "vitest";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { checkFreshnessAll, type FreshnessReport, type FreshnessEntry } from "../src/freshness.js";

// Resolve path to the adversarial-hashing stress test fixture
const __dirname = fileURLToPath(new URL(".", import.meta.url));
const FIXTURE_DIR = join(__dirname, "../../stress-tests/adversarial-hashing");

const VALID_STATES = new Set(["fresh", "stale", "modified", "conflict", "pending", "structural", "ghost-stale", "test-drifted"]);

describe("freshness compat -- Python orchestrator format contract", () => {
  it("returns a report with the correct top-level fields", async () => {
    const report: FreshnessReport = await checkFreshnessAll(FIXTURE_DIR);

    // Top-level fields must exist and have the right types
    expect(report).toHaveProperty("status");
    expect(report).toHaveProperty("files");
    expect(report).toHaveProperty("summary");

    expect(typeof report.status).toBe("string");
    expect(["ok", "fail"]).toContain(report.status);
    expect(Array.isArray(report.files)).toBe(true);
    expect(typeof report.summary).toBe("object");
  });

  it("each file entry has the required fields: managed, spec, state", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    for (const entry of report.files) {
      expect(entry).toHaveProperty("spec");
      expect(entry).toHaveProperty("managed");
      expect(entry).toHaveProperty("state");

      expect(typeof entry.spec).toBe("string");
      expect(typeof entry.managed).toBe("string");
      expect(typeof entry.state).toBe("string");

      // hint is optional -- if present it must be a string
      if ("hint" in entry) {
        expect(typeof entry.hint).toBe("string");
      }
    }
  });

  it("finds at least the hashing.py.spec.md spec", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    const specPaths = report.files.map((f: FreshnessEntry) => f.spec);
    const found = specPaths.some((p) => p.includes("hashing.py.spec.md"));
    expect(found).toBe(true);
  });

  it("hashing entry has a valid freshness state", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    const hashingEntry = report.files.find((f: FreshnessEntry) =>
      f.spec.includes("hashing.py.spec.md"),
    );
    expect(hashingEntry).toBeDefined();
    expect(VALID_STATES.has(hashingEntry!.state)).toBe(true);
  });

  it("summary keys match the eight canonical state names", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    // These are the exact keys the Python server emits
    const expectedKeys = [
      "fresh",
      "stale",
      "modified",
      "conflict",
      "pending",
      "structural",
      "ghost-stale",
      "test-drifted",
    ];

    for (const key of expectedKeys) {
      expect(report.summary).toHaveProperty(key);
      expect(typeof report.summary[key as keyof typeof report.summary]).toBe("number");
    }
  });

  it("summary counts are non-negative integers", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    for (const [, count] of Object.entries(report.summary)) {
      expect(Number.isInteger(count)).toBe(true);
      expect(count).toBeGreaterThanOrEqual(0);
    }
  });

  it("summary counts sum to the number of files", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    const total = Object.values(report.summary).reduce((a, b) => a + b, 0);
    expect(total).toBe(report.files.length);
  });

  it("status is fail iff at least one file is in conflict or structural state", async () => {
    const report = await checkFreshnessAll(FIXTURE_DIR);

    const hasFailState = report.files.some(
      (f: FreshnessEntry) => f.state === "conflict" || f.state === "structural",
    );

    if (hasFailState) {
      expect(report.status).toBe("fail");
    } else {
      expect(report.status).toBe("ok");
    }
  });
});
