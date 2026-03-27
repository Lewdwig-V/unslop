# Worktree-Isolated Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace prompt-based "no peeking" enforcement with physical worktree isolation for all code generation, implementing the two-stage Architect/Builder execution model.

**Architecture:** Stage A (Architect) runs in the user's session -- processes change intent, updates specs, stages but does not commit. Stage B (Builder) runs as a fresh Agent with `isolation: "worktree"` -- generates code from spec only, runs tests. On success, worktree merges and spec+code commit atomically. On failure, worktree is discarded and staged spec reverted.

**Tech Stack:** Python 3.8+ (orchestrator), Markdown (skills/commands), pytest (tests), Claude Code Agent tool with `isolation: "worktree"`

**Design Spec:** `docs/superpowers/specs/2026-03-22-worktree-isolation-design.md`

---

### Task 1: Add `file-tree` subcommand to orchestrator

The Architect stage needs a file listing (names only, no contents) to reference correct paths without seeing implementation. This is a lightweight wrapper around `git ls-files`.

**Files:**
- Modify: `unslop/scripts/orchestrator.py:597-689` (add subcommand to `main()`, add `file_tree()` function)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test for `file_tree()`**

```python
def test_file_tree_returns_tracked_files(tmp_path):
    """file_tree should return git-tracked filenames as a JSON-serializable list."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "util.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("# readme")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp_path, capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )

    from orchestrator import file_tree
    result = file_tree(str(tmp_path))
    assert isinstance(result, list)
    assert "src/main.py" in result
    assert "src/util.py" in result
    assert "README.md" in result


def test_file_tree_excludes_untracked(tmp_path):
    """Untracked files should not appear in file_tree output."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "tracked.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp_path, capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    (tmp_path / "untracked.py").write_text("y = 2")

    from orchestrator import file_tree
    result = file_tree(str(tmp_path))
    assert "tracked.py" in result
    assert "untracked.py" not in result


def test_file_tree_nonexistent_directory():
    """file_tree should raise ValueError for nonexistent directories."""
    from orchestrator import file_tree
    import pytest
    with pytest.raises(ValueError, match="Directory does not exist"):
        file_tree("/nonexistent/path")


def test_file_tree_not_a_git_repo(tmp_path):
    """file_tree should raise ValueError for non-git directories."""
    from orchestrator import file_tree
    import pytest
    with pytest.raises(ValueError, match="Not a git repository"):
        file_tree(str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "file_tree" -v`
Expected: FAIL with `ImportError: cannot import name 'file_tree'`

- [ ] **Step 3: Implement `file_tree()` function**

Add to `unslop/scripts/orchestrator.py` before the `main()` function:

```python
def file_tree(directory: str) -> list[str]:
    """List git-tracked files in directory.

    Returns sorted list of tracked filenames relative to the directory.
    Used by the Architect stage to see file names without file contents.
    """
    import subprocess as _subprocess

    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    try:
        result = _subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except _subprocess.CalledProcessError:
        raise ValueError(f"Not a git repository: {directory}")

    files = [f for f in result.stdout.strip().split("\n") if f]
    return sorted(files)
```

- [ ] **Step 4: Add CLI subcommand to `main()`**

Add to the `main()` function's command dispatch, after the `check-freshness` block:

```python
    elif command == "file-tree":
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        try:
            result = file_tree(directory)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
```

Update the usage string in `main()` to include `file-tree`:

```python
print("Usage: orchestrator.py <discover|build-order|deps|check-freshness|file-tree> [args]", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/test_orchestrator.py -k "file_tree" -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 7: Lint**

Run: `cd /home/lewdwig/git/unslop && ruff check unslop/scripts/orchestrator.py tests/test_orchestrator.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add unslop/scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add file-tree subcommand to orchestrator

Lists git-tracked filenames for the Architect stage's context.
Returns JSON array of relative paths, no file contents."
```

---

### Task 2: Rewrite generation skill for two-stage execution model

This is the architectural core. The generation skill needs to describe the Architect/Builder split, commit atomicity, `{test_policy}` parameterization, and Phase 0c decomposition. The skill becomes the authoritative reference that all commands follow.

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:1-360` (major rewrite)

- [ ] **Step 1: Add Two-Stage Execution Model section**

Insert a new section after the YAML frontmatter and before Section 0, titled `## Execution Model: Two-Stage Worktree Isolation`. This section defines:

