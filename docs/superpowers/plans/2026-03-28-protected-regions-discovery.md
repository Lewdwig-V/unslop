# Protected-Regions/Blocked-By Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface `protected-regions` and `blocked-by` concrete spec fields in commands at the moments they're most relevant, so users discover the capability when it matters.

**Architecture:** Pure markdown command file edits. No Python code changes. Each command gains awareness of one or both fields at the exact point in its pipeline where the field is load-bearing.

**Tech Stack:** Markdown command files, plugin.json version bump.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `unslop/commands/distill.md` | Modify | Add Step 1.6 (tail block detection) + Phase 3 protected-regions message |
| `unslop/commands/harden.md` | Modify | Add protected-regions completeness check to Step 3 |
| `unslop/commands/generate.md` | Modify | Add Builder instructions for both fields |
| `unslop/commands/sync.md` | Modify | Add Builder instructions for both fields |
| `unslop/commands/elicit.md` | Modify | Add regeneration protection probe to Phase 2 |
| `unslop/commands/coherence.md` | Modify | Update description frontmatter |
| `unslop/.claude-plugin/plugin.json` | Modify | Bump to v0.47.0 |

---

### Task 1: distill.md -- Add tail block detection step

**Files:**
- Modify: `unslop/commands/distill.md:78-79`

- [ ] **Step 1: Add Step 1.6 after Step 1.5**

After line 78 (the "Examples of uncertainty triggers" line ending Step 1.5), insert:

```markdown

**Step 1.6: Detect protected regions**

Scan the source file for contiguous tail blocks that serve a different purpose than the implementation above. Common patterns:
- Test suites (e.g., `#[cfg(test)]`, `if __name__ == "__main__"` followed by tests, `describe`/`it` blocks at EOF)
- Main entry guards (`if __name__ == "__main__"`)
- Example code blocks
- Benchmark blocks

For each detected tail block, record: start line, end line (EOF), semantic category (`test-suite`, `entry-point`, `examples`, `benchmarks`), and the marker pattern used to identify it.

If no tail blocks are detected, skip to Phase 2.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/distill.md
git commit -m "fix(distill): add Step 1.6 for tail block detection (protected-regions prerequisite)"
```

---

### Task 2: distill.md -- Add protected-regions message in Phase 3

**Files:**
- Modify: `unslop/commands/distill.md` (Phase 3, after uncertainties list, before approval flow)

- [ ] **Step 1: Add protected-regions presentation**

After the uncertainties block (the line containing `[list each uncertainty with title, observation, and question]`) and before the line `Then offer the approval flow:`, insert:

```markdown

If the Archaeologist detected contiguous tail blocks in Step 1.6, present them explicitly:

> "Protected regions detected:
>
> `<file>`: lines <N>-EOF (`<semantics>` -- `<marker>`)
>
> These blocks will be recorded as `protected-regions` in the concrete spec.
> During future regeneration, the Builder preserves them verbatim -- your
> handwritten code stays untouched. To adjust protection boundaries later,
> edit the `protected-regions` frontmatter in the concrete spec (`<impl-path>`)."

If no tail blocks were detected in Step 1.6, skip this message.

```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/distill.md
git commit -m "fix(distill): surface protected-regions detection to user before spec approval"
```

---

### Task 3: harden.md -- Add protected-regions completeness check

**Files:**
- Modify: `unslop/commands/harden.md:55`

- [ ] **Step 1: Add fifth bullet to Step 3 examination list**

After line 55 (the "For unit specs specifically: are cross-file internal interfaces constrained?" bullet), insert:

```markdown
- Does the managed file have contiguous tail blocks (test suites, main guards, example code) that are NOT declared as `protected-regions` in the concrete spec? If a concrete spec exists without `protected-regions` but the code has obvious tail blocks, future regeneration may overwrite them. Frame as: "Consider adding: `protected-regions` for the <semantics> block (lines N-EOF). Without this declaration, future regeneration may overwrite this code. To declare, add `protected-regions` frontmatter to the concrete spec (`<impl-path>`)."
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/harden.md
git commit -m "fix(harden): check for undeclared protected-regions in completeness review"
```

---

### Task 4: generate.md -- Add Builder instructions for both fields

**Files:**
- Modify: `unslop/commands/generate.md:245`

- [ ] **Step 1: Add concrete spec field awareness after Builder inputs**

