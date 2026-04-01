import type { Spec, ConcreteSpec, DriftReport } from "../types.js";
import { queryAgent } from "../pipeline.js";

const SYSTEM_PROMPT = `You are the Archaeologist — a codebase analyst and strategy projector.

Your job is to examine existing code, infer patterns, refine an abstract spec into a concrete implementation strategy, and derive a behavioural contract.

## Process
1. Read the codebase to understand existing patterns, conventions, and architecture.
2. Identify integration points where the new spec touches existing code.
3. Project a strategy: which files to modify/create, which patterns to follow.
4. Refine the original spec with concrete details grounded in the codebase.
5. Derive a behavioural contract that captures the expected behaviour as testable preconditions, postconditions, invariants, and scenarios. Ground these in what the code should do, informed by what it currently does and what the spec requires.
6. Surface any correctness requirements implied by the strategy that the spec doesn't explicitly state. These are "discovered" items — transient findings that must be resolved (promoted to the spec or dismissed) before generation proceeds.

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary):
{
  "existingPatterns": ["patterns found in the codebase"],
  "integrationPoints": ["where new code connects to existing code"],
  "fileTargets": ["files to create or modify"],
  "strategyProjection": "narrative of the implementation approach",
  "refinedSpec": { ...original spec with refinements... },
  "behaviourContract": {
    "name": "PascalCase name for the component",
    "preconditions": ["conditions that must hold before the component is used"],
    "postconditions": ["conditions guaranteed after successful operation"],
    "invariants": ["properties that always hold"],
    "scenarios": [
      { "given": "initial state", "when": "action", "then": "expected outcome" }
    ]
  },
  "discovered": [
    { "title": "short name", "observation": "what you found", "question": "what the human should decide" }
  ]
}

Ground every recommendation in what you actually observe in the code. Do not speculate about code you haven't read.
The behavioural contract is consumed by a separate test-generation agent that has NO access to the codebase — make the contract self-contained and precise enough to generate tests without seeing source code.
The "discovered" array should be empty if all correctness requirements are covered by the spec. Only surface genuine ambiguities — not things the spec already addresses.`;

const TOOLS = ["Read", "Grep", "Glob", "LS", "Bash"] as const;

export async function runArchaeologist(
  spec: Spec,
  cwd: string,
): Promise<ConcreteSpec> {
  const result = await queryAgent({
    systemPrompt: SYSTEM_PROMPT,
    prompt: `Given this specification, analyze the codebase and produce a concrete implementation strategy.\n\nSpecification:\n${JSON.stringify(spec, null, 2)}`,
    tools: TOOLS as unknown as string[],
    cwd,
    outputSchema: {
      type: "object",
      properties: {
        existingPatterns: { type: "array", items: { type: "string" } },
        integrationPoints: { type: "array", items: { type: "string" } },
        fileTargets: { type: "array", items: { type: "string" } },
        strategyProjection: { type: "string" },
        refinedSpec: {
          type: "object",
          properties: {
            intent: { type: "string" },
            requirements: { type: "array", items: { type: "string" } },
            constraints: { type: "array", items: { type: "string" } },
            acceptanceCriteria: { type: "array", items: { type: "string" } },
          },
          required: [
            "intent",
            "requirements",
            "constraints",
            "acceptanceCriteria",
          ],
        },
        behaviourContract: {
          type: "object",
          properties: {
            name: { type: "string" },
            preconditions: { type: "array", items: { type: "string" } },
            postconditions: { type: "array", items: { type: "string" } },
            invariants: { type: "array", items: { type: "string" } },
            scenarios: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  given: { type: "string" },
                  when: { type: "string" },
                  then: { type: "string" },
                },
                required: ["given", "when", "then"],
              },
            },
          },
          required: [
            "name",
            "preconditions",
            "postconditions",
            "invariants",
            "scenarios",
          ],
        },
        discovered: {
          type: "array",
          items: {
            type: "object",
            properties: {
              title: { type: "string" },
              observation: { type: "string" },
              question: { type: "string" },
            },
            required: ["title", "observation", "question"],
          },
        },
      },
      required: [
        "existingPatterns",
        "integrationPoints",
        "fileTargets",
        "strategyProjection",
        "refinedSpec",
        "behaviourContract",
        "discovered",
      ],
    },
  });

  return result as ConcreteSpec;
}

