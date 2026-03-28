---
description: Structured spec elicitation -- Socratic dialogue for creating or amending specs
argument-hint: <target-path> [--create] [--force-constitutional]
---

**Parse arguments:** `$ARGUMENTS` contains the target path and an optional `--create` flag. Extract:
- The target path: first token that does not start with `--`. This may be a file path, a directory path (for unit specs), or a spec path directly.
- The `--create` flag, if present (forces creation mode even if a spec exists).
- The `--force-constitutional` flag, if present (skips the interactive constitutional violation prompt and goes directly to override mode).

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If not, stop:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Mode detection**

Derive the spec path from the target path. The target may be a file, a directory (unit spec), or a logical subsystem:
- For files: look for `<file>.spec.md` alongside the file.
- For directories: look for `<dirname>.unit.spec.md` inside the directory.
- If a `.spec.md` exists with `managed-file:` frontmatter pointing to the target, use that spec.

- **Creation mode:** No existing spec found for this target, or `--create` was passed.
- **Amendment mode:** Existing spec with frontmatter exists.

**Distillation review sub-mode:** If the target spec exists and its frontmatter contains `distilled-from:`, switch to distillation review mode. This is a variant of amendment mode with more aggressive interrogation -- the spec was machine-inferred by `/unslop:distill`, not human-authored.

When distillation review mode is detected, replace the standard amendment phases (Step 5) with the following sequence:

**Phase 1: Uncertainty resolution**
For each `uncertain:` entry in the spec frontmatter, present:
> "Distill flagged: [observation]. [question]"

The user resolves each item:
- **Incorporate:** Add the observation as a constraint in the spec body. Remove from `uncertain:`.
- **Non-goal:** Move to `non-goals:` (remove "(inferred)" suffix if present). Remove from `uncertain:`.
- **Dismiss:** Remove from `uncertain:` with no spec change.

**Phase 2: Non-goal ratification**
For each `non-goals:` entry with "(inferred)" suffix:
> "Distill inferred this as a non-goal: [text]. Confirm this is intentional?"

- Confirmed: keep the text, remove "(inferred)" suffix.
- Rejected: remove from `non-goals:`.

**Phase 3: Intent validation**
> "Distill inferred the intent as: [intent text]. Is this what this code *should* do, or just what it happens to do?"

User confirms or rewrites the intent statement.

**Phase 4: Standard amendment phases**
After distillation-specific phases complete, run the standard amendment phases (change scoping, non-goal audit, downstream impact) as normal.

**Rejected alternatives:** During the dialogue, if the user explicitly rejects an approach you proposed, prompt once for a rationale: "Can you say briefly why not? This helps avoid re-proposing it in future sessions." If the user provides a reason, record a `rejected:` entry with title and rationale. If the user declines ("just move on"), do not record. Do not prompt more than once per rejection. Do not record implicit dismissals (user ignores, changes topic).

**Post-distillation review:**
- `uncertain:` entries are cleared from the `.proposed` output.
- `distilled-from:` persists as provenance (do NOT clear it).
- `intent-approved: false` (user still promotes through normal lock cycle).
- Recompute `intent-hash` from the validated intent text.
- **HARD RULE:** Compute `intent-hash` at draft time. Embed it in the `.proposed` file.

**3. Ripple check (invariant -- always runs)**

**HARD RULE:** The ripple check runs regardless of mode. Do not skip it.

