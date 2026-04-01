import type { SpecDiffResult } from "./types.js";

function parseMdSections(text: string): Record<string, string> {
  const sections: Record<string, string> = {};
  let currentHeading: string | null = null;
  const currentLines: string[] = [];

  for (const line of text.split("\n")) {
    if (line.startsWith("## ")) {
      if (currentHeading !== null) {
        sections[currentHeading] = currentLines.join("\n").trim();
      }
      currentHeading = line.slice(3).trim();
      currentLines.length = 0;
    } else {
      currentLines.push(line);
    }
  }

  if (currentHeading !== null) {
    sections[currentHeading] = currentLines.join("\n").trim();
  }

  return sections;
}

export function computeSpecDiff(oldSpec: string, newSpec: string): SpecDiffResult {
  const oldSections = parseMdSections(oldSpec);
  const newSections = parseMdSections(newSpec);
  const allHeadings = new Set([...Object.keys(oldSections), ...Object.keys(newSections)]);
  const changedSections: string[] = [];
  const unchangedSections: string[] = [];

  for (const heading of [...allHeadings].sort()) {
    if (oldSections[heading] === newSections[heading]) {
      unchangedSections.push(heading);
    } else {
      changedSections.push(heading);
    }
  }

  return { changedSections, unchangedSections };
}
