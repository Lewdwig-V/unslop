/** Source file discovery: excludes tests, build artifacts, and noise directories. */

import { readdir } from "node:fs/promises";
import { join, relative } from "node:path";
import { stat } from "node:fs/promises";
import { isEnoent } from "./fs-utils.js";

export interface DiscoverOptions {
  extensions?: string[];
  extraExcludes?: string[];
}

/** Directories always excluded from source file discovery. */
const EXCLUDE_DIRS = new Set([
  "__pycache__",
  "node_modules",
  "target",
  ".git",
  ".venv",
  "venv",
  "dist",
  "build",
  ".tox",
  "vendor",
  ".mypy_cache",
  ".pytest_cache",
  ".eggs",
  ".prunejuice",
  ".unslop",
]);

/** Test directory names excluded from source file discovery. */
const TEST_DIRS = new Set(["__tests__", "tests", "spec"]);

/** Test file name patterns excluded from source file discovery. */
const TEST_FILE_PATTERNS = [
  /^test_/,
  /_test\./,
  /\.test\./,
  /\.spec\.(ts|js)$/,
];

/**
 * Discover source files in a directory, excluding tests and build artifacts.
 *
 * Returns a sorted list of file paths relative to `directory`.
 * Throws if `directory` does not exist or is not a directory.
 */
export async function discoverFiles(
  directory: string,
  options?: DiscoverOptions,
): Promise<string[]> {
  // Validate that directory exists and is a directory
  try {
    const s = await stat(directory);
    if (!s.isDirectory()) {
      throw new Error(`Not a directory: ${directory}`);
    }
  } catch (err) {
    if (isEnoent(err)) {
      throw new Error(`Directory does not exist: ${directory}`);
    }
    throw err;
  }

  const extraExcludeSet = new Set(options?.extraExcludes ?? []);
  const results: string[] = [];

  await walk(directory, directory, options?.extensions, extraExcludeSet, results);

  results.sort();
  return results;
}

async function walk(
  root: string,
  dir: string,
  extensions: string[] | undefined,
  extraExcludes: Set<string>,
  results: string[],
): Promise<void> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (err) {
    if (isEnoent(err)) return;
    throw err;
  }

  for (const entry of entries) {
    const name = entry.name;

    if (entry.isDirectory()) {
      // Skip excluded and test directories
      if (EXCLUDE_DIRS.has(name) || TEST_DIRS.has(name) || extraExcludes.has(name)) {
        continue;
      }
      await walk(root, join(dir, name), extensions, extraExcludes, results);
    } else if (entry.isFile()) {
      // Skip test files by name pattern
      if (TEST_FILE_PATTERNS.some((pat) => pat.test(name))) {
        continue;
      }

      // Filter by extension if specified
      if (extensions && extensions.length > 0) {
        const dot = name.lastIndexOf(".");
        const ext = dot >= 0 ? name.slice(dot) : "";
        if (!extensions.includes(ext)) {
          continue;
        }
      }

      results.push(relative(root, join(dir, name)));
    }
  }
}
