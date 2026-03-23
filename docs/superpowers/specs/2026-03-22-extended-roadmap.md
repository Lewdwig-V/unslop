# Extended Roadmap: Beyond the Gap Analysis

> A phased roadmap covering incremental improvements, new capabilities, and speculative architectural shifts — ordered from proven-and-ready to experimental.

**Context:** The original CodeSpeak gap analysis (Milestones A-C) is complete. This roadmap draws from the spec-driven tools landscape analysis and addresses remaining gaps, new ideas, and architectural evolution.

**Principle:** Each milestone should be independently valuable. Later milestones may depend on earlier ones, but no milestone should be blocked by a speculative one that might never ship.

---

## Milestone D: Project Principles Document

**Source:** Spec Kit's constitution concept
**Effort:** Low
**Impact:** High — reduces ambiguity across all specs without per-spec effort

### What

A project-level `principles.md` (or a `principles` field in `config.json`) that defines non-negotiable generation constraints. Referenced by the generation skill on every run.

Examples:
- "Always use dependency injection"
- "No global mutable state"
- "Errors must be typed — no bare Exception catches"
- "All public functions must have docstrings"
- "Prefer composition over inheritance"

### Why

The ambiguity linter (Phase 0b) catches per-spec ambiguity. Principles catch cross-project consistency — constraints that apply to every managed file but shouldn't be repeated in every spec. A spec that says "handle errors" is ambiguous without principles saying "errors must be typed." With principles, the ambiguity linter can check against them.

### Integration

- `/unslop:init` creates a starter `principles.md` (or prompts the user to define key principles)
- The generation skill reads `principles.md` as context alongside the spec, before Phase 0b
- Phase 0b (ambiguity detection) checks spec constraints against principles for conflicts
- `check-freshness` tracks a `principles-hash` in managed file headers (third hash alongside `spec-hash` and `output-hash`). When principles change, files generated under old principles are classified as stale. This requires a header format extension.
- `/unslop:change --tactical` must also load and enforce principles — the tactical flow bypasses the generation skill, so principles enforcement needs to be explicit in the change command's instructions, not just in the skill.

### Scope

- New file: `.unslop/principles.md`
- Update: `init` command, generation skill, config.json schema
- Update: `@unslop-managed` header format (add `principles-hash` field)
- Update: `change.md` command (load principles during tactical flow)
- No new commands needed — principles are edited directly

---

## Milestone E: Domain Skill Infrastructure

**Source:** Gap 8 (CodeSpeak gap analysis), Tessl's Tiles Registry
**Effort:** Medium (infrastructure) + High (content, ongoing)
**Impact:** High — reduces generation variance for common patterns

### What

A `unslop/domain/` directory structure where framework-specific skills live. Each domain skill provides:
- Few-shot spec examples for the pattern
- Generation priors (what framework constructs to reach for)
- Test scaffolding conventions
- Version-aware documentation references

### Structure

```
unslop/domain/
├── fastapi/
│   └── SKILL.md          # FastAPI adapter generation priors
├── react/
│   └── SKILL.md          # React component generation priors
├── sqlalchemy/
│   └── SKILL.md          # SQLAlchemy model generation priors
└── terraform/
    └── SKILL.md          # Terraform resource generation priors
```

### Loading

- The generation skill checks for domain skills matching the target file's framework (detected from imports, file structure, or `config.json`)
- Domain skills are additive context — they augment the generation skill, not replace it
- `/unslop:init` detects frameworks and suggests relevant domain skills

### Version pinning (from Tessl)

Domain skills reference framework documentation. When the project's `pyproject.toml` or `package.json` pins a framework version, the domain skill should reference documentation for that version, not the latest.

### Priority domains

FastAPI, React, SQLAlchemy, Terraform, dbt models, CLI commands (click/typer).

### Scope

- New directory: `unslop/domain/`
- Update: generation skill (domain skill loading), init command (framework detection)
- First domain skill (FastAPI) shipped with the infrastructure as proof of concept
- Community contributions welcome after infrastructure is proven

---

## Milestone F: Skill Evaluation Framework

**Source:** Tessl's eval approach, Superpowers' skill testing
**Effort:** Medium
**Impact:** Medium — enables data-driven skill development

### What

A way to measure whether a skill change actually improves generation output. Compare task outcomes with and without a skill, or before and after a skill change.

### Approach

- Define a set of "eval tasks" — specs with known-good expected outputs or test suites
- Run generation with skill A, record test pass rate and output quality metrics
- Run generation with skill B (or no skill), record same metrics
- Compare and report

### Integration

- New command: `/unslop:eval <skill-name>` (or a script in `unslop/scripts/`)
- Eval tasks live in `tests/eval/` — each is a spec + test suite pair
- Results are JSON (pass rate, token count, generation time)

### Why this matters

