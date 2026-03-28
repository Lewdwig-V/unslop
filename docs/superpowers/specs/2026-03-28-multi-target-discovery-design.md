# Multi-Target Lowering Discovery

> **For agentic workers:** This is a design spec, not an implementation plan. See the corresponding plan file for task-by-task execution.

**Goal:** Surface the existing multi-target lowering capability in commands so users can discover it through normal workflow.

**Context:** The generation skill, concrete-spec skill, and Python scripts (frontmatter parser, freshness checker, ripple check, graph renderer) all handle the `targets` concrete spec field. Parallel Builder dispatch, atomic merge, and multi-target staleness tracking are fully implemented. But no command mentions multi-target, so users who never manually read the concrete-spec skill docs have no way to discover the capability.

**Approach:** Discovery-only, same pattern as PR #89 (protected-regions/blocked-by). No new flags, no workflow commands. Concrete spec remains the durable declaration point for `targets` -- no ephemeral CLI flags that would need repeating every run.

---

## Touchpoints

Four commands get discovery hints:

| Command | Change | Purpose |
|---------|--------|---------|
| **generate** | Multi-target Builder hint alongside `protected-regions`/`blocked-by` | Runtime discovery |
| **sync** | Same hint as generate | Runtime discovery |
| **elicit** | Conditional probe in Phase 3 (Dependencies) | Design-time discovery |
| **harden** | Completeness review bullet in Step 3 | Retrofit discovery |

**Not changed:** distill, status, coherence, verify, cover, adversarial, takeover. Status and coherence handle `targets` correctly through the script layer -- their command prose not mentioning it is not hiding anything from users who are actively using those commands. The gap is upstream: users who never create a multi-target concrete spec because they did not know it was possible.

---

## 1. generate/sync: Builder hint

Add a third bullet alongside the existing `protected-regions` and `blocked-by` concrete spec field handling bullets.

**Placement in generate:** After line 247 (the `blocked-by` bullet in Step 5d).
**Placement in sync:** After line 306 (the `blocked-by` bullet in concrete spec field handling).

**Text:**

> If the concrete spec has `targets` (instead of `target-language`): generation dispatches parallel Builders -- one per target. Each Builder receives the same Abstract Spec, `## Strategy`, and `## Type Sketch`, but gets target-specific `## Lowering Notes` and `targets[].notes`. All Builders must succeed for the merge to proceed -- if any fails, all are discarded. See the `unslop/concrete-spec` skill for the full multi-target lowering specification.

This is informational for the Architect/Builder. The generation skill already implements the dispatch. The command acknowledges the field exists, same way it acknowledges `protected-regions` and `blocked-by`.

---

## 2. elicit: Conditional probe in Phase 3

Add a multi-target probe to Phase 3 (Dependencies), after the existing cross-reference and `depends-on` surfacing.

**The probe is conditional, not universal.** The Architect applies judgment about whether the spec's domain is plausibly language-agnostic before asking. A data serialization spec, cryptographic primitive, or shared protocol gets the question. A FastAPI endpoint, React component, or platform-specific integration does not. Universal probes become boilerplate that users learn to dismiss, which is worse than not asking.

**Text:**

> Multi-target lowering (does this spec describe behavior that is plausibly language-agnostic -- a data structure, protocol, algorithm, or shared contract -- where multiple language implementations would derive from the same intent?). If the Architect judges the spec's domain to be language-agnostic, probe:
>
> "Does this spec need to target multiple languages or runtimes? If so, the concrete spec can declare `targets` instead of `target-language`, and generation will dispatch parallel Builders -- one per target -- from the same strategy."
>
> If the user confirms, note for `targets` declaration in the concrete spec. If the user declines or the domain is inherently language-specific (a framework-bound endpoint, a UI component, a platform-specific integration), skip the probe silently.

Parallel to the `protected-regions` probe in Phase 2 -- same pattern of "note for concrete spec declaration" without touching the concrete spec.

---

## 3. harden: Completeness review bullet

Add a multi-target completeness check to Step 3, alongside the existing `protected-regions` completeness check.

**The check only fires when a concrete spec exists.** If there is no concrete spec, the user has not made any lowering decisions to review.

**Same false-positive carve-out pattern as protected-regions.** Do not suggest multi-target for specs that are inherently single-language (framework-bound, platform-specific). Only suggest when the behavior is plausibly language-agnostic.

**Text:**

> Is the spec's behavior language-agnostic (e.g., a data structure, protocol, algorithm, or shared contract) but the concrete spec targets only one language? If the spec constrains behavior that could be lowered to multiple languages from the same strategy, and the concrete spec uses `target-language` rather than `targets`, flag it: "Consider adding: `targets` in the concrete spec (`<impl-path>`) if this behavior needs to be implemented in multiple languages. Currently targeting only `<target-language>`. See the `unslop/concrete-spec` skill for multi-target syntax."

---

## 4. Version bump

Bump `plugin.json` to **v0.48.0**.

No Python script changes. No new tests -- changes are prose additions to command files. Existing test suite (405 tests) covers the underlying multi-target machinery.

---

## Non-goals

- No `--target` or `--targets` flags on generate/sync. Target declarations belong in the concrete spec (durable), not CLI flags (ephemeral).
- No workflow commands for creating or managing multi-target concrete specs. Discovery first -- watch whether users reach for manual spec editing or ask for a command. That determines whether workflow is worth building.
- No changes to status or coherence command prose. Their scripts already handle `targets` correctly.
- No changes to distill. Distill produces abstract specs, not concrete specs -- multi-target is a lowering decision made after distillation.
