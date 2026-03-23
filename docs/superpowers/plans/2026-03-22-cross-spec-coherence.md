# Cross-Spec Coherence Checking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cross-spec coherence checking that catches contract contradictions between related specs before generation.

**Architecture:** Two layers -- Phase 0e in the generation skill (lightweight, per-dependency, automatic) and `/unslop:coherence` command (full project-wide audit). Both are model-driven (LLM reads and compares specs), not deterministic. No Python code changes.

**Tech Stack:** Markdown (skills/commands), Claude Code plugin system

**Design Spec:** `docs/superpowers/specs/2026-03-22-cross-spec-coherence.md`

---

### Task 1: Add Phase 0e (Coherence Check) to the generation skill

Phase 0e runs after Phase 0d (Domain Skill Loading) and before Section 1 (Generation Mode Selection). It only fires when the target spec has `depends-on` frontmatter.

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:273-275` (insert new phase between Phase 0d's closing `---` and `## 1. Generation Mode Selection`)

- [ ] **Step 1: Insert Phase 0e section**

In `unslop/skills/generation/SKILL.md`, find the `---` separator after Phase 0d (line 273) and `## 1. Generation Mode Selection` (line 275). Insert the following content between them:

```markdown
### Phase 0e: Cross-Spec Coherence Check

After domain skill loading, check for contract consistency between the target spec and its dependencies. Only runs if the target spec has `depends-on` frontmatter. If the spec has no dependencies, skip to Section 1.

**1. Read the dependency list:**
Parse the target spec's frontmatter for `depends-on` entries. For each listed dependency, read the dependency spec file.

**2. For each dependency spec, check the shared interface:**

> Review the target spec and this dependency spec for cross-spec incoherence. Focus on the boundary where the dependency's outputs become the target's inputs.
>
> Check for:
> - **Type compatibility:** Do the specs agree on the shape of data crossing the boundary?
> - **Constraint compatibility:** Do numeric bounds, cardinality limits, or ordering guarantees agree?
> - **Error contract compatibility:** Do the specs agree on what constitutes an error and how it's signaled?
> - **Naming consistency:** Do the specs use the same names for the same concepts?
>
> Only flag contradictions between what the two specs explicitly state. A missing constraint is an ambiguity problem (Phase 0b), not a coherence problem.
>
> Do NOT flag:
> - Implementation details (algorithm choices, data structure preferences)
> - Style differences ("returns" vs "yields" unless sync/async semantics differ)
> - Constraints that don't cross the boundary between these two specs

**3. For unit specs (`*.unit.spec.md`), also run an intra-unit coherence pass:**
After checking external dependencies, check the contracts between files listed in the `## Files` section. For each pair of files that reference each other's outputs, apply the same coherence checks. This catches cross-file contradictions within a single unit spec that Phase 0b does not detect.

**4. Result handling:**

- **No incoherence found:** Report "Coherence check: specs are consistent." Proceed to Section 1.
- **Incoherence found:** Report each issue with quoted text from both specs:

> "Cross-spec incoherence between `<target-spec>` and `<dependency-spec>`:
> - `<target-spec>` says: [quoted text]
> - `<dependency-spec>` says: [quoted text]
> - Issue: [type mismatch / constraint conflict / naming mismatch] -- [brief explanation of why this will break generated code].
>
> Fix one of the specs to resolve the contradiction, then re-run."

**Stop generation** on incoherence. There is no `--force-incoherent` override -- coherence failures indicate real contract mismatches that will produce broken code.

---
```

- [ ] **Step 2: Update Phase 0d's closing text**

In Phase 0d, the last line currently says "If no domain skills match, this phase is a no-op. Proceed to Section 1." Change the destination to Phase 0e:

Find: `If no domain skills match, this phase is a no-op. Proceed to Section 1.`
Replace: `If no domain skills match, this phase is a no-op. Proceed to Phase 0e.`

- [ ] **Step 3: Verify document flow**

Read the generation skill from Phase 0d through Section 1 and verify:
1. Phase 0d ends with "Proceed to Phase 0e"
2. Phase 0e section is present between the `---` and `## 1.`
3. Phase 0e ends with "Proceed to Section 1" (on no incoherence)
4. No duplicate `---` separators

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Phase 0e (cross-spec coherence check) to generation skill

Checks target spec against its depends-on dependencies for contract
contradictions before Builder dispatch. Also runs intra-unit coherence
for unit specs. Blocks generation on incoherence -- no force override."
```

---

### Task 2: Create `/unslop:coherence` command

The standalone command for full project-wide coherence audits. Supports targeted mode (single spec, both directions) and full mode (all specs).

**Files:**
- Create: `unslop/commands/coherence.md`

- [ ] **Step 1: Write the command file**

Create `unslop/commands/coherence.md` with the following content:

```markdown
---
description: Check cross-spec coherence across related specs
argument-hint: "[spec-path]"
---

