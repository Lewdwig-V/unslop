# AGENTS.md -- Working with unslop

> This file is for AI agents working in or on the unslop codebase. It describes the architecture, invariants, and conventions that aren't obvious from the code alone.

## What unslop Is

unslop is a Claude Code plugin for spec-driven development. Specs (*.spec.md) are the source of truth. Generated code is a disposable artifact derived from specs. The plugin has 19 commands, 6 skills, and 1 domain skill (FastAPI).

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
| Saboteur | haiku | Mutation testing, async post-generate verification, cover gap analysis |

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
| non_goals | elicit | Manual | Machine-readable exclusions |
| needs-review | change (downstream flagging) | elicit, review-acknowledged | Soft-block in generate/sync |
| review-acknowledged | generate/sync (user dismissal) | Next elicit pass | Conscious dismissal of needs-review |
| uncertain | distill | elicit resolves | "Was this accidental?" questions |
| discovered | generate Stage 0 | generate Stage 0b resolves | "Does your intent require this?" |
| distilled-from | distill | Never (persists) | Epistemic provenance |
| absorbed-from | absorb | Ratification (-> provenance-history) | Structural provenance |
| exuded-from | exude | Ratification (-> provenance-history) | Structural provenance |
| provenance-history | ratification | Never (append-only) | Audit log |

## File Layout

```
unslop/
  .claude-plugin/plugin.json    # Plugin manifest (version, metadata)
  commands/*.md                 # 19 command definitions (the execution surface)
  skills/*/SKILL.md             # 6 skill reference files
  domain/*/SKILL.md             # Domain-specific skills (FastAPI)
  scripts/
    orchestrator.py             # Re-export facade for all Python modules
    core/
      frontmatter.py            # All frontmatter parsers
      hashing.py                # SHA-256 hash computation
      spec_discovery.py         # File discovery and spec parsing
    freshness/
      checker.py                # check_freshness() -- state classification
      manifest.py               # Concrete manifest computation
    dependencies/
      graph.py                  # Dependency graph and topo sort
      unified_dag.py            # Abstract + concrete DAG
      concrete_graph.py         # Concrete spec inheritance
    planning/
      ripple.py                 # Ripple check for downstream impact
      bulk_sync.py              # Bulk sync planning
      deep_sync.py              # Deep sync planning
      resume.py                 # Resume from failed sync
      graph_renderer.py         # Mermaid graph output
    validation/
      spec_diff.py              # Spec diff computation
    mcp_server.py               # MCP server (8 tools)
  .unslop/                      # Project state directory
    config.json                 # Test command, model overrides
    principles.md               # Project-wide constraints
    verification/               # Saboteur async results
    absorbed/                   # Staged originals from absorb
    exuded/                     # Staged originals from exude
tests/
  test_orchestrator.py          # 377 tests for all Python modules
```

## Conventions

### Commands vs Skills
Commands are the execution surface -- they define what happens step by step. Skills are reference material -- they define the rules agents follow during execution. Critical constraints must be in the command with HARD RULE format, not only in skills.

### Parser Pattern
All nested-list frontmatter parsers use `_parse_nested_list_field()` in frontmatter.py. To add a new field: call the helper with (content, field_name, first_key, required_fields). The helper handles frontmatter extraction, state machine parsing, indentation warnings, empty-value detection, and required-field validation.

### Test Pattern
Tests are in tests/test_orchestrator.py. Flat functions (not classes). Naming: `test_<function>_<scenario>()`. Parsers import from `unslop.scripts.orchestrator` (the facade). Freshness tests use `tmp_path` fixtures and create `.unslop/` directories.

### Version Bumps
Always bump plugin.json version when changing commands, skills, or hooks.
