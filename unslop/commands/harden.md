---
description: Review a spec for completeness and suggest tightening. Use --promote to promote a concrete spec to permanent.
argument-hint: "<spec-or-directory-path> [--promote]"
---

**Parse arguments:** Extract the first non-flag token from `$ARGUMENTS` as the target path. Strip flags (`--promote`) before using the path.

**Resolve target:**

- If the target ends in `.spec.md`: use as-is (spec path). Example: `src/retry.py.spec.md`
- If the target is a directory: look for `<dirname>.unit.spec.md` inside it. Example: `src/auth/` resolves to `src/auth/auth.unit.spec.md`. If the unit spec does not exist, stop:

  > "No unit spec found at `<dir>/<dirname>.unit.spec.md`. If you meant to run on individual file specs, pass them explicitly."

- Otherwise: treat as a managed file path and append `.spec.md`. Example: `src/retry.py` resolves to `src/retry.py.spec.md`. If the spec does not exist, stop:

  > "No spec found at `<path>.spec.md`."

**Note:** Harden reviews the spec holistically, not per-file. For unit specs, Steps 3-5 run once against the entire unit spec and all its managed files together. There is no per-file loop -- the completeness review covers cross-file interfaces as a single pass.

**Check for `--promote` flag:** If `$ARGUMENTS` contains `--promote`, run the Concrete Spec Promotion flow (Step 6) instead of the standard hardening review.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the spec file at the given path exists. If it does not exist, stop and tell the user:

> "Spec not found at `<path>`."

**2. Find managed files**

Determine which files this spec manages:

- For per-file specs (`*.spec.md` but not `*.unit.spec.md`): derive the managed file path by stripping `.spec.md` (e.g., `src/retry.py.spec.md` → `src/retry.py`).
- For unit specs (`*.unit.spec.md`): read the `## Files` section of the spec and resolve all listed file paths relative to the spec's directory.

Check that all derived managed file paths exist. If none of the managed files exist, stop and tell the user:

> "No generated files found for this spec. Run `/unslop:generate` first."

If some but not all managed files are missing (unit spec case), list the missing ones as a warning and proceed with the files that do exist.

**3. Run completeness review**

Read the spec file, all managed files that exist, and `.unslop/principles.md` if it exists.

Apply thorough mode analysis — the same depth used in the Section 7 post-takeover review. Examine the spec and the generated code together and ask:

- Are there behavioral aspects of the generated code that are NOT constrained by the spec? (i.e., the code makes choices the spec is silent about)
- Are there constraints that could be stated more precisely? (e.g., vague qualifiers like "reasonable", "appropriate", or "as needed" where a concrete rule is possible)
- Does the spec leave behavioral choices open that should be pinned down for reproducibility? (e.g., ordering of results, error message text, default values, edge case handling)
- For unit specs specifically: are cross-file internal interfaces constrained? Could one managed file change its internal structure without the spec catching the inconsistency?
- Does the managed file have tail blocks (test suites, main guards, example code) that are NOT declared as `protected-regions` in the concrete spec? If a concrete spec exists without `protected-regions` but the code has tail blocks, future regeneration may overwrite them. Do not suggest protection for tail blocks whose behavior is already described in the abstract spec -- protection is for code the spec does not govern and should not regenerate. Frame as: "Consider adding: `protected-regions` for the <semantics> block (lines N-EOF). Without this declaration, future regeneration may overwrite this code. To declare, add `protected-regions` frontmatter to the concrete spec (`<impl-path>`)."

If `.unslop/principles.md` exists, check whether the spec aligns with the project principles and flag any divergence as a suggestion.

Frame every finding as: "Consider adding: [constraint]" with a brief rationale explaining what behavioral variance the constraint would eliminate.

**4. Present results**

If no issues are found:

> "Spec is well-constrained. No suggestions."

If suggestions are found:

> "Spec hardening review found N suggestions:
> 1. Consider adding: [constraint] -- [rationale]
> 2. Consider adding: [constraint] -- [rationale]
>
> These are suggestions, not requirements. Accept or reject each one."

Present all suggestions before asking the user which to accept. Do not apply any changes until the user responds.

**5. Apply accepted suggestions**

Ask the user which suggestions to accept. They may accept all, some, or none.

For each accepted suggestion, edit the spec file to add the constraint in the most appropriate location (e.g., under an existing relevant section, or in a new `## Constraints` section if none fits). Preserve all existing spec content and formatting.

After all accepted suggestions are applied, tell the user:

> "Updated `<spec-path>` with N accepted suggestion(s). Run `/unslop:generate` to regenerate the managed file(s) against the tightened spec."

If the user accepts none, acknowledge and exit without modifying any file.

This command is advisory — it never blocks, never generates code, and never runs tests.

---

**6. Concrete Spec Promotion (`--promote`)**

This flow promotes an ephemeral Concrete Spec to a permanent, version-controlled artifact. It runs instead of Steps 3-5 when `--promote` is passed.

**6a. Check for existing Concrete Spec:**

Derive the concrete spec path from the abstract spec path:
- `src/retry.py.spec.md` → `src/retry.py.impl.md`
- `src/auth/auth.unit.spec.md` → `src/auth/auth.unit.impl.md`

If a permanent concrete spec already exists at that path, tell the user:

> "Concrete spec already exists at `<path>`. It will be regenerated from the current abstract spec and managed code."

**6b. Generate or regenerate the Concrete Spec:**

Read the abstract spec and all managed files. Use the **unslop/concrete-spec** skill to draft a Concrete Spec that captures the **current implementation's strategy** — not an idealized strategy, but what the generated code actually does today.

Write the concrete spec with the following sections:
- `## Strategy` — pseudocode extracted from the current generated code
- `## Pattern` — design patterns identified in the current implementation
- `## Type Sketch` — structural types from the current implementation
- `## Lowering Notes` — language-specific notes relevant to this implementation

Set frontmatter:
```yaml
---
source-spec: <abstract-spec-path>
target-language: <detected-language>
ephemeral: false
---
```

**6c. Present for review:**

> "Concrete spec generated at `<path>`. This captures the current implementation strategy as a permanent artifact.
>
> Review the strategy. This file will be version-controlled and used as guidance during future generation cycles."

**6d. On approval:**

Write the concrete spec to disk. Tell the user:

> "Promoted `<impl-path>`. The Builder will use this as strategic guidance on future generations. The abstract spec remains the source of truth for constraints."

**6e. On rejection:**

Acknowledge and exit without writing any file.
