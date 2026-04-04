---
description: Check cross-spec coherence across related specs, including blocked-by constraint tracking
argument-hint: "[spec-path]"
---

**Parse arguments:** `$ARGUMENTS` may contain an optional spec path. If present, run in targeted mode. If absent, run in full mode.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Scan for specs**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`). For each spec, read its frontmatter to extract any `depends-on` entries. This builds an in-memory dependency map: spec -> list of dependency spec paths.

Also collect all `*.unit.spec.md` files separately for intra-unit checking.

If `prunejuice_ripple_check` or `prunejuice_build_order` reports a cycle during dependency resolution, stop and report the error.

**3. Run coherence checks**

**Targeted mode** (spec path provided):

1. Verify the spec file exists. If not, stop: "Spec not found at `<path>`."
2. Resolve upstream dependencies: call `prunejuice_resolve_deps` with `{ specPath: "<spec-path>", cwd: "." }`
3. Resolve reverse dependents: scan the dependency map for specs whose `depends-on` lists reference the target spec path.
4. For each upstream dependency: read both specs and check for incoherence (same checks as Phase 0e in the generation skill -- type compatibility, constraint compatibility, error contract compatibility, naming consistency).
5. For each reverse dependent: read both specs and check for incoherence.
6. If the target is a unit spec (`*.unit.spec.md`): also run the intra-unit coherence pass on files listed in `## Files`.

**Full mode** (no arguments):

1. For each spec with `depends-on` entries: read the spec and each of its direct dependencies, check each pair for incoherence.
2. For each unit spec (`*.unit.spec.md`): run the intra-unit coherence pass on files listed in `## Files`, regardless of whether the unit spec has external dependencies.

If no dependency relationships exist AND no unit specs exist, report:

> "No dependency relationships or unit specs found. Coherence checking requires specs with `depends-on` frontmatter or `*.unit.spec.md` files."

**4. Report results**

Display results in this format:

```
Cross-spec coherence check:

  <spec-a> <-> <spec-b>
    ✓ consistent

  <spec-c> <-> <spec-d>
    ✗ <issue-type>: <brief description>

  <unit-spec> (intra-unit)
    ✓ consistent

N incoherence(s) found across M dependency pairs.
```

For each incoherence, include:
- The two specs (or unit spec name for intra-unit issues)
- The issue type (naming mismatch, type mismatch, constraint conflict, error contract mismatch)
- Quoted text from both specs showing the contradiction
- A brief explanation of why this will break generated code

If no incoherences are found:

> "All specs are coherent. 0 incoherences across N dependency pairs."

**5. Concrete Spec Coherence (Strategy Layer)**

After abstract spec coherence checks, extend the audit to permanent concrete specs (`*.impl.md`).

**5a. Discover concrete specs:**

For each spec pair checked in Step 3, look for corresponding permanent concrete specs:
- `src/handler.py.spec.md` → `src/handler.py.impl.md`
- `src/auth/tokens.py.spec.md` → `src/auth/tokens.py.impl.md`

Collect pairs where both specs in a dependency relationship have permanent concrete specs.

**5b. Strategy coherence checks:**

For each concrete spec pair, apply the same checks defined in Phase 0e.1 of the generation skill:

- **Concurrency model compatibility**: sync vs async mismatch
- **Type sketch compatibility**: structural type disagreements at the boundary
- **Pattern compatibility**: architectural approach conflicts
- **Lowering notes conflict**: conflicting assumptions for the same target language

**5b.1 Blocked constraint awareness:**

For each concrete spec pair being checked, read the `blocked-by` frontmatter of both specs. If either spec has `blocked-by` entries:

- Display the blocked constraint with `⊘` (not `✗`):
  ```
    ⊘ blocked constraint: <affects> (known -- tracked in blocked-by)
  ```
- Do NOT count blocked constraints toward the incoherence total
- If the upstream concrete spec in the pair is ghost-stale (already flagged by cascade detection or ghost-staleness logic), append an advisory:
  ```
    ⊘ blocked constraint: <affects> (known -- tracked in blocked-by)
      ℹ upstream <impl-path> is ghost-stale -- blocker may be resolved
  ```

The lookup boundary is the same as step 5a -- only concrete spec pairs derived from abstract spec `depends-on` relationships are checked. Coherence does NOT scan all `.impl.md` files in the project looking for symbol matches, and does NOT use `concrete-dependencies` or `extends` edges for pair discovery. If a `blocked-by` entry's symbol lives in a file with no abstract-level `depends-on` edge, the blocker is invisible to coherence (it still appears in `/unslop:status`). No additional pair discovery or pairing logic changes are needed.

**5c. Cascade detection:**

For each concrete spec that has changed since its last generation (compare `source-spec` hash in frontmatter against current abstract spec hash):

1. Find all downstream dependents that also have permanent concrete specs
2. Flag them as potentially stale:

> "Strategy cascade: `<changed.impl.md>` has changed. Downstream concrete specs may need re-lowering:
> - `<dependent-1.impl.md>` — [reason: e.g., 'assumes sync calls to changed module']
> - `<dependent-2.impl.md>` — [reason: e.g., 'type sketch references changed types']"

Cascade detection is **advisory** — it flags potential issues but does not block.

**5d. Report format:**

Append concrete spec results to the existing report:

```
Concrete spec coherence:

  <target.impl.md> <-> <dep.impl.md>
    ✓ strategies compatible

  <target.impl.md> <-> <dep.impl.md>
    ✗ concurrency mismatch: target assumes sync, dependency uses AWAIT

  Strategy cascade alerts:
    ⚠ <changed.impl.md> changed — 2 downstream specs may need re-lowering

N strategy issue(s) found. M cascade alert(s).
```

If no permanent concrete specs exist:

> "No permanent concrete specs found. Strategy coherence checks skipped."

**6. This command is read-only**

Do not modify any files, generate any code, or run any tests. This is an audit command.
