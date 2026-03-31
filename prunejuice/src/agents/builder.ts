import type {
  Spec,
  ConcreteSpec,
  GeneratedTests,
  Implementation,
} from "../types.js";
import { queryAgent } from "../pipeline.js";

const SYSTEM_PROMPT = `You are the Builder — an implementation specialist.

You receive a specification, a concrete strategy, and tests. Your job is to write code that passes the tests and satisfies the spec.

## What You See
- The original specification (intent, requirements, constraints, acceptance criteria)
- A concrete specification (existing patterns, integration points, file targets, strategy)
- Generated tests (test code and coverage targets)

## What You Do NOT See
- How the tests were derived (Mason's logic is hidden from you)
- The mutation testing strategy (Saboteur's logic is hidden from you)

## Process
1. Study the spec, concrete spec, and tests to understand what must be built.
2. Read existing code at the file targets to understand the integration surface.
3. Write implementation code that satisfies ALL tests and spec requirements.
4. Verify your implementation compiles and passes basic sanity checks.

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary):
{
  "files": [
    { "path": "relative/file/path.ts", "content": "full file content" }
  ],
  "summary": "brief description of what was implemented and key decisions"
}

Write production-quality code. No TODOs, no placeholders, no shortcuts.`;

const TOOLS = ["Read", "Grep", "Glob", "LS", "Bash", "Write", "Edit"] as const;

export async function runBuilder(
  spec: Spec,
  concreteSpec: ConcreteSpec,
  tests: GeneratedTests,
  cwd: string,
): Promise<Implementation> {
  const result = await queryAgent({
    systemPrompt: SYSTEM_PROMPT,
    prompt: `Implement code that satisfies this specification and passes these tests.

## Specification
${JSON.stringify(spec, null, 2)}

## Concrete Strategy
${JSON.stringify(concreteSpec, null, 2)}

## Tests To Pass
File paths: ${tests.testFilePaths.join(", ")}
Coverage targets: ${tests.coverageTargets.join(", ")}

Test code:
\`\`\`
${tests.testCode}
\`\`\``,
    tools: [...TOOLS],
    cwd,
    outputSchema: {
      type: "object",
      properties: {
        files: {
          type: "array",
          items: {
            type: "object",
            properties: {
              path: { type: "string" },
              content: { type: "string" },
            },
            required: ["path", "content"],
          },
        },
        summary: { type: "string" },
      },
      required: ["files", "summary"],
    },
  });

  return result as Implementation;
}
