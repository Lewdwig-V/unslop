import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, dirname } from "node:path";
import {
  truncatedHash,
  parseHeader,
  getBodyBelowHeader,
  classifyFreshness,
  type FreshnessState,
} from "./hashchain.js";
import type { TruncatedHash } from "./types.js";

// -- Interfaces ---------------------------------------------------------------

export interface FreshnessEntry {
  /** Path to the spec file, relative to cwd */
  spec: string;
  /** Path to the managed file, relative to cwd */
  managed: string;
  /** Freshness state from the eight-state classifier */
  state: FreshnessState;
  /** Human-readable hint for non-fresh states */
  hint?: string;
}

export interface FreshnessReport {
  /** "fail" if any file is in conflict or structural state, otherwise "ok" */
  status: "ok" | "fail";
  /** One entry per discovered spec file */
  files: FreshnessEntry[];
  /** Summary counts by state */
  summary: Record<FreshnessState, number>;
}

// -- Defaults -----------------------------------------------------------------

const DEFAULT_EXCLUDE = new Set([
  ".prunejuice",
  ".unslop",
  "node_modules",
  ".git",
  "__pycache__",
  "dist",
  "build",
  ".venv",
  "venv",
]);

const HINT: Partial<Record<FreshnessState, string>> = {
  stale: "Spec changed since last generation -- regenerate to update managed file",
  modified: "Managed file was manually edited -- coordinator must decide whether to preserve or overwrite",
  conflict: "Both spec and managed file changed -- manual resolution required",
  pending: "Managed file does not exist yet -- generate to create it",
  structural: "Managed file disappeared but provenance header exists -- lifecycle issue",
  "ghost-stale": "An upstream dependency spec changed -- cascade regeneration may be needed",
  "test-drifted": "Spec changed since tests were last generated -- regenerate tests",
};

const FAIL_STATES = new Set<FreshnessState>(["conflict", "structural"]);

// -- Recursive spec discovery -------------------------------------------------

async function findSpecFiles(
  dir: string,
  excludeSet: Set<string>,
): Promise<string[]> {
  let results: string[] = [];
  let names: string[];
  try {
    names = await readdir(dir);
  } catch {
    return results;
  }
  for (const name of names) {
    if (excludeSet.has(name)) continue;
    const fullPath = join(dir, name);
    let isDir = false;
    try {
      const s = await stat(fullPath);
      isDir = s.isDirectory();
    } catch {
      continue;
    }
    if (isDir) {
      const nested = await findSpecFiles(fullPath, excludeSet);
      results = results.concat(nested);
    } else if (name.endsWith(".spec.md")) {
      results.push(fullPath);
    }
  }
  return results;
}

// -- Entry classification -----------------------------------------------------

async function classifyEntry(
  specAbsPath: string,
  cwd: string,
): Promise<FreshnessEntry> {
  const specRel = relative(cwd, specAbsPath);
  // Derive managed file path: strip ".spec.md" suffix
  const managedRel = specRel.replace(/\.spec\.md$/, "");
  const managedAbsPath = join(cwd, managedRel);

  // Read spec content
  let specContent = "";
  try {
    specContent = await readFile(specAbsPath, "utf-8");
  } catch {
    // If we can't read the spec, treat as no spec content
  }
  const currentSpecHash: TruncatedHash = truncatedHash(specContent);

  // Check managed file existence
  let codeFileExists = false;
  let managedContent = "";
  try {
    managedContent = await readFile(managedAbsPath, "utf-8");
    codeFileExists = true;
  } catch {
    codeFileExists = false;
  }

  // Parse header from managed file
  const header = codeFileExists ? parseHeader(managedContent) : null;
  const headerSpecHash = header ? header.specHash : null;
  const headerOutputHash = header ? header.outputHash : null;

  // Compute current output hash from body (excluding header)
  const currentOutputHash: TruncatedHash | null = codeFileExists
    ? truncatedHash(getBodyBelowHeader(managedContent))
    : null;

  const state = classifyFreshness({
    currentSpecHash,
    headerSpecHash,
    currentOutputHash,
    headerOutputHash,
    codeFileExists,
    upstreamChanged: false, // Phase 1: no DAG yet
    specChangedSinceTests: false, // Phase 1: no DAG yet
  });

  const entry: FreshnessEntry = {
    spec: specRel,
    managed: managedRel,
    state,
  };
  if (state !== "fresh") {
    const hint = HINT[state];
    if (hint) entry.hint = hint;
  }
  return entry;
}

// -- Public API ---------------------------------------------------------------

/**
 * Scan all *.spec.md files under `cwd`, classify each one's freshness, and
 * return a FreshnessReport. Directories in the default exclude list (plus any
 * user-supplied `excludePatterns`) are skipped during discovery.
 */
export async function checkFreshnessAll(
  cwd: string,
  options?: { excludePatterns?: string[] },
): Promise<FreshnessReport> {
  const excludeSet = new Set(DEFAULT_EXCLUDE);
  if (options?.excludePatterns) {
    for (const pattern of options.excludePatterns) {
      excludeSet.add(pattern);
    }
  }

  const specPaths = await findSpecFiles(cwd, excludeSet);

  const files: FreshnessEntry[] = await Promise.all(
    specPaths.map((p) => classifyEntry(p, cwd)),
  );

  // Sort for deterministic output
  files.sort((a, b) => a.spec.localeCompare(b.spec));

  // Compute summary
  const summary = {
    fresh: 0,
    stale: 0,
    modified: 0,
    conflict: 0,
    pending: 0,
    structural: 0,
    "ghost-stale": 0,
    "test-drifted": 0,
  } as Record<FreshnessState, number>;
  for (const f of files) {
    summary[f.state]++;
  }

  const status: "ok" | "fail" = files.some((f) => FAIL_STATES.has(f.state))
    ? "fail"
    : "ok";

  return { status, files, summary };
}
