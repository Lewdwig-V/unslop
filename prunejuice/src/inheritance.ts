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

// -- Section extraction ------------------------------------------------------

/**
 * Extract `## ` sections from a markdown file into a Map.
 * Strips frontmatter before scanning for headings. The map key is the heading
 * text (trimmed); the value is the section body joined with newlines and
 * stripped of leading/trailing whitespace.
 */
export function extractSections(content: string): Map<string, string> {
  const sections = new Map<string, string>();
  const lines = content.split("\n");

  // Skip frontmatter
  let bodyStart = 0;
  if (lines.length > 0 && lines[0]!.trim() === "---") {
    for (let i = 1; i < lines.length; i++) {
      if (lines[i]!.trim() === "---") {
        bodyStart = i + 1;
        break;
      }
    }
  }

  let currentName: string | null = null;
  let currentLines: string[] = [];

  for (let i = bodyStart; i < lines.length; i++) {
    const line = lines[i]!;
    const match = line.match(/^## (.+)$/);
    if (match) {
      if (currentName !== null) {
        sections.set(currentName, currentLines.join("\n").trim());
      }
      currentName = match[1]!.trim();
      currentLines = [];
    } else if (currentName !== null) {
      currentLines.push(line);
    }
  }

  if (currentName !== null) {
    sections.set(currentName, currentLines.join("\n").trim());
  }

  return sections;
}

// -- Merge rules -------------------------------------------------------------

/** Parse `- **Key**: Value` bullet lines into a Map. */
function parsePatternEntries(content: string): Map<string, string> {
  const entries = new Map<string, string>();
  for (const line of content.split("\n")) {
    const match = line.match(/^\s*-\s+\*\*(.+?)\*\*:\s*(.+)$/);
    if (match) {
      entries.set(match[1]!.trim(), match[2]!.trim());
    }
  }
  return entries;
}

/**
 * Merge two Pattern sections. Child keys override parent keys with the same name.
 * Keys only in parent are preserved.
 */
export function mergePatternSections(parent: string, child: string): string {
  const parentEntries = parsePatternEntries(parent);
  const childEntries = parsePatternEntries(child);
  const merged = new Map([...parentEntries, ...childEntries]);
  return [...merged.entries()].map(([k, v]) => `- **${k}**: ${v}`).join("\n");
}

/** Parse `### Language` blocks into a Map. */
function parseLanguageBlocks(content: string): Map<string, string> {
  const blocks = new Map<string, string>();
  let currentLang: string | null = null;
  let currentLines: string[] = [];

  for (const line of content.split("\n")) {
    const match = line.match(/^### (.+)$/);
    if (match) {
      if (currentLang !== null) {
        blocks.set(currentLang, currentLines.join("\n").trim());
      }
      currentLang = match[1]!.trim();
      currentLines = [];
    } else if (currentLang !== null) {
      currentLines.push(line);
    }
  }

  if (currentLang !== null) {
    blocks.set(currentLang, currentLines.join("\n").trim());
  }

  return blocks;
}

/**
 * Merge two Lowering Notes sections. Child language blocks override matching
 * parent language blocks by heading name.
 */
export function mergeLoweringNotes(parent: string, child: string): string {
  const parentLangs = parseLanguageBlocks(parent);
  const childLangs = parseLanguageBlocks(child);
  const merged = new Map([...parentLangs, ...childLangs]);
  const parts: string[] = [];
  for (const [lang, langContent] of merged) {
    parts.push(`### ${lang}`);
    parts.push(langContent);
  }
  return parts.join("\n\n");
}
