# AGENTS.md -- Working with unslop

> This file is for AI agents working in or on the unslop codebase. It describes the architecture, invariants, and conventions that aren't obvious from the code alone.

## What unslop Is

unslop is a Claude Code plugin for spec-driven development. Specs (*.spec.md) are the source of truth. Generated code is a disposable artifact derived from specs. The plugin has 20 commands and 6 skills, with three-tier skill discovery for project-local and user-local domain skills.

## Design Philosophy

The spec is a communication protocol between two stateful agents with different memory architectures. The human has persistent memory, rich context, and ambiguous intent. The model has precise execution, no persistent memory, and needs structured state to reconstruct what the human meant. Everything in the frontmatter solves that mismatch -- not making English more precise, but making the human's mental state more legible to a context-free reader.

## Architecture

### Five-Phase Model

Five independent phases, each a user-invocable command:

| Phase | Command | Operation | Key Agent |
|---|---|---|---|
| Distill | /unslop:distill | Infer spec from existing code | Archaeologist (opus) |
| Elicit | /unslop:elicit | Create/amend spec via Socratic dialogue | Architect (opus) |
| Generate | /unslop:generate | Tests-then-implementation from spec | Archaeologist (sonnet) + Mason + Builder |
| Cover | /unslop:cover | Find and fill test coverage gaps | Saboteur + Archaeologist + Mason |
| Weed | /unslop:weed | Detect intent drift (static + dynamic) | Architect |

Three orchestrators compose phases: takeover (distill -> elicit -> generate), change (elicit -> generate with ripple check), sync (generate with dependency resolution).

### Testless Takeover (Adversarial Path)

When `/unslop:takeover` discovers no existing tests for the target, the adversarial pipeline becomes the quality gate instead of existing tests:

1. **Distill + Elicit** proceed normally (spec inference and review)
2. **Step 2c:** Architect produces `behaviour.yaml` from the spec (testless-only pre-generation step)
3. **Generate Stage 0:** Archaeologist produces concrete spec
4. **Generate Stage 1:** Mason generates tests from `behaviour.yaml` ONLY (Chinese Wall -- never sees source code or spec)
5. **Generate Stage 2:** Builder implements from concrete spec, validated against Mason's tests
6. **Generate Stage 3:** Saboteur runs mutation testing (kill rate >= 80% required)

If kill rate is below threshold, the convergence loop runs (up to 3 normal iterations + 1 radical spec hardening iteration, 4 total, if entropy stalls). Each iteration classifies surviving mutants as `weak_test` (Mason strengthens), `spec_gap` (Architect enriches behaviour.yaml), or `equivalent` (no action).

Override with `--skip-adversarial` (bypass) or `--full-adversarial` (force even when tests exist).

### Unified Generate Pipeline

Stage 0: Archaeologist produces concrete spec + behaviour.yaml + discovered constraints
Stage 0b: Discovery gate -- soft-blocks on discovered correctness requirements. User promotes into abstract spec or dismisses. Re-runs Stage 0 if promoted.
Stage 1: Mason derives tests from behaviour.yaml (conditional -- skipped if tests exist, --regenerate-tests to override)
Stage 2: Builder implements in worktree isolation
Stage 3: Saboteur verifies async (fire-and-forget)

### Agent Model

| Agent | Model Default | Role |
|---|---|---|
| Architect | opus | Socratic elicitation, intent validation, spec reconciliation (absorb) |
| Archaeologist | opus (distill/exude), sonnet (generate) | Spec inference from code, spec projection, spec partitioning |
| Mason | sonnet | Test derivation from behaviour.yaml ONLY (Chinese Wall) |
| Builder | sonnet | Implementation from abstract + concrete spec + tests (worktree isolation) |
| Saboteur | sonnet | Mutation testing, constitutional compliance, edge case probing, cover gap analysis |

## Key Invariants

### Chinese Wall
Mason sees behaviour.yaml only. Builder never sees test derivation logic. Neither sees the other's work. Collapsing them would produce tautological tests.

### Concrete Spec Is Not a Ratification Path
The concrete spec (*.impl.md) is an internal artifact of the generate pipeline. If the Archaeologist discovers a correctness requirement during projection, it surfaces via `discovered:` frontmatter and flows back through the abstract spec via explicit user approval. The concrete spec never becomes a back-channel for ratifying constraints.

### Intent Lock
`intent-approved` is an ISO 8601 timestamp (not a boolean). `intent-hash` is SHA-256 of the spec body. Together they form tamper detection -- if the body changes but intent-approved doesn't reset, the hash won't match.

### Provenance Lifecycle
- `distilled-from:` persists after ratification (epistemic provenance -- "was this spec machine-inferred?")
- `absorbed-from:` / `exuded-from:` clear on ratification, move to `provenance-history:` (structural provenance -- "how was this spec composed?")
- `uncertain:` clears when elicit resolves each item
- `discovered:` must be resolved before generate proceeds (transient)
- `provenance-history:` is append-only, excluded from all analysis layers

### Freshness States