- Stage A (Architect): runs in user session. Inputs: change intent, spec, principles, file tree (via `orchestrator.py file-tree`). Blocked from: source code, test files. Output: staged spec update (NOT committed).
- Stage B (Builder): fresh Agent with `isolation: "worktree"`. Inputs: spec, principles, config, existing source code, test files. Blocked from: change intent, conversation history.
- Commit atomicity: spec update staged but not committed. On Builder success, spec + code commit atomically. On failure, `git checkout HEAD -- <spec_path>` reverts the staged spec.
- Verification: check Agent result status (DONE/DONE_WITH_CONCERNS/BLOCKED). Auto-merge on green tests. Discard worktree + revert spec on failure.

Content to add (insert after frontmatter, before `## 0. Pre-Generation Validation`):

```markdown
## Execution Model: Two-Stage Worktree Isolation

All code generation uses a two-stage model with physical worktree isolation. No exceptions.

### Stage A: Architect (Current Session)

The Architect processes change intent and updates the spec. It runs in the user's current session.

**Inputs:**
- Change request intent (from `*.change.md` or user prompt)
- Current `*.spec.md`
- `.unslop/principles.md`
- File tree (`python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py file-tree .`) -- names only, no contents

**Blocked from:**
- Reading source code files
- Reading test files

**Output:**
- Updated `*.spec.md` (staged via `git add`, NOT committed)
- User approves the spec update before Stage B

**Commit atomicity:** The Architect's spec update is written to disk and staged (`git add`) but NOT committed. The spec and generated code are committed together as a single atomic commit after the Builder succeeds and the worktree is merged. If the Builder fails, the spec update is reverted (`git checkout HEAD -- <spec_path>`), leaving main truly untouched.

**Exception:** During `/unslop:takeover`, the Architect reads existing source code and tests -- the point of takeover is extracting intent FROM code. Stage B still runs in a clean worktree.

### Stage B: Builder (Fresh Agent, Worktree Isolation)

The Builder generates code from the spec. It runs as a fresh Agent in an isolated git worktree with zero conversation history.

**Dispatch:**

```python
Agent(
    description="Implement spec changes in isolated worktree",
    isolation="worktree",
    prompt="""You are implementing changes to managed files based on their specs.

    Target spec: {spec_path}
    Test command: {test_command}

    Instructions:
    1. Read the spec at {spec_path}
    2. Read .unslop/principles.md if it exists
    3. Implement the code to match the spec exactly
    4. {test_policy}
    5. Run tests: {test_command}
    6. If tests pass, report DONE with the list of changed files
    7. If tests fail, iterate until green or report BLOCKED

    The spec is your sole source of truth. Do not look for or follow
    any change requests. If the spec seems incomplete, report
    DONE_WITH_CONCERNS describing what appears to be missing."""
)
```

**`{test_policy}` values by originating command:**
- **takeover:** `"Write or extend tests as needed for newly explicit constraints"`
- **generate / sync:** `"Do NOT create or modify test files. Use existing tests for validation only"`
- **change (tactical):** `"Extend tests if the spec update introduced new constraints that lack coverage. Do not modify existing assertions"`

### Verification (Controlling Session)

After the Builder Agent completes:
1. Check result status: DONE / DONE_WITH_CONCERNS / BLOCKED
2. If DONE with green tests: Claude Code handles worktree merge automatically
3. Compute `output-hash` on merged code, update `@unslop-managed` header
4. Commit the staged spec update + merged code as a single atomic commit

If BLOCKED or tests fail: discard the worktree AND revert the staged spec update (`git checkout HEAD -- <spec_path>`). Main branch is untouched.

### Builder Failure Reports

When the Builder reports BLOCKED or test failures, it must provide a structured post-mortem:

```markdown
## Builder Failure Report

### Failing Tests
- <test_name>: <assertion message>

### What Was Attempted
<Builder's interpretation of the spec and what it implemented>