Without measurement, skill development is vibes-driven. "Does adding few-shot examples to the FastAPI domain skill actually improve output?" becomes an answerable question.

### Scope

- New script or command for running evals
- New test fixture directory structure
- No changes to existing skills or commands

---

## Milestone G: Persuasion-Aware Prompt Engineering

**Source:** Superpowers' persuasion principles
**Effort:** Low
**Impact:** Medium — improves model compliance with generation constraints

### What

Embed persuasion principles (authority, commitment/consistency, social proof) in skill text to improve model compliance. This is not manipulation — it's prompt engineering that leverages known cognitive patterns in language models.

### Examples

- **Authority:** "This rule was established after analyzing 500+ generation failures. It is non-negotiable."
- **Commitment:** "You have already validated the spec. The spec is correct. Generate code that matches it exactly."
- **Social proof:** "Every successful takeover in the project history followed this pattern."
- **Scarcity:** "This is the only opportunity to get the generation right. There is no retry loop for this step."

### Where to apply

- Generation skill's "no peeking" rule (currently violated ~5% of the time based on feedback)
- Convergence loop discipline (enriching spec vs patching code)
- Phase 0b ambiguity detection (ensuring thoroughness)

### Scope

- Skill text updates only — no new code, commands, or scripts
- A/B testable via the eval framework (Milestone F)
- Reversible if it doesn't improve outcomes

---

## Milestone H: `/unslop:harden` Command

**Source:** Gap 3 (reproducibility), gap analysis roadmap item 10
**Effort:** Low
**Impact:** Medium — improves spec quality post-takeover

### What