// -- Distill mode: infer a spec from existing code ---------------------------

const DISTILL_PROMPT = `You are the Archaeologist in distill mode — a codebase analyst who infers specifications from existing code.

Your job is to read the codebase and produce a specification that captures the intent, requirements, constraints, and acceptance criteria of the existing implementation.

## Process
1. Read the codebase to understand what it does, why, and how.
2. Infer the intent behind the code — not just what it does, but what problem it solves.
3. Extract requirements (functional behaviours), constraints (design boundaries), and acceptance criteria (testable assertions).
4. Produce a structured specification.

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary):
{
  "intent": "inferred statement of what this code does and why",
  "requirements": ["functional requirements inferred from the code"],
  "constraints": ["design constraints inferred from the code"],
  "acceptanceCriteria": ["testable statements that the code currently satisfies"]
}

Be precise. Distinguish between intentional behaviour and accidental implementation details. If a code pattern looks deliberate, capture it as a requirement. If it looks incidental, omit it.`;

export async function runDistiller(cwd: string): Promise<Spec> {
  const result = await queryAgent({
    systemPrompt: DISTILL_PROMPT,
    prompt:
      "Analyze the codebase and infer a specification from the existing implementation.",
    tools: TOOLS as unknown as string[],
    cwd,
    outputSchema: {
      type: "object",
      properties: {
        intent: { type: "string" },
        requirements: { type: "array", items: { type: "string" } },
        constraints: { type: "array", items: { type: "string" } },
        acceptanceCriteria: { type: "array", items: { type: "string" } },
      },
      required: ["intent", "requirements", "constraints", "acceptanceCriteria"],
    },
  });

  return result as Spec;
}

// -- Weed mode: detect intent drift between spec and code --------------------

const WEED_PROMPT = `You are the Archaeologist in weed mode — a drift detector who compares specifications against current code.

Your job is to read a specification and the current codebase, then identify meaningful discrepancies where the code has drifted from the spec's intent.

## Process
1. Read the specification carefully — understand the intent, requirements, constraints, and acceptance criteria.
2. Read the codebase and compare against each spec element.
3. For each discrepancy, classify its severity and recommend a remediation.
4. Distinguish between genuine drift (the code does something the spec doesn't intend) and spec incompleteness (the code does something the spec doesn't mention).

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary):
{
  "findings": [
    {
      "location": { "filePath": "path/to/file.ts", "detail": "optional function name or line range" },
      "specIntent": "what the spec says should happen",
      "codeReality": "what the code actually does",
      "severity": "high" | "medium" | "low",
      "recommendation": "how to resolve the drift"
    }
  ],
  "specPath": "path to the spec file analyzed",
  "filesChecked": ["files that were examined"],
  "overallAssessment": "summary of drift status"
}

Be precise. Not every difference is drift — some are legitimate implementation choices within the spec's constraints. Only report genuine mismatches between intent and reality.`;

export async function runWeeder(spec: Spec, cwd: string): Promise<DriftReport> {
  const result = await queryAgent({
    systemPrompt: WEED_PROMPT,
    prompt: `Compare this specification against the current codebase and identify intent drift.

## Specification
${JSON.stringify(spec, null, 2)}`,
    tools: TOOLS as unknown as string[],
    cwd,
    outputSchema: {
      type: "object",
      properties: {
        findings: {
          type: "array",
          items: {
            type: "object",
            properties: {
              location: {
                type: "object",
                properties: {
                  filePath: { type: "string" },
                  detail: { type: "string" },
                },
                required: ["filePath"],
              },
              specIntent: { type: "string" },
              codeReality: { type: "string" },
              severity: { type: "string", enum: ["high", "medium", "low"] },
              recommendation: { type: "string" },
            },
            required: [
              "location",
              "specIntent",
              "codeReality",
              "severity",
              "recommendation",
            ],
          },
        },
        specPath: { type: "string" },
        filesChecked: { type: "array", items: { type: "string" } },
        overallAssessment: { type: "string" },
      },
      required: ["findings", "specPath", "filesChecked", "overallAssessment"],
    },
  });

  const report = result as DriftReport;
  report.hasDrift = report.findings.length > 0;
  return report;
}
