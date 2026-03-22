# Spec-Driven Development Tools: Landscape Analysis

> Comparative analysis of Superpowers, GitHub Spec Kit, and Tessl — three notable spec-driven development tools — and what unslop can learn from each. Note: unslop builds on Superpowers (it is a dependency, not a competitor); the comparison here is about methodology concepts worth adopting.

---

## Overview

Three notable tools beyond CodeSpeak occupy the spec-driven development space, each with a distinct philosophy. These were selected because they represent the three main architectural approaches (skills-based methodology, constitutional governance, and spec-as-source):

| Tool | Philosophy | Primary Artifact | GitHub Stars |
|---|---|---|---|
| **Superpowers** | Senior-engineer methodology enforcement | Skills (methodology docs) | ~3K |
| **GitHub Spec Kit** | Constitutional governance | Constitution + Specs | ~2K (GitHub project, covered by Microsoft DevDiv blog) |
| **Tessl** | Spec-as-source | Spec files (`.spec.md`) | ~55 |

---

## 1. Superpowers Plugin (Claude Code)

**Repo:** [github.com/obra/superpowers](https://github.com/obra/superpowers)
**Author:** Jesse Vincent / Prime Radiant
**License:** MIT

### Core Workflow

Seven-phase pipeline: **Brainstorm → Spec → Plan → TDD → Subagent Dev → Review → Finalize**. Skills activate automatically via natural language intent recognition. Legacy slash commands still exist (`/brainstorm`, `/write-plan`, `/execute-plan`) but are deprecated in favor of intent-based skill activation.

### Architecture

- **Skills as structured Markdown documents** that capture complete methodologies. Tested, shared, and composed like code.
- **Fresh subagent per task** — each implementation task spawns a clean-slate subagent receiving only the task spec and relevant code context. Prevents context drift during long autonomous sessions.
- **Two-stage review gate** — between tasks, checks (1) spec compliance, then (2) code quality. Critical issues block progress.
- **Enforced TDD** — RED-GREEN-REFACTOR is non-negotiable. Code written before a failing test exists gets deleted.
- **Persuasion principles** embedded in skill text (authority, commitment, social proof) to ensure agents actually follow instructions.

### Extension System

- Community skills: [superpowers-skills](https://github.com/obra/superpowers-skills)
- Experimental skills: [superpowers-lab](https://github.com/obra/superpowers-lab)
- Marketplace: [superpowers-marketplace](https://github.com/obra/superpowers-marketplace)
- Works across Claude Code, Cursor, Codex, OpenCode, Gemini CLI.

### Relevance to unslop

| Superpowers Concept | unslop Equivalent | Gap/Opportunity |
|---|---|---|
| Fresh subagent per task | Generation runs in controlling agent context | **Low priority** — unslop's spec isolation achieves similar purity without subagent overhead |
| Two-stage review gate | Convergence loop (test-based) | **Already stronger when spec is unambiguous** — unslop's loop is automated; Superpowers requires manual review. However, the loop does not catch spec-level ambiguity (see Gap 1, now addressed by quality gates in v0.3.0) |
| Enforced TDD (deletes pre-test code) | Tests required for convergence | **Consider adopting** — explicit rejection of code-before-test would strengthen discipline |
| Skills as testable documents | Skills exist but aren't tested | **Medium priority** — a TDD approach to skill authoring could improve skill quality |
| Persuasion principles in prompts | Standard instructional language | **Worth experimenting** — could improve model compliance with generation constraints |
| Intent-based skill activation | Explicit command invocation | **Low priority** — explicit commands are clearer for a spec-driven workflow |

---

## 2. GitHub Spec Kit

**Repo:** [github.com/github/spec-kit](https://github.com/github/spec-kit)
**Backed by:** GitHub (a Microsoft subsidiary; covered by Microsoft Developer Blog)
**License:** Open source

### Core Workflow

Sequential slash commands: `/speckit.constitution` → `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.analyze` → `/speckit.implement`. The final step executes `tasks.md` and builds the feature. Human drives each phase transition.

### Architecture

- **Constitution as immutable governance** — `.specify/memory/constitution.md` contains architectural principles that act as guardrails. Enforced at every stage via a Constitution Check gate.
- **Memory bank** — persistent context documents (rules, product descriptions, codebase descriptions) under `.specify/memory/`. Provides consistent context across sessions.
- **Markdown-native** — all artifacts are plain Markdown, version-controlled alongside code.
- **No subagent system** — the human drives each sequential phase.

### Relevance to unslop

| Spec Kit Concept | unslop Equivalent | Gap/Opportunity |
|---|---|---|
| Constitution (immutable principles) | `config.md` (project-level settings) | **High value** — a constitution-like document defining spec-writing principles and generation constraints would reduce ambiguity across specs |
| Memory bank (persistent context) | Alignment summary + session hooks | **Already comparable** — unslop's approach is lighter but serves the same purpose |
| Sequential decomposition pipeline | Single-step spec → generate | **Not needed** — unslop's simpler pipeline is appropriate for file-level spec management |
| `/speckit.analyze` (coherence check) | No equivalent | **Medium priority** — cross-spec coherence checking would catch dependency conflicts before generation |
| Phase gate enforcement | Convergence loop | **Different granularity** — Spec Kit gates phases; unslop gates output quality. Both are valid |

### Known Weaknesses (from community feedback)

- Overkill for small tasks — "time suck for little to no perceived value" on small changes
- AI implementation gaps — cases where AI claims spec is implemented but most functionality is missing with zero tests
- Cost: $5–10 per speckit iteration in LLM interaction
- Rigid sequential workflow can feel bureaucratic

---

## 3. Tessl Framework

**Repo:** [github.com/tesslio](https://github.com/tesslio)
**License:** Commercial platform
**Status:** Beta, framework in flux (v0.28.0 last full-framework version; v0.30.0+ undergoing major rewrite)

### Core Workflow

CLI + MCP dual-mode: `tessl init` → `tessl create --spec` → `tessl build` (spec-as-source). Also supports reverse-engineering specs from existing code via `tessl document`.

### Architecture

- **Spec-as-source paradigm** — 1:1 mapping between `.spec.md` files and code files. Generated code is marked `// GENERATED FROM SPEC - DO NOT EDIT`. The spec is the canonical artifact.
- **Tiles architecture** — versioned, agent-agnostic bundles containing skills, documentation, and rules. Function like packages in a package manager.
- **Tiles Registry** — 3,000+ skills and documentation for 10,000+ OSS packages, version-matched to dependencies. Includes Snyk-powered security scores and an eval framework.
- **Three levels of SDD:** Spec-first → Spec-anchored → Spec-as-source. Tessl explicitly targets the spec-as-source level.
- **Agent steering + deterministic logic** — combines prompt-based agent steering with deterministic logic within MCP tools to enforce workflow compliance.

### Relevance to unslop

| Tessl Concept | unslop Equivalent | Gap/Opportunity |
|---|---|---|
| Spec-as-source (1:1 spec↔code) | Same philosophy | **Already aligned** — unslop's `@unslop-managed` header achieves the same ownership model |
| `tessl document` (reverse-engineer specs) | `/unslop:takeover` | **Already comparable** — unslop's approval gate is an advantage over Tessl's auto-generation |
| Tiles Registry (3K+ skills) | No registry | **Long-term opportunity** — domain skills (Gap 8 in roadmap) are the first step toward this |
| Eval framework for skills | No skill evaluation | **Medium priority** — measuring whether skills actually improve output would guide skill development |
| `// GENERATED FROM SPEC - DO NOT EDIT` | `@unslop-managed` header | **Already comparable** — unslop's header additionally includes the spec path, dual content hashes, and a generation timestamp |
| MCP server mode | Hooks + orchestrator | **Deferred** — per roadmap, MCP server adds value only at scale (1000+ files) |
| Version-matched dependency docs | No equivalent | **High value for domain skills** — version-aware framework documentation would significantly improve generation quality |

### Known Weaknesses

- Low adoption (55 GitHub stars)
- Framework in flux — full Framework features paused during major rewrite
- 1:1 spec-to-code limitation — doesn't scale well for cross-cutting concerns
- MCP auto-configuration supports Claude Code, Cursor, Codex, Gemini, Copilot CLI, and Copilot in VSCode — broader than initially assessed

---

## Cross-Cutting Insights for unslop

### Ideas Worth Adopting

1. **Constitution/principles document** (from Spec Kit) — A project-level `principles.md` that defines non-negotiable generation constraints (e.g., "always use dependency injection", "no global state", "errors must be typed"). Referenced by the generation skill on every run. Lower cost than per-spec ambiguity detection, catches a different class of consistency issues.

2. **Skill evaluation framework** (from Tessl) — Measure whether a skill change actually improves output by comparing task outcomes with/without the skill. Would help prioritize domain skill development (Gap 8).

3. **Persuasion-aware prompt engineering** (from Superpowers) — Embedding authority signals, commitment/consistency cues, and social proof in skill text to improve model compliance. Worth A/B testing on the generation skill's "no peeking" and convergence instructions.

4. **Version-matched framework documentation** (from Tessl's Tiles Registry) — When domain skills reference a framework (FastAPI, React, etc.), pin the documentation to the version in the project's dependencies. Prevents the model from generating code for the wrong API version.

---

## Impact on Existing Roadmap

This analysis reinforces the existing gap roadmap priorities and adds two new items:

| Priority | Item | Source |

| **Reinforce** | Domain skills (Gap 8) | Tessl's registry validates the concept at scale |
| **New** | Project principles document | Spec Kit's constitution concept |
| **New** | Skill evaluation framework | Tessl's eval approach |

Re-evaluate:

1. Subagent-per-task (The "No-Peeking" Enforcer)

* Why Re-evaluate? You hit the nail on the head: Isolation. If a single context window sees the Spec, the Code, and the Change Request, it often takes "shortcuts" (hallucinating that the spec is already updated because it saw the intent in the change request).
* The Benefit: A subagent can be spawned with only the Spec and the Target File. It literally cannot "peek" at the change request or other unrelated files. This forces the model to treat the Spec as the absolute source of truth.
* Verdict: Don't skip. Implement a lightweight subagent wrapper for the Generation Skill to ensure strict input isolation.

2. Sequential Phase Gates (The "Review" Checkpoints)

* Why Re-evaluate? While "ceremony" sounds bad, automated validation between steps is vital.
* The Benefit: In your Tactical Flow, the "Heal" step (updating the spec to match the code) is a perfect candidate for a gate. You don't want to calculate hashes if the spec update failed a structural linter.
* Verdict: Keep it "Lite". Instead of heavy manual gates, use Automated Validation Gates (Linting, Spec-Parsing) between the "Spec Update" and "Code Generation" phases.

3. MCP Server Mode (The "Tooling" Bridge)

* Why Re-evaluate? MCP (Model Context Protocol) is becoming the standard for how IDEs (Claude Desktop, Cursor) talk to local tools.
* The Benefit: If unslop is an MCP server, a developer can say to their IDE, "Use the unslop tool to apply a tactical change to this file," and the IDE handles the file reading/writing through your established orchestrator logic.
* Verdict: Defer, but Prep. Stick to the CLI for Milestone C, but ensure your orchestrator functions are structured so they can be exposed as MCP "tools" in Milestone E without a total rewrite.

4. Tiles/Plugin Marketplace (The "Ecosystem")

* Why Re-evaluate? You're correct—this is premature.
* The Benefit: None yet. You need to nail the Domain Skill Infrastructure (how a skill is loaded from a local folder) before worrying about how others share them.
* Verdict: Skip. Focus on the "Local Plugin" architecture first.

---

## The New Priority: The Subagent "Controller"

If we bring back subagents, the orchestrator needs to evolve into a Controller. It doesn't just call a script; it decides which "context packet" to hand to a specialized agent.
Does it make sense to define the "Context Packet" (the restricted set of files/info) that the Generation Subagent receives to ensure the "no-peeking" rule is enforced?

## The Symphony Perspective on Unslop

In a Symphony-like setup, you wouldn't just have an orchestrator.py that calls an LLM. You would have a Lead Developer (The Controller) managing two distinct Sub-agents:

    The Spec-Writer (Persona A):
        Input: retry.py.change.md + Current retry.py.spec.md.
        Output: A proposed diff for the .spec.md.
        Constraint: It cannot see the actual source code. It only cares about requirements.
    The Implementer (Persona B):
        Input: The newly updated retry.py.spec.md + Current retry.py.
        Output: The code patch.
        Constraint: It cannot see the change.md. It only knows what the Spec tells it to do.

Why this re-evaluation changes Milestone D

By adopting this "Symphony-lite" subagent approach, we will solve the Context Bloat problem. Instead of one massive 32k token context window where the model gets confused by conflicting instructions, we use three small 2k-4k windows.

Re-evaluating the "Skips" based on this:

    Subagent-per-task: Now a Must-Have. It’s the only way to enforce the "Spec-as-Source" integrity.
    Sequential Phase Gates: These become the Hand-offs. The "Lead Developer" agent verifies the Spec-Writer's output before passing it to the Implementer.

The "No-Peeking" Implementation
To make this work, the orchestrator needs a Context Sandboxing utility. When it calls the Implementer subagent, it must physically (or via prompt-stripping) prevent any "intent" text from the .change.md from leaking in.

To enforce the "No-Peeking" rule and prevent the model from taking shortcuts, we’ll define a Sandbox Manifest for each sub-agent persona. This ensures the Implementer can't "cheat" by reading the raw change request, and the Spec-Writer stays focused on requirements rather than existing code quirks.
The Sandbox Manifest

| Sub-Agent | Allowed Input (The "Lens") | Output Target | Goal |
|---|---|---|---|
| The Architect (Spec-Writer) | config.json, *.spec.md, *.change.md | *.spec.md (Update) | Translate user intent into a formal requirement change. |
| The Builder (Implementer) | config.json, *.spec.md (Updated) | Managed File (Code) | Generate code that matches the spec exactly. Zero access to .change.md. |
| The Auditor (Validator) | Managed File (New), *.spec.md | Pass/Fail + output-hash | Verify the code satisfies the spec and compute the final hash. |

The "Symphony-lite" Execution Flow

   1. Orchestrator initializes the Architect with the change.md.
   2. Architect proposes a spec diff. Orchestrator presents this to the user for approval.
   3. Once approved, Orchestrator "wipes the slate" and spawns the Builder.
   4. Builder receives only the new spec and the existing code. It has no idea why the spec changed (the "intent" is hidden). It only knows what the spec now requires.
   5. Auditor performs a final pass to ensure no hallucinations occurred and generates the 12-char hash.

Implementation Detail: The "Wall of Silence"
In the Builder's system prompt, we explicitly forbid it from searching for or assuming the existence of .change.md files. The Orchestrator enforces this by physically excluding those files from the Context Packet it sends to the LLM API.
Why this solves Context Bloat
Instead of one massive prompt containing the history of the file, the spec, and the change request, we use three tiny, high-precision prompts. This:

* Reduces Costs: Fewer tokens per call.
* Increases Accuracy: The model isn't distracted by "intent" when it should be focused on "implementation."
* Enforces SDD: If the Architect misses a requirement in the spec update, the Builder won't include it in the code—immediately surfacing the gap.

---

To enforce the "No-Peeking" rule, the system prompts must act as the primary cognitive boundary for each sub-agent. By giving them distinct "identities" and restricted instructions, we ensure the Builder cannot hallucinate based on the original intent—only the final requirements.
Here are the specific System Prompts for the Architect and Builder personas:
1. The Architect (The Spec-Writer)
Role: Requirements Engineer
Input: .change.md (Intent), current.spec.md (Current State), config.json (Project Standards)
No-Peeking Rule: Forbidden from looking at the implementation code to avoid "reverse-engineering" the spec from existing bugs.

System Prompt:
"You are an Expert Requirements Engineer. Your sole mission is to update the Markdown Specification (.spec.md) based on the provided Change Request (.change.md).
Constraints:

* Do NOT write or suggest code.
* Focus strictly on 'What' the system must do, not 'How' it is implemented.
* Ensure all business logic, edge cases, and constraints are explicitly defined in the spec.
* If the Change Request is ambiguous, flag it for the Orchestrator rather than guessing.

Output: Provide a precise diff or a full rewrite of the .spec.md only."

------------------------------
2. The Builder (The Implementer)
Role: Senior Software Engineer
Input: updated.spec.md (Source of Truth), current_file.py (Target)
No-Peeking Rule: Physically blocked from seeing the .change.md. This forces the Builder to rely entirely on the Architect's work.

System Prompt:
"You are a Senior Software Engineer. Your goal is to implement the logic defined in the provided .spec.md into the target file.
Constraints:

* The .spec.md is your ABSOLUTE source of truth. If a feature isn't in the spec, it doesn't exist.
* Do NOT assume intent beyond what is written in the spec.
* Maintain existing architectural patterns found in the target file unless the spec dictates a change.
* You must generate the entire body of the file (everything below the @unslop-managed header).

Output: The complete, byte-exact content for the managed file."

------------------------------
The "Symphony" Orchestration Logic
The Orchestrator acts as the silent mediator (the "Conductor"). To make this work:

   1. It strips all mentions of "Change Requests" or "Jira tickets" when calling the Builder.
   2. It treats the Architect's output as the only valid input for the Builder.
   3. If the Builder produces code that fails the Auditor's hash-check (i.e., it hallucinated something not in the spec), the Orchestrator blames the Architect for a weak spec and restarts the loop.

Why this matters for your "Heal" Step
In a Tactical Fix (Code-First), the personas swap roles:

   1. The Builder is given the .change.md (Intent) and the Code.
   2. Once the code is patched, the Architect is given the New Code and told: "The code changed; update the Spec to reflect this reality."

This ensures that even when we move fast, the Architect is forced to document the "why" after the fact.

The Auditor is the final safety gate. Its job is to act as a "blind" reviewer—it compares the Builder's new code against the Architect's updated spec without knowing what the original change request was.
If the Auditor finds a discrepancy, it triggers a "Spec-Code Mismatch" error, forcing the Architect or Builder to reconcile.
3. The Auditor (The Validator)
Role: Quality Assurance / Compliance
Input: updated.spec.md (Requirements), new_code.py (Implementation)
No-Peeking Rule: Forbidden from seeing the .change.md or the previous version of the code. It only sees the "proposed future."

System Prompt:
"You are a Senior Technical Auditor. Your task is to verify that the provided implementation (new_code.py) perfectly satisfies the requirements defined in the specification (updated.spec.md).
Evaluation Criteria:

   1. Completeness: Does the code implement EVERY requirement in the spec?
   2. Constraint Check: Does the code respect all 'Do Not' or 'Must Not' constraints in the spec?
   3. Purity: Is there logic in the code that is NOT defined in the spec? (Flag this as 'Spec Leakage').
   4. Interface Match: Do function signatures and data structures match the spec exactly?

Output:

* If PASS: Return only 'STATUS: PASS' followed by the 12-char SHA-256 hash of the code body.
* If FAIL: Provide a bulleted list of specific discrepancies (e.g., 'Requirement 4.2 missing from implementation')."

The Orchestrator's "Conflict Resolution" Logic
When the Auditor fails the build, the Orchestrator has a deterministic path:

   1. Feedback Loop: It feeds the Auditor's "Discrepancy List" back to the Builder.
   2. The "Who's at Fault?" Check: If the Builder insists the spec is impossible or ambiguous, the Orchestrator passes the feedback back to the Architect to refine the spec.
   3. The Final Gate: The output-hash is only written to the file header once the Auditor returns a PASS.

Why the Auditor is Essential
By having a third, independent persona, you eliminate the "Lazy Model" bias where the Builder might say "Yeah, that looks right" to its own work. The Auditor provides the deterministic verification needed for a true Spec-Driven Development (SDD) pipeline.
Using separate worktrees is the high-fidelity solution. It transforms the "locking" problem into a version control problem, which Git is already designed to solve.
By giving each sub-agent its own ephemeral worktree, you create a physical sandbox that matches the cognitive sandbox of their prompts.
The Worktree-Isolated Workflow

   1. Orchestrator creates a hidden branch/worktree for the Architect (e.g., .unslop/worktrees/arch-retry-py).
   2. Architect updates the spec in that worktree. Orchestrator runs Auditor against the spec's structure.
   3. Upon "Spec Approval," the Orchestrator creates a second worktree for the Builder based on the Architect's branch.
   4. Builder implements the code. Auditor verifies the code against the spec in that isolated tree.
   5. Merge & Purge: Only once the Auditor returns PASS does the Orchestrator merge the worktree changes back to the main branch, update the output-hash, and delete the temporary worktrees.

Why Worktrees Win

* Parallelism: You can have multiple sub-agents working on different files simultaneously without them stepping on each other's import or sys.path.
* Atomic Rollback: If a generation fails or the user rejects a proposal, you simply rm -rf the worktree. Your main working directory remains untouched and "clean."
* No "Dirty State" Contamination: The Builder can run tests in its worktree without affecting the developer's local environment or test database.
* Audit Trail: Each sub-agent's work exists as a discrete Git commit in a hidden ref, providing a perfect "black box" recording of how the code evolved.

Implementation Detail: The "Shadow" Ref
Instead of cluttering the user's branch list, the Orchestrator should use hidden Git refs (e.g., refs/unslop/agents/...) to manage these worktrees. This keeps the git branch output clean for the human developer.
Should we define the "Cleanup" trigger—does the worktree vanish immediately after the merge, or do we keep it until the next unslop:status check confirms the hash is fresh?

---

## Sources

- [Superpowers GitHub](https://github.com/obra/superpowers)
- [GitHub Spec Kit](https://github.com/github/spec-kit)
- [Tessl Docs](https://docs.tessl.io)
- [Martin Fowler — Understanding SDD: Kiro, spec-kit, and Tessl](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)
- [Superpowers Complete Guide 2026](https://pasqualepillitteri.it/en/news/215/superpowers-claude-code-complete-guide)
- [Microsoft Developer Blog — Spec Kit](https://developer.microsoft.com/blog/spec-driven-development-spec-kit)
- [Tessl SDD Tile](https://github.com/tesslio/spec-driven-development-tile)
