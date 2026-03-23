# unslop

> Spec-driven development for Claude Code. Write what you mean. Generate what you need.

`unslop` is a Claude Code plugin that implements spec-driven development (SDD) -- a workflow where spec files are the source of truth and generated code is a disposable output. You maintain specs; `unslop` maintains code. The name is deliberately provocative: it started as a tool for rescuing vibe-coded prototypes, but it's grown into a full-featured SDD harness that works equally well for greenfield projects.

## What it does

`unslop` manages the lifecycle of spec-driven code:

1. **You write specs** -- human-readable documents that describe *what* code should do, not *how*
2. **Builders generate code** -- isolated agents produce code from specs in git worktrees, with zero access to your conversation history
3. **Tests validate** -- your test suite is the acceptance gate, not LLM judgment
4. **Specs evolve** -- change requests, hardening reviews, and coherence checks keep specs accurate as your project grows

The generated code is always overwritten on the next generation cycle. The only way to change a managed file's behaviour is to change its spec. This inversion is enforced structurally, not by convention.

## Prerequisites

- [Claude Code](https://claude.ai/code)
- [superpowers](https://github.com/obra/superpowers-marketplace) plugin installed

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

## Installation

```
/plugin marketplace add Lewdwig-V/unslop
/plugin install unslop@unslop
```

## Quick start

### Initialise

```
/unslop:init
```

Creates `.unslop/` with your test command, optional project principles, framework detection, and a CI workflow for freshness checks. Run this once per project.

### Path 1: Greenfield (new project, no existing code)

Write a spec, generate the code.

```
/unslop:spec src/retry.py           # create a skeleton spec (file doesn't need to exist)
# fill in src/retry.py.spec.md with your intent
/unslop:generate                    # generate code from specs
```

`/unslop:spec` creates the spec file for you -- even when the source file doesn't exist yet. Fill it with your requirements, then `/unslop:generate` builds all managed files in dependency order.

For multiple related files, write specs with `depends-on` frontmatter to declare relationships. `/unslop:generate` resolves the build order automatically.

### Path 2: Rescue (existing prototype, bring it under harness)

You have working code and tests. Extract the intent into a spec.

```
/unslop:takeover src/retry.py
```

The takeover pipeline:

1. Reads the existing file and its tests
2. Drafts a spec capturing intent, not implementation
3. Archives the original to `.unslop/archive/`
4. Generates fresh code from the spec alone -- no anchoring on the original
5. Runs the test suite
6. If tests fail: surfaces the missing constraint, enriches the spec, regenerates
7. Iterates until green (max 3 iterations)
8. Commits the spec and generated file together

The convergence loop is the point. If the spec is sufficient to regenerate passing code from scratch, it's a real spec. If it isn't, the failing tests tell you exactly what's missing.

For entire directories: `/unslop:takeover src/auth/` scans, discovers, and offers per-file or per-unit spec granularity.

### Path 3: Maintenance (iterating on managed code)

Record a change intent, then regenerate.

```
/unslop:change src/retry.py "add circuit breaker with 5-failure threshold"
/unslop:generate
```

Or for immediate execution:

```
/unslop:change src/retry.py "fix null check on empty response" --tactical
```

The `--tactical` flag means "do it now" -- the Architect proposes a spec update, the Builder generates in an isolated worktree, and the result is committed atomically if tests pass. If the Builder fails, everything is reverted.

## Architecture

### Two-stage worktree isolation

All code generation uses a two-stage model with physical isolation:

**Stage A (Architect)** runs in your session. It processes change intent, updates specs, and stages changes. It can see the file tree but cannot read source code (except during takeover, where reading code is the point).

**Stage B (Builder)** runs as a fresh agent in an isolated git worktree. By default (Mode A), it generates code from the spec alone -- no conversation history, no change request context. In incremental mode (`--incremental` / Mode B), the Builder also reads the existing managed file to produce targeted edits, but still has no access to change requests or conversation history.

This isn't a prompt-based rule ("don't peek at the code"). It's a structural guarantee: the Builder's context window physically cannot contain your conversation. The spec is the only bridge between the two stages.

On success, the worktree merges and the spec + code commit atomically. On failure, the worktree is discarded and all staged changes are reverted. Main is never left in a half-committed state.

### Triage routing

When `unslop` detects a `.unslop/` directory in your project, it auto-activates a triage skill that routes your intent to the right command:

| You say | unslop routes to |
|---|---|
| "Let's refactor the auth module" | `/unslop:takeover` |
| "Add retry logic to the API client" | `/unslop:change` |
| "Just fix this null check" | `/unslop:change --tactical` |
| "Is this implementation solid?" | `/unslop:harden` |
| "What's out of date?" | `/unslop:status` |
| "Sync everything that's stale" | `/unslop:sync --stale-only` |
| "Why is X ghost-stale?" | `/unslop:graph --stale-only` |
| "Do these specs agree?" | `/unslop:coherence` |

If you explicitly ask to edit a managed file directly, unslop warns once (the file will show as `modified` in status) and steps aside. It's a tool, not a gatekeeper.

## Spec conventions

Specs live alongside their source files:

```
src/
  retry.py           # managed -- do not edit
  retry.py.spec.md   # edit this
  retry_test.py      # human-owned -- ground truth
```

Specs describe intent, not implementation:

| Write this (intent) | Not this (implementation) |
|---|---|
| Messages are stored in SQLite with a monotonic sequence ID | Use INSERT OR REPLACE with a rowid alias column |
| Retries use exponential backoff with jitter, max 5 attempts | `sleep(2**attempt + random.uniform(0,1))` |
| Validation rejects inputs over 1MB | `if len(data) > 1_048_576: raise ValueError` |

If your spec reads like commented-out code, it's over-specified. The LLM fills the implementation gap. The tests constrain what filling is acceptable.

### Dependencies between specs

When a managed file imports from another managed file, declare the relationship in frontmatter:

```markdown
---
depends-on:
  - src/auth/tokens.py.spec.md
---

# handler.py spec
...
```

`unslop` resolves dependencies transitively and generates files in dependency order. The coherence checker validates that dependent specs don't contradict each other.

### Unit specs

For tightly coupled files that form a logical unit, write a single spec:

```markdown
# auth module spec

## Files
- `__init__.py` -- public API re-exports
- `tokens.py` -- JWT token creation and verification
- `middleware.py` -- request authentication middleware
```

Unit specs are named `<dir>.unit.spec.md` and placed inside the directory.

### Project principles

`.unslop/principles.md` defines non-negotiable constraints for all generated code:

```markdown
# Project Principles

## Error Handling
- All errors must be typed -- no bare Exception catches
- Public functions must return Result types, not raise

## Architecture
- No global mutable state
- Prefer composition over inheritance
```

Principles are checked during every generation cycle. If a spec contradicts a principle, generation stops with a clear conflict report.

## Quality gates

Generation runs through a validation pipeline before the Builder ever starts:

| Phase | What it checks | Blocks on failure? |
|---|---|---|
| **0a: Structural** | Minimum length, required sections, code fence misuse | Yes |
| **0b: Ambiguity** | Semantic ambiguity the Builder could misinterpret | Yes (override: `--force-ambiguous`) |
| **0c: Changes** | Pending change requests absorbed into spec | Yes (on conflict) |
| **0d: Domain** | Framework-specific skills loaded (FastAPI, React, etc.) | No |
| **0e: Coherence** | Cross-spec contract consistency with dependencies | Yes (no override) |

### Staleness detection

Every managed file carries a dual-hash header:

```python
# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
```

Four states: **fresh** (both hashes match), **stale** (spec changed), **modified** (code edited directly), **conflict** (both changed). `/unslop:status` reports all of these. CI can enforce freshness via `check-freshness`.

### Ghost staleness

When a concrete spec (`*.impl.md`) changes, all downstream managed files that depend on it through `extends` or `concrete-dependencies` become **ghost-stale** -- their abstract spec hasn't changed, but their implementation strategy has. Ghost staleness is tracked via a per-dependency manifest in the managed file header:

```python
# concrete-manifest:core.impl.md:a3f8c2e9b7d1,utils.impl.md:7f2e1b8a9c04
```

`/unslop:graph --stale-only` renders the **causal subgraph** -- not just stale nodes, but the upstream concrete providers that triggered the staleness. Context providers (the cause) are styled with dashed grey borders so you can trace the infection path from root cause to symptom, even when the cause has no managed output of its own.

### Bulk sync

`/unslop:sync --stale-only` scans the entire project for stale files and batches them into worktree groups that respect topological order from both abstract (`depends-on`) and concrete (`extends`/`concrete-dependencies`) graphs. Files within a batch share no dependency edges, so they can be processed efficiently in a single worktree.

```
/unslop:sync --stale-only                    # sync all stale files in batched topo order
/unslop:sync --stale-only --dry-run          # show the plan without regenerating
/unslop:sync --stale-only --force            # include modified/conflict files
/unslop:sync --stale-only --max-batch 4      # cap files per worktree batch
/unslop:sync src/retry.py --deep             # sync one file + its downstream blast radius
```

## Commands

| Command | Description |
|---|---|
| `/unslop:init` | Initialise `.unslop/`, detect test command, optional principles + CI |
| `/unslop:spec <file>` | Create or edit the spec for a source file |
| `/unslop:takeover <file\|dir>` | Bring existing code under spec management |
| `/unslop:generate` | Regenerate all stale managed files |
| `/unslop:sync <file>` | Regenerate one specific managed file |
| `/unslop:sync <file> --deep` | Regenerate a file and its entire downstream blast radius |
| `/unslop:sync --stale-only` | Batch-sync all stale files in dependency order |
| `/unslop:status` | List managed files, staleness, pending changes |
| `/unslop:change <file> "desc" [--tactical]` | Record or immediately execute a change request |
| `/unslop:harden <spec-path>` | Stress-test a spec for completeness and edge cases |
| `/unslop:coherence [spec-path]` | Check cross-spec consistency across dependencies |
| `/unslop:graph [--stale-only]` | Render Mermaid dependency graph (causal subgraph if stale-only) |

## Skills

`unslop` ships skills that activate contextually:

| Skill | Purpose |
|---|---|
| **spec-language** | Vocabulary guide for writing specs -- intent vs implementation |
| **concrete-spec** | Writing concrete specs (strategy-focused, compiler IR model) |
| **generation** | Two-stage execution model, quality gates, test policy |
| **takeover** | Takeover pipeline, convergence loop, archive conventions |
| **triage** | Auto-routes user intent to the correct unslop command (sync, deep sync, bulk sync, graph, harden, etc.) |
| **domain/fastapi** | FastAPI-specific generation priors (dependency injection, schemas, async) |

Domain skills are additive -- they augment the generation skill with framework conventions. Community contributions for React, SQLAlchemy, Terraform, and other frameworks are welcome.

## CI integration

`/unslop:init` optionally generates a GitHub Actions workflow:

```yaml
name: unslop freshness check
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv python install 3.11
      - run: uv run python .unslop/scripts/orchestrator.py check-freshness .
```

This ensures no PR ships stale managed files. The orchestrator is vendored into `.unslop/scripts/` so CI doesn't need the plugin installed.

## What belongs under unslop management

`unslop` works best for code where the *what* is completely separable from the *how*: adapters, parsers, boilerplate, glue code, serialisation logic, CLI wrappers, CRUD endpoints, data transformations.

Code where the implementation *is* the semantics -- performance-critical algorithms, type-level invariants, anything with subtle concurrency behaviour -- belongs in human-owned files.

`unslop` does not try to manage everything. It manages the things where managing them is sound. The takeover pipeline will tell you which: if the convergence loop can't converge without over-specifying to implementation detail, the file probably shouldn't be managed.

## Philosophy

The spec is the durable artefact. The code is derived.

This is an inversion of the usual model, where the code is the ground truth and documentation is the afterthought. `unslop` enforces the inversion structurally: managed files are overwritten on every generation cycle, so editing them directly is pointless. The only way to change the behaviour of a managed file is to change its spec.

The practical consequence: code review happens at the spec level, not the code level. Diffs are spec diffs. The generated code is an output of the review process, not an input to it.

## Contributing

The domain skills directory is the most useful place to contribute. Framework-specific skills for common patterns make `unslop` useful for more codebases with less configuration. See `unslop/domain/fastapi/SKILL.md` for the format. PRs welcome.

## Acknowledgements

Built on [superpowers](https://github.com/obra/superpowers-marketplace) by Jesse Vincent. The spec-as-source-of-truth model draws from [CodeSpeak](https://codespeak.dev/). Project principles and the constitution concept are inspired by [Spec Kit](https://github.com/anthropics/spec-kit). The domain skill registry and eval-driven skill development approach are informed by [Tessl](https://tessl.io/). The two-stage Architect/Builder dataflow and structured information siloing draw from OpenAI's [Symphony](https://github.com/openai/openai-cookbook/tree/main/examples/orchestrating_agents) framework, though we replaced its persona model with physical worktree isolation.

## License

MPL 2.0
