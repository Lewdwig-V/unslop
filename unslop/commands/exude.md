---
description: Partition a unit spec into file specs (spec granularity splitting)
argument-hint: "<unit-spec-path> <file-1> <file-2> [...] | <unit-spec-path> --propose | --cleanup"
---

**Parse arguments:** `$ARGUMENTS` may contain:
- A unit spec path (first non-flag argument, must be `*.unit.spec.md`)
- One or more target file paths
- `--propose` flag (LLM proposes partition based on existing code)
- `--cleanup` flag (remove ratified staged originals from `.unslop/exuded/`)

**Check for `--cleanup` flag:** If present, skip to **Cleanup** section below.

**1. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

Verify the unit spec path exists and is a `*.unit.spec.md` file. If not:

> "Exude requires a unit spec (*.unit.spec.md). Got: <path>"

If neither `--propose` nor target file paths are provided:

> "Exude requires target file paths or --propose. Usage: /unslop:exude <unit-spec> <file-1> <file-2> [...]"

**2. Mode detection**

For each target file path, check if the file exists:
- **All files exist:** Post-refactor mode (reconciliation).
- **No files exist:** Pre-refactor mode (planning). Child specs enter `pending` state.
- **Mixed:** Report which exist and which don't. Proceed -- each child spec gets the appropriate state.

**3. Partition proposal (Archaeologist agent -- opus)**

Dispatch an Archaeologist subagent to produce the partition proposal.

**Inputs:**
- The full content of the unit spec
- Target file paths (or `--propose` to let the LLM infer targets from code)
- For post-refactor mode: the content of each existing target file
- For `--propose` mode: file tree of the unit spec's directory

**Output:** A partition proposal mapping each section of the unit spec to a target file.

Present the proposal to the user:

```
Proposed partition of <unit-spec-path>:

  <file-1>.spec.md:
    Goals: [summary]
    Constraints: [summary]
    Non-goals: [summary]

  <file-2>.spec.md:
    Goals: [summary]
    Constraints: [summary]

  Unpartitioned (requires manual assignment):
    - [section]: "[content summary]"
      (Applies to [explanation] -- which spec owns this?)
```

**HARD RULE:** Unpartitioned sections block exude. Every section of the source spec must have a destination. The user must assign every section, explicitly discard sections (which become non-goals or are removed with acknowledgement), or abort.

Wait for user approval or modification. If the user modifies the partition, update accordingly. If the user aborts:

> "Exude aborted. Unit spec unchanged."

**4. Write child specs**

After approval, for each target file:

1. Write a `<file>.spec.md` with:
   - The assigned sections from the partition
   - `intent-approved: false` (always -- granularity changes break locks)
   - `exuded-from:` provenance list:
     ```yaml
     exuded-from:
       - path: <unit-spec-path>
         hash: <unit-spec-content-hash>
     ```
   - `depends-on:` inherited from the unit spec where applicable, plus cross-dependencies between child specs if the partition reveals them

2. For pre-refactor mode targets (file doesn't exist): the child spec enters `pending` state naturally (spec exists, no managed file, no blocking provenance).

**5. DAG update**

Scan all `*.spec.md` files for `depends-on` entries referencing the unit spec path. For each dependent spec, present:

```
Spec `<dependent-path>` depends on `<unit-spec-path>`.
Which child spec(s) should it depend on?

  (a) All children: <file-1>.spec.md, <file-2>.spec.md, ...
  (s) Specific: [let user choose]
  (d) Defer: mark needs-review and decide later
```

For each modified dependent spec, write `needs-review: <hash>` and stage.

**6. Stage original**

Move the unit spec to `.unslop/exuded/<original-filename>`. Create the directory if needed. Do NOT delete.

Report:

```
Exude complete:
  Created: <file-1>.spec.md, <file-2>.spec.md, ...
  Staged original: .unslop/exuded/<unit-spec-filename>
  Updated dependencies: N specs
  [Pre-refactor mode: child specs are pending -- run /unslop:generate for each]
```

---

**Cleanup**

When `--cleanup` is passed:

1. Scan `.unslop/exuded/` for staged spec files.
2. For each staged file, find the successor specs (child specs with `exuded-from:` matching the staged file). Check if ALL successors have `intent-approved` set to a timestamp.
3. If all ratified: delete the staged original. Report: `Cleaned: <filename>`
4. If any not ratified: skip. Report: `Skipped (N of M children pending ratification): <filename>`
5. If no staged files exist: report `No staged originals to clean.`

---

**Model:** `config.models.archaeologist` (default: `opus` for exude -- partitioning is analytical judgment, similar to distill-mode cognitive load).

This command is NOT read-only. It writes child specs, moves the original to staging, and updates dependency references.