If a spec exists, call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ripple-check <spec-path> --root .` (or use MCP `unslop_ripple_check` if available). Store the downstream dependents for use in Phase 5 of amendment mode and for downstream flagging in Step 7.

If creating a new spec, skip the ripple check (nothing depends on a spec that doesn't exist yet).

**4. Creation mode: Socratic spec elicitation**

Run the following dialogue phases in order. Do not skip phases. Do not collapse phases into a single prompt.

**Phase 1: Goals**

> "What should `<target>` do? Describe the observable behavior -- what a caller sees, not how it works internally."

The target may be a file, a directory module (unit spec), or a logical subsystem. Adapt the question accordingly ("What should this module do?" / "What should this subsystem do?").

Push toward behavior language, away from implementation language (per the spec-language skill). If the user describes algorithms or data structures, reframe: "That sounds like a strategy choice. What's the *behavior* a caller would observe?"

**Phase 2: Constraints**

> "What invariants must hold? What can go wrong? What are the boundary conditions?"

Probe specifically for:
- Error handling semantics (propagate? recover? which errors?)
- Concurrency guarantees (thread-safe? reentrant?)
- Performance bounds (if any)
- Input validation rules
- Regeneration protection (are there handwritten regions -- tests, entry points, examples -- that must survive regeneration verbatim? If yes, note for `protected-regions` declaration in the concrete spec). This probe is most relevant when existing code is being brought under management (post-distill or takeover). In pure creation mode, defer unless the user volunteers that handwritten regions will be added later.
- Multi-target lowering (does this spec describe behavior that is plausibly language-agnostic -- a data structure, protocol, algorithm, or shared contract -- where multiple language implementations would derive from the same intent?). If the Architect judges the spec's domain to be language-agnostic, probe:

  > "Does this spec need to target multiple languages or runtimes? If so, the concrete spec can declare `targets` instead of `target-language`, and generation will dispatch parallel Builders -- one per target -- from the same strategy. The decision test: if you change a constraint in the abstract spec, must all language implementations update atomically? If yes, multi-target is appropriate."

  If the user confirms, note for `targets` declaration in the concrete spec. If the user declines or the domain is inherently language-specific (a framework-bound endpoint, a UI component, a platform-specific integration), skip the probe silently.

**Phase 3: Dependencies**

> "What does this [file/unit/subsystem] depend on? What will depend on it?"

Cross-reference against existing specs in the project. Use `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py discover .` (or MCP `unslop_discover`) to show existing managed files. Surface potential `depends-on` relationships.

**Phase 4: Non-goals (inferred)**

Based on the goals gathered in Phase 1, generate 2-5 candidate non-goals. Present each as a yes/no confirmation:

> "Based on [goal X], I'm inferring you're *not* trying to [Y]. Confirm or reject."

Each confirmed non-goal enters the `non-goals:` frontmatter field. Each rejected inference is discarded silently.

If the user volunteers additional non-goals, accept them directly.

**Phase 5: Success criteria**

> "How do you know this is done? What would a test look like?"

These inform the spec's constraints section, not the test suite directly.

**Rejected alternatives:** During the dialogue, if the user explicitly rejects an approach you proposed, prompt once for a rationale: "Can you say briefly why not? This helps avoid re-proposing it in future sessions." If the user provides a reason, record a `rejected:` entry with title and rationale. If the user declines ("just move on"), do not record. Do not prompt more than once per rejection. Do not record implicit dismissals (user ignores, changes topic).

**Phase 6: Draft candidate**

After all phases complete, produce a complete spec file and write it to `<spec-path>.proposed`. The candidate includes:

```yaml
---
intent: >
  [drafted intent statement synthesized from dialogue]
intent-approved: false
intent-hash: [pre-computed SHA-256 of intent text, 12 hex chars]
non-goals:
  - [confirmed non-goal 1]
  - [confirmed non-goal 2]
depends-on:
  - [identified dependency 1]
---
```

Followed by the spec body with sections: `## Purpose`, `## Behavior`, `## Constraints`, `## Error Handling`, `## Dependencies` (as appropriate based on the dialogue).

**HARD RULE:** Compute `intent-hash` at draft time. Do not defer hash computation to the approval step.

Present the candidate to the user for review.

**5. Amendment mode: surgical spec mutation**

**Read rejected alternatives:** Before proposing any changes, read the `rejected:` frontmatter. If you consider proposing something that aligns with a rejected entry, acknowledge the prior decision: "This was previously rejected because [rationale]. Has anything changed?" Do not silently re-propose rejected approaches.

**Phase 1: Context loading**

