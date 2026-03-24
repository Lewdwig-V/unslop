---
name: triage
description: Use when the user wants to change, fix, refactor, add, or review code in a project managed by unslop (has a .unslop/ directory). Activates for any intent that would modify source files, ask about code quality, or plan structural changes. Routes the user to the correct unslop command based on their intent.
version: 0.2.0
---

# Triage Skill

You are working in a project managed by unslop. The spec is the source of truth -- code is a derived artifact. Your job is to recognize what the user wants and route them to the right workflow. Do not suggest direct code edits for managed files.

---

## The Architect First Rule

If the user wants a structural change, a new feature, or a refactor, do not suggest code edits. The spec must change first.

**Pattern:** "Let's refactor X", "Add Y to Z", "We need to change how W works"
**Route:** `/unslop:change <file> "description"` to record the change intent, then:
- `/unslop:sync <file>` -- regenerate a single file
- `/unslop:sync <file> --deep` -- regenerate the file and its entire downstream blast radius
- `/unslop:sync --stale-only` -- regenerate all stale files across the project in batched topological order
- `/unslop:generate` -- regenerate all stale files (legacy, equivalent to `--stale-only`)

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

## The Implementation Strategy Prompt

If the user wants to understand, document, or preserve the implementation strategy (algorithm, patterns, data flow) of a managed file, route to concrete spec promotion.

**Pattern:** "Document the implementation strategy", "Promote the concrete spec", "I want to preserve how this works", "Make the implementation strategy permanent", "Show me the algorithm"
**Route:** `/unslop:promote <spec-path>` to generate or promote a permanent Concrete Spec (`*.impl.md`) alongside the Abstract Spec. Equivalent to `/unslop:harden <spec-path> --promote`.

## The Language Switch Prompt

If the user wants to port a managed file to a different language while keeping the same behavior, this is a lowering operation through the concrete spec layer.

**Pattern:** "Port this to Go", "Rewrite in TypeScript", "Switch from Python to Rust"
**Route:** Explain the lowering workflow: the Abstract Spec stays unchanged, only the Concrete Spec's `target-language` and `## Lowering Notes` change, then regenerate. Start with `/unslop:harden <spec-path> --promote` to capture the current strategy, then update the concrete spec's target language.

## The Coherence Check

If the user is working with multiple related specs and asks about consistency, contract mismatches, or whether specs agree with each other, route to coherence.

**Pattern:** "Do these specs agree?", "Is this consistent with the auth spec?", "Check if my specs contradict each other"
**Route:** `/unslop:coherence` (all specs) or `/unslop:coherence <spec-path>` (targeted, checks both upstream and downstream)

## The Adversarial Quality Check

If the user wants to validate test quality, run mutation tests, or generate black-box tests against a spec, route to adversarial.

**Pattern:** "Run mutation tests", "Generate black-box tests", "Are my tests any good?", "Validate test coverage", "Adversarial check"
**Route:** `/unslop:adversarial <spec-path>` to run the adversarial quality pipeline -- mutation testing, black-box test generation, and test quality validation against the spec's constraints.

## The Staleness Check

If the user is unsure what's current, what's changed, or where things stand, route to status. If they want to see the dependency graph, or specifically the stale subgraph, route to graph.

**Pattern:** "What's out of date?", "Which files need regeneration?", "Show me the state"
**Route:** `/unslop:status`

**Pattern:** "Show me the dependency graph", "What depends on what?"
**Route:** `/unslop:graph`

**Pattern:** "Show me what's stale and why", "Why is X ghost-stale?", "What caused this staleness?"
**Route:** `/unslop:graph --stale-only` -- renders the causal subgraph including upstream concrete providers that triggered the staleness, even if those providers have no managed output of their own. Context providers are styled distinctly so the user can trace the infection path from cause to symptom.

## The Bulk Sync

If the user wants to sync everything that's stale across the project, route to bulk sync. This batches all stale files into worktree groups that respect topological order.

**Pattern:** "Sync everything", "Regenerate all stale files", "Bring everything up to date", "Batch sync"
**Route:** `/unslop:sync --stale-only` -- scans the entire project, groups stale files into dependency-aware batches, and processes them sequentially. No file path needed.

**Pattern:** "What would a full sync look like?", "Show me the sync plan", "Dry run a bulk sync"
**Route:** `/unslop:sync --stale-only --dry-run` -- shows the batched plan without regenerating anything.

If the user wants to sync a single file and its full downstream blast radius (not the whole project), use deep sync instead.

**Pattern:** "Sync this file and everything downstream", "Deep sync X"
**Route:** `/unslop:sync <file> --deep`

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

## Plugin Feedback

When a workflow ends with a result that suggests a **plugin-level improvement** (not a user code issue), offer to raise it as a GitHub issue. This applies when:

- A convergence loop exhausts iterations due to a skill gap (not a spec gap)
- A command produces a confusing error that could have a better message
- A pipeline step behaves unexpectedly in a way the user didn't cause
- The Builder or Mason makes a systematic mistake that better prompt engineering could prevent

**How to offer:**

> "I noticed [specific issue]. This looks like it could be improved in the unslop plugin itself. Would you like me to raise a GitHub issue?"

If the user agrees, create the issue:

```
gh issue create --repo Lewdwig-V/unslop \
  --title "<concise description>" \
  --body "<structured report: what happened, expected behaviour, reproduction context>"
```

**What NOT to file:** User-side issues (bad specs, missing tests, config problems). Only file when the plugin's skills, commands, or scripts could be improved to handle the situation better.

**Do not file automatically.** Always ask first. The user decides what reaches the maintainer.