**Parse arguments:** `$ARGUMENTS` may contain an optional spec path. If present, run in targeted mode. If absent, run in full mode.

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Build the dependency graph**

Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py build-order .` to get the full dependency graph. If the orchestrator reports a cycle, stop and report the error.

If no specs have `depends-on` frontmatter, report:

> "No dependency relationships found. Coherence checking requires specs with `depends-on` frontmatter."

**3. Run coherence checks**

**Targeted mode** (spec path provided):

1. Verify the spec file exists. If not, stop: "Spec not found at `<path>`."
2. Resolve upstream dependencies: `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .`
3. Resolve reverse dependents: scan all `*.spec.md` files in the project for `depends-on` entries that reference the target spec path.
4. For each upstream dependency: read both specs and check for incoherence (same checks as Phase 0e in the generation skill -- type compatibility, constraint compatibility, error contract compatibility, naming consistency).
5. For each reverse dependent: read both specs and check for incoherence.
6. If the target is a unit spec (`*.unit.spec.md`): also run the intra-unit coherence pass on files listed in `## Files`.

**Full mode** (no arguments):

1. For each dependency edge in the build-order graph: read both specs and check for incoherence.
2. For each unit spec: run the intra-unit coherence pass.

**4. Report results**

Display results in this format:

```
Cross-spec coherence check:

  <spec-a> <-> <spec-b>
    ✓ consistent

  <spec-c> <-> <spec-d>
    ✗ <issue-type>: <brief description>

  <unit-spec> (intra-unit)
    ✓ consistent

N incoherence(s) found across M dependency pairs.
```

For each incoherence, include:
- The two specs (or unit spec name for intra-unit issues)
- The issue type (naming mismatch, type mismatch, constraint conflict, error contract mismatch)
- Quoted text from both specs showing the contradiction
- A brief explanation of why this will break generated code

If no incoherences are found:

> "All specs are coherent. 0 incoherences across N dependency pairs."

**5. This command is read-only**

Do not modify any files, generate any code, or run any tests. This is an audit command.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/coherence.md
git commit -m "feat: add /unslop:coherence command for project-wide audits

Targeted mode checks a single spec in both directions (upstream deps
and reverse dependents). Full mode checks all dependency pairs.
Read-only audit -- no file modifications."
```

---

### Task 3: Add coherence route to triage skill and hook

The triage skill and load-context hook need to know about `/unslop:coherence` so the model can route users to it.

**Files:**
- Modify: `unslop/skills/triage/SKILL.md:36-37` (add coherence section after hardening)
- Modify: `unslop/hooks/scripts/load-context.sh:50-51` (add coherence line to routing table)

- [ ] **Step 1: Add coherence section to triage skill**

In `unslop/skills/triage/SKILL.md`, after the Hardening Prompt section (after line 36), insert:

```markdown

## The Coherence Check

If the user is working with multiple related specs and asks about consistency, contract mismatches, or whether specs agree with each other, route to coherence.

**Pattern:** "Do these specs agree?", "Is this consistent with the auth spec?", "Check if my specs contradict each other"
**Route:** `/unslop:coherence` (all specs) or `/unslop:coherence <spec-path>` (targeted, checks both upstream and downstream)
```

- [ ] **Step 2: Add coherence line to load-context hook**

In `unslop/hooks/scripts/load-context.sh`, add a new line after the harden routing entry (after the line containing `harden`). Add:

```bash
- Cross-spec consistency: \`/unslop:coherence\` (all) or \`/unslop:coherence <spec-path>\` (targeted)
```

- [ ] **Step 3: Test the hook output**

```bash
tmpdir=$(mktemp -d) && mkdir -p "$tmpdir/.unslop" && echo '{"test_command": "pytest"}' > "$tmpdir/.unslop/config.json" && printf '# alignment\n\n## Managed files\n\nNone.\n' > "$tmpdir/.unslop/alignment-summary.md" && CLAUDE_PROJECT_DIR="$tmpdir" bash unslop/hooks/scripts/load-context.sh < /dev/null | grep coherence && rm -rf "$tmpdir"
```

Expected: line containing `/unslop:coherence`

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/triage/SKILL.md unslop/hooks/scripts/load-context.sh
git commit -m "feat: add coherence route to triage skill and session hook

Routes 'do these specs agree?' intent to /unslop:coherence.
Persists across context compaction via the routing table in load-context.sh."
```

---

### Task 4: Update version and validate

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3` (version bump)

- [ ] **Step 1: Bump version to 0.10.0**

In `unslop/.claude-plugin/plugin.json`, change `"version": "0.9.0"` to `"version": "0.10.0"`.

- [ ] **Step 2: Run full test suite**

```bash
cd /home/lewdwig/git/unslop && python -m pytest tests/ -v
```

Expected: All 102 tests pass (no Python changes, no regressions)

- [ ] **Step 3: Lint**

```bash
cd /home/lewdwig/git/unslop && ruff check unslop/scripts/ tests/
```

Expected: Clean

- [ ] **Step 4: Cross-reference audit**

Verify:
1. `generation/SKILL.md` Phase 0d says "Proceed to Phase 0e" (not "Section 1")
2. `generation/SKILL.md` Phase 0e exists between Phase 0d and Section 1
3. `coherence.md` references `orchestrator.py deps` and `orchestrator.py build-order` -- both exist
4. `triage/SKILL.md` has a coherence section
5. `load-context.sh` has a coherence line in the routing table
6. `plugin.json` version is `0.10.0`

```bash
grep -n "Phase 0e" unslop/skills/generation/SKILL.md | head -5
grep -n "coherence" unslop/commands/coherence.md | head -3
grep -n "coherence" unslop/skills/triage/SKILL.md | head -3
grep -n "coherence" unslop/hooks/scripts/load-context.sh
grep "version" unslop/.claude-plugin/plugin.json
```

- [ ] **Step 5: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump version to 0.10.0 for cross-spec coherence"
```
