# Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add config-driven model selection so each unslop agent role dispatches on the right model tier (Opus/Sonnet/Haiku).

**Architecture:** A `models` block in `.unslop/config.json` maps role names to model aliases. The generation and adversarial skills read this config before dispatching subagents and pass the value as the `model` parameter to `Agent()`. No Python code, no new files -- all changes are to existing markdown instruction files.

**Tech Stack:** Claude Code plugin markdown (YAML frontmatter, prompt instructions)

**Spec:** `docs/superpowers/specs/2026-03-24-model-selection-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `unslop/skills/generation/SKILL.md` | Modify | Add model resolution block; add `model=` to Builder `Agent()` call |
| `unslop/skills/adversarial/SKILL.md` | Modify | Add model resolution block; add `model=` to phase dispatch instructions |
| `unslop/commands/init.md` | Modify | Add `models` block to config.json template |
| `unslop/.claude-plugin/plugin.json` | Modify | Version bump to 0.17.0 |

No new files. No test files (these are prompt instruction changes -- validated by running the pipeline on a real project).

---

### Task 1: Add model resolution instruction block to Generation Skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:84-86` (before the Stage B section)

- [ ] **Step 1: Read the current file**

Read `unslop/skills/generation/SKILL.md` lines 80-95 to confirm the exact insertion point. The model resolution block goes immediately before the `### Stage B: Builder` heading.

- [ ] **Step 2: Insert the model resolution block**

Add the following immediately before the `### Stage B: Builder (Fresh Agent, Worktree Isolation)` heading (currently line 84):

```markdown
### Model Selection

Before dispatching any subagent, read `.unslop/config.json`. If a `models` block exists and contains a key matching the agent role, pass that value as the `model` parameter to `Agent()`. If the `models` block is missing or the role key is absent, use the hardcoded default:

| Role | Default |
|---|---|
| builder | sonnet |

The `model` parameter controls which Claude model runs the subagent. Valid values: `sonnet`, `opus`, `haiku`, or a full model ID (e.g., `claude-sonnet-4-6`).
```

- [ ] **Step 3: Add `model=` to the Builder `Agent()` call**

In the existing `Agent()` dispatch block (currently at line 153), add `model=` after `isolation="worktree",`:

Change:
```python
Agent(
    description="Implement spec changes in isolated worktree",
    isolation="worktree",
    prompt="""You are implementing changes...
```

To:
```python
Agent(
    description="Implement spec changes in isolated worktree",
    isolation="worktree",
    model=config.models.builder,  # from .unslop/config.json, default: sonnet
    prompt="""You are implementing changes...
```

- [ ] **Step 4: Verify no other `Agent(` calls exist in this file**

Search `unslop/skills/generation/SKILL.md` for `Agent(` -- there should be exactly one. Confirm no other dispatch points were missed.

- [ ] **Step 5: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat(generation): add model selection for Builder dispatch"
```

---

### Task 2: Add model resolution instruction block to Adversarial Skill

**Note:** Unlike the generation skill, the adversarial skill describes agents as prose phases -- there are no `Agent()` code blocks. Model selection is communicated via `**Dispatch model:**` annotations on each phase heading, which the controlling session reads when dispatching agents.

**Files:**
- Modify: `unslop/skills/adversarial/SKILL.md:36-37` (after the architecture diagram, before Phase 1)

- [ ] **Step 1: Read the current file**

Read `unslop/skills/adversarial/SKILL.md` lines 34-50 to confirm the exact insertion point. The model resolution block goes after the architecture diagram closing block and before `### Phase 1: Archaeologist`.

- [ ] **Step 2: Insert the model resolution block**

Add the following between the architecture diagram and `### Phase 1`:

```markdown
### Model Selection

Before dispatching any adversarial agent, read `.unslop/config.json`. If a `models` block exists and contains a key matching the agent role, pass that value as the `model` parameter to `Agent()`. If the `models` block is missing or the role key is absent, use the hardcoded default:

| Role | Default |
|---|---|
| archaeologist | sonnet |
| mason | haiku |
| saboteur | haiku |
| prosecutor | sonnet |

The `model` parameter controls which Claude model runs the subagent. Valid values: `sonnet`, `opus`, `haiku`, or a full model ID (e.g., `claude-sonnet-4-6`).
```

- [ ] **Step 3: Add model annotation to Phase 1 (Archaeologist)**

After the `### Phase 1: Archaeologist (Intent Extraction)` heading, add a dispatch annotation:

```markdown
**Dispatch model:** `config.models.archaeologist` (default: sonnet)
```

Add this after the heading and before the description paragraph (currently "The Archaeologist reads source code...").

- [ ] **Step 4: Add model annotation to Phase 2 (Mason)**

After the `### Phase 2: Mason (Spec-Blind Test Construction)` heading, add:

```markdown
**Dispatch model:** `config.models.mason` (default: haiku)
```

Add this after the heading and before the description paragraph.

- [ ] **Step 5: Add model annotation to Phase 3 (Saboteur)**

After the `### Phase 3: Saboteur (Mutation Validation)` heading, add:

```markdown
**Dispatch model:** `config.models.saboteur` (default: haiku)
```

Add this after the heading and before the description paragraph.

- [ ] **Step 6: Add model annotation to Phase 3b (Prosecutor)**

After the `### Phase 3b: Prosecutor (Equivalent Mutant Classification)` heading, add:

```markdown
**Dispatch model:** `config.models.prosecutor` (default: sonnet)
```

Add this after the heading and before the description paragraph.

- [ ] **Step 7: Commit**

```bash
git add unslop/skills/adversarial/SKILL.md
git commit -m "feat(adversarial): add model selection for all pipeline agents"
```

---

### Task 3: Add `models` block to init command config template

**Files:**
- Modify: `unslop/commands/init.md:40-41` (inside the config.json template in Step 4)

- [ ] **Step 1: Read the current file**

Read `unslop/commands/init.md` lines 36-56 to see the current config.json template.

- [ ] **Step 2: Insert `models` block into config template**

In the config.json template (Step 4), add the `models` block and `models_note` after `"test_command_note"` and before `"exclude_patterns"`:

```json
  "models": {
    "architect": "opus",
    "builder": "sonnet",
    "archaeologist": "sonnet",
    "mason": "haiku",
    "saboteur": "haiku",
    "prosecutor": "sonnet"
  },
  "models_note": "Model selection per agent role. architect is a session recommendation (not dispatched). Valid values: opus, sonnet, haiku, or a full model ID.",
```

This goes between the `"test_command_note": "Detected from <source>",` line and the `"exclude_patterns": [],` line.

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat(init): seed models block in config template"
```

---

### Task 4: Version bump and final verification

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Bump version in plugin.json**

Change `"version": "0.16.0"` to `"version": "0.17.0"` in `unslop/.claude-plugin/plugin.json`.

- [ ] **Step 2: Verify all changes are consistent**

Run the following checks:

1. Search for `config.models` in generation SKILL.md -- should find exactly 1 match (Builder dispatch)
2. Search for `config.models` in adversarial SKILL.md -- should find exactly 4 matches (one per phase)
3. Search for `"models"` in init.md -- should find exactly 1 match (config template)
4. Verify plugin.json shows `"version": "0.17.0"`

- [ ] **Step 3: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.17.0 for model selection"
```
