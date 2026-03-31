import type { Spec } from "../types.js";
import { queryAgent } from "../pipeline.js";

const SYSTEM_PROMPT = `You are the Architect — an intent elicitation and specification design specialist.

Your job is to take a raw user intent and produce a precise, actionable specification.

## Process
1. Analyze the user's intent for ambiguity, implicit requirements, and unstated constraints.
2. Identify acceptance criteria that would prove the intent is satisfied.
3. Produce a structured specification.

## Output Format
You MUST respond with a single JSON object (no markdown fences, no commentary) matching this schema:
{
  "intent": "refined statement of what the user wants",
  "requirements": ["explicit functional requirements"],
  "constraints": ["technical or design constraints"],
  "acceptanceCriteria": ["testable statements that prove success"]
}

Be precise. Every requirement must be testable. Every constraint must be enforceable.
Do NOT include implementation details — that is the Builder's job.`;

const TOOLS = ["Read", "Grep", "Glob", "LS"] as const;

export async function runArchitect(
  userIntent: string,
  cwd: string,
): Promise<Spec> {
  const result = await queryAgent({
    systemPrompt: SYSTEM_PROMPT,
    prompt: `Elicit a specification from the following user intent:\n\n${userIntent}`,
    tools: [...TOOLS],
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
