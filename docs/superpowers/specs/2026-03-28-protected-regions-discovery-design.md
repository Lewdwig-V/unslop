# Discovery surfaces for protected-regions and blocked-by -- Design Spec

Follow-on from #82 scope consistency work. Addresses the "unsurfaced skill capabilities" bucket, specifically `protected-regions` and `blocked-by` concrete spec frontmatter fields.

## Problem

`protected-regions` and `blocked-by` are fully implemented (Python parsing, freshness checking, test coverage) and referenced by skills (generation, concrete-spec, takeover, coherence). But no command tells users they exist. Users who need fine-grained regeneration control have no way to discover the capability. They'll over-generate (regenerating code they wanted to protect) or raise bugs that are actually missing knowledge.

## Scope

**Discovery only.** Surface the fields in commands at the moments they're most relevant. No new commands, flags, or workflow changes. Workflow design follows after observing how users interact with the discovered capability.

**This PR (A+C):** Command hints + takeover/distill awareness (high-value discovery moments).

**Follow-on PR (B):** spec-language skill reference docs (destination when commands say "see concrete spec documentation").

## Out of scope

- Workflow for creating/managing these fields (manual spec editing is the current path)
- Multi-target lowering (separate capability)
- Adversarial takeover mode (separate capability)

---

## Changes

### 1. distill.md -- protected-regions detection and awareness (highest value)

**Current state:** The Archaeologist reads the file and produces a candidate spec. The distill command doesn't instruct the Archaeologist to detect tail blocks -- that logic only exists in the takeover skill's Step 0a. Even when invoked via takeover (which loads the skill), the detection results aren't surfaced to the user.

**Prerequisite:** The distill command's Archaeologist steps (1.1-1.5) don't currently instruct tail block detection -- that logic lives in the takeover skill's Step 0a. Add a new Step 1.6 after Step 1.5 (Identify uncertainties, line 78):

```markdown
**Step 1.6: Detect protected regions**

Scan the source file for contiguous tail blocks that serve a different purpose than the implementation above. Common patterns:
- Test suites (e.g., `#[cfg(test)]`, `if __name__ == "__main__"` followed by tests, `describe`/`it` blocks at EOF)
- Main entry guards (`if __name__ == "__main__"`)
- Example code blocks
- Benchmark blocks

For each detected tail block, record: start line, end line (EOF), semantic category (`test-suite`, `entry-point`, `examples`, `benchmarks`), and the marker pattern used to identify it.

If no tail blocks are detected, skip to Phase 2.
```

**Change:** In Phase 3 (Present and Approve), after uncertainties are listed (line 149) and before the approval flow (line 151), add:

```markdown
If the Archaeologist detected contiguous tail blocks serving a different purpose than the implementation above (test suites, entry points, examples, benchmarks), present them explicitly:

> "Protected regions detected:
>
> `<file>`: lines <N>-EOF (`<semantics>` -- `<marker>`)
>
> These blocks will be recorded as `protected-regions` in the concrete spec.
> During future regeneration, the Builder preserves them verbatim -- your
> handwritten code stays untouched. To adjust protection boundaries later,
> edit the `protected-regions` frontmatter in the concrete spec (`<impl-path>`)."

If no tail blocks were detected, skip this message.
```

**Why here:** Takeover/distill is the moment protected regions are *created*. If the user doesn't learn about the capability here, they learn about it never (until something goes wrong).

### 2. harden.md -- protected-regions completeness check

**Current state:** Step 3 (completeness review, lines 52-55) has four bullet points examining spec-code alignment. None mention protected regions.

**Change:** Add a fifth bullet to the Step 3 examination list (after line 55):

```markdown
- Does the managed file have contiguous tail blocks (test suites, main guards, example code) that are NOT declared as `protected-regions` in the concrete spec? If so, future regeneration may overwrite them.
```

This produces suggestions in harden's existing "Consider adding" format:

```
Consider adding: `protected-regions` for the test suite block (lines N-EOF).
Without this declaration, future regeneration may overwrite these tests.
To declare, add `protected-regions` frontmatter to the concrete spec (<impl-path>).
```

**Why here:** Harden is the "is my spec complete?" command. Missing protected-regions is a completeness gap.

### 3. generate.md -- Builder awareness of both fields

**Current state:** Step 5d (Builder dispatch, lines 232-245) describes what the Builder receives but doesn't mention how it should handle `protected-regions` or `blocked-by` from the concrete spec.

**Change:** After the Builder input list (after line 245, the Surgical mode context blocks line), add:

```markdown
   - If the concrete spec has `protected-regions`: the Builder MUST preserve these regions verbatim. Extract the protected region before generation, append it unchanged after generation, and verify the hash matches. See the generation skill's protected-regions protocol.
   - If the concrete spec has `blocked-by` entries: the Builder treats each as an explicit deviation permit. Proceed normally with unblocked constraints. Add code comments at deviation sites: `// blocked-by: <symbol> -- <reason>`.
```

**Why here:** Generate is where both fields are *enforced*. The command should tell the Builder about them explicitly, not rely on the skill being loaded.

### 4. sync.md -- Builder awareness of both fields

**Current state:** Stage B (Builder dispatch, lines 294-302) has the same gap as generate.

**Change:** After the mode selection block (after line 302), add the same two bullet points as generate:

```markdown
   - If the concrete spec has `protected-regions`: the Builder MUST preserve these regions verbatim. Extract the protected region before generation, append it unchanged after generation, and verify the hash matches. See the generation skill's protected-regions protocol.
   - If the concrete spec has `blocked-by` entries: the Builder treats each as an explicit deviation permit. Proceed normally with unblocked constraints. Add code comments at deviation sites: `// blocked-by: <symbol> -- <reason>`.
```

### 5. elicit.md -- protection question in Phase 2

**Current state:** Phase 2 (Constraints, lines 84-92) probes for error handling, concurrency, performance, and input validation. No mention of regeneration protection.

**Change:** Add a fifth probe to the bullet list (after line 92):

```markdown
- Regeneration protection (are there handwritten regions -- tests, entry points, examples -- that must survive regeneration verbatim?)
```

If the user identifies protected regions, note in the spec draft that these should be declared as `protected-regions` in the concrete spec during the generation pipeline. Example elicit response:

```
"Noted: the test suite at lines 150-EOF should be preserved during regeneration.
This will be recorded as a `protected-regions` entry in the concrete spec when
the file is generated. The Builder will preserve it verbatim."
```

### 6. coherence.md -- description update

**Current state:** Line 2 says `description: Check cross-spec coherence across related specs`. The body (Step 5b.1) already handles `blocked-by` display, but the description doesn't mention it.

**Change:** Update the description to:

```markdown
description: Check cross-spec coherence across related specs, including blocked-by constraint tracking
```

### 7. plugin.json -- version bump

Bump `0.46.0` --> `0.47.0`.

---

## Testing strategy

Command-file-only changes (markdown). Run `python -m pytest tests/test_orchestrator.py -q` for regression (405 tests). Verification is read review -- each insertion fits the existing command structure and follows established patterns.

## Follow-on

PR 2: Update the spec-language skill to document `protected-regions` and `blocked-by` frontmatter syntax with examples. This becomes the destination when command messages say "edit the `protected-regions` frontmatter in the concrete spec."
