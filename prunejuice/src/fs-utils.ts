/** Shared filesystem utilities used by dag.ts, ripple.ts, freshness.ts, and store.ts. */

/** Check if an error is ENOENT (file/directory not found). */
export function isEnoent(err: unknown): boolean {
  return (
    err instanceof Error &&
    "code" in err &&
    (err as NodeJS.ErrnoException).code === "ENOENT"
  );
}

/** Directories excluded from recursive spec/impl file discovery. */
export const EXCLUDE_DIRS = new Set([
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