An on-demand command that runs the post-takeover completeness review (Section 7's thorough mode) on any spec, regardless of how it was created.

```
/unslop:harden src/retry.py.spec.md
```

### What it does

1. Reads the spec and ALL generated files it manages (handles both per-file and unit specs — for `*.unit.spec.md`, reads every file listed in the `## Files` section)
2. Asks: "What behavioral aspects of the generated code are NOT constrained by the spec?"
3. For unit specs: also checks cross-file contracts — are internal interfaces between files constrained?
4. Suggests specific additions to tighten the spec for reproducibility
5. User reviews and accepts/rejects each suggestion

### Why

After a successful takeover, Section 7 already does this automatically. But user-written specs don't get this treatment. `/unslop:harden` fills that gap — it's the "make this spec bulletproof" tool.

### Scope

- New command: `unslop/commands/harden.md`
- No new skills — reuses Section 7's post-takeover mode
- No script changes

---

## Milestone I: GitHub Actions Template

**Source:** Gap 6 (CI integration), gap analysis roadmap item 9
**Effort:** Low
**Impact:** Medium — enables team adoption

### What

`/unslop:init` generates a `.github/workflows/unslop.yml` that runs `check-freshness` on every PR.

### Implementation note: orchestrator availability in CI

The orchestrator (`orchestrator.py`) lives in the unslop plugin, not in the user's project. CI runners don't have Claude Code plugins installed. Two options:

1. **Vendor approach**: `/unslop:init` copies `orchestrator.py` and `validate_spec.py` into the project's `.unslop/scripts/` directory. The CI workflow references the vendored copy. This is self-contained but creates a maintenance burden (vendored copies can go stale).

2. **pip install approach**: Publish the orchestrator as a pip-installable package (`pip install unslop-tools`). CI installs it. Cleaner but requires a PyPI package.

**Recommended**: Option 1 for now (vendor). The scripts are small (~500 lines total), stable, and self-contained. Add a version marker so `/unslop:init` can detect and update stale vendored copies.

### Template

```yaml
name: unslop freshness check
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run python .unslop/scripts/orchestrator.py check-freshness .
```

### Scope

- Update: `init` command offers to generate the workflow and vendor scripts
- New template file generated into `.github/workflows/`
- Vendored scripts copied to `.unslop/scripts/` with version marker
- Update: `init` detects and refreshes stale vendored copies

---

## Milestone J: Cross-Spec Coherence Checking

**Source:** Spec Kit's `/speckit.analyze`, landscape analysis
**Effort:** Medium
**Impact:** Medium — catches dependency conflicts before generation

### What

A check that validates consistency across related specs — do specs that depend on each other agree on shared contracts?

### Examples of incoherence

- Spec A says "returns a dict with key 'user_id'"
- Spec B (depends on A) says "expects a 'userId' key from A's output"
- Neither spec is ambiguous alone, but together they're inconsistent

### Integration

- Could be a new Phase 0d in the generation skill, or a standalone command
- Uses the orchestrator's dependency graph to identify related specs
- LLM-driven comparison of shared interfaces

### Scope

- New command or phase in generation skill
- Uses existing dependency infrastructure
- Model-driven (not deterministic)

---

## Milestone K: Symphony-Lite Subagent Architecture (Speculative)

**Source:** Landscape analysis "Re-evaluate" section
**Effort:** High
**Impact:** High (if context isolation proves necessary) or Low (if current approach is sufficient)
**Status:** Speculative — implement only if current single-context generation proves unreliable

### What

Split the generation pipeline into three persona-based subagents:
- **Architect** (Spec-Writer): Receives change intent + current spec. Outputs spec diff. Cannot see implementation code.
- **Builder** (Implementer): Receives updated spec + current code. Outputs code. Cannot see change requests.
- **Auditor** (Validator): Receives new code + spec. Outputs pass/fail + hash. Cannot see change history.

### Why this might be needed

The current single-context approach works but has a theoretical weakness: the model sees the spec, the code, and the change request simultaneously. It can take shortcuts — generating code that satisfies the change request directly rather than going through the spec. The "no peeking" rule is enforced by prompt, not by architecture.

### Why this might NOT be needed

- The quality gates (Phase 0a/0b/0c) already catch most issues
- The convergence loop structurally enforces spec fidelity
- Adding subagent orchestration significantly increases complexity and cost
- The current approach has not yet demonstrated the failure mode this solves

### Prerequisites


- Evidence from real-world usage that single-context generation is producing spec-bypassing code
- Milestone F (eval framework) to measure whether subagents actually improve output quality
- Milestone G (persuasion engineering) exhausted as a simpler solution first

### If implemented

- Orchestrator gains a `spawn-agent` subcommand for context-sandboxed execution
- Generation skill delegates to subagents instead of generating directly
- Each subagent receives a restricted "Context Packet" — the Sandbox Manifest from the landscape analysis
- Worktree isolation (Milestone L) provides physical file-system sandboxing

### Scope

- Major refactor of the generation skill
- New orchestrator capabilities
- Significant testing required
- Should NOT be attempted until Milestones D-I are complete and evaluated

---

## Milestone L: Worktree Isolation (Speculative)

**Source:** Landscape analysis "Worktree-Isolated Workflow" section
**Effort:** High
**Impact:** Medium — enables parallel agent work and atomic rollback
**Status:** Speculative — implement only alongside Milestone K

### What

Each subagent works in its own ephemeral Git worktree. Changes are merged back to the main branch only after the Auditor passes.

### Benefits

- Physical isolation prevents agents from reading files outside their Context Packet
- Atomic rollback — `rm -rf` the worktree on failure
- Parallel processing — multiple agents can work simultaneously without conflicts
- Clean audit trail — each agent's work is a discrete commit

### Implementation

- Orchestrator manages worktree lifecycle (create, merge, purge)
- Hidden Git refs (`refs/unslop/agents/...`) keep the branch list clean
- Superpowers already has a `using-git-worktrees` skill that could be leveraged

### Prerequisites

- Milestone K (subagent architecture) — worktrees only make sense with multiple agents
- Proven need for physical isolation (vs prompt-based isolation)

---

## Milestone M: MCP Server Mode (Speculative)

**Source:** Tessl's MCP integration, landscape analysis
**Effort:** High
**Impact:** Medium — enables IDE integration
**Status:** Deferred — implement when scale demands it (1000+ managed files)

### What

Expose orchestrator functions as MCP tools, enabling IDE integration. A developer could say "use the unslop tool to apply a tactical change to this file" from within Claude Desktop, Cursor, or any MCP-compatible IDE.

### Prerequisites

- Milestones D-I complete (core functionality stable)
- Evidence that CLI-based workflow is insufficient
- Orchestrator functions already structured as pure functions (they are)

### Why defer

The current hooks + orchestrator + commands architecture handles everything the MCP server would. MCP adds value when:
- Cross-file staleness queries need to be fast (1000+ files)
- Real-time spec validation during editing is wanted
- Team-mode state management is needed

None of these are current requirements.

---

## Summary

| Milestone | Effort | Impact | Status | Depends on |
|---|---|---|---|---|
| **D: Project Principles** | Low | High | Ready | — |
| **E: Domain Skills** | Medium | High | Ready | — |
| **F: Skill Evaluation** | Medium | Medium | Ready | E (for content to eval) |
| **G: Persuasion Engineering** | Low | Medium | Ready | — |
| **H: /unslop:harden** | Low | Medium | Ready | — |
| **I: GitHub Actions Template** | Low | Medium | Ready | — |
| **J: Cross-Spec Coherence** | Medium | Medium | Ready | — |
| **K: Symphony-Lite Subagents** | High | TBD | Speculative | F, G, evidence of need |
| **L: Worktree Isolation** | High | Medium | Speculative | K |
| **M: MCP Server** | High | Medium | Deferred | D-I stable |

**Recommended execution order:** D → G → H → I (all low-effort, ship quickly) → E → F → J (medium-effort, higher value) → K/L/M (only if evidence supports).
