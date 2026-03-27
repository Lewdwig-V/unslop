# Multi-File Takeover Design

> Extend unslop to take over entire functional units (modules, crates, packages) — not just individual files.

## Problem

The MVP takeover pipeline operates on a single source file. Real codebases have tightly coupled files that form logical units — a Python module directory, a Rust crate, a set of files sharing internal APIs and tests. Taking over files individually misses cross-file contracts and breaks when files depend on each other.

## Scope

This design extends the existing takeover, generate, sync, spec, and status commands to support multi-file operations with dependency-aware build ordering. It adds an orchestrator script for the stateful parts (dependency resolution, topological sort) while keeping the model in charge of spec drafting and code generation.

## Spec Frontmatter — Dependencies

Specs gain optional YAML frontmatter for declaring dependencies:

```markdown
---
depends-on:
  - src/auth/tokens.py.spec.md
  - src/auth/errors.py.spec.md
---

# handler.py spec

## Purpose
HTTP request handler for authentication endpoints.
```

Rules:
- `depends-on` is a list of spec file paths (relative to project root)
- Dependencies mean: "this file imports from or relies on the behavior described by those specs"
- The orchestrator uses this to determine build order — dependents are generated after their dependencies
- Circular dependencies are an error — the orchestrator detects and reports them
- Missing dependencies (spec listed but doesn't exist) are a warning, not a blocker
- Single-file specs with no dependencies omit the frontmatter entirely (backwards compatible with MVP)

### Frontmatter parsing format

The orchestrator parses frontmatter using simple string matching, not a full YAML parser. The supported format is strictly:

```
---
depends-on:
  - path/to/spec.py.spec.md
  - path/to/other.py.spec.md
---
```

- Content between the first pair of `---` delimiters
- A line matching `^depends-on:$` followed by lines matching `^  - (.+)$`
- Paths must not be quoted and must not contain YAML-special characters (`:`, `#`, `{`, `}`)
- No other YAML features are supported
- Files without frontmatter or with empty `depends-on` are treated as having no dependencies

## Spec Granularity

When taking over a multi-file unit, the user chooses between two modes:

### Per-file specs

Each source file gets its own `*.spec.md`. Cross-file contracts are expressed through `depends-on` frontmatter. Files are generated independently in dependency order.

### Per-unit specs

One spec describes the entire unit. Named `<directory-name>.unit.spec.md`, placed inside the directory (e.g., `src/auth/auth.unit.spec.md`).

A `## Files` section lists all output files and their responsibilities:

```markdown
# auth module spec

## Files
- `__init__.py` — public API re-exports
- `tokens.py` — JWT token creation and verification
- `middleware.py` — request authentication middleware
- `errors.py` — authentication error types

## Behavior
...
```

The generation skill produces multiple files from a single spec. All generated files reference the unit spec in their `@unslop-managed` header (e.g., `Edit src/auth/auth.unit.spec.md instead.`). No inter-spec dependencies to resolve — the orchestrator is not needed.

### Spec path resolution

Commands that need to find a file's spec (sync, status, generate) use this resolution order:
1. Read the `@unslop-managed` header from the managed file — the header contains the spec path
2. If the header is missing or the file is not yet managed, derive the spec path by appending `.spec.md` to the filename (per-file convention)

This means commands always trust the header over the naming convention. Per-unit specs work because the header points to the `.unit.spec.md` file directly.

## Orchestrator Script

A Python script at `unslop/scripts/orchestrator.py` handles the structural, stateful parts of multi-file workflows. The model calls it via Bash. Python 3.8+ is required for multi-file mode.

### Interface

```bash
# Discover source files in a directory
python orchestrator.py discover src/auth/ --extensions .py
# Output: JSON list of source files found (excludes test files and common non-source dirs)

# Parse dependencies from spec frontmatter and return build order
python orchestrator.py build-order src/auth/
# Output: JSON list of spec paths in topological order (leaves first)
# Errors: reports cycles, missing deps

# Resolve a single spec's dependencies (transitive)
python orchestrator.py deps src/auth/handler.py.spec.md
# Output: JSON list of transitive dependencies in build order
```

### Discovery exclusions

The `discover` subcommand excludes by default:
- Test files: `*_test.*`, `test_*.*`, `*.test.*`, `*.spec.ts`, `*.spec.js`, files in `__tests__/`, `spec/`, `tests/`
- Common non-source directories: `__pycache__`, `node_modules`, `target`, `.git`, `.venv`, `venv`, `dist`, `build`, `.tox`, `*.egg-info`, `vendor`

Additional exclusion patterns can be configured in `.unslop/config.md`:
```markdown
# unslop configuration

Test command: `pytest`
Exclude patterns: `.mypy_cache`, `generated/`
```

### Implementation

- Pure Python 3.8+, zero external dependencies (stdlib only)
- Frontmatter parsing as specified above (string matching, not YAML library)
- Topological sort via Kahn's algorithm (detects cycles)
- All output is JSON on stdout, errors on stderr
- Exit codes: 0 = success, 1 = error (cycle, invalid frontmatter, etc.)

### What the script does NOT do

- Draft specs, generate code, run tests — that stays in skills
- Track staleness or alignment summaries — that stays in commands
- Make decisions about what to take over — the model proposes, user confirms

The script is a pure function: inputs in, deterministic outputs out.

## Multi-File Takeover Pipeline

When a user runs `/unslop:takeover src/auth/`:

### Step 1: Discover
- Call `orchestrator.py discover` to scan the directory
- Present file list to user for confirmation
- User can add/remove files before proceeding
- For units larger than ~10 files, suggest per-file mode with a note that very large units may exceed context limits

### Step 2: Choose Spec Granularity
- Ask user: one spec per file, or one spec for the whole unit?
- Per-file: each file gets its own `.spec.md` with `depends-on` frontmatter
- Per-unit: one `<dir>.unit.spec.md` describes the whole module, generates all files

### Step 3: Draft Specs
- Read ALL files in the unit and their tests together
- Draft spec(s) capturing intent and cross-file contracts
- For per-file mode: declare `depends-on` frontmatter based on import analysis
- User reviews ALL specs before proceeding

### Step 4: Archive
- Archive all original files in the unit to `.unslop/archive/`

### Step 5: Resolve Build Order
- Call `orchestrator.py build-order` to get topological sort
- Per-unit mode skips this step (single spec, no inter-spec deps)

### Step 6: Generate in Order
- For each spec in build order: generate code from spec only (no peeking)
- Dependencies are already generated — imports resolve correctly
- Per-unit mode: generate all files from the single spec

### Step 7: Validate
- Run tests for the whole unit (not per-file)
- If green: commit all specs + generated files
- If red: enter convergence loop

### Step 8: Convergence Loop (max 3 iterations)
- Analyze test failures
- Enrich the relevant spec(s) — content only, do NOT change `depends-on` frontmatter during convergence (changing the dependency graph mid-loop creates cascading instability)
- Regenerate files whose specs were enriched, plus their dependents (using the existing, stable build order)
- Re-run tests
- If the orchestrator reports an error (cycle, missing dep) during convergence, abort immediately and surface the error to the user
- On abandonment: keep draft specs, keep last generated attempt, originals remain in archive

## Command Changes

### `/unslop:takeover` — updated

Gains directory/glob support:

```
/unslop:takeover src/auth/           # directory — multi-file mode
/unslop:takeover src/auth/*.py       # glob — multi-file mode
/unslop:takeover src/retry.py        # single file — existing behavior
```

Detection: if `$ARGUMENTS` is a directory, enter multi-file mode. If it contains glob characters (`*`, `?`), the model expands the glob (Claude Code commands receive `$ARGUMENTS` as a raw string, not shell-expanded) and enters multi-file mode if multiple files match. Otherwise, single-file mode (unchanged from MVP).

### `/unslop:generate` — updated

With dependencies, regeneration must respect build order:
1. Resolve build order across all stale specs via `orchestrator.py build-order`
2. Regenerate in dependency order (leaves first)
3. If a dependency was regenerated, its dependents are also regenerated even if their own specs haven't changed (the dependency's implementation may have changed)
4. **No convergence loop.** If cascading regeneration of a dependent breaks tests, stop and report: which upstream regeneration caused the failure, which dependent broke, and the test output. The user must decide whether to update the dependent's spec or revert the upstream change. This preserves the MVP's rule: generate does not converge.