After line 245 (the "For Surgical mode: include Existing Code, Spec Diff, and Affected Symbols context blocks." line), insert:

```markdown
   - If the concrete spec has `protected-regions`: the Builder MUST preserve these regions verbatim. Extract the protected region before generation, append it unchanged after generation, and verify the hash matches. See the generation skill's protected-regions protocol.
   - If the concrete spec has `blocked-by` entries: the Builder treats each as an explicit deviation permit. Proceed normally with unblocked constraints. Add code comments at deviation sites: `// blocked-by: <symbol> -- <reason>`.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "fix(generate): add Builder instructions for protected-regions and blocked-by"
```

---

### Task 5: sync.md -- Add Builder instructions for both fields

**Files:**
- Modify: `unslop/commands/sync.md:302`

- [ ] **Step 1: Add concrete spec field awareness after mode selection**

After line 302 (the "Otherwise: **Surgical mode** (default)..." line), insert:

```markdown

**Concrete spec field handling:**
- If the concrete spec has `protected-regions`: the Builder MUST preserve these regions verbatim. Extract the protected region before generation, append it unchanged after generation, and verify the hash matches. See the generation skill's protected-regions protocol.
- If the concrete spec has `blocked-by` entries: the Builder treats each as an explicit deviation permit. Proceed normally with unblocked constraints. Add code comments at deviation sites: `// blocked-by: <symbol> -- <reason>`.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "fix(sync): add Builder instructions for protected-regions and blocked-by"
```

---

### Task 6: elicit.md -- Add regeneration protection probe

**Files:**
- Modify: `unslop/commands/elicit.md:92`

- [ ] **Step 1: Add fifth probe to Phase 2 Constraints**

After line 92 (the "Input validation rules" bullet), insert:

```markdown
- Regeneration protection (are there handwritten regions -- tests, entry points, examples -- that must survive regeneration verbatim? If yes, note for `protected-regions` declaration in the concrete spec)
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/elicit.md
git commit -m "fix(elicit): add regeneration protection probe to Phase 2 Constraints"
```

---

### Task 7: coherence.md -- Update description frontmatter

**Files:**
- Modify: `unslop/commands/coherence.md:2`

- [ ] **Step 1: Update the description**

Change line 2 from:

```markdown
description: Check cross-spec coherence across related specs
```

to:

```markdown
description: Check cross-spec coherence across related specs, including blocked-by constraint tracking
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/coherence.md
git commit -m "fix(coherence): mention blocked-by tracking in command description"
```

---

### Task 8: Version bump + regression test + PR

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3`

- [ ] **Step 1: Bump plugin version**

Change line 3 from:

```json
  "version": "0.46.0",
```

to:

```json
  "version": "0.47.0",
```

- [ ] **Step 2: Run regression tests**

```bash
python -m pytest tests/test_orchestrator.py -q
```

Expected: 405 passed.

- [ ] **Step 3: Commit version bump**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump version to 0.47.0 for protected-regions/blocked-by discovery"
```

- [ ] **Step 4: Create PR**

```bash
gh pr create --title "fix: surface protected-regions and blocked-by in commands (v0.47.0)" --body "$(cat <<'EOF'
## Summary

Surfaces two concrete spec frontmatter fields (`protected-regions` and `blocked-by`) in commands at high-value discovery moments. These fields are fully implemented in the Python layer but no command previously told users they exist.

- **distill**: add Step 1.6 (tail block detection) + surface detected regions to user before spec approval
- **harden**: check for undeclared protected-regions in completeness review
- **generate, sync**: add Builder instructions for both fields
- **elicit**: add regeneration protection probe to Phase 2 Constraints
- **coherence**: mention blocked-by tracking in description

Discovery only -- no new commands, flags, or workflow changes. Follow-on PR will add syntax documentation to the spec-language skill.

Refs unsurfaced capabilities tracked in project memory.

## Test plan

- [x] `python -m pytest tests/test_orchestrator.py -q` -- 405 passed, no regressions
- [ ] Run `/unslop:distill` on a file with a test suite at EOF -- should show "Protected regions detected" message
- [ ] Run `/unslop:harden` on a spec with no protected-regions but code with tail tests -- should suggest adding them
- [ ] Run `/unslop:elicit` -- Phase 2 should probe for regeneration protection
- [ ] Check `/unslop:coherence` description shows blocked-by mention

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
