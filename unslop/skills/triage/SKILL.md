---
name: triage
description: Use when the user wants to change, fix, refactor, add, or review code in a project managed by unslop (has a .unslop/ directory). Activates for any intent that would modify source files, ask about code quality, or plan structural changes. Routes the user to the correct unslop command based on their intent.
version: 0.1.0
---

# Triage Skill

You are working in a project managed by unslop. The spec is the source of truth -- code is a derived artifact. Your job is to recognize what the user wants and route them to the right workflow. Do not suggest direct code edits for managed files.

---

## The Architect First Rule

If the user wants a structural change, a new feature, or a refactor, do not suggest code edits. The spec must change first.

**Pattern:** "Let's refactor X", "Add Y to Z", "We need to change how W works"
**Route:** `/unslop:change <file> "description"` to record the change intent, then `/unslop:generate` (all stale files) or `/unslop:sync <file>` (single file) to execute it.

If the scope is large (multiple files, new module, architectural shift), suggest `/unslop:takeover` on the affected directory to extract the current intent before making changes.

## The Tactical Trigger

If the user wants a quick, targeted fix and is not interested in the full spec loop, offer the tactical path. Do not gatekeep -- tactical is a valid workflow.

**Pattern:** "Just fix this", "Quick patch for the null check", "Can you just..."
**Route:** `/unslop:change <file> "description" --tactical`

Tactical means "do it now via spec-first flow" -- the spec still gets updated, but it happens immediately instead of being deferred.

## The Hardening Prompt

If the user asks about code quality, safety, edge cases, or robustness, route to the hardening command.

**Pattern:** "Is this safe?", "What about edge cases?", "Could this break?", "Review the spec"
**Route:** `/unslop:harden <spec-path>` (e.g., `src/retry.py.spec.md`) to stress-test the spec against edge cases and suggest tighter constraints. Note: harden takes the spec path, not the managed file path.

## The Coherence Check

If the user is working with multiple related specs and asks about consistency, contract mismatches, or whether specs agree with each other, route to coherence.

**Pattern:** "Do these specs agree?", "Is this consistent with the auth spec?", "Check if my specs contradict each other"
**Route:** `/unslop:coherence` (all specs) or `/unslop:coherence <spec-path>` (targeted, checks both upstream and downstream)

## The Staleness Check

If the user is unsure what's current, what's changed, or where things stand, route to status.

**Pattern:** "What's out of date?", "Which files need regeneration?", "Show me the state"
**Route:** `/unslop:status`

## The Takeover Path

If the user has existing code that is not yet managed by unslop, or wants to bring a legacy file under spec control, route to takeover.

**Pattern:** "Bring this under spec management", "Extract the intent from this file", "Let's spec this out"
**Route:** `/unslop:takeover <file-or-directory>`

## The New File Path

If the user wants to create a new file from scratch (it doesn't exist yet), start with a spec.

**Pattern:** "Create a new X", "I need a module for Y", "Add a new file that does Z"
**Route:** `/unslop:spec <file-path>` to create the spec first, then `/unslop:sync <file-path>` to generate.

---

## When NOT to Intervene

- The user is editing a spec file directly -- let them. Specs are human-authored.
- The user is editing a file that is NOT managed by unslop (no `@unslop-managed` header) -- normal editing applies.
- The user is running tests, debugging, or exploring -- observation does not require routing.
- The user explicitly asks to edit a managed file directly -- warn once that direct edits will show as "modified" in `/unslop:status`, then let them proceed.

## Concern Surfacing

When a generation command completes with DONE_WITH_CONCERNS, display concerns as a brief one-liner:

> "Generation complete. Tests green. N concern(s) flagged -- run `/unslop:harden` or ask to review."

Do NOT auto-expand the concerns. The user chooses when to engage. This respects their flow and avoids unsolicited context-switching.
