---
name: triage
description: Use when the user wants to change, fix, refactor, add, or review code in a project managed by unslop (has a .unslop/ directory). Activates for any intent that would modify source files, ask about code quality, or plan structural changes. Routes the user to the correct unslop command based on their intent.
version: 0.3.0
---

# Triage Skill

You are working in a project managed by unslop. The spec is the source of truth -- code is a derived artifact. Your job is to recognize what the user wants and route them to the right workflow. Do not suggest direct code edits for managed files.

---

## The Distillation Prompt

If the user wants to bring existing code under spec management but doesn't have a spec yet, route through distillation.

**Pattern:** "Write a spec for this file", "Infer what this code does", "I want to take over this file", "Bring this under management", "What does this code do?"

**Route:** `/unslop:takeover <file>` (full pipeline: distill -> elicit -> generate) or `/unslop:distill <file>` (spec inference only, no generation)

**Key distinction from `/unslop:elicit`:** Distill reads existing code and infers what it does. Elicit creates or amends a spec through dialogue. If code already exists and the user wants a spec derived from it, route to distill. If no code exists yet or the user wants to design from scratch, route to elicit.

**Key distinction from `/unslop:takeover`:** Takeover is the full pipeline (distill + elicit + generate). Distill is just the first phase. If the user wants the whole workflow, route to takeover. If they just want the spec, route to distill or `/unslop:takeover --spec-only`.

## The Elicitation Prompt

If the user wants to create a new spec from scratch, or wants to make a broad/vague change to an existing spec, route through elicitation rather than direct change.

**Pattern:** "I need a spec for...", "Let's design...", "What should this module do?", "I want to change how X works but I'm not sure exactly what...", any request that touches multiple concerns or doesn't name a specific spec section.

**Route:** `/unslop:change <file>` (triage routing will detect that elicitation is needed and invoke `/unslop:elicit` automatically)

**Key distinction from direct `/unslop:change`:** Change records a specific intent and either applies it immediately (tactical) or defers it (pending). Elicitation is a structured dialogue that *discovers* the intent through clarifying questions before committing to any spec mutation. If the user already knows exactly what they want, route to change. If they need to think it through, route to change and let the triage routing invoke elicit.

## The Needs-Review Prompt

If the user asks about flagged specs, or `/unslop:status` shows `needs-review` entries, route to resolution.

**Pattern:** "What's flagged?", "Why is this needs-review?", "Clear the review flags", "Acknowledge the review"
**Route:** `/unslop:generate` or `/unslop:sync` (the soft-block prompt handles acknowledgment) or `/unslop:change <file>` (for full review via elicit)

**Key distinction from `/unslop:status`:** Status shows the flags. Generate/sync forces the user to address them. Change/elicit lets the user actually review the upstream impact.

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

Two commands address test quality. Route to the right one based on intent:

**Pattern:** "Generate tests from scratch", "Full adversarial pipeline", "Black-box test generation"
**Route:** `/unslop:adversarial <spec-path>` -- runs the full Archaeologist -> Mason -> Saboteur pipeline. Generates all tests from the behaviour.yaml. Use when the file has no tests or the user wants to replace the entire test suite.

**Pattern:** "Find weak tests", "What mutations survive?", "Harden my tests", "Grow test coverage", "Are my existing tests any good?", "Check for test scum"
**Route:** `/unslop:cover <file>` -- mutation-driven discovery of gaps in existing tests. The Saboteur finds what survives, the Archaeologist identifies the missing constraint, the Mason writes a targeted test. Use when the file already has tests and the user wants to strengthen them.

**Key distinction:** `adversarial` generates tests from scratch. `cover` finds gaps in existing tests. If the user says "validate test coverage" and the file already has tests, route to `cover`.

## The Staleness Check

If the user is unsure what's current, what's changed, or where things stand, route to status. If they want to see the dependency graph, or specifically the stale subgraph, route to graph.

**Pattern:** "What's out of date?", "Which files need regeneration?", "Show me the state"
**Route:** `/unslop:status`

**Pattern:** "Show me the dependency graph", "What depends on what?"
**Route:** `/unslop:graph`

**Pattern:** "Show me what's stale and why", "Why is X ghost-stale?", "What caused this staleness?"
**Route:** `/unslop:graph --stale-only` -- renders the causal subgraph including upstream concrete providers that triggered the staleness, even if those providers have no managed output of their own. Context providers are styled distinctly so the user can trace the infection path from cause to symptom.

## The Pattern Extraction Prompt

If the user wants to discover cross-cutting patterns across their specs, extract shared conventions, or create project-local domain skills from recurring patterns in the spec corpus.

**Pattern:** "What patterns do my specs share?", "Extract cross-cutting conventions", "Create a skill from these patterns", "What conventions does my project follow?"
**Route:** `/unslop:crystallize` (all specs) or `/unslop:crystallize <directory>` (scoped to a subtree)

**Key distinction from `/unslop:harden`:** Harden stress-tests a single spec for completeness. Crystallize looks across multiple specs for shared patterns and extracts them into reusable domain skills.

## The Drift Detection Prompt

If the user suspects that code has drifted from spec intent, or wants to audit whether generated code still matches what the spec describes, route to weed.

