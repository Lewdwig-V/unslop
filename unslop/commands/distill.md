---
description: Infer a spec from existing code -- Archaeologist reads code and produces a candidate spec
argument-hint: <target-path>
---

**Parse arguments:** `$ARGUMENTS` contains the target path. Extract the first token as the target path (file or directory).

**0. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If not, stop:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the target path exists. If not, stop:

> "Target `<target-path>` does not exist."

Check that the target is NOT already managed. Read the first line of the target file (or, for a directory, check each source file in the directory) for the `@unslop-managed` header. If any managed file is found, stop:

> "This file is already under spec management. Use `/unslop:change` to amend the spec or `/unslop:weed` to reconcile drift."

**HARD RULE:** Distill does not generate code. It produces a spec only. Do not write, modify, or propose any source code changes during this command.

**1. Mode detection**

Derive the spec path from the target path:

- **File mode:** target is a single file. Spec path will be `<file>.spec.md`. Produce a single file spec.
- **Directory mode:** target is a directory. Spec path will be `<dirname>.unit.spec.md` inside the directory. Produce a unit spec covering all files in the directory.

**Phase 1: Read and Infer (Archaeologist)**

**Model note:** Distillation is judgment work -- inferring intent from code under uncertainty. The Archaeologist's distill mode recommends opus. If running as a subagent, dispatch with `model: "opus"` (or `config.models.archaeologist_distill` if configured). See the adversarial skill's model table.

The Archaeologist reads the existing code without any prior knowledge of its intent. Infer everything from what is actually present.

**Step 1.1: Read the source**

- **File mode:** Read the target file in full.
- **Directory mode:** Read all source files in the directory (recursively, excluding hidden files, `__pycache__`, and build artifacts). List the files read.

**Step 1.2: Read existing tests**

Search for test files associated with the target:
- For a file `src/foo.py`, look for `tests/test_foo.py`, `src/test_foo.py`, `src/foo_test.py`, or any file that imports the target module.
- For a directory, look for a parallel `tests/` directory or test files within the directory.

If tests are found, read them. Tests reveal:
- Expected inputs and outputs
- Edge cases the author cared about
- Error conditions that were anticipated
- Behaviour contracts enforced at the boundary

If no tests are found, note this as an uncertainty.

**Step 1.3: Infer intent**

From the code and tests, synthesize:

1. **What it does:** The primary observable behaviour -- what a caller sees, not internal implementation details.
2. **Contracts:** Pre-conditions (what callers must supply), post-conditions (what callers can rely on), and invariants (what must always hold).
3. **Error handling:** Which errors are caught, which are propagated, which are transformed, and which are silently swallowed. Note any silent swallowing as a concern.
4. **Dependencies:** External modules, services, files, or environment variables the code reads from or writes to at runtime.

**Step 1.4: Infer non-goals**

Based on what the code does NOT do (despite plausibly being in scope), generate 2-5 candidate non-goals. Each non-goal must end with the suffix `(inferred)`. Examples:
- "Does not validate input encoding -- callers must supply UTF-8 (inferred)"
- "Does not cache results across calls (inferred)"

**Step 1.5: Identify uncertainties**

List things that look like bugs, shortcuts, or accidental behaviour. Each uncertainty has:
- `title`: short label
- `observation`: what the code actually does
- `question`: what the intent might have been

Examples of uncertainty triggers: unreachable branches, swallowed exceptions, hardcoded magic values, TODOs, asymmetric error handling, undocumented side effects, behaviour that contradicts the function name.

**Step 1.6: Detect protected regions**

Scan the source file for contiguous tail blocks that serve a different purpose than the implementation above. Common patterns:
- Test suites (e.g., `#[cfg(test)]`, `if __name__ == "__main__"` followed by tests, `describe`/`it` blocks at EOF)
- Main entry guards (`if __name__ == "__main__"`)
- Example code blocks
- Benchmark blocks

For each detected tail block, record: start line, end line (EOF), semantic category (`test-suite`, `entry-point`, `examples`, `benchmarks`), and the marker pattern used to identify it.

