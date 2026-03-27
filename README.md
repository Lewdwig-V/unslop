# unslop

> The spec is the source of truth. Generated code is a disposable artifact.

`unslop` is a Claude Code plugin for **intent-first development** -- a workflow where you maintain spec files describing *what* code should do, and the system maintains the code. Edit the spec, regenerate, run tests. The generated code is overwritten on every cycle; the only way to change a managed file's behaviour is to change its spec.

The name started as a joke about rescuing vibe-coded prototypes. It stuck because the workflow works just as well for greenfield projects -- and because "unslop your codebase" is a satisfying thing to say.

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

### Greenfield: write a spec from scratch

```
/unslop:init
/unslop:elicit src/retry.py       # Socratic dialogue to build the spec
/unslop:generate                   # tests-then-implementation from spec
```

### Takeover: bring existing code under management

```
/unslop:takeover src/retry.py          # single file
/unslop:takeover src/auth/             # entire module
/unslop:takeover src/**/*.py           # glob pattern
```

Reads the code, infers a spec via `distill`, refines it via `elicit`, archives the originals, and regenerates fresh code from specs alone. For directories and globs, unslop discovers files, resolves their dependency order, and offers per-file or per-unit spec granularity.

### Change: modify a managed file's behaviour

```
/unslop:change src/retry.py "add circuit breaker with 5-failure threshold"
```

Records the intent, opens a Socratic dialogue to amend the spec, then regenerates. For quick fixes:

```
/unslop:change src/retry.py "fix null check on empty response" --tactical
```

---

## The Five-Phase Model

unslop decomposes development into five independent phases. Each can be run standalone or composed by orchestrators.

| Phase | Command | What it does |
|---|---|---|
| **Distill** | `/unslop:distill` | Infer spec from existing code |
| **Elicit** | `/unslop:elicit` | Create/amend spec via Socratic dialogue |
| **Generate** | `/unslop:generate` | Tests-then-implementation from spec |
| **Cover** | `/unslop:cover` | Find and fill gaps in test coverage |
| **Weed** | `/unslop:weed` | Detect intent drift between spec and code |

Three orchestrators compose these phases into workflows:

- **takeover** -- distill, then elicit, then generate. Brings existing code under management.
- **change** -- elicit, then generate. Records a change and regenerates.
- **sync** -- generate with dependency resolution. Regenerates one file, a blast radius, or everything stale.

---

## The Core Inversion

In most projects, code is the ground truth and documentation is the afterthought. `unslop` inverts this: the spec is the durable artifact, and the code is derived from it.

**This is enforced structurally, not by convention.** The code generator is physically blocked from seeing your conversation history, your change requests, or the original code (except during takeover). It receives only the spec. If the spec is insufficient, the tests fail -- and the failing test tells you exactly what the spec is missing.

The practical consequence: code review happens at the spec level. Diffs are spec diffs. The generated code is an output of the review process, not an input to it.

---

## The Artifacts

```
src/
  retry.py             # managed file -- do not edit directly
  retry.py.spec.md     # per-file spec -- edit this
  retry_test.py        # human-owned tests -- the acceptance gate
  auth/
    __init__.py         # managed
    tokens.py           # managed
    middleware.py        # managed
    auth.unit.spec.md   # unit spec -- one spec for the whole module
```

**Per-file specs** (`*.spec.md`) manage a single file. **Unit specs** (`*.unit.spec.md`) manage a group of tightly coupled files as a single logical unit -- one spec, multiple outputs. Dependencies between specs are declared in frontmatter and resolved transitively.

Specs describe intent, not implementation. If your spec reads like commented-out code, it's over-specified.

| Write this (intent) | Not this (implementation) |
|---|---|
| Retries use exponential backoff with jitter, max 5 attempts | `sleep(2**attempt + random.uniform(0,1))` |
| Messages are stored in SQLite with a monotonic sequence ID | Use INSERT OR REPLACE with a rowid alias |
| Validation rejects inputs over 1MB | `if len(data) > 1_048_576: raise ValueError` |

**Project principles** (`.unslop/principles.md`) define non-negotiable constraints that apply to *all* generated code -- error handling style, architecture patterns, security requirements. Every generation cycle checks the spec against principles and stops on contradiction.

**Dependencies** between specs are declared in frontmatter (`depends-on:`) and resolved transitively. Generation respects dependency order automatically. The coherence checker validates that dependent specs don't contradict each other.

**Provenance tracking** -- specs carry `absorbed-from:`, `exuded-from:`, and `provenance-history:` frontmatter that records how specs were created, merged, and split. The `.unslop/absorbed/` and `.unslop/exuded/` staging areas hold intermediate artifacts during absorb and exude operations.

---

## Agent Model

unslop uses five specialised agents, each with a fixed role and model assignment.

| Agent | Model | Role |
|---|---|---|
| **Architect** | opus | Socratic elicitation, spec reconciliation, absorb/exude |
| **Archaeologist** | opus (distill/exude), sonnet (generate) | Spec inference, spec projection, spec partitioning |
| **Mason** | sonnet | Test derivation from behaviour.yaml only (Chinese Wall -- no access to implementation) |
| **Builder** | sonnet | Implementation from spec + tests in worktree isolation |
| **Saboteur** | haiku | Mutation testing, async post-generate verification |