### Suspected Spec Gaps
- <What the spec is silent on that caused the failure>
```

The Builder identifies gaps only -- it does NOT suggest spec language. The Architect decides how to constrain gaps because it thinks in requirements, not code.

### Convergence Loop

For takeover, the convergence loop crosses the stage boundary:

1. Stage A: Draft/enrich spec -> user approves
2. Stage B: Generate in worktree -> tests fail -> structured failure report
3. Stage A: Enrich spec based on failure report -> user approves
4. Stage B: New fresh Agent, new worktree -> generate -> tests pass -> merge

Each Stage B is a fresh Agent dispatch. Maximum 3 iterations.

### Commands Without an Architect Stage

For `generate` and `sync`, there is no Architect stage for spec authoring -- the spec is already the input. However, if pending `*.change.md` entries exist, the controlling command still runs Phase 0c (Stage A behavior) to absorb changes into the spec before dispatching the Builder. The Builder always runs in a worktree to ensure:
- The model generating code never has conversation history
- Every generation starts with a clean context
- File system isolation is the default

---
```

- [ ] **Step 2: Rewrite Phase 0c for Stage A decomposition**

Replace the current Phase 0c content (lines 76-113) with the split-stage version:

```markdown
### Phase 0c: Change Request Consumption (Stage A Only)

Under two-stage isolation, Phase 0c runs ONLY in Stage A (Architect). The Builder skips Phase 0c entirely -- by the time the Builder runs, all change requests have been absorbed into the spec.

When running in worktree isolation (which is always), the Builder's generation skill omits Phase 0c.

**Stage A behavior:**

Check for a `*.change.md` sidecar file for the target managed file.

If no change file exists, skip to Phase 0d.

If change entries exist:

**1. Conflict detection (model-driven):** Review each entry's intent against the current spec. If any entry contradicts the spec, surface the conflict:

> "Change request conflicts with current spec: [quote entry] vs [quote spec]. Resolve before proceeding."

Stop until resolved.

**2. For each `[pending]` entry:**
- Propose a spec update that captures the entry's intent
- Present to user: "This change request suggests updating the spec as follows: [diff]. Approve?"
- On approval: apply spec update, stage it (`git add`), continue
- On rejection: skip this entry

**3. For each `[tactical]` entry:**
- Propose a spec update (tactical now means "do it now", not "code first")
- Present to user for approval
- On approval: apply spec update, stage it (`git add`), continue
- On rejection: skip this entry

**4. After processing:**
- Delete each promoted entry from the change.md file
- If file is empty, delete it entirely
- All spec updates are staged but NOT committed -- they commit atomically with the Builder's output

**Note:** The controlling command (generate/sync/change) dispatches the Builder AFTER Phase 0c completes for all files with pending changes.
```

- [ ] **Step 3: Update Section 1 (Mode Selection) for worktree context**

Add a note at the end of Mode A's "Prohibited reads" section:

```markdown
**Worktree context:** In worktree isolation (all generation), Mode A is the natural fit. The Builder starts with a clean context and generates from the spec. The worktree contains the current codebase state but the Builder is instructed not to read the existing managed file.
```

Add a note at the end of Mode B's section:

```markdown
**Worktree context:** In worktree isolation, Mode B means the Builder reads the existing managed file in the worktree and produces targeted edits. The Builder still has no access to change request intent or conversation history. The `--incremental` flag is passed through to the Builder Agent's prompt:
- Without `--incremental`: "Generate the managed file from the spec. Do not read the existing file."
- With `--incremental`: "Update the managed file to match the updated spec. Read the existing file and make targeted edits only."
```

- [ ] **Step 4: Update Section 3 (TDD) for test-writing policy**

Replace the existing note at line 279 with the policy-aware version:

```markdown
**Test-writing policy (enforced via `{test_policy}` in Builder prompt):**
- **Takeover:** Builder may write or extend tests for newly explicit constraints.
- **Generate/Sync:** Builder uses existing tests for validation only. Does NOT create or modify test files. This prevents the Builder from weakening assertions to make bad code pass.
- **Change (tactical):** Builder may extend tests for new constraints but must not modify existing assertions.
```

- [ ] **Step 5: Add Section on Unit Specs under worktree isolation**

After Section 6 (Multi-File Generation), add:

```markdown
**Worktree context:** For unit specs, the Builder generates all files listed in `## Files` within the same worktree session. The worktree captures all changes as a single atomic diff.
```

- [ ] **Step 6: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: rewrite generation skill for two-stage worktree isolation

Adds Execution Model section defining Architect/Builder split.
Rewrites Phase 0c for Stage A decomposition.
Adds {test_policy} parameterization per originating command.
Adds Builder Failure Report structure.
Adds convergence loop across stage boundary."
```

---

### Task 3: Rewrite `change.md` command for two-stage tactical flow

