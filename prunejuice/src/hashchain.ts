import { createHash } from "node:crypto";
import type { TruncatedHash } from "./types.js";

// -- Hash computation --------------------------------------------------------

/** SHA-256, truncated to 12 hex characters (48 bits). Matches unslop's format. */
export function truncatedHash(content: string): TruncatedHash {
  return createHash("sha256")
    .update(content, "utf-8")
    .digest("hex")
    .slice(0, 12) as TruncatedHash;
}

// -- Managed file header format ----------------------------------------------

export interface ManagedHeader {
  specHash: TruncatedHash;
  outputHash: TruncatedHash;
  generated: string; // ISO 8601
}

const HASH_LINE_RE =
  /^# spec-hash:([0-9a-f]{12}) output-hash:([0-9a-f]{12}) generated:(.+)$/;

/** Build the two-line header block for a managed file. */
export function formatHeader(
  specPath: string,
  header: ManagedHeader,
  commentStyle: "#" | "//" = "#",
): string {
  const c = commentStyle;
  return [
    `${c} @prunejuice-managed -- Edit ${specPath} instead`,
    `${c} spec-hash:${header.specHash} output-hash:${header.outputHash} generated:${header.generated}`,
  ].join("\n");
}

/** Parse a managed header from the first lines of a file. Returns null if not managed. */
export function parseHeader(fileContent: string): ManagedHeader | null {
  const lines = fileContent.split("\n");
  for (const line of lines.slice(0, 5)) {
    const match = line.replace(/^\/\//, "#").match(HASH_LINE_RE);
    if (match) {
      return {
        specHash: match[1]! as TruncatedHash,
        outputHash: match[2]! as TruncatedHash,
        generated: match[3]!,
      };
    }
  }
  return null;
}

/** Extract the body below the managed header (the actual code). */
export function getBodyBelowHeader(fileContent: string): string {
  const lines = fileContent.split("\n");
  let bodyStart = 0;
  // Recognize ALL known header-comment lines so the body we return matches
  // exactly what was passed to truncatedHash() at write time:
  //   - @prunejuice-managed marker line
  //   - spec-hash/output-hash/generated line
  //   - concrete-manifest line (optional, only when the writer emitted one)
  // If new header lines get added in the future, they MUST be recognized here
  // or the round-trip hash check will desync and report every file as modified.
  // Scan up to 8 lines to accommodate future header growth.
  for (let i = 0; i < Math.min(lines.length, 8); i++) {
    const normalized = lines[i]!.replace(/^\/\//, "#");
    if (
      lines[i]!.includes("@prunejuice-managed") ||
      HASH_LINE_RE.test(normalized) ||
      MANIFEST_LINE_RE.test(normalized)
    ) {
      bodyStart = i + 1;
    }
  }
  // Skip blank line after header
  if (bodyStart < lines.length && lines[bodyStart]!.trim() === "") {
    bodyStart++;
  }
  return lines.slice(bodyStart).join("\n");
}

// -- Eight-state freshness classifier ----------------------------------------

export type FreshnessState =
  | "fresh"
  | "stale"
  | "modified"
  | "conflict"
  | "pending"
  | "structural"
  | "ghost-stale"
  | "test-drifted";

export interface FreshnessInput {
  /** Current hash of the spec artifact */
  currentSpecHash: TruncatedHash | null;
  /** The spec-hash recorded in the managed file header */
  headerSpecHash: TruncatedHash | null;
  /** Current hash of the code body (recomputed from the file) */
  currentOutputHash: TruncatedHash | null;
  /** The output-hash recorded in the managed file header */
  headerOutputHash: TruncatedHash | null;
  /** Whether the managed file exists on disk */
  codeFileExists: boolean;
  /** Whether any upstream dependency spec has changed */
  upstreamChanged: boolean;
  /** Whether spec has changed since tests were last generated */
  specChangedSinceTests: boolean;
}

export function classifyFreshness(input: FreshnessInput): FreshnessState {
  const {
    currentSpecHash,
    headerSpecHash,
    currentOutputHash,
    headerOutputHash,
    codeFileExists,
    upstreamChanged,
    specChangedSinceTests,
  } = input;

  // No code file on disk
  if (!codeFileExists) {
    if (headerSpecHash !== null) return "structural"; // had provenance, code vanished
    return "pending"; // no code yet
  }

  // Upstream dependency changed — takes priority over local state
  if (upstreamChanged) return "ghost-stale";

  // Spec changed since tests generated — test-specific staleness
  if (specChangedSinceTests) return "test-drifted";

  // No header → pending (unmanaged file)
  if (headerSpecHash === null || headerOutputHash === null) return "pending";

  const specChanged = currentSpecHash !== headerSpecHash;
  const codeChanged = currentOutputHash !== headerOutputHash;

  if (!specChanged && !codeChanged) return "fresh";
  if (specChanged && !codeChanged) return "stale";
  if (!specChanged && codeChanged) return "modified";
  return "conflict";
}

// -- Freshness action mapping (discriminated union) --------------------------

export type FreshnessAction =
  | { kind: "skip"; description: string }
  | { kind: "regenerate"; description: string }
  | { kind: "coordinate"; description: string }
  | { kind: "error"; description: string };

export function actionForState(state: FreshnessState): FreshnessAction {
  switch (state) {
    case "fresh":
      return { kind: "skip", description: "Up to date" };
    case "stale":
      return { kind: "regenerate", description: "Spec changed, regenerating" };
    case "pending":
      return { kind: "regenerate", description: "No code yet, generating" };
    case "structural":
      return {
        kind: "error",
        description: "Code disappeared — lifecycle issue",
      };
    case "test-drifted":
      return {
        kind: "regenerate",
        description: "Spec changed since tests, regenerating tests",
      };
    case "modified":
      return {
        kind: "coordinate",
        description: "Code was manually edited — coordinator decides",
      };
    case "conflict":
      return {
        kind: "coordinate",
        description: "Both spec and code changed — coordinator decides",
      };
    case "ghost-stale":
      return {
        kind: "coordinate",
        description:
          "Upstream dependency changed — coordinator decides cascade scope",
      };
  }
}

// -- Concrete manifest header line --------------------------------------------

const MANIFEST_LINE_RE = /^[#/]+ concrete-manifest:(.*)$/;

/**
 * Format a concrete manifest Map as a header-safe line.
 *
 * Paths must not contain commas -- they are the entry delimiter. Throws if a
 * path contains a comma (release-mode invariant: the roundtrip through
 * `parseManifestLine` would be lossy).
 */
export function formatManifestLine(
  manifest: Map<string, TruncatedHash>,
  commentStyle: "#" | "//" = "#",
): string {
  for (const path of manifest.keys()) {
    if (path.includes(",")) {
      throw new Error(
        `formatManifestLine: dep path contains comma, which is the entry delimiter: ${JSON.stringify(path)}`,
      );
    }
  }
  const entries = [...manifest.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, hash]) => `${path}:${hash}`)
    .join(",");
  return `${commentStyle} concrete-manifest:${entries}`;
}

/** Parse a concrete-manifest header line back to a Map. Returns null if not a manifest line. */
export function parseManifestLine(
  line: string,
): Map<string, TruncatedHash> | null {
  const match = line.replace(/^\/\//, "#").match(MANIFEST_LINE_RE);
  if (!match) return null;

  const body = match[1]!.trim();
  const result = new Map<string, TruncatedHash>();
  if (body === "") return result;

  for (const entry of body.split(",")) {
    const lastColon = entry.lastIndexOf(":");
    if (lastColon === -1) continue;
    const path = entry.slice(0, lastColon);
    const hash = entry.slice(lastColon + 1) as TruncatedHash;
    result.set(path, hash);
  }

  return result;
}
