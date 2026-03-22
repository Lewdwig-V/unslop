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

The New Priority: The Subagent "Controller"
If we bring back subagents, the orchestrator needs to evolve into a Controller. It doesn't just call a script; it decides which "context packet" to hand to a specialized agent.
Does it make sense to define the "Context Packet" (the restricted set of files/info) that the Generation Subagent receives to ensure the "no-peeking" rule is enforced?

---

## Sources

- [Superpowers GitHub](https://github.com/obra/superpowers)
- [GitHub Spec Kit](https://github.com/github/spec-kit)
- [Tessl Docs](https://docs.tessl.io)
- [Martin Fowler — Understanding SDD: Kiro, spec-kit, and Tessl](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)
- [Superpowers Complete Guide 2026](https://pasqualepillitteri.it/en/news/215/superpowers-claude-code-complete-guide)
- [Microsoft Developer Blog — Spec Kit](https://developer.microsoft.com/blog/spec-driven-development-spec-kit)
- [Tessl SDD Tile](https://github.com/tesslio/spec-driven-development-tile)
