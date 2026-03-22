---
description: Check cross-spec coherence across related specs
argument-hint: "[spec-path]"
---

**Parse arguments:** `$ARGUMENTS` may contain an optional spec path. If present, run in targeted mode. If absent, run in full mode.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Scan for specs**

Find all `*.spec.md` files in the project tree (excluding `.unslop/` and `node_modules/`). For each spec, read its frontmatter to extract any `depends-on` entries. This builds an in-memory dependency map: spec -> list of dependency spec paths.

Also collect all `*.unit.spec.md` files separately for intra-unit checking.

If the orchestrator reports a cycle during dependency resolution, stop and report the error.

**3. Run coherence checks**

**Targeted mode** (spec path provided):

1. Verify the spec file exists. If not, stop: "Spec not found at `<path>`."
2. Resolve upstream dependencies: `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .`
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

**5. This command is read-only**

Do not modify any files, generate any code, or run any tests. This is an audit command.
