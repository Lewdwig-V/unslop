import type { BehaviourContract, GeneratedTests } from "../types.js";
import { queryAgent } from "../pipeline.js";

const SYSTEM_PROMPT = `You are the Mason — a test generation specialist who works exclusively from behavioural contracts.

CRITICAL: You have NO access to source code, implementation details, or specifications beyond the behavioural contract provided in your prompt. You write tests purely from the contract's preconditions, postconditions, invariants, and scenarios.

## Process
1. Parse the behavioural contract's scenarios into test cases.
2. Generate tests that verify each postcondition given its preconditions.
3. Generate tests that verify invariants hold across all scenarios.
4. Generate edge-case tests implied by the contract boundaries.

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary):
{
  "testCode": "complete test file source code as a string",
  "testFilePaths": ["suggested file paths for the test files"],
  "coverageTargets": ["what each test validates, mapped to contract clauses"]
}

Write tests that are:
- Self-contained (no imports from the implementation beyond the public API named in the contract)
- Deterministic (no randomness, no wall-clock time)
- Behavioural (test WHAT, not HOW)`;

// Mason gets NO filesystem tools — complete information isolation
const TOOLS: string[] = [];

export async function runMason(
  behaviourContract: BehaviourContract,
): Promise<GeneratedTests> {
  const result = await queryAgent({
    systemPrompt: SYSTEM_PROMPT,
    prompt: `Generate tests from this behavioural contract:\n\n${JSON.stringify(behaviourContract, null, 2)}`,
    tools: TOOLS,
    cwd: "/tmp", // irrelevant — no filesystem access
    outputSchema: {
      type: "object",
      properties: {
        testCode: { type: "string" },
        testFilePaths: { type: "array", items: { type: "string" } },
        coverageTargets: { type: "array", items: { type: "string" } },
      },
      required: ["testCode", "testFilePaths", "coverageTargets"],
    },
  });

  return result as GeneratedTests;
}
