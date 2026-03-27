---
description: Merge file specs into a unit spec (spec granularity consolidation)
argument-hint: "<target-directory> <spec-1> <spec-2> [...] | <target-directory> --all | --cleanup"
---

**Parse arguments:** `$ARGUMENTS` may contain:
- A target directory path (first non-flag argument)
- One or more spec file paths
- `--all` flag (absorb all file specs in the target directory)
- `--cleanup` flag (remove ratified staged originals from `.unslop/absorbed/`)

**Check for `--cleanup` flag:** If present, skip to **Cleanup** section below.

**1. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

Verify the target directory exists. If `--all` is passed, find all `*.spec.md` files in the target directory (excluding `*.unit.spec.md`). If specific spec paths are provided, verify each exists.

If fewer than 2 input specs, stop:

> "Absorb requires at least 2 specs to merge."

**2. Mode detection**

Check if `<target-directory>/<dirname>.unit.spec.md` exists:
- **Exists:** Amendment mode. Read the existing unit spec.
- **Does not exist:** Creation mode. Fresh unit spec.

**3. Read all input specs**

For each input spec:
1. Read the full content.
2. Parse frontmatter: `intent`, `intent-approved`, `non_goals`, `depends-on`, `needs-review`, `uncertain`, `discovered`, `distilled-from`, `absorbed-from`, `exuded-from`.
3. Parse the spec body (sections after frontmatter).

If amendment mode, also read the existing unit spec with the same parsing.

**4. Conflict detection (Architect agent -- opus)**

Dispatch an Architect subagent to analyze the input specs and detect:

1. **Intent conflicts:** Goals or constraints in one spec that contradict another.
2. **Non-goal conflicts:** Non-goals in one spec that overlap with goals in another.
3. **Dependency conflicts:** Circular or contradictory `depends-on` relationships.

Each conflict becomes an `uncertain:` entry with title/observation/question structure.

**Input preconditions:** Absorb proceeds regardless of `intent-approved` state on inputs. Any existing `uncertain:` or `discovered:` entries on input specs are merged into the output -- they do not disappear because the spec was absorbed.

**5. Merge**

The Architect produces the merged unit spec:

1. **Goals:** Concatenate from all inputs. Deduplicate semantically identical goals.
2. **Constraints:** Union. Conflicts surfaced as `uncertain:` entries.
3. **Dependencies:** Union of all `depends-on` lists. Remove self-references (a file spec that depended on another absorbed file spec).
4. **Non-goals:** Union. Conflicts against merged goals become `uncertain:` entries.
5. **Managed files:** List all files from all absorbed file specs in the `## Files` section.

**6. Write output**

Write the merged unit spec with:
- `intent-approved: false` (always -- merge requires ratification)
- `absorbed-from:` provenance list (path + hash for each absorbed spec)
- Merged `uncertain:` entries (from conflicts + carried forward from inputs)
- Merged `discovered:` entries (carried forward from inputs)

**7. DAG update**

Scan all `*.spec.md` files in the project for `depends-on` entries referencing any absorbed spec path. For each match:
1. Rewrite the `depends-on` entry to reference the unit spec path.
2. Write `needs-review: <intent-hash>` into the modified spec's frontmatter.
3. Stage the modified spec (`git add`).

Report which specs were updated.

**8. Stage originals**

Move each absorbed file spec to `.unslop/absorbed/<original-filename>`. Create the directory if needed. Do NOT delete originals.

**9. Route to elicit**

If the merged spec has `uncertain:` entries (from conflicts or carried forward):

> "Merged spec has N uncertain entries requiring resolution. Routing to `/unslop:elicit` for review."

Run `/unslop:elicit <unit-spec-path>` in amendment mode.

If no `uncertain:` entries, present the merged spec for review:

> "Merged spec written to <path>. Review and ratify with `/unslop:elicit <path>` or approve directly."

---

**Cleanup**

When `--cleanup` is passed:

1. Scan `.unslop/absorbed/` for staged spec files.
2. For each staged file, find the successor spec (the unit spec that absorbed it). Check if the successor has `intent-approved` set to a timestamp.
3. If ratified: delete the staged original. Report: `Cleaned: <filename>`
4. If not ratified: skip. Report: `Skipped (pending ratification): <filename>`
5. If no staged files exist: report `No staged originals to clean.`

---

**Model:** `config.models.architect` (default: `opus`). Absorb is reconciliation work -- merging intent sections and detecting conflicts requires judgment under ambiguity.

This command is NOT read-only. It writes the merged unit spec, moves originals to staging, and updates dependency references across the project.