If no tail blocks are detected, skip to Phase 2.

**Phase 2: Produce Candidate Spec**

Compute the `intent-hash`: take the inferred intent text (the folded scalar value), compute its SHA-256, and use the first 12 hex characters. Embed this in the frontmatter before writing the file.

**HARD RULE:** Compute `intent-hash` at draft time from the intent text. Do not defer hash computation to the approval step.

Compute `distilled-from` entries: for each source file read, record its path and compute its SHA-256 hash at the time of distillation. This snapshot anchors the spec to a specific version of the code.

Write the candidate spec to `<spec-path>.proposed` with the following structure:

```yaml
---
intent: >
  [synthesized intent statement -- what the code does, in behavior language]
intent-approved: false
intent-hash: [pre-computed SHA-256 of intent text, first 12 hex chars]
distilled-from:
  - path: <source-file-path>
    hash: <sha256-of-source-file-at-distillation-time, first 12 hex chars>
non-goals:
  - [inferred non-goal 1 (inferred)]
  - [inferred non-goal 2 (inferred)]
uncertain:
  - title: [short label]
    observation: [what the code actually does]
    question: [what the intent might have been]
depends-on:
  - [inferred dependency 1]
---
```

Followed by the spec body with sections as applicable:

```markdown
## Purpose

[Paragraph describing what this file/unit exists to accomplish. Written in behavior language -- what callers observe, not how it works.]

## Behavior

[Enumerated list of observable behaviors. Each bullet is a contract a caller can rely on.]

## Constraints

[Invariants, pre-conditions, post-conditions, input validation rules, concurrency guarantees, or performance bounds inferred from the code.]

## Error Handling

[Which errors are caught vs propagated. Which are transformed. Any silent failures that were observed (flag these explicitly).]

## Dependencies

[Runtime dependencies: modules, services, environment variables, files. Derived from imports and usage, not just import statements.]
```

Omit sections that have no content to contribute. A unit spec may include a `## Files` section listing the managed files in the directory.

**Phase 3: Present and Approve**

Present the candidate spec to the user:

> "Candidate spec written to `<spec-path>.proposed`. Here is what was inferred:"

Display the full candidate spec content.

If there are uncertainties, call them out explicitly:

> "The following uncertainties were found during analysis. Review and resolve them before approving the spec:"
>
> [list each uncertainty with title, observation, and question]

Then offer the approval flow:

> **(a) Approve** -- rename `.proposed` to `<spec-path>`, stage with `git add <spec-path>`
> **(b) Revise** -- describe what to change; the candidate will be regenerated and re-presented
> **(c) Reject** -- delete `.proposed`, no spec is written

**Approval:**

Rename `<spec-path>.proposed` to `<spec-path>`. The pre-computed `intent-hash` is already embedded. `intent-approved` remains `false` -- intent is promoted through the normal lock cycle via `/unslop:elicit`.

**Changelog entry:** After writing the spec, append both:
1. A `spec-changelog:` frontmatter entry with the new intent-hash, current timestamp, operation `distill`, and the prior intent-hash (null for initial distillation).
2. A `## Changelog` prose entry at the bottom of the spec body (reverse chronological -- prepend to the section) describing what changed and why.

Stage the spec: `git add <spec-path>`.

**Revise:**

User describes what to change. Regenerate the `.proposed` sidecar with updated content and a newly pre-computed `intent-hash`. Re-present for review.

**Reject:**

Delete the `.proposed` sidecar. No spec is written.

**Post-distill summary**

```
Distillation complete:
  Spec written: <spec-path>
  Source files read: N
  Non-goals inferred: N
  Uncertainties flagged: N
  Dependencies identified: N

Next steps:
  /unslop:elicit <target>   -- review and lock intent through Socratic dialogue
  /unslop:takeover <target> -- full pipeline: spec lock, concrete spec, code generation
```

If there were uncertainties, add:

> "Resolve the flagged uncertainties before running `/unslop:takeover`. Unresolved ambiguities in the spec will propagate into generated code."
