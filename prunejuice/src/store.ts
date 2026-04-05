import { readFile, mkdir, rename, open, unlink, stat } from "node:fs/promises";
import { resolve, dirname, basename } from "node:path";
import { randomBytes } from "node:crypto";
import { truncatedHash, formatHeader, formatManifestLine } from "./hashchain.js";
import { isEnoent } from "./fs-utils.js";
import { computeConcreteManifest } from "./manifest.js";
import type {
  Spec,
  ConcreteSpec,
  BehaviourContract,
  GeneratedTests,
  Implementation,
  SaboteurReport,
  PipelineState,
  TruncatedHash,
} from "./types.js";

const STORE_DIR = ".prunejuice";

// -- Directory layout --------------------------------------------------------

function storePath(cwd: string, ...segments: string[]): string {
  return resolve(cwd, STORE_DIR, ...segments);
}

export async function ensureStore(cwd: string): Promise<void> {
  const dirs = [
    storePath(cwd),
    storePath(cwd, "artifacts"),
    storePath(cwd, "verification"),
  ];
  for (const dir of dirs) {
    try {
      await mkdir(dir, { recursive: true });
    } catch (err) {
      throw new Error(
        `Failed to create prunejuice store directory "${dir}": ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
}

// -- Atomic write primitive --------------------------------------------------

/**
 * Write `content` to `targetPath` atomically: write to a sibling temp file,
 * fsync the data to disk, then rename over the target. On POSIX, rename(2) is
 * atomic, so a reader (or the next freshness check) never observes a partially
 * written file. On crash or SIGKILL mid-write, the target is left at its
 * previous content (or absent if it didn't exist); only a stale `.tmp-*`
 * sibling may remain, which is safe to clean up on next run.
 *
 * The fsync ensures the temp file's bytes are on disk before the rename makes
 * the directory entry point at them -- without it, a crash between rename and
 * the kernel flushing the page cache can leave an empty file at the new path
 * on some filesystems.
 *
 * Permission preservation: `rename(2)` swaps inodes, which would otherwise
 * replace the target's mode bits with the temp file's umask-derived defaults.
 * Before rename we `fchmod` the temp file to match the existing target's
 * mode so managed files keep their `+x` and other mode bits across rewrites.
 * For new files (target does not exist), the default mode is used.
 *
 * If any step fails, we best-effort remove the temp file so we don't leak
 * stale siblings; the original error propagates.
 */
export async function atomicWriteFile(
  targetPath: string,
  content: string,
): Promise<void> {
  await mkdir(dirname(targetPath), { recursive: true });

  // Capture existing target's mode so we can preserve it across the rename.
  // `fchmod` on the temp file is race-free relative to rename; `chmod` after
  // rename would leave a window where the file has wrong permissions.
  let existingMode: number | null = null;
  try {
    const st = await stat(targetPath);
    existingMode = st.mode;
  } catch (err) {
    if (!isEnoent(err)) throw err;
    // Target does not exist yet -- use umask-derived default for new files.
  }

  // Temp sibling in the SAME directory so the rename is on the same filesystem
  // (cross-filesystem rename is not atomic on POSIX -- it falls back to copy).
  const tmpName = `.${basename(targetPath)}.tmp-${process.pid}-${randomBytes(6).toString("hex")}`;
  const tmpPath = resolve(dirname(targetPath), tmpName);

  let fh;
  try {
    fh = await open(tmpPath, "w");
    await fh.writeFile(content, "utf-8");
    if (existingMode !== null) {
      await fh.chmod(existingMode);
    }
    await fh.sync();
  } catch (err) {
    if (fh) {
      try {
        await fh.close();
      } catch {
        // Ignore close errors during cleanup
      }
    }
    try {
      await unlink(tmpPath);
    } catch (cleanupErr) {
      if (!isEnoent(cleanupErr)) {
        // Leaking the temp file is less bad than masking the original error
      }
    }
    throw err;
  }
  await fh.close();

  try {
    await rename(tmpPath, targetPath);
  } catch (err) {
    try {
      await unlink(tmpPath);
    } catch (cleanupErr) {
      if (!isEnoent(cleanupErr)) {
        // Same as above: don't mask the rename error
      }
    }
    throw err;
  }
}

// -- Artifact I/O ------------------------------------------------------------

async function writeArtifact(
  cwd: string,
  name: string,
  data: unknown,
): Promise<TruncatedHash> {
  const content = JSON.stringify(data, null, 2);
  const path = storePath(cwd, "artifacts", `${name}.json`);
  await atomicWriteFile(path, content);
  return truncatedHash(content);
}

async function readArtifact<T>(cwd: string, name: string): Promise<T | null> {
  const path = storePath(cwd, "artifacts", `${name}.json`);
  let content: string;
  try {
    content = await readFile(path, "utf-8");
  } catch (err: unknown) {
    if (isEnoent(err)) return null;
    throw new Error(
      `Failed to read artifact "${name}" at ${path}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  try {
    return JSON.parse(content) as T;
  } catch (err: unknown) {
    throw new Error(
      `Corrupt artifact "${name}" at ${path}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

// -- Typed artifact accessors ------------------------------------------------

export async function saveSpec(
  cwd: string,
  spec: Spec,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "spec", spec);
}

export async function loadSpec(cwd: string): Promise<Spec | null> {
  return readArtifact<Spec>(cwd, "spec");
}

export async function saveConcreteSpec(
  cwd: string,
  concreteSpec: ConcreteSpec,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "concrete-spec", concreteSpec);
}

export async function loadConcreteSpec(
  cwd: string,
): Promise<ConcreteSpec | null> {
  return readArtifact<ConcreteSpec>(cwd, "concrete-spec");
}

export async function saveBehaviourContract(
  cwd: string,
  contract: BehaviourContract,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "behaviour-contract", contract);
}

export async function loadBehaviourContract(
  cwd: string,
): Promise<BehaviourContract | null> {
  return readArtifact<BehaviourContract>(cwd, "behaviour-contract");
}

export async function saveTests(
  cwd: string,
  tests: GeneratedTests,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "tests", tests);
}

export async function loadTests(cwd: string): Promise<GeneratedTests | null> {
  return readArtifact<GeneratedTests>(cwd, "tests");
}

export async function saveImplementation(
  cwd: string,
  impl: Implementation,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "implementation", impl);
}

export async function loadImplementation(
  cwd: string,
): Promise<Implementation | null> {
  return readArtifact<Implementation>(cwd, "implementation");
}

export async function saveSaboteurReport(
  cwd: string,
  report: SaboteurReport,
): Promise<TruncatedHash> {
  return writeArtifact(cwd, "saboteur-report", report);
}

export async function loadSaboteurReport(
  cwd: string,
): Promise<SaboteurReport | null> {
  return readArtifact<SaboteurReport>(cwd, "saboteur-report");
}

// -- Convergence state persistence -------------------------------------------

interface ConvergenceState {
  convergenceIteration: number;
  killRateHistory: number[];
  radicalHardeningAttempted: boolean;
}

async function saveConvergenceState(
  cwd: string,
  state: ConvergenceState,
): Promise<void> {
  await writeArtifact(cwd, "convergence", state);
}

async function loadConvergenceState(
  cwd: string,
): Promise<ConvergenceState | null> {
  return readArtifact<ConvergenceState>(cwd, "convergence");
}

// -- Hash lookups (for freshness classification) -----------------------------

export async function artifactHash(
  cwd: string,
  name: string,
): Promise<TruncatedHash | null> {
  const path = storePath(cwd, "artifacts", `${name}.json`);
  let content: string;
  try {
    content = await readFile(path, "utf-8");
  } catch (err: unknown) {
    if (isEnoent(err)) return null;
    throw new Error(
      `Failed to read artifact "${name}" for hashing at ${path}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  return truncatedHash(content);
}

// -- Comment style detection -------------------------------------------------

export function commentStyleForPath(path: string): "#" | "//" {
  const hashCommentExtensions = [
    ".py",
    ".sh",
    ".rb",
    ".yaml",
    ".yml",
    ".toml",
    ".pl",
    ".r",
    ".jl",
  ];
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  return hashCommentExtensions.includes(ext) ? "#" : "//";
}

// -- Managed file writing (adds hash chain headers) -------------------------

/**
 * Options for writing a managed file. `concreteManifest` is the per-dependency
 * hash map for the concrete spec this file derives from, if one exists. When
 * present, it is emitted as a `concrete-manifest:` line in the header so the
 * ghost staleness diagnostic in ripple check can diff it against the current
 * disk state on subsequent runs.
 */
export interface WriteManagedFileOptions {
  concreteManifest?: Map<string, TruncatedHash>;
}

export async function writeManagedFile(
  cwd: string,
  filePath: string,
  content: string,
  specArtifactName: string,
  timestamp: string,
  options?: WriteManagedFileOptions,
): Promise<void> {
  const specHash = await artifactHash(cwd, specArtifactName);
  if (!specHash) {
    throw new Error(
      `Cannot write managed file: spec artifact "${specArtifactName}" not found in store`,
    );
  }

  const outputHash = truncatedHash(content);
  const commentStyle = commentStyleForPath(filePath);
  const header = formatHeader(
    `.prunejuice/artifacts/${specArtifactName}.json`,
    { specHash, outputHash, generated: timestamp },
    commentStyle,
  );

  // Append a concrete-manifest line when the caller provided a non-empty
  // manifest. This is the write side of the ghost staleness diagnostic --
  // ripple.ts scans managed headers for this line and diffs it against the
  // current manifest to explain WHY a downstream file is ghost-stale.
  const manifestLine =
    options?.concreteManifest && options.concreteManifest.size > 0
      ? `\n${formatManifestLine(options.concreteManifest, commentStyle)}`
      : "";

  const fullContent = `${header}${manifestLine}\n\n${content}`;
  const absPath = resolve(cwd, filePath);
  await atomicWriteFile(absPath, fullContent);
}

/**
 * Locate a conventional `.impl.md` file for a managed output, if one exists.
 * Tries `<managed-file-path>.impl.md` in the same directory. Returns the path
 * (relative to cwd) if found, otherwise null.
 *
 * This is the bridge between prunejuice's runtime ConcreteSpec model (a TS
 * object with no dependency edges) and the filesystem `.impl.md` convention
 * used by the unslop plugin for hand-authored concrete specs with deps.
 * Users in the dual workflow get ghost staleness diagnostics; prunejuice-only
 * users get no `.impl.md` lookup and no manifest line, which is correct.
 */
async function findConventionalImplMd(
  cwd: string,
  managedFilePath: string,
): Promise<string | null> {
  const candidate = `${managedFilePath}.impl.md`;
  const absCandidate = resolve(cwd, candidate);
  try {
    await stat(absCandidate);
    return candidate;
  } catch (err) {
    if (isEnoent(err)) return null;
    throw err;
  }
}

export async function writeImplementationFiles(
  cwd: string,
  implementation: Implementation,
  timestamp: string,
): Promise<void> {
  for (const file of implementation.files) {
    // Opportunistically look up a conventional .impl.md for this output.
    // If found, compute its concrete manifest and include it in the header
    // so ghost staleness diagnostics work on subsequent ripple checks.
    const implPath = await findConventionalImplMd(cwd, file.path);
    const concreteManifest = implPath
      ? (await computeConcreteManifest(implPath, cwd)) ?? undefined
      : undefined;

    await writeManagedFile(
      cwd,
      file.path,
      file.content,
      "concrete-spec",
      timestamp,
      concreteManifest ? { concreteManifest } : undefined,
    );
  }
}

export async function writeTestFiles(
  cwd: string,
  tests: GeneratedTests,
  timestamp: string,
): Promise<void> {
  if (tests.testFilePaths.length === 0) {
    throw new Error("Mason produced no test file paths");
  }
  if (tests.testFilePaths.length > 1) {
    throw new Error(
      `writeTestFiles: Mason declared ${tests.testFilePaths.length} test file paths but only single-file output is supported. ` +
        `Paths: ${tests.testFilePaths.join(", ")}`,
    );
  }
  const filePath = tests.testFilePaths[0]!;
  await writeManagedFile(
    cwd,
    filePath,
    tests.testCode,
    "behaviour-contract",
    timestamp,
  );
}

// -- Full pipeline state persistence -----------------------------------------

export async function savePipelineState(
  cwd: string,
  state: PipelineState,
): Promise<void> {
  // Save sequentially to avoid partial persistence on failure
  if (state.spec) await saveSpec(cwd, state.spec);
  if (state.concreteSpec) await saveConcreteSpec(cwd, state.concreteSpec);
  if (state.behaviourContract)
    await saveBehaviourContract(cwd, state.behaviourContract);
  if (state.tests) await saveTests(cwd, state.tests);
  if (state.implementation) await saveImplementation(cwd, state.implementation);
  if (state.saboteurReport) await saveSaboteurReport(cwd, state.saboteurReport);
  await saveConvergenceState(cwd, {
    convergenceIteration: state.convergenceIteration,
    killRateHistory: state.killRateHistory,
    radicalHardeningAttempted: state.radicalHardeningAttempted,
  });
}

export async function loadPipelineState(
  cwd: string,
): Promise<Partial<PipelineState>> {
  const [
    spec,
    concreteSpec,
    behaviourContract,
    tests,
    implementation,
    saboteurReport,
    convergence,
  ] = await Promise.all([
    loadSpec(cwd),
    loadConcreteSpec(cwd),
    loadBehaviourContract(cwd),
    loadTests(cwd),
    loadImplementation(cwd),
    loadSaboteurReport(cwd),
    loadConvergenceState(cwd),
  ]);

  const state: Partial<PipelineState> = {};
  if (spec) state.spec = spec;
  if (concreteSpec) state.concreteSpec = concreteSpec;
  // Prefer independently-saved behaviour contract (may be enriched during convergence)
  if (behaviourContract) state.behaviourContract = behaviourContract;
  else if (concreteSpec)
    state.behaviourContract = concreteSpec.behaviourContract;
  if (tests) state.tests = tests;
  if (implementation) state.implementation = implementation;
  if (saboteurReport) state.saboteurReport = saboteurReport;
  if (convergence) {
    state.convergenceIteration = convergence.convergenceIteration;
    state.killRateHistory = convergence.killRateHistory;
    state.radicalHardeningAttempted = convergence.radicalHardeningAttempted;
  }
  return state;
}