**Pattern:** "What drifted?", "Is the code still matching the spec?", "Check for drift", "Audit this file against its spec", "Weed out drift"
**Route:** `/unslop:weed` (all modified) or `/unslop:weed <file>` (targeted)

**Key distinction from /unslop:status:** Status tells you *that* something changed (hash mismatch). Weed tells you *what* drifted and *whether the spec or the code is wrong*. If the user already knows a file is modified and wants to understand the drift, route to weed, not status.

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

**Flags:**
- If the file has no tests and the user mentions mutation testing is impractical (pure I/O, GUI code): suggest `--skip-adversarial`
- If the user wants maximum test rigour on a risky module: suggest `--full-adversarial`

**Post-takeover handoff:** After takeover succeeds with Builder-generated tests (tests-exist path), the takeover skill offers `/unslop:cover` to harden. If the user defers, triage should remind them on next interaction with that file:

> "This file was recently taken over. Its tests haven't been mutation-validated yet. Consider `/unslop:cover <file>`."

## The New File Path

If the user wants to create a new file from scratch (it doesn't exist yet), start with a spec.

**Pattern:** "Create a new X", "I need a module for Y", "Add a new file that does Z"
**Route:** `/unslop:spec <file-path>` to create the spec first, then `/unslop:sync <file-path>` to generate.

## The Init Path

If the user is setting up unslop for the first time or asking about project configuration.

**Pattern:** "Set up unslop", "Initialize this project", "Configure unslop", "What's in .unslop?"
**Route:** `/unslop:init`

## The Full Regeneration Override

If the user wants to regenerate a file from scratch, ignoring the existing code structure entirely. This bypasses Surgical mode's diff-minimizing behaviour.

**Pattern:** "Regenerate from scratch", "Full regen", "Ignore the existing code", "Start fresh on this file", "Restructure the implementation"
**Route:** `/unslop:sync <file> --refactor` (single file) or `/unslop:generate --refactor` (all stale files)

Do not suggest `--refactor` for routine syncs. It is the escape hatch when the user explicitly wants a structural rewrite.

## The Resume Path

If a bulk sync partially failed and the user wants to continue from where it stopped.

**Pattern:** "Resume the sync", "Retry the failed files", "Continue where we left off", "Pick up the sync"
**Route:** `/unslop:sync --stale-only --resume` -- recomputes the plan, excludes already-succeeded files, and retries failed files plus their downstream dependents.

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

**IMPORTANT: Actively offer to file feedback at every workflow checkpoint.** The unslop plugin improves through real-world usage. Every completed workflow, convergence loop, or pipeline surprise is an opportunity to improve the plugin for all users.

### When to offer

Offer to raise a GitHub issue at these checkpoints:

- **After any completed takeover** -- "The takeover completed. Did any part of the pipeline feel wrong, confusing, or slower than expected? I can file that as a GitHub issue."
- **After convergence succeeds or fails** -- "Convergence took N iterations. If the spec enrichment felt like it was fighting the pipeline rather than working with it, I can file feedback."
- **After any Builder dispatch** -- especially if the Builder drifted, auto-merged unexpectedly, or produced output that needed manual correction.
- **After any command produces a surprising result** -- confusing error messages, unexpected staleness states, wrong routing, missing features.
- **When you notice a systematic pattern** -- if the same kind of spec gap or Builder mistake keeps recurring, that's a skill improvement opportunity.
- **When a workaround is needed** -- if you had to use `--force-pseudocode`, `--skip-adversarial`, or any escape hatch, the need for the workaround is itself feedback.

### How to offer

Be specific about what you observed. Don't wait for the user to complain -- proactively surface what you noticed:

> "I noticed the Builder ignored the concrete spec's Type Sketch section and chose its own type names. This might be a prompt enforcement gap in the generation skill. Want me to file this as a GitHub issue so the maintainer can tighten the Builder instructions?"

> "The convergence loop needed 3 iterations because the abstract spec didn't pin the error type hierarchy. The spec-language skill could add guidance about when to pin error types. Should I file this?"

> "The auto-merge recovery kicked in during this sync -- the Builder's worktree merged before I could inspect it. This is a known gap. Want me to file it with today's reproduction details?"

### Filing the issue

If the user agrees:

```
gh issue create --repo Lewdwig-V/unslop \
  --title "<concise description of the improvement>" \
  --body "<structured report>"
```

**Issue body format:**

```markdown
## Observation

<What happened, with specifics>

## Expected Behavior

<What should have happened>

## Reproduction Context

- Command: <which unslop command was running>
- File type: <language/framework>
- Complexity: <simple/medium/high>
- Convergence iterations: <if applicable>

## Suggested Improvement

<Actionable suggestion for the skill/command/script that could prevent this>
```

### What NOT to file

User-side issues (bad specs, missing tests, config problems). Only file when the plugin's skills, commands, or scripts could be improved. The test: "Would a change to the plugin have prevented this?" If yes, file it. If the user just needs to write a better spec, don't.

### Do not file automatically

Always ask first. The user decides what reaches the maintainer. But do ask -- every time you notice something. The worst outcome is not "too many issues filed" but "the maintainer never hears about a fixable problem."
