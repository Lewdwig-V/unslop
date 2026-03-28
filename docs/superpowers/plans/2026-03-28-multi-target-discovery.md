# Multi-Target Lowering Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the existing multi-target lowering capability in four commands so users can discover it through normal workflow.

**Architecture:** Prose-only changes to four command markdown files (generate, sync, elicit, harden) plus a version bump. No Python script changes, no new tests -- the underlying multi-target machinery already works and is tested.

**Tech Stack:** Markdown command files, plugin.json

---

## File Structure

All modifications, no new files:

| File | Responsibility |
|------|---------------|
| `unslop/commands/generate.md` | Add multi-target Builder hint (line 247, after `blocked-by` bullet) |
| `unslop/commands/sync.md` | Add multi-target Builder hint (line 306, after `blocked-by` bullet) |
| `unslop/commands/elicit.md` | Add conditional multi-target probe (line 99, after Dependencies cross-reference) |
| `unslop/commands/harden.md` | Add multi-target completeness bullet (line 56, after `protected-regions` bullet) |
| `unslop/.claude-plugin/plugin.json` | Version bump 0.47.0 -> 0.48.0 |

---

### Task 1: Add multi-target hint to generate command

**Files:**
- Modify: `unslop/commands/generate.md:247`

- [ ] **Step 1: Add the multi-target Builder hint**

In `unslop/commands/generate.md`, find the `blocked-by` bullet (line 247) that ends with `unlisted constraints are fully binding.` and insert after it:

```markdown
   - If the concrete spec has `targets` (instead of `target-language`): generation dispatches parallel Builders -- one per target. Each Builder receives the same Abstract Spec, `## Strategy`, and `## Type Sketch`, but gets target-specific `## Lowering Notes` and `targets[].notes`. All Builders must succeed for the merge to proceed -- if any fails, all are discarded. See the `unslop/concrete-spec` skill for the full multi-target lowering specification.
```

Note: indent with 3 spaces to match the existing bullet indentation at this nesting level.

- [ ] **Step 2: Verify the edit**

Read lines 245-250 of `unslop/commands/generate.md` and confirm:
- The `protected-regions` bullet is on line 246
- The `blocked-by` bullet is on line 247
- The new `targets` bullet follows on line 248
- The `3. **Verify result:**` line follows after

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "feat(generate): surface multi-target lowering in Builder hints"
```

---

### Task 2: Add multi-target hint to sync command

**Files:**
- Modify: `unslop/commands/sync.md:306`

- [ ] **Step 1: Add the multi-target Builder hint**

In `unslop/commands/sync.md`, find the `blocked-by` bullet (line 306) that ends with `unlisted constraints are fully binding.` and insert after it:

```markdown
- If the concrete spec has `targets` (instead of `target-language`): generation dispatches parallel Builders -- one per target. Each Builder receives the same Abstract Spec, `## Strategy`, and `## Type Sketch`, but gets target-specific `## Lowering Notes` and `targets[].notes`. All Builders must succeed for the merge to proceed -- if any fails, all are discarded. See the `unslop/concrete-spec` skill for the full multi-target lowering specification.
```

Note: no leading spaces -- sync's concrete spec field handling bullets are at root indentation level (matching the existing `protected-regions` and `blocked-by` bullets).

- [ ] **Step 2: Verify the edit**

Read lines 304-310 of `unslop/commands/sync.md` and confirm:
- `**Concrete spec field handling:**` header is on line 304
- The `protected-regions` bullet is on line 305
- The `blocked-by` bullet is on line 306
- The new `targets` bullet follows on line 307
- A blank line separates from `**4. Verify result**`

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "feat(sync): surface multi-target lowering in Builder hints"
```

---

### Task 3: Add conditional multi-target probe to elicit

**Files:**
- Modify: `unslop/commands/elicit.md:99`

- [ ] **Step 1: Add the conditional probe**

In `unslop/commands/elicit.md`, find Phase 3 (Dependencies). After line 99 (`Surface potential \`depends-on\` relationships.`) and before the blank line before Phase 4, insert:

```markdown
- Multi-target lowering (does this spec describe behavior that is plausibly language-agnostic -- a data structure, protocol, algorithm, or shared contract -- where multiple language implementations would derive from the same intent?). If the Architect judges the spec's domain to be language-agnostic, probe:

  > "Does this spec need to target multiple languages or runtimes? If so, the concrete spec can declare `targets` instead of `target-language`, and generation will dispatch parallel Builders -- one per target -- from the same strategy."

  If the user confirms, note for `targets` declaration in the concrete spec. If the user declines or the domain is inherently language-specific (a framework-bound endpoint, a UI component, a platform-specific integration), skip the probe silently.
```

- [ ] **Step 2: Verify the edit**

Read lines 95-110 of `unslop/commands/elicit.md` and confirm:
- Phase 3 header and quote are on lines 95-97
- Cross-reference instruction is on lines 99
- The new multi-target probe follows
- Phase 4 still starts after a blank line

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/elicit.md
git commit -m "feat(elicit): add conditional multi-target lowering probe in Phase 3"
```

---

### Task 4: Add multi-target completeness bullet to harden

**Files:**
- Modify: `unslop/commands/harden.md:56-57`

- [ ] **Step 1: Add the completeness review bullet**

In `unslop/commands/harden.md`, find the `protected-regions` bullet in Step 3 (line 56). After that bullet and before the `principles.md` check (line 58), insert:

```markdown
- Is the spec's behavior language-agnostic (e.g., a data structure, protocol, algorithm, or shared contract) but the concrete spec targets only one language? If the spec constrains behavior that could be lowered to multiple languages from the same strategy, and the concrete spec uses `target-language` rather than `targets`, flag it: "Consider adding: `targets` in the concrete spec (`<impl-path>`) if this behavior needs to be implemented in multiple languages. Currently targeting only `<target-language>`. See the `unslop/concrete-spec` skill for multi-target syntax."
```

- [ ] **Step 2: Verify the edit**

Read lines 54-62 of `unslop/commands/harden.md` and confirm:
- The `protected-regions` bullet is on line 56
- The new `targets` bullet follows on line 57
- The `principles.md` check follows after a blank line

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/harden.md
git commit -m "feat(harden): add multi-target completeness check in Step 3"
```

---

### Task 5: Version bump and final commit

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Bump version**

In `unslop/.claude-plugin/plugin.json`, change line 3:

From:
```json
  "version": "0.47.0",
```

To:
```json
  "version": "0.48.0",
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_orchestrator.py -q
```

Expected: 405 tests pass (no new tests -- this is prose-only).

- [ ] **Step 3: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump version to v0.48.0"
```