The agent boundaries are structural. The Mason never sees implementation code. The Builder never sees conversation history. These walls prevent the generated code from encoding anything not captured in the spec.

---

## Staleness States

Every managed file tracks hashes that detect exactly *why* it needs regeneration:

| State | Meaning | Action |
|---|---|---|
| **fresh** | Everything in sync | Nothing |
| **stale** | Spec changed since last generation | `/unslop:sync <file>` |
| **modified** | Someone edited the managed file directly | `/unslop:sync <file>` to overwrite, or update the spec |
| **ghost-stale** | An upstream dependency's spec changed | `/unslop:sync <file> --deep` |
| **conflict** | Spec and code both changed | Resolve manually, then sync |
| **pending** | Spec written but never generated | `/unslop:generate` |
| **structural** | File structure changed (renames, splits) | `/unslop:sync <file>` |
| **test-drifted** | Tests changed but spec hasn't | `/unslop:weed` to check for drift |

`/unslop:status` reports all of these. `/unslop:graph --stale-only` renders the causal chain so you can trace ghost staleness from root cause to symptom.

---

## Triage

When `unslop` detects a `.unslop/` directory in your project, it auto-routes your intent:

| You say | unslop does |
|---|---|
| "Let's refactor the auth module" | `/unslop:takeover` |
| "I need a spec for X" | `/unslop:elicit` |
| "Add retry logic" | `/unslop:change` |
| "Just fix this null check" | `/unslop:change --tactical` |
| "What does this code do?" | `/unslop:distill` |
| "Is this implementation solid?" | `/unslop:harden` |
| "What's out of date?" | `/unslop:status` |
| "Sync everything stale" | `/unslop:sync --stale-only` |
| "Do these specs agree?" | `/unslop:coherence` |
| "Find weak tests" | `/unslop:cover` |
| "Has the code drifted from spec?" | `/unslop:weed` |
| "Check fidelity right now" | `/unslop:verify` |
| "Merge these file specs" | `/unslop:absorb` |
| "Split this module spec" | `/unslop:exude` |

If you explicitly ask to edit a managed file directly, unslop warns once (the file will show as `modified` in status) and steps aside. It's a tool, not a gatekeeper.

---

## Commands

### Phases

| Command | Description |
|---|---|
| `/unslop:distill` | Infer spec from existing code |
| `/unslop:elicit` | Create/amend spec via Socratic dialogue |
| `/unslop:generate` | Regenerate all stale managed files |
| `/unslop:cover` | Grow test coverage via mutation testing |
| `/unslop:weed` | Detect spec-code drift |

### Orchestrators

| Command | Description |
|---|---|
| `/unslop:takeover` | Bring code under management (distill, elicit, generate) |
| `/unslop:change` | Record or execute a spec change |
| `/unslop:sync` | Regenerate one file, a blast radius, or everything stale |

### Inspection

| Command | Description |
|---|---|
| `/unslop:status` | Show managed files and staleness |
| `/unslop:verify` | Run synchronous fidelity check on a file |
| `/unslop:graph` | Render dependency graph |
| `/unslop:coherence` | Check cross-spec consistency |

### Maintenance

| Command | Description |
|---|---|
| `/unslop:init` | Initialise the project |
| `/unslop:spec` | Create or edit a spec |
| `/unslop:harden` | Stress-test a spec for completeness |
| `/unslop:adversarial` | Full adversarial quality pipeline |
| `/unslop:promote` | Promote ephemeral concrete spec to permanent |
| `/unslop:absorb` | Merge file specs into unit spec |
| `/unslop:exude` | Partition unit spec into file specs |

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

`unslop` works at every scale -- a single utility function, a module with a dozen files, or an entire service layer. It works best for code where *what* is completely separable from *how*: adapters, parsers, API layers, glue code, serialisation logic, CLI wrappers, CRUD endpoints, data transformations.

Code where the implementation *is* the semantics -- performance-critical algorithms, type-level invariants, subtle concurrency -- belongs in human-owned files. The takeover pipeline will tell you which: if convergence can't succeed without over-specifying to implementation detail, the file probably shouldn't be managed. A typical project has a mix: spec-managed modules for the application layer, human-owned files for the core domain logic.

---

## Under the Hood

For a deep dive into the generation pipeline, quality gates, and architectural constraints, read the skill files in `unslop/skills/`. The agent model -- roles, boundaries, and model assignments -- is defined in `AGENTS.md`. The `unslop/scripts/` directory contains the deterministic infrastructure (dependency resolution, staleness detection, mutation testing) that enforces these rules mechanically.

---

## Contributing

Domain skills are the most useful place to contribute. Framework-specific skills for common patterns (React, SQLAlchemy, Terraform, etc.) make `unslop` useful for more codebases with less configuration. See `unslop/domain/fastapi/SKILL.md` for the format.

## Acknowledgements

Built on [superpowers](https://github.com/obra/superpowers-marketplace) by Jesse Vincent. The spec-as-source-of-truth model draws from [CodeSpeak](https://codespeak.dev/). Project principles are inspired by [Spec Kit](https://github.com/anthropics/spec-kit). Domain skill design is informed by [Tessl](https://tessl.io/).

## License

MPL 2.0
