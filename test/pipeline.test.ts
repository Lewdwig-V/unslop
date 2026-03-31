import { describe, it, expect } from "vitest";
import {
  recomputeKillRate,
  validateSaboteurReport,
  routeSurvivors,
  evaluateConvergence,
  nextStage,
  STAGE_ORDER,
} from "../src/pipeline.js";
import type {
  PipelineState,
  MutationResult,
  SaboteurReport,
} from "../src/types.js";

// -- Test helpers ------------------------------------------------------------

function killed(mutation: string): MutationResult {
  return { mutation, killed: true, details: "caught by test" };
}

function survived(
  mutation: string,
  classification: "weak_test" | "spec_gap" | "equivalent",
): MutationResult {
  return { mutation, killed: false, details: "not caught", classification };
}

function makeReport(overrides: Partial<SaboteurReport> = {}): SaboteurReport {
  return {
    mutationResults: [killed("m1"), killed("m2")],
    complianceViolations: [],
    verdict: "pass",
    recommendations: [],
    killRate: 1.0,
    ...overrides,
  };
}

function makeState(overrides: Partial<PipelineState> = {}): PipelineState {
  return {
    userIntent: "test",
    cwd: "/tmp",
    convergenceIteration: 0,
    killRateHistory: [],
    radicalHardeningAttempted: false,
    ...overrides,
  };
}

// -- recomputeKillRate -------------------------------------------------------

describe("recomputeKillRate", () => {
  it("returns 1.0 when all mutations killed", () => {
    expect(recomputeKillRate([killed("a"), killed("b"), killed("c")])).toBe(
      1.0,
    );
  });

  it("returns 0 when no mutations killed (none equivalent)", () => {
    expect(
      recomputeKillRate([
        survived("a", "weak_test"),
        survived("b", "spec_gap"),
      ]),
    ).toBe(0);
  });

  it("excludes equivalent mutants from denominator", () => {
    // 2 killed, 1 equivalent, 1 weak_test → 2 / (4 - 1) = 2/3
    const results: MutationResult[] = [
      killed("a"),
      killed("b"),
      survived("c", "equivalent"),
      survived("d", "weak_test"),
    ];
    expect(recomputeKillRate(results)).toBeCloseTo(2 / 3);
  });

  it("returns 1.0 when all survivors are equivalent", () => {
    // 2 killed, 2 equivalent → 2 / (4 - 2) = 1.0
    const results: MutationResult[] = [
      killed("a"),
      killed("b"),
      survived("c", "equivalent"),
      survived("d", "equivalent"),
    ];
    expect(recomputeKillRate(results)).toBe(1.0);
  });

  it("returns 1.0 for empty input (vacuously passing)", () => {
    expect(recomputeKillRate([])).toBe(1.0);
  });

  it("returns 1.0 when all mutations are equivalent (zero non-equivalent)", () => {
    expect(
      recomputeKillRate([
        survived("a", "equivalent"),
        survived("b", "equivalent"),
      ]),
    ).toBe(1.0);
  });
});

// -- validateSaboteurReport --------------------------------------------------

describe("validateSaboteurReport", () => {
  it("passes valid report through with recomputed killRate", () => {
    const report = makeReport({
      mutationResults: [killed("a"), survived("b", "weak_test")],
      killRate: 0.99, // wrong, should be 0.5
      verdict: "fail",
    });
    const validated = validateSaboteurReport(report);
    expect(validated.killRate).toBeCloseTo(0.5);
  });

  it("throws when survivor lacks classification", () => {
    const report = makeReport({
      mutationResults: [
        killed("a"),
        // Force an unclassified survivor (simulating bad LLM output)
        {
          mutation: "b",
          killed: false,
          details: "not caught",
        } as MutationResult,
      ],
    });
    expect(() => validateSaboteurReport(report)).toThrow(
      "without classification",
    );
  });
});

// -- routeSurvivors ----------------------------------------------------------

describe("routeSurvivors", () => {
  it("routes weak_test to mason", () => {
    const result = routeSurvivors([
      { mutation: "m1", classification: "weak_test" },
    ]);
    expect(result.masonTargets).toEqual(["m1"]);
    expect(result.architectTargets).toEqual([]);
    expect(result.skipped).toEqual([]);
  });

  it("routes spec_gap to architect", () => {
    const result = routeSurvivors([
      { mutation: "m1", classification: "spec_gap" },
    ]);
    expect(result.architectTargets).toEqual(["m1"]);
  });

  it("routes equivalent to skipped", () => {
    const result = routeSurvivors([
      { mutation: "m1", classification: "equivalent" },
    ]);
    expect(result.skipped).toEqual(["m1"]);
  });

  it("partitions mixed survivors correctly", () => {
    const result = routeSurvivors([
      { mutation: "a", classification: "weak_test" },
      { mutation: "b", classification: "spec_gap" },
      { mutation: "c", classification: "equivalent" },
      { mutation: "d", classification: "weak_test" },
    ]);
    expect(result.masonTargets).toEqual(["a", "d"]);
    expect(result.architectTargets).toEqual(["b"]);
    expect(result.skipped).toEqual(["c"]);
  });

  it("handles empty input", () => {
    const result = routeSurvivors([]);
    expect(result.masonTargets).toEqual([]);
    expect(result.architectTargets).toEqual([]);
    expect(result.skipped).toEqual([]);
  });
});