### `/unslop:sync` — updated

With dependencies:
1. Read the `@unslop-managed` header to find the spec path (supports both per-file and per-unit specs)
2. Call `orchestrator.py deps <spec>` to find transitive dependencies
3. Check if any dependencies are stale — if so, regenerate them first (in dependency order)
4. Then regenerate the target file

### `/unslop:spec` — updated

When creating per-file specs in a module, the model should suggest `depends-on` frontmatter based on import analysis.

### `/unslop:status` — updated

Status gains dependency and unit awareness:

```
Managed files:
  fresh    src/auth/tokens.py       <- src/auth/tokens.py.spec.md
  fresh    src/auth/errors.py       <- src/auth/errors.py.spec.md
  stale    src/auth/handler.py      <- src/auth/handler.py.spec.md (spec edited 2h ago)
                                       depends on: tokens.py.spec.md, errors.py.spec.md
  stale*   src/auth/middleware.py   <- src/auth/middleware.py.spec.md (dependency stale)
                                       depends on: handler.py.spec.md

Unit specs:
  fresh    src/utils/               <- src/utils/utils.unit.spec.md (4 files)
```

New states:
- **stale\*** (transitive staleness) — the file's own spec hasn't changed, but one of its dependencies is stale. Displayed with an asterisk and the note "(dependency stale)".