Read:
- Current abstract spec (`*.spec.md` or `*.unit.spec.md`)
- Current concrete spec (`*.impl.md`) if it exists
- Managed code (single file, or managed files listed in unit spec's `## Files` section)
- Dependency DAG from the ripple check (Step 3)

**Load applicable skills:** Discover and load project-local and user-local skills using three-tier discovery (see generation skill Phase 0d). The Architect reads loaded skills as context for the Socratic dialogue. If the user's request aligns with or contradicts a skill pattern, surface it: "This aligns with project skill 'typed-error-handling' which recommends Result types" or "This would deviate from project skill 'kafka-patterns'."

**Phase 2: Intent verification**

Read `intent`, `intent-approved`, and `intent-hash` from the current spec frontmatter.

If intent is locked (intent-approved is a timestamp AND intent-hash validates):

> "This spec has approved intent: [intent text]. Your proposed change would modify sections [list sections]. Confirm you want to reopen intent review."

Wait for explicit confirmation. If denied, stop.

On confirmation, the candidate output will set `intent-approved: false` and recompute `intent-hash`.

**Phase 3: Change scoping**

> "What exactly should change? What should stay invariant?"

Ground the discussion in specific spec sections. For each section the user wants to change, ask for the desired behavior in behavior language.

Probe for ripple effects using the downstream dependents from Step 3:

> "This change to [section A] might affect [downstream spec B] because [dependency relationship]. Should B change too?"

**Phase 4: Non-goal audit**

Read existing `non-goals:` from current spec.

If the proposed change conflicts with an existing non-goal:

> "Your change implies [X], but non-goal [Y] explicitly excludes this. Which takes priority?"

Ask if the change adds, removes, or modifies any non-goals.

**Phase 5: Downstream impact**

For each downstream dependent surfaced by the ripple check:

> "Spec `<dep-spec>` depends on this spec. Does your change affect its behavior?"

- User confirms: note for downstream flagging in Step 7.
- User denies: acknowledged and recorded.

**Rejected alternatives:** During the dialogue, if the user explicitly rejects an approach you proposed, prompt once for a rationale: "Can you say briefly why not? This helps avoid re-proposing it in future sessions." If the user provides a reason, record a `rejected:` entry with title and rationale. If the user declines ("just move on"), do not record. Do not prompt more than once per rejection. Do not record implicit dismissals (user ignores, changes topic).

**Phase 6: Draft candidate**

Produce the complete proposed spec state (not a diff format -- the full file as it would look after the change) and write to `<spec-path>.proposed`.

Update the frontmatter:
- `intent`: revised if the change alters the module's purpose
- `intent-approved: false` (always -- forces re-lock)
- `intent-hash`: pre-computed from new intent text
- `non-goals:`: updated if changed
- `needs-review`: removed if it was present (this spec is being actively reviewed now)
- `review-acknowledged`: removed if it was present

**HARD RULE:** Compute `intent-hash` at draft time. Embed it in the `.proposed` file.

Present the candidate to the user for review.

**6. Approval flow**

After presenting the candidate:

**(a) Approve:**

**Constitutional violation check:** Before finalizing the spec, check if a verification result exists at `.unslop/verification/<managed-file-hash>.json` (hash the managed file path, SHA-256 truncated to 12 hex). If it exists, first check freshness: compare the result's `source_hash` and `spec_hash` against the current file/spec hashes. If either hash doesn't match, the result is stale -- skip the constitutional gate (the violations may no longer apply after the spec/code changed). If the result is fresh and contains non-empty `constitutional_violations`:

⚠ Generated code violates N principle(s):
  - [principle]: [violation] at [location]

Ratifying this spec would approve code that violates project principles.
Options:
  (f) Fix -- re-generate to produce compliant code
  (o) Override -- requires rationale for each violation
  (s) Skip -- leave intent-approved as false

**Option (f):** Rename the proposed file to the canonical spec path (so generate has the updated spec to work from), but leave `intent-approved: false`. Tell the user to re-run `/unslop:generate` to produce compliant code, then re-run `/unslop:elicit` to ratify.

**Option (o):** Prompt for a rationale. **HARD RULE:** Rationale is required -- empty rationale is rejected. Write a `constitutional-overrides:` frontmatter entry (principle, rationale, current timestamp) into the proposed spec. Write a `## Changelog` prose entry. Then proceed with the rename.

**Option (s):** Do not rename. Spec remains as `.spec.md.proposed`.

If `--force-constitutional` was passed as an argument, skip the (f)/(o)/(s) selection menu and go directly to option (o). The rationale prompt still appears -- `--force-constitutional` skips only the menu, not the rationale requirement.

If no verification result exists, or if `constitutional_violations` is empty, proceed normally.

Rename `<spec-path>.proposed` to `<spec-path>`. The pre-computed `intent-hash` is already embedded. `intent-approved` is `false` -- the user promotes intent through the normal lock cycle.

**Changelog entry:** After writing the spec, append both:
1. A `spec-changelog:` frontmatter entry with the new intent-hash, current timestamp, the appropriate operation (`elicit-create`, `elicit-amend`, or `elicit-distill-review`), and the prior intent-hash (null for creation, previous hash for amendment).
2. A `## Changelog` prose entry at the bottom of the spec body (reverse chronological -- prepend to the section) describing what changed and why.

Stage the spec: `git add <spec-path>`.

**(b) Revise:**

User requests specific changes. Regenerate the `.proposed` sidecar with updated content and a new pre-computed hash. Re-present for review.

**(c) Reject:**

Delete the `.proposed` sidecar. No spec changes.

**7. Downstream flagging**

After approval, for each downstream dependent identified in Step 3:

**Depth 1 (direct dependents):**

> "Spec `<dep>` depends on the spec you just changed. Run elicit on it now? (y/n)"

If yes: queue for an immediate elicit pass (amendment mode) after this one completes.
If no: write `needs-review: <intent-hash of changed spec>` into the dependent spec's frontmatter.

**Depth 2+ (transitive dependents):**

Write `needs-review: <intent-hash of changed spec>` into each transitive dependent's frontmatter. Report:

> "N transitive dependents flagged for review: [list]. They will soft-block on next generate/sync."

**8. Post-elicitation summary**

```
Elicitation complete:
  Spec written: <spec-path>
  Non-goals: N confirmed
  Dependencies: N declared
  Downstream: N flagged for review, M queued for immediate elicit

Next: /unslop:generate or /unslop:sync <file> to generate code from this spec.
```