The tactical flow changes from "code first, spec later" to "spec first, then Builder executes." The `--tactical` flag now means "do it now" rather than "defer to next generate."

**Files:**
- Modify: `unslop/commands/change.md:98-119` (Step 5: Execute or defer)

- [ ] **Step 1: Rewrite Step 5 (Execute or defer) for two-stage tactical**

Replace the current Step 5 content (lines 98-119) with:

```markdown
**5. Execute or defer**

**If `--tactical` was passed**, execute the two-stage tactical flow immediately:

**Stage A (Architect -- current session):**
1. Read the current spec, `.unslop/principles.md` (if it exists), and the file tree (`python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py file-tree .`). Do NOT read the managed source file.
2. Based on the change intent, propose a spec update that captures the change in the spec's constraints/behavior language. Do not describe implementation -- describe intent.
3. Present the draft spec update to the user for approval.
4. If approved: apply the spec update to the spec file, stage it (`git add <spec_path>`). Do NOT commit.
5. If rejected: stop. The entry remains in `<file>.change.md` for manual resolution.

**Stage B (Builder -- worktree isolation):**
6. Dispatch a Builder Agent using the generation skill's two-stage execution model. Use test_policy: `"Extend tests if the spec update introduced new constraints that lack coverage. Do not modify existing assertions"`.
7. The Builder implements from the updated spec in an isolated worktree, runs tests.

**Verification (back in controlling session):**
8. If Builder succeeds (DONE, green tests):
   a. Worktree merges automatically.
   b. Compute `output-hash` on the merged code, update `@unslop-managed` header (including `spec-hash`, `output-hash`, `principles-hash`).
   c. Delete the tactical entry from `<file>.change.md` (if file is now empty, delete the sidecar entirely).
   d. Commit the spec update + generated code + sidecar change as a single atomic commit.
9. If Builder fails (BLOCKED or tests fail):
   a. Discard the worktree.
   b. Revert the staged spec update: `git checkout HEAD -- <spec_path>`.
   c. Report the Builder's failure report (failing tests, what was attempted, suspected spec gaps).
   d. The entry remains in `<file>.change.md`.

**If `[pending]` (default, no `--tactical` flag)**, inform the user:

> "Change recorded in `<file>.change.md`. Run `/unslop:generate` or `/unslop:sync <file>` to apply."
```

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/change.md
git commit -m "feat: rewrite tactical flow for two-stage worktree isolation

Tactical now means 'spec first, then Builder in worktree' instead of
'code first, spec later'. Architect proposes spec update, Builder
implements in isolation. Atomic commit on success, full revert on failure."
```

---

### Task 4: Rewrite `generate.md` command for worktree Builder dispatch

The generate command becomes a dispatcher: it classifies files, runs Stage A (Phase 0c) for files with pending changes, then dispatches Builders in worktrees.

**Files:**
- Modify: `unslop/commands/generate.md:1-93` (full rewrite of steps 3-7)

- [ ] **Step 1: Rewrite Steps 3b-5 for two-stage dispatch**

Replace the current processing logic (steps 3b through 5, lines 28-76) to add Stage A and Builder dispatch:

```markdown
**3b. Resolve build order**

(Unchanged -- keep existing build-order logic.)

**3c. Stage A: Process pending changes (Architect)**

Before dispatching any Builders, run Phase 0c for ALL files that have pending `*.change.md` entries:

1. For each file with a `*.change.md` sidecar (in build order):
   a. Run the generation skill's Phase 0c (Stage A behavior) -- propose spec updates for each pending/tactical entry, get user approval.
   b. Stage approved spec updates (`git add`). Do NOT commit.
2. After all Phase 0c processing is complete, proceed to classification and Builder dispatch.

This ensures all spec updates are finalized before any code generation begins.

**4. Classify each spec file**

(Unchanged -- keep existing classification logic.)

**5. Dispatch Builders (Stage B -- worktree isolation)**

For each file classified as new, stale, modified (confirmed), or conflict (confirmed), in build order:

1. **Select generation mode.** New files always use Mode A. For others, default is Mode A; use Mode B if `--incremental` was passed.
2. **Dispatch a Builder Agent** using the generation skill's two-stage execution model:
   - test_policy: `"Do NOT create or modify test files. Use existing tests for validation only"`
   - Pass `--incremental` to the Builder prompt if Mode B was selected.
