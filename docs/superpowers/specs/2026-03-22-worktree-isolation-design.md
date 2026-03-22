# Worktree-Isolated Generation Design (Milestones K+L Unified)

> Enforce the "no peeking" rule structurally by running all code generation in isolated git worktrees with fresh Agent contexts. The spec file is the only handoff between the Architect (intent processing) and the Builder (code generation).

## Problem

The current generation pipeline runs in the user's session context. The model sees the spec, the code, the change request, and the conversation history simultaneously. While prompt-based rules ("do not read the existing file") work most of the time, they are probabilistic — the model can violate them silently. The "no peeking" rule is enforced by trust, not by architecture.

## Solution

Replace prompt-based isolation with physical isolation:
- **Stage A (Architect)**: Processes change intent and updates the spec. Runs in the current session. Cannot read source code.
- **Stage B (Builder)**: Generates code from the spec. Runs as a fresh Agent in an isolated git worktree. Cannot see the change request or conversation history.
- **Tests as Auditor**: The Builder runs tests in the worktree. Tests are the acceptance criteria — no third-party LLM review needed.

The spec file is the only bridge between the two stages.

## Two-Stage Execution Model

### Stage A: Architect (Current Session)

```
Inputs:
  - Change request intent (from *.change.md or user prompt)
  - Current *.spec.md
  - .unslop/principles.md
  - File tree (git ls-files -- names only, no file contents)

Blocked from:
  - Reading source code files
  - Reading test files

Output:
  - Updated *.spec.md (staged, NOT committed)
  - User approves the spec update before Stage B
```

The Architect thinks in requirements because it has no code to copy or anchor on. It knows what files exist (via the file tree) so it can reference correct paths, but it cannot see implementation details.

**Commit atomicity**: The Architect's spec update is written to disk and staged (`git add`) but NOT committed. The spec and generated code are committed together as a single atomic commit after the Builder succeeds and the worktree is merged. If the Builder fails, the spec update is reverted (`git checkout HEAD -- <spec_path>`), leaving main truly untouched.

**Exception**: During `/unslop:takeover`, the Architect reads the existing source code and tests — because the entire point of takeover is extracting intent FROM code. Stage B still runs in a clean worktree.

### Stage B: Builder (Fresh Agent, Worktree Isolation)

```
Dispatched via: Agent tool, isolation: "worktree"

Prompt: "Implement the spec at <path>. Follow project principles.
         You do not have access to the original change request.
         The spec is your sole source of truth."

Inputs (in worktree):
  - Updated *.spec.md
  - .unslop/principles.md
  - .unslop/config.json
  - Existing source code
  - Test files

Blocked from (by fresh context):
  - Change request intent
  - Architect's reasoning and conversation history
  - User's session context

Output:
  - Modified source code (in worktree)
  - Test results
```

The Builder starts with zero conversation history. It cannot be biased by what the user said because those tokens never enter its context window.

### Verification (Back in Controlling Session)

After the Builder Agent completes:
1. Check the Agent's result status (DONE / DONE_WITH_CONCERNS / BLOCKED)
2. If DONE with green tests: Claude Code handles the worktree merge automatically
3. Compute `output-hash` on the merged code, update `@unslop-managed` header
4. Commit the staged spec update + merged code together as a single atomic commit

If BLOCKED or tests fail: discard the worktree AND revert the staged spec update (`git checkout HEAD -- <spec_path>`). Main branch is untouched -- both spec and code remain at their pre-run state.

## Worktree Isolation is Mandatory

All code generation uses worktree isolation. No exceptions. No configuration flag.

| Command | Stage A (Architect) | Stage B (Builder in worktree) |
|---|---|---|
| `/unslop:change --tactical` | Read change + spec + principles + file tree -> update spec | Implement from updated spec |
| `/unslop:change [pending]` via generate | Phase 0c proposes spec update -> user approves | Implement from updated spec |
| `/unslop:takeover` | Read code + tests -> draft spec (Architect sees code here) | Generate fresh from spec only |
| `/unslop:generate` | No Architect stage -- spec is already the input | Implement from spec |
| `/unslop:sync` | No Architect stage | Implement from spec |

For `generate` and `sync`, there is no Architect stage (no change intent to process), but the Builder still runs in a worktree. This ensures:
- The model generating code NEVER has conversation history from the user's session
- Every generation starts with a clean context
- File system isolation is the default, not a privilege

## Orchestrator Changes

### New subcommand: `file-tree`

```bash
python orchestrator.py file-tree [directory]
# Output: JSON list of tracked filenames (git ls-files)
```

Lightweight — just a file listing for the Architect's context. No file contents.

### No worktree management

The orchestrator does NOT manage worktrees. Claude Code's Agent tool with `isolation: "worktree"` handles creation, branch management, and cleanup. The orchestrator's role is context preparation, not filesystem management.

## Builder Agent Dispatch

The controlling session dispatches the Builder as:

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