For unit specs: display the directory and file count rather than listing each managed file individually.

The status command calls `orchestrator.py deps` to detect transitive staleness.

### No new commands

Multi-file takeover reuses `/unslop:takeover` — no new commands needed.

## Skill Updates

### `takeover` skill

Gains a "multi-file mode" section covering:
- Discovery: how to use the orchestrator's discover subcommand
- Granularity prompt: how to present the per-file vs per-unit choice
- Cross-file spec drafting: read all files together, identify internal contracts
- Build-order-aware generation: call the orchestrator, process in order
- Unit-level validation: run tests once for the whole unit
- Smarter convergence: only regenerate changed specs + dependents; do not change `depends-on` during convergence
- Size guidance: suggest per-file mode for units larger than ~10 files

Existing single-file behavior is preserved.

### `generation` skill

Gains a "multi-file generation" section for per-unit specs:
- When a spec has a `## Files` section listing multiple output files, generate each file separately
- Apply `@unslop-managed` header to every generated file
- All files reference the unit spec path in their header

### `spec-language` skill

Gains guidance on:
- When to use `depends-on` frontmatter
- How to write cross-file contracts
- Per-unit spec conventions: naming (`<dir>.unit.spec.md`), the `## Files` section

## Backwards Compatibility

### Fully backwards compatible

- Single-file takeover works exactly as before
- Specs without frontmatter are treated as having no dependencies
- Existing commands accept the same arguments — directory/glob is additive
- No migration step required
- Commands now prefer the `@unslop-managed` header for spec path resolution, falling back to the naming convention. Existing managed files already have the correct header.

### Graceful degradation

If Python is not available, multi-file mode is not supported — the command reports an error and suggests installing Python 3.8+. Single-file operations and per-unit specs (which don't need the orchestrator) continue to work without Python.

## Plugin Structure Changes

```
unslop/
├── .claude-plugin/
│   └── plugin.json
├── commands/           # updated: takeover, generate, sync, spec, status
├── skills/             # updated: takeover, generation, spec-language
├── hooks/              # unchanged
└── scripts/
    └── orchestrator.py # new — Python 3.8+, zero dependencies
```