3. **Verify result:**
   - If DONE with green tests: worktree merges automatically. Compute `output-hash`, update header.
   - If BLOCKED or tests fail: discard worktree, revert any staged spec update for this file (`git checkout HEAD -- <spec_path>`). Report failure and **stop immediately**. Do not process remaining files.
4. If a dependency was regenerated in this run, mark its dependents as stale even if their own specs haven't changed.

If cascading regeneration of a dependent causes Builder failure, stop and report: which upstream regeneration caused the failure, which dependent broke, and the Builder's failure report.
```

- [ ] **Step 2: Update Step 7 (Commit) for atomic commit**

Replace the current commit step:

```markdown
**7. Commit**

After all Builders have succeeded and worktrees are merged, commit all changes atomically:
- All staged spec updates (from Phase 0c)
- All merged generated code (from Builder worktrees)
- Updated alignment summary

This is a single atomic commit covering all files processed in this run.
```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "feat: rewrite generate command for worktree Builder dispatch

Stage A processes all pending changes first (Phase 0c).
Stage B dispatches Builders per file in build order.
Single atomic commit after all Builders succeed."
```

---

### Task 5: Rewrite `sync.md` command for worktree Builder dispatch

The sync command is simpler than generate (single file, no Phase 0c batch), but still needs Builder dispatch.

**Files:**
- Modify: `unslop/commands/sync.md:1-68` (rewrite steps 3-6)

- [ ] **Step 1: Rewrite Steps 3-4 for two-stage dispatch**

Replace the current generation and test logic (steps 3-4, lines 34-52):

```markdown
**3. Classify and dispatch**

Classify the target file using hash-based logic (same as `/unslop:generate`).

For **modified** files: warn the user. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.
For **conflict** files: warn the user. If `--force` was passed, proceed. Otherwise, ask for confirmation. If declined, stop.

**Stage A (Architect -- if pending changes exist):**
If a `*.change.md` sidecar exists for this file with pending entries, run the generation skill's Phase 0c (Stage A behavior):
- Propose spec updates for each entry, get user approval.
- Stage approved spec updates (`git add`). Do NOT commit.

**Stage B (Builder -- worktree isolation):**
Dispatch a Builder Agent using the generation skill's two-stage execution model:
- test_policy: `"Do NOT create or modify test files. Use existing tests for validation only"`
- If `--incremental` was passed: pass through to Builder prompt for Mode B.
- If the managed file does not yet exist: always Mode A.

**4. Verify result**

- If DONE with green tests: worktree merges automatically. Compute `output-hash`, update `@unslop-managed` header.
- If BLOCKED or tests fail: discard worktree, revert any staged spec update (`git checkout HEAD -- <spec_path>`). Report the Builder's failure report and stop. Do not attempt to fix or retry.
```

- [ ] **Step 2: Update Step 6 (Commit) for atomic commit**

Replace the current commit step:

```markdown
**6. Commit**

After Builder success and worktree merge, commit atomically:
- Staged spec update (if Phase 0c ran)
- Merged generated code
- Updated alignment summary
```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "feat: rewrite sync command for worktree Builder dispatch

Single-file two-stage flow: optional Phase 0c, then Builder in worktree.
Atomic commit on success, full revert on failure."
```

---

### Task 6: Rewrite `takeover.md` command and skill for worktree isolation

Takeover is the most complex case: the Architect reads existing code (exception to the normal rule), drafts a spec, then the Builder generates in a worktree. The convergence loop crosses the stage boundary.

**Files:**
- Modify: `unslop/commands/takeover.md:34-74` (single-file and multi-file modes)
- Modify: `unslop/skills/takeover/SKILL.md:84-140` (Steps 4-6: Generate, Validate, Convergence. Leave Abandonment State at line 143+ untouched.)

- [ ] **Step 1: Update takeover skill Steps 4-6 for worktree Builder**

Replace Steps 4-6 in `unslop/skills/takeover/SKILL.md` (lines 84-140 only -- preserve the `## Abandonment State` section at line 143 and everything after it):