| State | Meaning |
|---|---|
| fresh | Spec and code hashes match |
| stale | Spec changed, code unchanged |
| modified | Code edited directly, spec unchanged |
| conflict | Both spec and code changed |
| pending | Spec exists, no implementation, no active provenance |
| structural | Spec exists, no implementation, has active provenance |
| ghost-stale | Upstream concrete spec changed |
| test-drifted | Spec changed since tests were generated |

`pending` is neutral (planned, not yet generated). `structural` is a warning (absorb/exude/removal needed). `structural` is a hard block in generate/sync; `pending` is not.

## Frontmatter Fields

| Field | Written By | Cleared By | Purpose |
|---|---|---|---|
| intent | elicit, change | -- | One-line description of what the spec describes |
| intent-approved | elicit (timestamp) | Any spec body change resets to false | Tamper-detected approval |
| intent-hash | elicit | Recomputed on any body change | SHA-256 of spec body |
| depends-on | elicit, change | Manual | Spec dependency list |
| non-goals | elicit | Manual | Machine-readable exclusions |
| needs-review | change (downstream flagging) | elicit, review-acknowledged | Soft-block in generate/sync |
| review-acknowledged | generate/sync (user dismissal) | Next elicit pass | Conscious dismissal of needs-review |
| uncertain | distill | elicit resolves | "Was this accidental?" questions |
| discovered | generate Stage 0 | generate Stage 0b resolves | "Does your intent require this?" |
| distilled-from | distill | Never (persists) | Epistemic provenance |
| absorbed-from | absorb | Ratification (-> provenance-history) | Structural provenance |
| exuded-from | exude | Ratification (-> provenance-history) | Structural provenance |
| provenance-history | ratification | Never (append-only) | Audit log |
| rejected | elicit | Manual removal | Closed design decisions with rationale |
| spec-changelog | elicit, change, distill, absorb, exude | Never (append-only) | Structured mutation history |
| constitutional-overrides | elicit (--force-constitutional) | Manual removal | Audited principle override with rationale |

## File Layout

```
prunejuice/
  src/
    api.ts                  # Library API: five phases + three orchestrators
    types.ts                # Shared types, branded hashes, discriminated unions
    pipeline.ts             # queryAgent(), convergence logic, survivor routing
    hashchain.ts            # SHA-256/12 hashing, managed file headers, freshness
    store.ts                # Artifact persistence to .prunejuice/
    dag.ts                  # Dependency graph cache, topological sort, build order
    ripple.ts               # Three-layer ripple check (abstract/concrete/code)
    sync.ts                 # deepSync/bulkSync/resumeSync planning + batching
    manifest.ts             # Concrete deps hashing + ghost staleness diagnostics
    inheritance.ts          # Extends chain + flattening (STRICT_CHILD_ONLY rules)
    freshness.ts            # Eight-state freshness classifier
    discover.ts             # Source file discovery
    spec-diff.ts            # Spec section diff
    validators.ts           # Pseudocode lint (ported from Python)
    mcp.ts                  # MCP server with 15+ tools
    agents/                 # Architect, Archaeologist, Mason, Builder, Saboteur
  test/
    *.test.ts               # vitest unit tests (300+ tests)

unslop/
  commands/                 # Markdown slash commands
  skills/                   # Domain reference skills
  hooks/                    # Shell hook scripts (load-context, regenerate-summary)
  .claude-plugin/
    plugin.json             # Plugin manifest
    .mcp.json               # MCP server config pointing to prunejuice
```

## Skill Discovery

Three tiers, highest priority wins:

1. **User-local:** `~/.config/unslop/skills/<name>/SKILL.md`
2. **Project-local:** `.unslop/skills/<name>/SKILL.md`
3. **Plugin:** `${CLAUDE_PLUGIN_ROOT}/skills/<name>/SKILL.md`

When a skill name exists at multiple tiers, the highest-priority tier wins. The lower-tier skill is completely suppressed -- not loaded, not merged, not consulted.

Skills declare `enforcement` (advisory or constitutional) and `applies-to` (glob patterns for applicability filtering). Constitutional skills are scoped principles checked by the Saboteur during generation. User-local skills are always downgraded to advisory -- constitutional enforcement requires version-controlled, code-reviewed project-local skills.

Create project skills with `/unslop:crystallize` (extracts cross-cutting patterns from the spec corpus) or manually in `.unslop/skills/<name>/SKILL.md`.

## Conventions

### Commands vs Skills
Commands are the execution surface -- they define what happens step by step. Skills are reference material -- they define the rules agents follow during execution. Critical constraints must be in the command with HARD RULE format, not only in skills.

### Test Pattern
Tests are in `prunejuice/test/*.test.ts` using vitest. Flat functions (not classes). Naming: `test('<function> <scenario>', ...)`. Freshness tests create `.unslop/` directories in a temp fixture.

### Version Bumps
Always bump plugin.json version when changing commands, skills, or hooks.

### Skill/Command Alignment

Skill docs are the ground truth agents read. After any command implementation that diverges from its reference skill, the skill update is a correctness fix, not optional housekeeping.

- **Command** is loaded at execution time. It's what runs.
- **Skill** is loaded as reference during planning. It's what agents believe.

When they diverge, the skill wins the epistemic battle even when the command is correct. An agent consulting the skill during planning will reason from stale information and may route around a capability that actually exists. After shipping a command change, update the corresponding skill in the same PR.
