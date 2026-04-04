import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isEnoent } from "./fs-utils.js";
import { parseConcreteSpecFrontmatter } from "./ripple.js";

// -- Constants ---------------------------------------------------------------

export const MAX_EXTENDS_DEPTH = 3;

/** Sections that always come from the child, never merged from parents. */
export const STRICT_CHILD_ONLY: ReadonlySet<string> = new Set([
  "Strategy",
  "Type Sketch",
  "Representation Invariants",
  "Safety Contracts",
  "Concurrency Model",
  "State Machine",
  "Migration Notes",
  "Error Taxonomy",
  "Test Seams",
]);

// -- Errors ------------------------------------------------------------------

export class InheritanceCycleError extends Error {
  constructor(cycle: string[]) {
    super(`Cycle detected in extends chain: ${cycle.join(" -> ")}`);
    this.name = "InheritanceCycleError";
  }
}

// -- Extends chain resolution -------------------------------------------------

/**
 * Resolve the extends chain for a concrete spec.
 *
 * Returns a list of impl paths starting from `specPath` (most specific, the
 * child) and walking up to the root parent (most general). `specPath` is
 * always the first element.
 *
 * Throws:
 *   - `InheritanceCycleError` on a cycle in the extends graph
 *   - Error with "exceeds maximum depth" message when chain > MAX_EXTENDS_DEPTH
 *   - Error with "Missing parent" message when an extends target doesn't exist
 *
 * If `specPath` itself does not exist, returns `[specPath]` without error --
 * callers decide how to handle missing starting points.
 */
export async function resolveExtendsChain(
  specPath: string,
  cwd: string,
): Promise<string[]> {
  const absCwd = resolve(cwd);
  const chain: string[] = [];
  const visited = new Set<string>();
  let current: string | null = specPath;

  while (current !== null) {
    const absPath = resolve(absCwd, current);

    if (visited.has(absPath)) {
      throw new InheritanceCycleError([...chain, current]);
    }

    chain.push(current);
    visited.add(absPath);

    if (chain.length > MAX_EXTENDS_DEPTH) {
      throw new Error(
        `Extends chain exceeds maximum depth of ${MAX_EXTENDS_DEPTH}: ${chain.join(" -> ")}. Flatten the hierarchy.`,
      );
    }

    let content: string;
    try {
      content = await readFile(absPath, "utf-8");
    } catch (err) {
      if (isEnoent(err)) {
        if (chain.length === 1) {
          // Starting impl doesn't exist -- return chain as-is
          return chain;
        }
        throw new Error(
          `Missing parent concrete spec in extends chain: ${current}`,
        );
      }
      throw err;
    }

    const meta = parseConcreteSpecFrontmatter(content);
    current = meta.extends;
  }

  return chain;
}