```markdown
## Step 4: Generate (Stage B -- Builder in Worktree)

Use the **unslop/generation** skill's two-stage execution model.

**CRITICAL: Takeover always uses full regeneration mode (Mode A). The Builder does NOT read the archived original.**

Dispatch a Builder Agent with:
- test_policy: `"Write or extend tests as needed for newly explicit constraints"`
- Mode A (full regeneration) -- always, no incremental for takeover
- The spec path as the sole source of truth

The Architect stage (Steps 1-2) already ran in the user's session -- it read the code, drafted the spec, and got user approval. The Builder starts fresh with zero knowledge of the original code.

---

## Step 5: Validate (Verification in Controlling Session)

After the Builder Agent completes:

**If DONE with green tests:**

- Worktree merges automatically
- Compute `output-hash` on merged code, update `@unslop-managed` header
- Commit the spec file and the generated file together as a single atomic commit
- Report success to the calling command

**If BLOCKED or tests fail:**

- Discard the worktree
- Enter the convergence loop (Step 6) using the Builder's failure report

---

## Step 6: Convergence Loop (Cross-Stage)

Maximum **3 iterations**. Track the iteration count.

For each iteration:

a. **Read the Builder's failure report** -- failing test names, assertion messages, what was attempted, suspected spec gaps. Do NOT request raw test output or code snippets.

b. **Enrich the spec (Stage A)** -- Based on the failure report's suspected spec gaps, add missing constraints in spec-language voice. The Architect identifies gaps only -- it does NOT copy implementation suggestions from the Builder.

c. **Get user approval** -- Present the enriched spec to the user. Wait for approval.

d. **Stage the spec update** -- `git add <spec_path>`. Do NOT commit.

e. **Dispatch a new Builder (Stage B)** -- Fresh Agent, new worktree. The Builder never knows why the spec changed. test_policy: `"Write or extend tests as needed for newly explicit constraints"`.

f. **Verify** -- Same as Step 5. If green: commit atomically, done. If red: next iteration.

**If maximum iterations reached:** discard the worktree, revert the staged spec update. Present:
- The Builder's latest failure report
- What constraints were added during convergence
- The archive location for manual recovery

Then ask the user for guidance.
```

- [ ] **Step 2: Update takeover command single-file mode**

In `unslop/commands/takeover.md`, update the single-file mode section (lines 34-60) to reference the two-stage model:

```markdown
**Single-file mode**

**2. Load context**

Read `.unslop/config.json` to obtain the test command.

**3. Run the takeover pipeline (two-stage)**

Use the **unslop/takeover** skill. The pipeline now operates in two stages:
- **Stage A (Architect -- current session):** Steps 1-3 of the takeover skill (Discover, Draft Spec, Archive). The Architect reads the existing code and tests to draft the spec. This is the exception where the Architect sees source code.
- **Stage B (Builder -- worktree):** Steps 4-6 of the takeover skill (Generate, Validate, Convergence). Each Builder dispatch runs in an isolated worktree.

The spec update is staged but not committed until the Builder succeeds. On convergence failure, the staged spec is reverted.

Use the **unslop/spec-language** skill for spec drafting guidance.
Use the **unslop/generation** skill for the Builder's code generation discipline.
```

- [ ] **Step 3: Update takeover command multi-file mode**

In the multi-file mode section (lines 63-74), add worktree context:

```markdown
**Multi-file mode**

(Steps 1-2 unchanged -- discovery and user confirmation.)

3. After confirmation, use the **unslop/takeover** skill in multi-file mode. Each Builder dispatch (Step 4) runs in an isolated worktree. For per-file mode, Builders are dispatched in build order. For per-unit mode, a single Builder generates all files in one worktree session.
4-7. (Unchanged -- spec-language skill, generation skill, test command, alignment summary.)
```

- [ ] **Step 4: Update convergence loop in multi-file mode**

In `unslop/skills/takeover/SKILL.md`, update the multi-file convergence section (lines 208-214):

```markdown
### Convergence Loop (Step 6 -- updated)

The loop works the same as single-file mode with these changes:
- Each convergence iteration dispatches a fresh Builder Agent in a new worktree
- Enrich whichever spec(s) are relevant to the failing tests (based on the Builder's failure report)
- **Do NOT change `depends-on` frontmatter during convergence**
- Regenerate only files whose specs were enriched, plus dependents (check build order)
- For per-unit specs: the Builder generates all files in a single worktree session
- On convergence failure: discard the worktree, revert all staged spec updates
```

- [ ] **Step 5: Commit**

