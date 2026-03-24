# v0.17.0 Model Selection Design Spec

**Date:** 2026-03-24
**Status:** Design-Locked

## Problem

All unslop subagents inherit the parent session's model. A user running Opus pays Opus prices for every Mason test-write and every Saboteur mutation -- tasks that are mechanical and constrained by design. There is no way to route cheap tasks to cheaper models or to tune model assignment per project.

## Solution: Config-Driven Model Map

Add a `models` block to `.unslop/config.json` that maps agent roles to model aliases. Skills read this map before dispatching subagents and pass the value as the `model` parameter to `Agent()`.

### Why not agent `.md` files?

Unslop's agents are fundamentally dynamic. The Builder's prompt is interpolated with `{spec_path}`, `{test_policy}`, `{previous_failure}`, and mode flags. Extracting these into static frontmatter files would make them brittle and harder to lint. The config-driven approach preserves the existing architecture:

- **Skills define the logic** (the "What")
- **Config defines the infrastructure** (the "Who")

### Design principles

1. **User sovereignty.** The config is a hard floor, not a suggestion. No auto-upgrade logic. Claude Code's native adaptive delegation may escalate complex tasks to Opus -- that is the harness's behavior, not ours.
2. **Zero new dependencies.** Config resolution is an instruction pattern in the skill markdown, not a Python function.
3. **Opinionated defaults.** Missing config falls back to hardcoded defaults that reflect the recommended tier split. No `inherit` fallback -- the defaults are the recommendation.

---

## 1. Config Schema

Add a `models` block to `.unslop/config.json`:

```json
{
  "models": {
    "architect": "opus",
    "builder": "sonnet",
    "archaeologist": "sonnet",
    "mason": "haiku",
    "saboteur": "haiku",
    "prosecutor": "sonnet"
  },
  "models_note": "Model selection per agent role. architect is a session recommendation (not dispatched). Valid values: opus, sonnet, haiku, or a full model ID."
}
```

### Model Tiers

| Tier | Roles | Rationale |
|---|---|---|
| **Opus** (strategic) | Architect | Intent extraction, spec design, lowering -- errors cascade to everything downstream |
| **Sonnet** (creative) | Builder, Archaeologist, Prosecutor | Code generation, behavioural extraction, mutant classification -- substantial but bounded |
| **Haiku** (mechanical) | Mason, Saboteur | Test writing from structured YAML, mutation execution -- constrained and formulaic |

### The Architect Key

The Architect runs inline as the controlling session -- it is not dispatched as a subagent. The `"architect": "opus"` config entry is **documentation of intent**: it tells the user what model this role is designed for and serves as a recommendation for what model to run the session under. No dispatch logic reads this key.

### Valid Values

- Model aliases: `"sonnet"`, `"opus"`, `"haiku"`
- Full model IDs: e.g., `"claude-sonnet-4-6"`

No schema validation of model values. Invalid values cause `Agent()` to fail at dispatch time -- the harness surfaces the error.

### Missing Config Behavior

If the `models` block is absent or a role key is missing, use these defaults:

| Role | Default |
|---|---|
| architect | opus (session recommendation) |
| builder | sonnet |
| archaeologist | sonnet |
| mason | haiku |
| saboteur | haiku |
| prosecutor | sonnet |

---

## 2. Dispatch Points

Two skill files contain all subagent dispatch logic. Commands delegate to these skills.

### Generation Skill (`skills/generation/SKILL.md`)

**Builder dispatch (Stage B):** The existing `Agent()` call gains a `model` parameter:

```python
Agent(
    description="Implement spec changes in isolated worktree",
    isolation="worktree",
    model=config.models.builder,  # from .unslop/config.json, default: sonnet
    prompt="""You are implementing changes to managed files based on their specs.
    ...existing prompt template unchanged...
    """
)
```

No other changes to the Builder's prompt, isolation, or verification logic.

### Adversarial Skill (`skills/adversarial/SKILL.md`)

Four agent dispatches gain `model` parameters:

| Phase | Agent | Model Config Key |
|---|---|---|
| Phase 1 | Archaeologist | `config.models.archaeologist` |
| Phase 2 | Mason | `config.models.mason` |
| Phase 3 | Saboteur | `config.models.saboteur` |
| Phase 3b | Prosecutor | `config.models.prosecutor` |

### Commands

The following commands dispatch Builders but delegate to the generation skill:

- `commands/generate.md` -- "use the generation skill's two-stage execution model"
- `commands/sync.md` -- same delegation
- `commands/change.md` -- same delegation
- `commands/takeover.md` -- delegates to takeover skill, which delegates to generation skill

No command-level changes needed. The model parameter is resolved in the generation skill's `Agent()` call.

---

## 3. Config Resolution Logic

Added as an instruction block to both the generation and adversarial skills:

> **Model Selection:** Before dispatching any subagent, read `.unslop/config.json`. If a `models` block exists and contains a key matching the agent role, pass that value as the `model` parameter to `Agent()`. If the `models` block is missing or the role key is absent, use the hardcoded default:
>
> - builder: sonnet
> - archaeologist: sonnet
> - mason: haiku
> - saboteur: haiku
> - prosecutor: sonnet

This is a prompt instruction, not a Python function. The controlling session reads the config and interpolates the value.

---

## 4. Changes to `/unslop:init`

**Step 4 (Write config.json):** Add the `models` block and `models_note` to the generated config template, positioned after `test_command_note` and before `exclude_patterns`.

No interactive prompt for model selection during init. The defaults are opinionated and correct. Users tune by editing config.json directly.

No migration step for existing configs. Missing `models` blocks fall back to hardcoded defaults.

---

## 5. What This Spec Defers

- **Per-file model override:** A future version could allow `model: opus` in spec frontmatter to override the config for specific high-complexity files. Deferred until there is evidence the per-role config is too coarse.
- **Cost tracking:** Logging which model ran which agent and estimated token cost. Useful but orthogonal to model selection itself.
- **Auto-upgrade based on complexity score:** Explicitly rejected. The config is a hard floor. Convergence loops handle failures from model capability mismatches.

---

## Summary of Changes

| File | Change |
|---|---|
| `skills/generation/SKILL.md` | Add model resolution instruction block; add `model=` to Builder `Agent()` call |
| `skills/adversarial/SKILL.md` | Add model resolution instruction block; add `model=` to all four agent dispatches |
| `commands/init.md` | Add `models` block and `models_note` to config template |
| `plugin.json` | Version bump to 0.17.0 |