# test_policy is set per originating command:
#   takeover:           "Write or extend tests as needed for newly explicit constraints"
#   generate / sync:    "Do NOT create or modify test files. Use existing tests for validation only"
#   change (tactical):  "Extend tests if the spec update introduced new constraints that lack coverage.
#                        Do not modify existing assertions"
```

Auto-merge on green tests. No manual diff confirmation — the user already approved the spec. Tests are the acceptance criteria.

## Convergence Loop Across Stages

For takeover, the convergence loop crosses the stage boundary:

```
Stage A: Draft spec -> user approves
Stage B: Generate in worktree -> tests fail -> report back
Stage A: Enrich spec based on failure report -> user approves
Stage B: New fresh Agent, new worktree -> generate -> tests pass -> merge
```

Each Stage B is a fresh Agent dispatch. No context accumulates across iterations. The Builder never knows why the spec changed between iterations -- it just implements the latest spec.

**Builder failure reports** must include structured information the Architect can act on without seeing code: failing test names, assertion messages, and a natural-language summary of what was attempted. The Architect uses this to identify which spec constraint is missing or incorrect.

Maximum 3 iterations (same as current convergence limit).

## Error Handling

| Scenario | Behavior |
|---|---|
| Tests fail after 3 iterations | Discard worktree. Report failing tests. Suggest `/unslop:harden`. |
| Builder reports BLOCKED | Discard worktree. Surface blocker. User fixes spec and re-runs. |
| Builder reports DONE_WITH_CONCERNS | Merge worktree (tests passed). Surface concerns for spec tightening. |
| Worktree creation fails | Report git error. Check for uncommitted changes or locked refs. |
| Agent crashes mid-execution | Worktree orphaned. Next command detects and offers cleanup. |

### Orphaned worktree cleanup

On each generation command, check `git worktree list` for orphaned unslop worktrees. Worktrees created by unslop use the branch naming convention `unslop/builder/<timestamp>` to distinguish them from user-created worktrees. Only worktrees matching this pattern are flagged for cleanup.

## Impact on `/unslop:change --tactical`

**Breaking behavioral change:** The `[tactical]` designation no longer means "code first, spec later." With two-stage isolation, the Architect always updates the spec first. `--tactical` means "do it now" rather than "defer to next generate." The "heal step" is eliminated -- the spec is updated before code generation, not after.

**Why this is acceptable:** The original code-first flow existed because updating the spec felt like unnecessary ceremony for a one-line fix. With worktree isolation, the Architect stage is lightweight (it only sees the spec + file tree, not the full codebase), so the overhead of spec-first is minimal. The benefit -- every change goes through the spec, ensuring the spec remains the source of truth -- outweighs the lost convenience.

This simplifies the change request lifecycle:
- `[pending]`: spec update deferred to next generate
- `[tactical]`: spec update happens immediately, then Builder executes

Both paths go through the same two-stage flow. The only difference is timing.

## Generation Modes Under Worktree Isolation

**Mode A (Full Regeneration)** is the default for all worktree-isolated generation. The Builder starts with a clean context and generates from the spec. This is the natural fit for the two-stage model.

**Mode B (Incremental Generation)** is still supported when `--incremental` is passed to `generate` or `sync`. In a worktree, Mode B means the Builder reads the existing managed file in the worktree and produces targeted edits. The worktree contains the current codebase state, so the Builder has access to the existing code -- but crucially, it still has no access to the change request intent or conversation history.

The `--incremental` flag is passed through to the Builder Agent's prompt:
- Without `--incremental`: "Generate the managed file from the spec. Do not read the existing file."
- With `--incremental`: "Update the managed file to match the updated spec. Read the existing file and make targeted edits only."

## Phase 0c Decomposition

Under two-stage isolation, Phase 0c (Change Request Consumption) is **split across stages**:

- **Stage A (Architect)**: Reads `*.change.md` sidecars. For each entry, proposes a spec update. User approves. This is where the change intent is consumed -- the Architect absorbs it into the spec.
- **Stage B (Builder)**: Skips Phase 0c entirely. By the time the Builder runs, all change requests have been absorbed into the spec. The Builder's generation skill omits Phase 0c when running in worktree isolation.

For `/unslop:generate` processing pending changes: the controlling session runs Stage A for each file with pending changes (updating specs), then dispatches Stage B Builders for each file that needs regeneration.

## Builder Test-Writing Policy

The Builder's test-writing permissions depend on the originating command and are enforced via the `{test_policy}` parameter in the Builder Agent's prompt (see Builder Agent Dispatch above):

- **Takeover**: Builder may write or extend tests. The spec was just drafted from existing code and may need test coverage for newly explicit constraints.
- **Generate/Sync**: Builder uses existing tests for validation only. Does NOT create or modify test files. This prevents the Builder from weakening assertions to make bad code pass.
- **Change (tactical)**: Builder may extend tests if the spec update introduced new constraints that lack coverage, but must not modify existing assertions.

## Unit Specs and Multi-File Generation

For unit specs (`*.unit.spec.md`), the Builder generates all files listed in `## Files` within the same worktree session. The worktree captures all changes as a single atomic diff.

## What This Replaces

This design replaces and unifies:
- **Milestone K (Symphony-Lite Subagents)**: The Architect/Builder split is implemented via session context + worktree Agent, not persona prompts
- **Milestone L (Worktree Isolation)**: Worktrees are the isolation mechanism, managed by Claude Code's Agent tool
- **The three-persona model (Architect/Builder/Auditor)**: Reduced to two stages + tests. The Auditor is the test suite.

## Backwards Compatibility

This is a breaking change in execution model. All code generation moves to worktree isolation. There is no "legacy mode."

However, the user-facing commands are unchanged — same commands, same arguments, same output. The change is internal to how the generation skill executes.

## Plugin Structure Changes

```
unslop/
├── scripts/
│   └── orchestrator.py        # MODIFIED -- new file-tree subcommand
├── skills/
│   └── generation/
│       └── SKILL.md           # MODIFIED -- two-stage execution model
├── commands/
│   ├── change.md              # MODIFIED -- two-stage tactical flow
│   ├── takeover.md            # MODIFIED -- worktree Builder stage
│   ├── generate.md            # MODIFIED -- worktree Builder dispatch
│   └── sync.md                # MODIFIED -- worktree Builder dispatch
└── ...
```