```bash
git add unslop/commands/takeover.md unslop/skills/takeover/SKILL.md
git commit -m "feat: rewrite takeover for cross-stage convergence loop

Architect (Steps 1-3) runs in user session, reads code to draft spec.
Builder (Steps 4-6) runs in worktree, generates from spec only.
Convergence loop crosses stage boundary with fresh Agent each iteration.
Builder failure reports provide structured post-mortem for spec enrichment."
```

---

### Task 7: Update version and plugin metadata

Bump the version to reflect the breaking execution model change.

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json:3` (version bump)
- Modify: `unslop/commands/init.md:122,125` (vendored orchestrator version marker)

- [ ] **Step 1: Bump version to 0.9.0**

In `unslop/.claude-plugin/plugin.json`, change:
```json
"version": "0.9.0"
```

This is a significant behavioral change (all generation now uses worktree isolation) but not a 1.0 since the user-facing command API is unchanged.

- [ ] **Step 2: Update vendored orchestrator version marker**

In `unslop/commands/init.md`, update the version marker reference from `v0.8.0` to `v0.9.0` (two occurrences -- the version comment and the version check).

- [ ] **Step 3: Commit**

```bash
git add unslop/.claude-plugin/plugin.json unslop/commands/init.md
git commit -m "chore: bump version to 0.9.0 for worktree isolation"
```

---

### Task 8: Add orphaned worktree cleanup to generation skill

The design spec (lines 177-179) requires that each generation command checks for orphaned unslop worktrees and offers cleanup. Worktrees use the `unslop/builder/<timestamp>` branch naming convention.

**Files:**
- Modify: `unslop/skills/generation/SKILL.md` (add cleanup section to Execution Model)

- [ ] **Step 1: Add orphaned worktree cleanup section**

Add the following after the "Convergence Loop" section in the Execution Model, before the `---` separator:

```markdown
### Orphaned Worktree Cleanup

On each generation command invocation, before dispatching any Builder, check for orphaned unslop worktrees:

1. Run `git worktree list --porcelain`
2. Look for worktrees on branches matching `unslop/builder/*`
3. If any are found, report them to the user:

> "Found N orphaned unslop worktree(s) from previous runs. Clean up? (y/n)"

4. If the user confirms: run `git worktree remove <path>` for each, then `git branch -D <branch>` for each
5. If the user declines: proceed without cleanup

Only worktrees matching the `unslop/builder/*` pattern are flagged. User-created worktrees are never touched.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add orphaned worktree cleanup to generation skill

Checks for unslop/builder/* worktrees before each generation run.
Offers cleanup for leaked worktrees from crashed Agent runs."
```

---

### Task 9: Integration validation

Verify all changes work together and no cross-references are broken.

**Files:**
- Read: all modified files (no new modifications expected)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Run full test suite**

Run: `cd /home/lewdwig/git/unslop && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Lint all Python files**

Run: `cd /home/lewdwig/git/unslop && ruff check unslop/scripts/ tests/`
Expected: No errors

- [ ] **Step 3: Cross-reference audit**

Verify that:
1. `generation/SKILL.md` references `orchestrator.py file-tree` -- and the subcommand exists
2. `change.md` references the generation skill's "two-stage execution model" section -- and that section exists
3. `generate.md` references "Phase 0c (Stage A behavior)" -- and Phase 0c mentions Stage A
4. `sync.md` references "Phase 0c (Stage A behavior)" -- same check
5. `takeover.md` references takeover skill Steps 4-6 -- and those steps describe Builder dispatch
6. `takeover/SKILL.md` references "Builder failure report" structure -- and that structure is defined in generation skill
7. `plugin.json` version is `0.9.0`
8. `init.md` version marker references `v0.9.0`
9. No command or skill references the old "code first, spec later" tactical flow

Run: `cd /home/lewdwig/git/unslop && grep -rn "code first" unslop/ || echo "Clean"`
Run: `cd /home/lewdwig/git/unslop && grep -rn "heal step" unslop/ || echo "Clean"`
Run: `cd /home/lewdwig/git/unslop && grep -rn "patch code and propose spec" unslop/ || echo "Clean"`
Expected: "Clean" for all three (no remnants of old tactical flow)

- [ ] **Step 4: Verify check-freshness still works**

Run: `cd /home/lewdwig/git/unslop && python unslop/scripts/orchestrator.py check-freshness .`
Expected: JSON output with status field (pass or fail depending on current state)

- [ ] **Step 5: Final commit (if any fixups needed)**

Only if cross-reference audit found issues. Otherwise skip.
