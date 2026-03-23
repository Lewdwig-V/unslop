# unslop

> The spec is the source of truth. Generated code is a disposable artifact.

`unslop` is a Claude Code plugin for **intent-first development** -- a workflow where you maintain spec files describing *what* code should do, and the system maintains the code. Edit the spec, regenerate, run tests. The generated code is overwritten on every cycle; the only way to change a managed file's behaviour is to change its spec.

The name started as a joke about rescuing vibe-coded prototypes. It stuck because the workflow works just as well for greenfield projects.

## Prerequisites

- [Claude Code](https://claude.ai/code)
- [superpowers](https://github.com/obra/superpowers-marketplace) plugin

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

## Installation

```
/plugin marketplace add Lewdwig-V/unslop
/plugin install unslop@unslop
```

## Quick Start

### 1. Initialise

```
/unslop:init
```

Detects your test runner, sets up `.unslop/`, and optionally creates project principles and a CI workflow.

### 2. Bring existing code under management

```
/unslop:takeover src/retry.py
```

Reads the file, drafts a spec capturing the intent (not the implementation), archives the original, and regenerates fresh code from the spec alone. If tests fail, it surfaces the missing constraint, enriches the spec, and retries -- up to 3 iterations. Files without tests are handled automatically via a quality pipeline that generates and validates tests independently.

For entire directories: `/unslop:takeover src/auth/`

### 3. Make changes through the spec

```
/unslop:change src/retry.py "add circuit breaker with 5-failure threshold"
```

Records the intent. On the next `/unslop:generate`, the spec absorbs the change and code is regenerated. For immediate execution:

```
/unslop:change src/retry.py "fix null check on empty response" --tactical
```

### 4. Check what's stale

```
/unslop:status
```

---

## The Core Inversion

In most projects, code is the ground truth and documentation is the afterthought. `unslop` inverts this: the spec is the durable artifact, and the code is derived from it.

**This is enforced structurally, not by convention.** The code generator is physically blocked from seeing your conversation history, your change requests, or the original code (except during takeover). It receives only the spec. If the spec is insufficient, the tests fail -- and the failing test tells you exactly what the spec is missing.

The practical consequence: code review happens at the spec level. Diffs are spec diffs. The generated code is an output of the review process, not an input to it.

---

## The Artifacts

```
src/
  retry.py           # managed -- do not edit directly
  retry.py.spec.md   # the source of truth -- edit this
  retry_test.py      # human-owned tests -- the acceptance gate
```

**Specs** (`*.spec.md`) describe intent: what the code does, its contracts, constraints, and error conditions. They do not describe implementation. If your spec reads like commented-out code, it's over-specified.

| Write this (intent) | Not this (implementation) |
|---|---|
| Retries use exponential backoff with jitter, max 5 attempts | `sleep(2**attempt + random.uniform(0,1))` |
| Messages are stored in SQLite with a monotonic sequence ID | Use INSERT OR REPLACE with a rowid alias |
| Validation rejects inputs over 1MB | `if len(data) > 1_048_576: raise ValueError` |

**Project principles** (`.unslop/principles.md`) define non-negotiable constraints that apply to *all* generated code -- error handling style, architecture patterns, security requirements. Every generation cycle checks the spec against principles and stops on contradiction.

**Dependencies** between specs are declared in frontmatter (`depends-on:`) and resolved transitively. The coherence checker validates that dependent specs don't contradict each other.

---

## Three Kinds of Stale

Every managed file tracks hashes that detect exactly *why* it needs regeneration:

| State | Meaning | Action |
|---|---|---|
| **Spec stale** | The requirements changed | `/unslop:sync <file>` |
| **Ghost stale** | An upstream strategy changed | `/unslop:sync <file> --deep` to include the blast radius |
| **Principles stale** | The project's "constitution" changed | `/unslop:generate` to re-check everything |

`/unslop:status` reports all of these. `/unslop:graph --stale-only` renders the causal chain so you can trace ghost staleness from root cause to symptom.

---

## Triage

When `unslop` detects a `.unslop/` directory in your project, it auto-routes your intent:

| You say | unslop does |
|---|---|
| "Let's refactor the auth module" | `/unslop:takeover` |
| "Add retry logic to the API client" | `/unslop:change` |
| "Just fix this null check" | `/unslop:change --tactical` |
| "Is this implementation solid?" | `/unslop:harden` |
| "What's out of date?" | `/unslop:status` |
| "Sync everything that's stale" | `/unslop:sync --stale-only` |
| "Do these specs agree?" | `/unslop:coherence` |

If you explicitly ask to edit a managed file directly, unslop warns once (the file will show as `modified` in status) and steps aside. It's a tool, not a gatekeeper.

---

## Commands

| Command | Description |
|---|---|
| `/unslop:init` | Initialise the project |
| `/unslop:spec <file>` | Create or edit a spec |
| `/unslop:takeover <file\|dir>` | Bring existing code under spec management |
| `/unslop:generate` | Regenerate all stale managed files |
| `/unslop:sync <file> [--deep] [--stale-only]` | Regenerate one file, a blast radius, or everything stale |
| `/unslop:status` | Show managed files and staleness |
| `/unslop:change <file> "desc" [--tactical]` | Record or immediately execute a change |
| `/unslop:harden <spec>` | Stress-test a spec for completeness |
| `/unslop:coherence [spec]` | Check cross-spec consistency |
| `/unslop:graph [--stale-only]` | Render dependency graph |

---

## CI Integration

`/unslop:init` optionally generates a GitHub Actions workflow that blocks PRs shipping stale managed files:

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

The orchestrator is vendored into `.unslop/scripts/` so CI doesn't need the plugin installed.

---

## What Belongs Under Management

`unslop` works best for code where *what* is completely separable from *how*: adapters, parsers, boilerplate, glue code, serialisation logic, CLI wrappers, CRUD endpoints, data transformations.

Code where the implementation *is* the semantics -- performance-critical algorithms, type-level invariants, subtle concurrency -- belongs in human-owned files. The takeover pipeline will tell you which: if convergence can't succeed without over-specifying to implementation detail, the file probably shouldn't be managed.

---

## Under the Hood

For a deep dive into the generation pipeline, quality gates, and architectural constraints, read the skill files in `unslop/skills/`. They define the non-negotiable rules for how code is lowered from intent to implementation. The `unslop/scripts/` directory contains the deterministic infrastructure (dependency resolution, staleness detection, mutation testing) that enforces these rules mechanically.

---

## Contributing

Domain skills are the most useful place to contribute. Framework-specific skills for common patterns (React, SQLAlchemy, Terraform, etc.) make `unslop` useful for more codebases with less configuration. See `unslop/domain/fastapi/SKILL.md` for the format.

## Acknowledgements

Built on [superpowers](https://github.com/obra/superpowers-marketplace) by Jesse Vincent. The spec-as-source-of-truth model draws from [CodeSpeak](https://codespeak.dev/). Project principles are inspired by [Spec Kit](https://github.com/anthropics/spec-kit). Domain skill design is informed by [Tessl](https://tessl.io/).

## License

MPL 2.0