// -- evaluateConvergence -----------------------------------------------------

describe("evaluateConvergence", () => {
  it("returns abort when no report", () => {
    const result = evaluateConvergence(makeState());
    expect(result.action).toBe("abort");
  });

  it("converges when kill rate >= 0.8 and no violations", () => {
    const state = makeState({
      saboteurReport: makeReport({ killRate: 0.85 }),
    });
    const result = evaluateConvergence(state);
    expect(result.converged).toBe(true);
    expect(result.action).toBe("proceed");
  });

  it("routes compliance violations to architect even with good kill rate", () => {
    const state = makeState({
      saboteurReport: makeReport({
        killRate: 0.9,
        complianceViolations: ["missing error handling"],
      }),
    });
    const result = evaluateConvergence(state);
    expect(result.converged).toBe(false);
    expect(result.action).toBe("retry-architect");
    expect(result.reason).toContain("compliance violation");
  });

  it("aborts after radical hardening already attempted", () => {
    const state = makeState({
      radicalHardeningAttempted: true,
      saboteurReport: makeReport({ killRate: 0.5, verdict: "fail" }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("abort");
    expect(result.reason).toContain("Radical hardening already attempted");
  });

  it("triggers radical-harden at max iterations", () => {
    const state = makeState({
      convergenceIteration: 3,
      saboteurReport: makeReport({ killRate: 0.5, verdict: "fail" }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("radical-harden");
  });

  it("aborts on kill rate regression", () => {
    const state = makeState({
      killRateHistory: [0.7, 0.6], // got worse
      saboteurReport: makeReport({ killRate: 0.6, verdict: "fail" }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("abort");
    expect(result.reason).toContain("regressed");
  });

  it("triggers radical-harden on entropy stall (< 5% improvement)", () => {
    const state = makeState({
      killRateHistory: [0.5, 0.52], // only 2% improvement
      saboteurReport: makeReport({ killRate: 0.52, verdict: "fail" }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("radical-harden");
    expect(result.reason).toContain("Entropy stall");
  });

  it("routes spec_gap survivors to architect", () => {
    const state = makeState({
      saboteurReport: makeReport({
        mutationResults: [killed("m1"), survived("m2", "spec_gap")],
        killRate: 0.5,
        verdict: "fail",
      }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("retry-architect");
    expect(result.routing?.architectTargets).toEqual(["m2"]);
  });

  it("routes weak_test survivors to mason", () => {
    const state = makeState({
      saboteurReport: makeReport({
        mutationResults: [killed("m1"), survived("m2", "weak_test")],
        killRate: 0.5,
        verdict: "fail",
      }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("retry-mason");
    expect(result.routing?.masonTargets).toEqual(["m2"]);
  });

  it("prefers architect when both spec_gap and weak_test exist", () => {
    const state = makeState({
      saboteurReport: makeReport({
        mutationResults: [
          survived("m1", "spec_gap"),
          survived("m2", "weak_test"),
        ],
        killRate: 0.0,
        verdict: "fail",
      }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("retry-architect");
    expect(result.reason).toContain("spec gaps");
    expect(result.reason).toContain("weak tests");
  });

  it("aborts when all survivors are equivalent but kill rate still low", () => {
    const state = makeState({
      saboteurReport: makeReport({
        mutationResults: [
          killed("m1"),
          survived("m2", "equivalent"),
          survived("m3", "equivalent"),
          survived("m4", "equivalent"),
          survived("m5", "equivalent"),
        ],
        killRate: 0.2, // low but all survivors equivalent
        verdict: "fail",
      }),
    });
    const result = evaluateConvergence(state);
    expect(result.action).toBe("abort");
    expect(result.reason).toContain("classification may be drifting");
  });
});

// -- nextStage ---------------------------------------------------------------

describe("nextStage", () => {
  it("returns archaeologist after architect", () => {
    expect(nextStage("architect")).toBe("archaeologist");
  });

  it("returns discovery-gate after archaeologist", () => {
    expect(nextStage("archaeologist")).toBe("discovery-gate");
  });

  it("returns null after saboteur (last stage)", () => {
    expect(nextStage("saboteur")).toBeNull();
  });

  it("covers the full pipeline order", () => {
    let stage = STAGE_ORDER[0]!;
    const visited = [stage];
    while (true) {
      const next = nextStage(stage);
      if (!next) break;
      visited.push(next);
      stage = next;
    }
    expect(visited).toEqual(STAGE_ORDER);
  });
});
