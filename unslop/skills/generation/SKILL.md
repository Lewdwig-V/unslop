---
name: generation
description: Use when generating or regenerating code from unslop spec files. Activates during /unslop:generate, /unslop:sync, and the generation step of /unslop:takeover.
version: 0.1.0
---

# Generation Skill

You are generating a managed source file from an unslop spec. These instructions are authoritative. Follow them exactly.

---

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

### Stage A.2: Archaeologist (Subagent)

After the Architect finalizes the Abstract Spec (Stage A.1) and before dispatching the Builder, the Archaeologist drafts a Concrete Spec -- the "Middle-End IR" that bridges intent and code.

**The Archaeologist runs as a subagent** for context hygiene. The Architect dispatches it with `model` from `config.models.archaeologist`. The Archaeologist's algorithmic analysis stays in its own context, keeping the Architect clean for orchestration.

**Persona:** Senior Implementation Engineer. Thinks in algorithms and patterns, not business requirements or syntax.

**Inputs (provided by the Architect):**
- Approved Abstract Spec (`*.spec.md`)
- `.unslop/principles.md`
- Existing Concrete Spec (`*.impl.md`) if one exists and is permanent
- File tree (names only)
- Domain skills (loaded in Phase 0d)

**Output (returned to the Architect):**
- A Concrete Spec (`*.impl.md`) content -- either written as a file or returned for prompt-embedding
- A `behaviour.yaml` fragment -- behavioural DSL entries derived from the Abstract Spec's constraints, for Mason's exclusive use

**Dual projection:** The Archaeologist produces both artefacts in a single pass. The Concrete Spec is the implementation strategy for the Builder (algorithmic "how"). The `behaviour.yaml` fragment is the testable constraint set for Mason (behavioural "what"). `non_goals:` from the Abstract Spec are projected into `behaviour.yaml` as negative constraints (invariants asserting behaviour is NOT present) and into the Concrete Spec as explicit exclusions. The two projections are derived from the same spec read but delivered to different consumers -- the Builder never reads `behaviour.yaml` and Mason never reads the Concrete Spec (Chinese Wall).

**Discovered constraints:** During spec projection, the Archaeologist may discover correctness requirements the abstract spec didn't anticipate -- implicit ordering constraints, hidden dependencies, boundary conditions the spec failed to specify. These are returned as `discovered:` entries (title/observation/question) alongside the concrete spec and behaviour.yaml. Generate's Stage 0b presents each discovery to the user for promote-or-dismiss resolution. Promoted discoveries update the abstract spec and trigger a Stage 0 re-run. The concrete spec must never silently absorb a constraint the user didn't explicitly approve.

**When Stage A.2 runs:**
- **Always** for new files and takeover (full pipeline)
- **Always** for `--force` regeneration
- **Skipped** for Surgical mode (default existing-file sync) unless the spec delta changes algorithmic behavior
- **Skipped** if a permanent Concrete Spec (`ephemeral: false`) already exists and the Abstract Spec hasn't changed
- **Hard block** if the managed file does not exist AND the spec has active provenance (`distilled-from:`, `absorbed-from:`, `exuded-from:`). This is a structural mismatch -- the spec's subject disappeared. Generate cannot proceed. Report the mismatch and suggest `/unslop:absorb`, `/unslop:exude`, or spec removal.
- **Pending specs** (managed file missing, no active provenance): the Archaeologist skips the existing-code read entirely and projects from the abstract spec alone. No implementation context is available, so the concrete spec is based purely on spec intent. The discovery gate (Stage 0b) is especially important for pending specs -- without existing code as a safety net, undiscovered correctness requirements are more likely.

**Ephemeral vs Permanent:**
- By default, the Concrete Spec is **ephemeral** — generated as the Builder's strategic input, discarded after successful generation
- Promoted to **permanent** via `/unslop:promote <spec-path>`, or automatically if the project or spec is marked `complexity: high` in `.unslop/config.json` or spec frontmatter
- When permanent: lives alongside the Abstract Spec as `<file>.impl.md`, version-controlled, code-reviewed

**Ephemeral delivery:** The Archaeologist subagent returns the concrete spec content to the Architect. Two delivery methods to the Builder:
- **File-based (preferred for permanent specs):** The Architect writes the `.impl.md` file to disk. The Builder reads it from the path listed in the prompt template.
- **Prompt-embedded (acceptable for ephemeral specs):** The Architect embeds the Archaeologist's output directly in the Builder's dispatch prompt under the `## Ephemeral Concrete Spec` section. This avoids creating a file that will be immediately discarded. Either method is valid -- the Builder receives the same strategic guidance.

**Concrete Spec format:** See the `unslop/concrete-spec` skill for the full format specification. The key sections are:
- `## Strategy` — pseudocode for the core algorithm
- `## Pattern` — named design patterns and architectural approach
- `## Type Sketch` — structural type signatures (language-agnostic)
- `## Lowering Notes` — language-specific considerations (optional, only for permanent specs)

**Deferred Constraints (blocked-by):** If the concrete spec's frontmatter contains `blocked-by` entries, the Builder treats each entry as an **explicit deviation permit**. The `affects` field names which part of the abstract spec can't be fulfilled yet; the `reason` field explains why. The Builder MUST proceed normally with all unblocked constraints. For the blocked scope, the Builder handles pragmatically -- keeping existing imports, using compatibility shims, or preserving legacy code paths. The Builder MUST NOT silently deviate on constraints not listed in `blocked-by`. The Builder SHOULD add a code comment at each deviation site: `// blocked-by: <symbol> -- <reason>`.

**Protected Regions:** If the concrete spec's frontmatter contains `protected-regions` entries, the Builder MUST preserve these regions verbatim during generation. Before writing any output, the Builder reads the existing managed file and extracts the protected region into memory (everything from `starts-at` to EOF for `tail` position). After generating the implementation, the Builder appends the protected region verbatim. The Builder then: (1) verifies the protected region is present in the output -- if missing, report BLOCKED; (2) counts the 1-indexed line number where the protected region starts and writes it as `managed-end-line` in the header; (3) updates the `starts-at` field in the concrete spec frontmatter to match; (4) computes `output-hash` over the implementation portion only (excluding the protected region). The Builder MUST NOT modify, reformat, or reorder the protected region content.

**Protected Region Hash Verification (Controlling Session):** After the Builder completes, the Architect MUST verify the protected region was preserved exactly. Hash the protected region content before the Builder runs and after. If the hashes differ, the Builder corrupted the region -- discard the worktree and re-dispatch. Do not rely on visual inspection for large protected regions (e.g., 3900-line test blocks).

**Strategy Inheritance:** If the concrete spec has `extends: <base.impl.md>` in its frontmatter, the Archaeologist resolves the inheritance chain via `resolve_inherited_sections()` before presenting the concrete spec to the Builder. The Builder receives the **resolved** concrete spec — it never sees the raw `extends` directive. Resolution uses three section-specific policies: `## Strategy` and `## Type Sketch` are **strict child-only** (parent is purged — a child that omits these fails Phase 0a.1 validation); `## Pattern` is **overridable** (child replaces parent by key, parent persists if child omits); `## Lowering Notes` is **additive** (parent + child merged by language heading). See the `unslop/concrete-spec` skill for full resolution semantics.

The Archaeologist should use `extends` when generating concrete specs for modules that share architectural patterns (e.g., multiple FastAPI endpoints inheriting from `shared/fastapi-async.impl.md`). This reduces token cost and ensures consistency across related modules.

**User approval:** Stage A.2 does NOT require user approval for ephemeral concrete specs. The user approved the Abstract Spec in Stage A.1 — the Concrete Spec is a derivation, not a new requirement. For permanent concrete specs, present a summary:

> "Implementation strategy: [pattern name] using [algorithm]. Promoting to permanent. Review?"

Only block on user rejection.

---

### Stage A.3: Mason (Subagent) -- Test Generation

After the Archaeologist delivers its dual output, the Architect dispatches the Mason to generate a test file from the `behaviour.yaml` fragment. The Mason runs before the Builder so that tests exist before code is generated.

**Chinese Wall:** The Mason receives ONLY the `behaviour.yaml` fragment as input. It does NOT read the Concrete Spec, the Abstract Spec, or any existing source code. This isolation ensures tests are derived purely from specified behaviour, not from implementation details.

**Inputs (provided by the Architect):**
- `behaviour.yaml` fragment from Stage A.2 (Archaeologist output)
- Model: `config.models.mason`

**Output:**
- A test file with an `@unslop-managed` header and a `## behaviour-source: behaviour.yaml` annotation
- The test file is written to the project's standard test location, derived from the managed file's path

**Conditional execution:**
- **Skipped** if existing tests are present for the managed file (test file already exists and is not `@unslop-managed`)
- **Runs with `--regenerate-tests`** even when existing tests are present (overwrites `@unslop-managed` test files; refuses to overwrite non-managed test files)

**Failure handling:** If Mason reports BLOCKED, the Architect does NOT proceed to Builder dispatch. Surface the failure to the user and halt the pipeline. The `behaviour.yaml` fragment and Concrete Spec are retained in the worktree for inspection.

---

### Model Selection

Before dispatching subagents, read `.unslop/config.json`. If a `models` block exists, use the role-specific key as the `model` parameter to `Agent()`. If the key is absent, use the default from the config template in `init.md`. See AGENTS.md for the canonical model/role mapping and rationale.

Valid model values: `sonnet`, `opus`, `haiku`, or a full model ID (e.g., `claude-sonnet-4-6`).

### Subagent Dependency Chain

The generation pipeline has a strict dependency order:

```
Archaeologist -> Discovery Gate (if discoveries) -> Mason -> Builder -> Validator
```

The Architect dispatches Archaeologist, receives the concrete spec and behaviour.yaml, dispatches Mason (test generation, if applicable), then dispatches Builder with the concrete spec. No parallelism within a single file's pipeline -- Mason must complete before Builder to ensure tests exist before code is generated.

**Multi-file parallelism:** When processing multiple files (e.g., `/unslop:generate` with several stale specs), independent files MAY have their Archaeologist, Mason, and Builder subagents dispatched in parallel. Two files are independent if neither appears in the other's `depends-on` chain. Files in the same dependency chain MUST be processed sequentially in build order (leaves first).

The Architect SHOULD maximize parallelism across independent files. For example, with 4 stale files where A depends on B but C and D are independent:

```
B.Archaeologist -> B.Mason -> B.Builder -> A.Archaeologist -> A.Mason -> A.Builder  (sequential: A depends on B)
C.Archaeologist -> C.Mason -> C.Builder                                             (parallel with B/A chain)
D.Archaeologist -> D.Mason -> D.Builder                                             (parallel with B/A chain and C)
```

### Stage B: Builder (Fresh Agent, Worktree Isolation)

The Builder generates code from the specs. It runs as a fresh Agent in an isolated git worktree with zero conversation history.

**HARD RULE: The Architect (you, in the controlling session) MUST NOT write code to managed files directly. ALL code generation MUST go through a Builder Agent dispatched with `isolation="worktree"`. If you find yourself writing code, creating files, or using the Edit/Write tools on a managed source file -- STOP. You are violating worktree isolation. Dispatch a Builder instead.** This is not a preference. It is the structural guarantee that failed Builders can be discarded without corrupting main.

#### Builder Prompt Template

The Architect MUST construct the Builder's prompt using this template. Do not improvise the format -- variance in prompt structure causes variance in output quality.

```
## Task
Generate: <comma-separated list of managed file paths>
Mode: <Mode A (full regeneration) | Surgical>

## Specs to read
- Abstract: <path to *.spec.md>
- Concrete: <path to *.impl.md OR "embedded below">
- Config: .unslop/config.json
- Principles: .unslop/principles.md (if it exists)

## Ephemeral Concrete Spec (if embedded)
<full concrete spec content, only if not written as a file>

## Protected Regions
<for each protected region from the concrete spec frontmatter:>
- File: <managed file path>
  Region: <marker description> at line <starts-at>
  Action: Read and hold in memory BEFORE writing. Append verbatim after generated code.
  Verification: Hash the region before and after -- they MUST match.
<or "None" if no protected regions>

## Validation
- Test command: <from .unslop/config.json>
- Additional checks: <e.g., "cargo clippy", "tsc --noEmit">
- Expected: all tests pass, no warnings

## Rules
- Generate a COMPLETE file, not a diff
- Write the @unslop-managed header with spec-hash, output-hash, generated timestamp
- If protected regions exist, write managed-end-line in the header
- Do NOT read archived originals
- In Mode A (takeover/full regeneration): do NOT read any file not listed above
- In Surgical mode: the Builder MAY also read the existing managed file and files referenced in the Surgical Context blocks
- Report DONE, DONE_WITH_CONCERNS, or BLOCKED per the hold-and-wait protocol
```

For **takeover** (Mode A), the Builder always generates from scratch. For **sync** (Surgical mode), include the three Surgical Context blocks (Existing Code, Spec Diff, Affected Symbols) instead of the concrete spec embedding.

**Multi-target dispatch:** If the concrete spec has `targets` (instead of `target-language`), Stage B dispatches **parallel Builders** — one per target. Each Builder runs in its own worktree on branch `unslop/builder/<target-path-hash>`. All Builders receive the same Abstract Spec and `## Strategy`, but each gets its target-specific `## Lowering Notes` (filtered by language heading) and `targets[].notes`. See the `unslop/concrete-spec` skill for the full multi-target lowering specification.

**Atomic merge for multi-target:** The controlling session waits for ALL parallel Builders to complete. If all report DONE with green tests: merge all worktrees and commit atomically. If any Builder fails: discard ALL worktrees and revert ALL staged spec updates. This all-or-nothing semantics prevents partial updates across language boundaries.

**Multi-target status board:** When dispatching parallel Builders, the controlling session displays a live status board that updates as each Builder reports back. This replaces a generic spinner with actionable visibility into parallel execution.

**Initial display** (immediately after dispatch):

```
Multi-target build: auth_logic.impl.md (2 targets)
  [1/2] src/api/auth.py        (python)     building...
  [2/2] frontend/src/api/auth.ts (typescript) building...
```

**As Builders complete**, update each line in place:

```
Multi-target build: auth_logic.impl.md (2 targets)
  [1/2] src/api/auth.py        (python)     DONE  (14 tests, 3.2s)
  [2/2] frontend/src/api/auth.ts (typescript) building...
```

**On completion** (all pass):

```
Multi-target build: auth_logic.impl.md (2 targets)
  [1/2] src/api/auth.py        (python)     DONE  (14 tests, 3.2s)
  [2/2] frontend/src/api/auth.ts (typescript) DONE  (8 tests, 1.7s)

All targets passed. Merging atomically.
```

**On failure** (any target fails):

```
Multi-target build: auth_logic.impl.md (2 targets)
  [1/2] src/api/auth.py        (python)     DONE  (14 tests, 3.2s)
  [2/2] frontend/src/api/auth.ts (typescript) BLOCKED — 2 test failures

Atomic merge aborted. All worktrees discarded.
Failure in target [2/2]: frontend/src/api/auth.ts
  See Builder failure report for details.
```

**Status states per target:**

| State | Display | Meaning |
|---|---|---|
| `building...` | Yellow/neutral | Builder is running in its worktree |
| `DONE` | Green | Builder succeeded, tests passed |
| `DONE_WITH_CONCERNS` | Amber | Builder succeeded but flagged concerns |
| `BLOCKED` | Red | Builder failed or tests failed |

**On DONE_WITH_CONCERNS for any target**, surface concerns after the atomic merge:

```
All targets passed. Merging atomically.
  Concerns flagged on 1 target — run /unslop:harden or ask to review.
```

**Single-target builds** (standard `target-language`) do NOT show the status board — the existing single-line progress reporting is sufficient.

**Dispatch:**

```python
Agent(
    description="Implement spec changes in isolated worktree",
    isolation="worktree",
    model=config.models.builder,  # from .unslop/config.json
    prompt="""You are implementing changes to managed files based on their specs.

    Target spec: {spec_path}
    Concrete spec: {impl_path_or_none}
    Test command: {test_command}

    {previous_failure}

    Instructions:
    1. Read the abstract spec at {spec_path} (source of truth for constraints)
    2. Read the concrete spec at {impl_path} if provided (strategy guidance)
    3. Read .unslop/principles.md if it exists
    4. If no concrete spec was provided, draft an ephemeral one in the
       worktree as your implementation plan before writing code
    5. Implement the code guided by both specs:
       - Abstract Spec governs WHAT (constraints, contracts, error behavior)
       - Concrete Spec governs HOW (algorithm, pattern, structure)
       - On conflict: Abstract Spec wins — always
    6. {test_policy}
    7. Run tests: {test_command}
    8. If tests pass: report your status and changed files, then WAIT.
       Do NOT exit. Do NOT terminate. The controlling session must
       validate your output before authorizing merge.
       Report format:
         STATUS: DONE (or DONE_WITH_CONCERNS)
         Changed files: [list]
         Test results: [pass count]
       Then say: "Awaiting Architect validation before merge."
    9. If tests fail and you cannot fix them: report BLOCKED with
       diagnostic details and EXIT IMMEDIATELY. Do not wait for
       authorization on failure -- the controlling session needs to
       discard the worktree and enter convergence.

    IMPORTANT: The hold-and-wait applies to SUCCESS states only
    (DONE, DONE_WITH_CONCERNS). You must NOT exit on success until
    the controlling session sends "Validation passed. You are
    authorized to exit." This keeps the worktree alive for inspection.
    BLOCKED states exit immediately -- failed worktrees are discarded,
    not merged.

    The abstract spec is your primary source of truth. The concrete spec
    is strategic guidance. Do not look for or follow any change requests.
    If the spec seems incomplete, report DONE_WITH_CONCERNS describing
    what appears to be missing.

    If the implementation turns out to be significantly harder than the
    concrete spec's complexity score suggests (e.g., unexpected edge
    cases, concurrency concerns, non-obvious invariants), include a
    COMPLEXITY_UPGRADE proposal in your DONE_WITH_CONCERNS report:
    'Propose complexity upgrade: medium → high. Reason: [explanation].'
    The controlling session will re-evaluate promotion."""
)
```

**`{impl_path_or_none}` value:**
- If a permanent Concrete Spec exists at the derived path (e.g., `src/retry.py.impl.md`): the path to that file.
- If Stage A.2 generated an ephemeral Concrete Spec in the worktree: the worktree-relative path.
- If neither exists: `"None — draft an ephemeral implementation strategy before coding."`

**`{previous_failure}` value:**
- If `.unslop/last-failure/<cache-key>.md` exists: `"Previous Implementation Failure:\n<contents of the failure report>"`. The Builder uses this to avoid repeating the same implementation choice.
- If no failure report exists: empty string (omitted from prompt).

**`{test_policy}` values by originating command:**
- **takeover (tests exist):** `"Write or extend tests as needed for newly explicit constraints"`
- **testless takeover:** `"Do NOT create, modify, or run test files. Report DONE based on successful code generation only. The adversarial pipeline will generate and validate tests separately."`
- **generate / sync:** `"Do NOT create or modify spec-backed test files. Use existing tests for validation only. Tests marked @unslop-incidental may be updated or removed if they fail against regenerated code that correctly follows the spec."`
- **change (tactical):** `"Extend tests if the spec update introduced new constraints that lack coverage. Do not modify existing assertions"`

**Note on `test_policy: "skip"` (testless takeover):** The Builder reports DONE after generating code that satisfies the spec. No tests are run. The calling pipeline (takeover) is responsible for running the Symbol Audit and adversarial pipeline as the quality gate. The Builder must NOT attempt to write tests -- the Mason writes them from the behaviour.yaml behind a Chinese Wall.

**Adversarial intensity tagging (testless takeover):** When testless takeover dispatches the Builder, the Architect tags the adversarial intensity based on file complexity:
- `adversarial: "full"` (default): Mason + Saboteur. For multi-function files, complex state, or tangled dependencies.
- `adversarial: "mason-only"`: Mason generates tests, Saboteur skipped. For single-function files with tight specs.
The user can override with `--full-adversarial`.

### `@unslop-incidental` Test Lifecycle

Tests generated by `/unslop:cover` that the user does not promote to spec requirements carry a comment marker:

```python
# @unslop-incidental -- generated by /unslop:cover, backed by behaviour.yaml but not yet promoted to spec.
# Safe to update or remove during sync if behaviour changes legitimately.
def test_retry_limit_enforced():
    ...
```

**Detection:** The Builder scans test files for `# @unslop-incidental` using string matching (same approach as `@unslop-managed` header detection).

**During generate/sync:** Spec-backed tests that fail block the pipeline. Incidental tests that fail may be updated or removed by the Builder if the regenerated code correctly follows the (updated) spec. This is the only exception to the "do not modify test files" rule.

**Promotion:** When a user later approves a previously-incidental constraint via `/unslop:cover`, the `@unslop-incidental` marker is removed from the corresponding test -- it becomes spec-backed.

**Coexistence:** Tests from `/unslop:takeover` or `/unslop:adversarial` are spec-backed by default. Only `/unslop:cover` generates incidental tests (when the user chooses "Keep as Incidental" in triage).

### Verification (Controlling Session)

The Builder does NOT exit on its own. It reports status and waits for the Architect's authorization. This keeps the worktree alive for inspection.

**Auto-merge detection:** The `isolation="worktree"` tool does not guarantee isolation -- it can auto-merge the Builder's changes into the working tree before the Architect has inspected them. Before proceeding, check which outcome occurred:

- **Outcome: worktree-live** -- The Agent tool returned a `worktreePath`. The Builder is waiting. The normal hold-and-authorize protocol applies.
- **Outcome: auto-merged** -- The Agent tool returned no `worktreePath` and the Builder's changes are already on disk.

**Ground-truth detection (auto-merged only):** Do NOT rely on the Builder's self-reported file list. Use `git diff HEAD --name-only` (no filter) to detect all modified files, and `git ls-files --others --exclude-standard` to detect new untracked files the Builder created. These two commands give the complete picture of what changed.

**Committed vs working-tree check:** Run `git status --porcelain` first. If the output shows changes in the working tree (unstaged), the auto-merge only touched the working tree. If `git status` is clean but `git diff HEAD~1 --name-only` shows the Builder's files, the auto-merge was committed. Use `HEAD~1` instead of `HEAD` for the diff/revert in this case.

After the Builder reports its status:

1. Check result status: DONE / DONE_WITH_CONCERNS / BLOCKED

2. **If DONE with green tests:**
   - **Worktree-live:** Inspect the Builder's output (worktree is still live). When satisfied, send via `SendMessage` to the Builder: `"Validation passed. You are authorized to exit."` The Builder then exits, triggering the worktree merge. Continue to step 3.
   - **Auto-merged:** Run `git diff HEAD --name-only` to see all changes (ground truth, not Builder's report). Inspect the diff. If valid: continue to step 3. If invalid: revert (see Revert Protocol below) and dispatch a new Builder. Do NOT continue to steps 3-6 in the revert case.

**Merge decision:** When the Builder reports DONE with green tests AND the Architect's inspection confirms the output is valid, merge the Builder's output. For takeover, the Builder's output is the new managed file (with `@unslop-managed` header) -- discarding it would lose the header and the spec-completeness proof. For sync/generate, the Builder's output reflects spec changes. If inspection reveals invalid changes despite green tests (e.g., wrong file modified, spec misinterpreted), follow the Revert Protocol above -- do NOT merge.

3. Compute `output-hash` on merged code, update `@unslop-managed` header. If the Builder's `generated:` timestamp is missing, `T00:00:00Z`, or older than the session start time, replace it with the current UTC time via `date -u +%Y-%m-%dT%H:%M:%SZ`.

4. Handle the Concrete Spec artifact:
   - If `ephemeral: true` (default): ensure the `*.impl.md` is NOT included in the merge -- it served its purpose
   - If `ephemeral: false` (promoted or high-complexity): include the `*.impl.md` in the merge and commit

5. Commit the staged spec update + merged code (+ concrete spec if permanent) as a single atomic commit

6. Delete `.unslop/last-failure/<cache-key>.md` if it exists (previous failure is now resolved)

7. If DONE_WITH_CONCERNS and includes COMPLEXITY_UPGRADE: re-evaluate the concrete spec's complexity score. If the new score meets the project's `promote-threshold`, update the concrete spec's frontmatter to `ephemeral: false` and include it in the merge. Notify the user:

> "Builder proposed complexity upgrade: [old] → [new]. Reason: [explanation]. Concrete spec promoted to permanent."

8. If DONE_WITH_CONCERNS (without upgrade): surface concerns as a one-liner after the commit:

> "Generation complete. Tests green. N concern(s) flagged -- run `/unslop:harden` or ask to review."

Do NOT auto-expand the concerns list. The user chooses when to engage.

**If BLOCKED or tests fail:**
- **Worktree-live:** Discard the worktree. Revert the staged spec update (`git checkout HEAD -- <spec_path>`). Main branch is untouched.
- **Auto-merged:** Run the Revert Protocol (below) to undo the auto-merge, then revert the staged spec update.

Write the Builder's failure report to the diagnostic cache (see below).

### Revert Protocol (Auto-Merge Recovery)

When an auto-merged Builder output needs to be undone (invalid DONE or BLOCKED):

```
1. git checkout HEAD -- <modified-files>      # revert modified files to HEAD
2. git clean -f -- <new-files>                # remove Builder-created files not in HEAD
3. git reset HEAD -- <staged-files>           # clear index of auto-merged entries
4. git diff HEAD --name-only                  # verify: should be empty
```

Use `git diff HEAD --name-only` (step 1) and `git ls-files --others --exclude-standard` (step 2) for ground-truth file lists -- do NOT use the Builder's self-reported list.

**Pre-existing dirty state:** If the working tree was dirty before the Builder ran (Architect's own staged spec update), `git checkout HEAD` will revert that too. Re-stage the spec update after the revert: `git add <spec_path>`.

**Diagnostic cache entry for auto-merge revert:** Write to `.unslop/last-failure/<cache-key>.md` with:
```markdown
## Auto-Merge Revert

Reason: <why the output was invalid>
Builder status: <DONE/BLOCKED>
Files reverted: <list from git diff>
Files cleaned: <list from git ls-files --others>
```

This uses the same cache path and lifecycle as normal Builder failure reports.

### Async Saboteur (Post-Generate, Fire-and-Forget)

After the Builder reports DONE with green tests and the Architect has authorized the merge, the Architect fires the Saboteur as a background verification task. The Saboteur does NOT block the generate pipeline -- the commit and merge happen before the Saboteur starts.

**Trigger:** Fired immediately after the atomic commit (step 5 of Verification), only on Builder DONE (not DONE_WITH_CONCERNS or BLOCKED).

**Fire-and-forget semantics:** The Architect dispatches the Saboteur and does not await its result before responding to the user. The generation command reports completion immediately. The Saboteur runs independently in the background.

**Saboteur inputs:**
- Path to the newly committed managed file
- Path to its `*.spec.md`
- Path to the Mason-generated test file (if present)
- Model: `config.models.saboteur`

**Saboteur outputs:** Results are written as JSON to `.unslop/verification/<managed-file-hash>.json`. The JSON contract matches what `/unslop:status` and `/unslop:verify` consume:

```json
{
  "managed": "<managed-file-path>",
  "spec": "<spec-path>",
  "timestamp": "<ISO8601>",
  "status": "pass|fail|error|timeout|pending",
  "mutants_total": 20,
  "mutants_killed": 18,
  "mutants_equivalent": 2,
  "mutants_surviving": 0,
  "surviving_details": [],
  "source_hash": "<12-hex>",
  "spec_hash": "<12-hex>"
}
```

These files are excluded from version control (`.unslop/.gitignore`).

**Timeout semantics:** The Saboteur has a configurable timeout: `config.verification_timeout` (default: 300 seconds). If it does not complete within the timeout, the result file is written with `"status": "timeout"` and a partial mutation report. The timeout does not affect the generation output in any way.

**Does not block generate:** A Saboteur failure or timeout never rolls back the commit, reverts the merge, or modifies the managed file. Saboteur results surface through `/unslop:status` and `/unslop:verify`. If the Saboteur identifies escaping mutants, the user can trigger a full cover run via `/unslop:cover` to investigate gaps.

**Skipped when:**
- `adversarial: "mason-only"` was set during testless takeover
- No test file exists for the managed file after Mason

### Optional Drift Check (Diagnostic Tool)

For intent drift detection after generation, use `/unslop:weed` to compare spec intent against generated code. The Surgical Context prompt blocks (Existing Code, Spec Diff, Affected Symbols) are the primary enforcement mechanism during generation -- they work for all languages without external tooling.

### Triage Summary Templates

After the merge completes, the controlling session emits a triage summary. The format depends on the generation mode and drift check result.

**Surgical Sync:**

```
Sync complete: <spec-path>
  Mode: surgical
  Affected symbols: s1, s2, s3
  Tests: N passed
```

**Full Regeneration (`--refactor` or new file):**

```
Generation complete: <spec-path>
  Mode: full regeneration (--refactor)
  Tests: N passed
```

### Multi-Target Surgical Note

For concrete specs with `targets[]` (multi-target dispatch), each target gets its own `affected_symbols` list. The controlling session computes Affected Symbols independently per target by mapping changed spec sections to the symbols in each target file.

For single-target specs (standard `target-language`), the `affected_symbols` are derived from the top-level spec frontmatter and injected into the single Builder dispatch.

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

### Diagnostic Cache (`.unslop/last-failure/`)

When a Builder fails (BLOCKED or test failures), the controlling session writes the structured failure report to disk:

**Path:** `.unslop/last-failure/<cache-key>.md` where `<cache-key>` is the spec's path relative to the project root with `/` replaced by `--` (e.g., `src/retry.py.spec.md` -> `.unslop/last-failure/src--retry.py.spec.md.md`). This prevents collisions between specs with the same filename in different directories.

**Write:** After discarding the worktree and reverting the staged spec, create `.unslop/last-failure/` if it does not exist, then write the Builder's failure report (Failing Tests, What Was Attempted, Suspected Spec Gaps) to the cache file. Overwrite any existing report for the same spec.

**Read:** Before dispatching any Builder or entering Stage A, the controlling command checks for `.unslop/last-failure/<cache-key>.md`. This check runs at the command level -- before worktree creation, before any agent dispatch. If a report exists:

1. **Surface to user:** Always display a one-liner:

> "Resuming from previous failure: [one-line summary of top suspected spec gap]. Ask to review full post-mortem."

2. **Route to the right stage:**
   - **Commands with Stage A** (`/unslop:change`, `/unslop:takeover`): Inject the report as "Previous Attempt Post-Mortem" context for the Architect. The Architect uses it to inform the spec patch -- it must not ignore this context.
   - **Commands without Stage A** (`/unslop:generate`, `/unslop:sync`): Inject the report into the Builder's worktree prompt as "Previous Implementation Failure." The Builder uses it to avoid repeating the same implementation choice that failed.

The read does not block -- the command proceeds to its normal flow after acknowledging. But it fires before anything else, ensuring the failure context is the first thing in the agent's window.

**Delete:** Only on Builder success. After the atomic commit (spec + code), delete the cache file for that spec. If the user cancels the Architect stage or abandons the run, the report persists for the next attempt.

**Cleanup:** `.unslop/last-failure/` is excluded from version control via `.unslop/.gitignore`. These are transient execution diagnostics, not project history.

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

### Orphaned Worktree Cleanup

On each generation command invocation, before dispatching any Builder, check for orphaned unslop worktrees:

1. Run `git worktree list --porcelain`
2. Look for worktrees on branches matching `unslop/builder/*`
3. If any are found, report them to the user:

> "Found N orphaned unslop worktree(s) from previous runs. Clean up? (y/n)"

4. If the user confirms: run `git worktree remove <path>` for each, then `git branch -D <branch>` for each
5. If the user declines: proceed without cleanup

Only worktrees matching the `unslop/builder/*` pattern are flagged. User-created worktrees are never touched.

---

### Ripple-Effect Analysis (`--dry-run`)

When invoked with `--dry-run`, the generation pipeline stops after classification and runs a ripple-effect analysis instead of dispatching Builders. This traces the "blast radius" of a spec change across all three layers of the compiler IR:

**Layer 1 — Abstract Specs:** Which specs are directly changed (stale/new/conflict) and which are transitively affected via `depends-on` chains.

**Layer 2 — Concrete Specs:** Which `*.impl.md` files need regeneration (their `source-spec` changed) and which become ghost-stale (their upstream `concrete-dependencies` or `extends` parent changed).

**Layer 3 — Managed Code:** Which source files would be regenerated, in what build order, and which would become ghost-stale.

**Implementation:** The orchestrator's `ripple-check` subcommand performs the analysis:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ripple-check <spec-path>... --root .
```

It returns a structured JSON report with:
- `layers.abstract`: directly changed vs transitively affected spec counts
- `layers.concrete`: affected impl files and ghost-stale impl files
- `layers.code`: files that would be regenerated and ghost-stale files
- `build_order`: topological order for the affected subgraph

The `--dry-run` flag is read-only — no files are modified, no worktrees are spawned, no commits are made. This is the bulk-refactor equivalent of a compiler's "what would this optimization pass change" diagnostic.

---

## 0. Pre-Generation Validation

Before generating any code, validate the spec. This section runs first — if validation fails, no code is written.

### Phase 0a.0: Intent Lock (Stage A Only)

Before any spec validation or mutation, the Architect must articulate the user's goal and receive explicit approval. This phase runs ONLY in Stage A (Architect) -- the Builder skips it entirely.

**When Phase 0a.0 fires:**

| Entry point | Trigger |
|---|---|
| `/unslop:change --tactical` | Always (before Architect drafts spec patch) |
| `/unslop:takeover` | Handled by the takeover skill (Step 1b), not this phase. Listed here for completeness. |
| `/unslop:generate` or `/unslop:sync` with pending `*.change.md` | Once per file with pending changes (gates entry to Phase 0c) |

**When Phase 0a.0 does NOT fire:**
- `/unslop:spec` -- manual authoring; user is sovereign
- `/unslop:generate` or `/unslop:sync` with no pending changes -- no Architect stage
- Stage B (Builder) -- never touches specs
- Non-interactive environments (CI) -- see CI Abort Protocol below

**The protocol:**

1. Read the change intent source (the `*.change.md` entries, the `--tactical` description, or the takeover target) and the current spec.
2. Draft a one-sentence **Intent Statement** in product language (not implementation language).
3. Present to the user and wait for explicit approval.
4. **Approved** -- proceed to Phase 0a (structural validation).
5. **Rejected** -- see Rejection Protocol below.

**Intent Statement format:**

Standard (tactical and pending changes):

> "I understand you want to [abstract goal]. To achieve this, I'll update the [spec name] spec to [constraint-level description of the change]."

Takeover variant (after reading existing code in Discover step):

> "From the existing code, I understand this module's purpose is [extracted intent]. I'll draft a spec that captures [key behaviors]. Does this match your understanding of what this code should do?"

**Language constraint:** The goal must be expressed in user/product language, not implementation language.

- **Pass:** "Ensure token expiration is strictly enforced"
- **Fail:** "Add a TTL check to the auth middleware"

If the Architect cannot explain the change without referencing implementation details, it has not extracted the requirement. It must reformulate before presenting.

**No force-approve.** There is no force-approve or auto-approve mechanism for Phase 0a.0. The double-gate (Intent Lock + spec approval) is mandatory for all Architect-mediated changes.

**Batched pending changes (generate/sync path):** When processing a file with multiple pending `*.change.md` entries, fire the Intent Lock **once per file** with an aggregated intent statement. If entries contain contradictory requirements, surface the conflict:

> "Pending changes for `[file]` contain conflicting intent: [Change A] requests [X], [Change B] requests [Y]. Which takes precedence?"

Phase 0a.0 approval is a prerequisite for entering Phase 0c for that file. Phase 0c's per-entry rejection still applies after Phase 0a.0 approval -- the Intent Lock validates combined direction; Phase 0c validates individual spec mutations.

**Rejection granularity:** Phase 0a.0 is all-or-nothing per file. Rejecting the aggregated intent retains all entries and skips the file. To remove a bad entry, edit `*.change.md` manually and re-run.

**Rejection protocol:**

- **Tactical (path a):** The entry remains in `*.change.md`. The Architect asks "Could you clarify the requirement?" and may reformulate in the same session. No limit on attempts.
- **Takeover (path b):** No spec is created. The Architect reformulates in the same session. If the user abandons (exits), no artifacts are left behind.
- **Pending changes (path c):** All entries retained. File skipped. Other files in the batch continue normally.

**CI abort:** In non-interactive environments, Phase 0a.0 never fires because the Intent Lock requires a TTY. Interactive commands (`sync`, `generate`) will hang waiting for input -- the correct failure mode (timeout, not silent auto-approve). The `check-freshness` command surfaces pending changes as a distinct error class (see Phase 0a.0 CI integration below).

### Phase 0a: Structural Validation

Call the structural validator script:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_spec.py <spec-path>
```

Read the JSON output:
- **`"status": "pass"`** — proceed to Phase 0b.
- **`"status": "warn"`** — surface warnings to the user, then proceed to Phase 0b.
- **`"status": "fail"`** — **stop immediately.** Report the issues to the user. Do not generate code. Tell them: "Spec failed structural validation. Fix the issues above and re-run."

There is no override for structural validation failures.

### Phase 0a.1: Pseudocode Linting (Concrete Specs Only)

After Phase 0a passes, if the target includes a Concrete Spec (`*.impl.md`) — either a permanent sidecar or one generated by Stage A.2 — validate its pseudocode blocks against the Pseudocode Discipline defined in the `unslop/spec-language` skill.

**Trigger:** This phase runs when:
- A permanent `*.impl.md` exists for the target spec
- Stage A.2 generated an ephemeral concrete spec
- The target IS a concrete spec (e.g., during `/unslop:promote`)

**Skip** if no concrete spec is involved in the current generation.

Call the pseudocode linter:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_pseudocode.py <impl-path>
```

The linter extracts all ` ```pseudocode ` fenced blocks from the file and checks:

**Structural checks (machine-enforceable):**
1. **Bare assignment**: Lines using `=` for assignment instead of `←` or `:=`
2. **Language-specific keywords**: `def`, `func`, `fn`, `let`, `var`, `const`, `lambda`, `=>`
3. **Multi-statement lines**: Lines containing `;` as a statement separator
4. **Library calls**: Dot-notation method invocations (e.g., `time.sleep()`, `random.uniform()`) — flag as potential library puns
5. **Missing scope boundaries**: `FUNCTION` without matching `END FUNCTION`
6. **Abbreviated identifiers**: Single-character variable names (excluding loop counters `i`, `j`, `k` and common math symbols)

**Advisory checks (model-assisted, not automated):**
7. **Missing error paths**: Does every `TRY` have a `CATCH`? Are edge cases branched?
8. **Magic numbers**: Numeric literals that should be named constants
9. **Abstraction level**: Is the pseudocode too close to a specific language? Too vague to implement?

**Result handling:**

- **All checks pass:** Report "Pseudocode lint: clean." Proceed to Phase 0b.
- **Structural violations found:** Report each violation with line number and fix suggestion:

> "Pseudocode lint found N violation(s) in `<impl-path>`:
> 1. Line 5: Bare assignment `delay = x` — use `SET delay ← x`
> 2. Line 8: Library call `time.sleep(delay)` — use `WAIT delay`
>
> Fix the pseudocode and re-run, or override with `--force-pseudocode`."

**Stop generation** on structural violations unless `--force-pseudocode` is passed, in which case report as warnings and proceed.

- **Advisory findings only:** Report as warnings, proceed to Phase 0b. Advisory checks never block.

### Phase 0b: Ambiguity Detection

After structural validation passes, review the spec for semantic ambiguity.

**Before reviewing**, scan the spec for Open Question exemptions:
1. Collect all lines containing `[open]` — these phrases are exempt
2. Collect all items listed under a `## Open Questions` section — these topics are exempt

Before running ambiguity detection, check if `.unslop/principles.md` exists. If it does, read it and use it as additional context:

1. **Principle conflict check**: If the spec directly contradicts a principle (e.g., spec says "use module-level mutable state" but principles say "no global mutable state"), **stop generation** and report the conflict. Tell the user: "Spec contradicts project principle: [quote spec] vs [quote principle]. Edit the spec to comply with principles, or update principles if the constraint no longer applies."

2. **Ambiguity resolution**: A spec phrase that would be ambiguous without principles may be unambiguous with them (e.g., "handle errors" is ambiguous alone, but if principles say "errors must be typed", the ambiguity is resolved). Use principles to narrow the interpretation space.

**Then review the spec** with this focus:

> Review this spec for semantic ambiguity — places where a reasonable implementer could make two substantively different choices that both satisfy the spec text. Be specific: quote the ambiguous phrase and describe the two interpretations.
>
> Do NOT flag:
> - Implementation choices left deliberately open (data structures, algorithms, variable names) — these are correctly vague
> - Items marked with `[open]` inline
> - Items listed in the `## Open Questions` section
> - Topics that overlap with Open Questions items (match by topic, not exact string)
>
> DO flag:
> - Behavioral ambiguity: "retries on failure" — what counts as failure?
> - Constraint ambiguity: "handles large inputs" — what is large? No bound specified.
> - Contract ambiguity: "returns an error" — what kind? Exception? Error code? None/null?

**Result handling:**

- **No ambiguities found:** Report "Spec passed ambiguity review." Proceed to Phase 0c.
- **Ambiguities found, all covered by Open Questions:** Report "Spec has N open questions acknowledged. Proceeding." Proceed to Phase 0c.
- **Ambiguities found, some NOT covered:**
  - If `--force-ambiguous` was passed: report ambiguities as warnings, proceed to Phase 0c.
  - Otherwise: **stop generation.** Report each uncovered ambiguity with the quoted phrase and two interpretations. Tell the user:

> "Found N ambiguities not marked as open questions. Either:
> 1. Resolve them by editing the spec to be more specific
> 2. Mark them as intentionally open with `[open]` or add to `## Open Questions`
> 3. Override with `--force-ambiguous` (not recommended)"

---

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

---

### Phase 0d: Skill Loading (Three-Tier Discovery)

After change request consumption, discover and load applicable domain skills from three tiers.

**Discovery order (highest priority wins):**

1. **User-local:** `~/.config/unslop/skills/<name>/SKILL.md`
2. **Project-local:** `.unslop/skills/<name>/SKILL.md`

Plugin workflow skills (`${CLAUDE_PLUGIN_ROOT}/skills/`) are NOT discovered by Phase 0d. Those are methodology skills (generation, triage, adversarial, etc.) loaded by the command framework via frontmatter `skills:` references. Phase 0d discovers only domain skills from the project-local and user-local tiers.

When a skill name exists at both tiers, the higher-priority tier wins. The lower-tier skill is completely suppressed -- not loaded, not merged, not consulted.

**Enforcement field:** Each project-local or user-local skill may declare `enforcement: advisory` (default) or `enforcement: constitutional` in its YAML frontmatter.
- `advisory`: The skill describes preferred patterns. The Archaeologist reads it as context and surfaces a `discovered:` item if it deviates.
- `constitutional`: The skill describes invariants. The Saboteur checks compliance during constitutional verification (same as `principles.md`).
- **User-local constitutional downgrade:** If a user-local skill declares `enforcement: constitutional`, silently downgrade to `advisory`. Constitutional enforcement requires project-local skills (version-controlled, code-reviewed).

**Applicability filtering:** If a skill has an `applies-to` field with glob patterns, load it only for files matching those patterns. If `applies-to` is absent or an empty list, the skill applies to all files.

**Loading steps:**

1. Scan user-local and project-local tiers. Build a merged skill map keyed by name (user-local wins on name collision).
2. For each skill in the map, check `applies-to` against the current target file path. Skip non-matching skills.
3. Read matching skills as additional generation context.

**Context priority:**
- Project Principles (highest -- non-negotiable)
- Constitutional Skills (scoped invariants)
- File Spec (file-specific requirements)
- Advisory Skills (framework conventions -- defaults that the spec can override)
- Generation Skill defaults (lowest)

**Saboteur integration:** Pass loaded `constitutional` skills to the Saboteur alongside `principles.md` for Phase 2 (constitutional compliance). Advisory skills are not checked by the Saboteur.

If no domain skills match, this phase is a no-op. Proceed to Phase 0e.

---

### Phase 0e: Cross-Spec Coherence Check

After domain skill loading, check for contract consistency between the target spec and its dependencies. Runs if the target spec has `depends-on` frontmatter OR is a unit spec (`*.unit.spec.md`). If the spec has no dependencies and is not a unit spec, skip to Section 1.

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

### Phase 0e.1: Concrete Spec Coherence (Implementation Strategy Layer)

After abstract spec coherence passes, check for **strategy-level** consistency between concrete specs. This phase catches mismatches that are invisible at the abstract spec layer — two specs may have compatible contracts but incompatible implementation strategies.

**Trigger:** Runs when:
- The target spec has a permanent concrete spec (`*.impl.md` with `ephemeral: false`)
- AND the target spec has `depends-on` entries whose dependencies also have permanent concrete specs

If no permanent concrete specs are involved, skip to Section 1.

**1. Build the concrete spec dependency graph:**

For each `depends-on` entry in the target's abstract spec, check if a corresponding `*.impl.md` exists for the dependency. Collect all pairs where both sides have permanent concrete specs.

**2. For each concrete spec pair, check implementation strategy coherence:**

> Review the target concrete spec and dependency concrete spec for strategy-level incoherence. Focus on the boundary where the dependency's implementation choices affect the target's implementation choices.
>
> Check for:
> - **Concurrency model compatibility:** Do both specs agree on sync vs async? If the dependency's `## Strategy` uses `AWAIT` or `YIELD`, does the target's strategy account for async calling conventions?
> - **Type sketch compatibility:** Do the `## Type Sketch` sections agree on the shape of types crossing the boundary? (This is more detailed than the abstract spec check — it compares structural types, not just observable contracts.)
> - **Pattern compatibility:** Do the `## Pattern` sections use compatible architectural approaches? (e.g., one uses "callback-based event handling" while the other assumes "synchronous return values")
> - **Lowering notes conflict:** Do the `## Lowering Notes` sections for the same target language make conflicting assumptions? (e.g., one assumes `asyncio` while the other assumes threading)
>
> Do NOT flag:
> - Differences in internal algorithm choice (the whole point of separate strategies)
> - Different complexity scores
> - Lowering notes for different target languages (they don't interact)

**3. Result handling:**

- **No strategy incoherence found:** Report "Concrete spec coherence: strategies are compatible." Proceed to Section 1.
- **Strategy incoherence found:** Report each issue:

> "Strategy incoherence between `<target.impl.md>` and `<dependency.impl.md>`:
> - `<target>` strategy assumes: [quoted pseudocode or pattern]
> - `<dependency>` strategy uses: [quoted pseudocode or pattern]
> - Issue: [concurrency mismatch / type sketch mismatch / pattern incompatibility] — [brief explanation].
>
> Update one of the concrete specs, or override with `--force-strategy`."

**Unlike abstract spec incoherence, strategy incoherence is overridable** with `--force-strategy`. The abstract spec contracts are still satisfied — the strategy mismatch may produce working but suboptimal code (e.g., sync wrappers around async calls). The override is available because strategy choices are more fluid than contract constraints.

---

## 1. Generation Mode Selection

Generation operates in one of three modes. **The controlling agent or command selects the mode.** The default depends on context -- see Dispatch Logic below.

### Dispatch Logic

| Condition | Mode |
|---|---|
| New file (no existing managed output) | Mode A -- Full Regeneration |
| Existing file, normal sync | Surgical mode |
| `--refactor` flag | Mode A -- Full Regeneration |
| `--incremental` flag (deprecated) | Surgical mode (with deprecation warning) |

The `--incremental` flag is a deprecated alias. If passed, emit a one-line warning:

> "`--incremental` is deprecated and treated as a no-op. Surgical mode is the default for existing files."

Then proceed with Surgical mode as normal.

### Surgical Mode (default for existing files)

The Builder receives three additional context blocks alongside the spec: **Existing Code**, **Spec Diff**, and **Affected Symbols**. These blocks scope the Builder's authority to modify only what the spec change requires while preserving everything else verbatim.

The Builder produces a **complete file** -- not a diff, not a patch. But protected symbols (those not listed in Affected Symbols) are copied verbatim from the Existing Code block. The output is a full file where only the authorized symbols have been re-derived from the spec.

**Permitted reads:**
- The spec file
- The current generated source file (provided as the Existing Code block)
- The test file(s) for the target module
- `.unslop/config.json` or `.unslop/config.md` (for test command and project conventions)
- `.unslop/principles.md` (project-wide generation constraints, if it exists)
- Language/framework documentation as needed

**Prohibited reads:**
- `.unslop/archive/` (original pre-takeover files)

**Discipline in Surgical mode:**
- Modify only the symbols listed in the Affected Symbols block. Copy all others verbatim from the Existing Code block.
- Do not reformat, reorder, or "improve" protected symbols. Gratuitous churn is a defect, not a feature.
- If the Spec Diff is ambiguous about scope, default to the narrower interpretation.
- If the Spec Diff contradicts the Existing Code, the Spec Diff wins. Always.
- Update the `@unslop-managed` header with new `output-hash`, `spec-hash`, and timestamp after applying edits. Re-hash the full body content for the output-hash.

**Worktree context:** In worktree isolation, the controlling session prepares the three Surgical Context blocks (see below) and injects them into the Builder Agent's prompt. The Builder generates a complete file in the worktree.

**When to use:** The default for all syncs against existing managed files. Covers small spec amendments, added constraints, absorbed change requests, and bug fixes discovered during convergence.

### Surgical Context Blocks

When dispatching the Builder in Surgical mode (existing file, not first generation, not `--refactor`), the controlling session injects three context blocks into the Builder prompt. These blocks are constructed by the controlling session before worktree dispatch -- the Builder receives them as read-only context.

#### Block 1: Existing Code ("Last Successful Compilation Target")

The current managed file, provided as a structural template. The Builder uses this as the baseline for its output -- protected symbols are copied from here verbatim.

**Prompt injection format:**

```
## Existing Code (Last Successful Compilation Target)

This is the current managed file. It is your structural template.
Copy all protected symbols from this file verbatim.
If the Spec Diff contradicts this code, the Spec Diff wins. Always.

<existing-code>
{contents of the current managed file}
</existing-code>
```

#### Block 2: Spec Diff

A summary of which spec sections changed and which did not. The controlling session computes this by diffing the previous spec (at the `spec-hash` recorded in the managed file's header) against the current spec.

**Prompt injection format:**

```
## Spec Diff

Changed sections:
- ## Retry Logic (modified)
- ## Error Types (added)

Unchanged sections:
- ## Module Purpose
- ## Public API
- ## Dependencies
- ## Concurrency Model
```

The Builder uses this to understand the blast radius. Changed sections drive re-derivation of affected symbols. Unchanged sections reinforce that their corresponding symbols are protected.

#### Block 3: Affected Symbols

An authorization list. The controlling session derives this from the Spec Diff by mapping changed spec sections to the symbols they govern (using the Existing Code's structure as the mapping source).

**Prompt injection format:**

```
## Affected Symbols

You are authorized to modify ONLY these symbols. Copy all others verbatim.
Do not reformat, reorder, or "improve" protected symbols.

Authorized symbols:
- retry_with_backoff (function) -- governed by "## Retry Logic"
- RetryError (class) -- governed by "## Error Types"
- MAX_RETRIES (constant) -- governed by "## Retry Logic"

Modify ONLY the authorized symbols listed above. Copy all other symbols verbatim from the Existing Code.
```

### Mode A: Full Regeneration

You MUST generate code from the spec file alone. Do not read the existing generated file -- it is about to be overwritten. Do not read archived originals. The spec is the single source of truth.

This is not a stylistic preference. Reading the current generated file introduces anchoring bias: you will unconsciously reproduce its implementation choices rather than deriving fresh, idiomatic code from the spec's intent. The validation loop exists precisely to catch what the spec missed -- that signal is destroyed if you peek at the previous output.

This rule was established after analyzing generation failures across multiple projects. Every case where the model read the existing file produced anchoring bias that degraded output quality. The rule is non-negotiable -- it has been validated by every successful takeover in unslop's history.

**Permitted reads:**
- The spec file
- The test file(s) for the target module
- `.unslop/config.json` or `.unslop/config.md` (for test command and project conventions)
- `.unslop/principles.md` (project-wide generation constraints, if it exists)
- Language/framework documentation as needed

**Prohibited reads:**
- The current generated source file
- `.unslop/archive/` (original pre-takeover files)

**Worktree context:** In worktree isolation (all generation), Mode A is the natural fit. The Builder starts with a clean context and generates from the spec. The worktree contains the current codebase state but the Builder is instructed not to read the existing managed file.

**When to use:** First generation (new file), takeover, major spec rewrites, `--refactor` flag, periodic "defrag" regeneration (`/unslop:generate --force`), or whenever the controlling agent suspects accumulated implementation drift.

### Mode B: Incremental Generation (DEPRECATED)

Mode B is deprecated. The `--incremental` flag is treated as a no-op with a deprecation warning. All existing-file syncs use Surgical mode instead.

Surgical mode supersedes Mode B by providing the same narrowly-scoped editing discipline but with explicit authorization boundaries (Affected Symbols) and structural context (Compilation Target) that Mode B lacked. Mode B's "honor system" approach to scope discipline was the single most common source of generation failures -- the Builder would expand scope mid-generation with no mechanism to detect or prevent it.

---

## 2. Write the @unslop-managed Header

Every generated file MUST begin with a two-line header using the correct comment syntax for the file's extension.

**Line 1:** `@unslop-managed — do not edit directly. Edit <spec-path> instead.`
**Line 2:** `spec-hash:<12hex> output-hash:<12hex> generated:<ISO8601>`
**Line 3 (optional):** `concrete-manifest:<dep1.impl.md>:<12hex>,<dep2.impl.md>:<12hex>`
**Line N (optional):** `managed-end-line:<line-number>` -- 1-indexed line number where the protected region starts. Present only when the concrete spec declares `protected-regions`. The freshness checker hashes only lines from below the header up to but not including this line.

Use UTC for the timestamp. Format: `2026-03-20T14:32:00Z`

The `concrete-manifest` line is written when the file has permanent concrete spec dependencies. It stores the hash of each direct strategy provider at generation time, enabling **surgical** ghost-staleness detection — `check_freshness()` can pinpoint exactly which upstream dependency changed rather than reporting all deps as suspects.

### Comment Syntax by Extension

| Extension | Comment syntax |
|---|---|
| `.py`, `.rb`, `.sh`, `.yaml`, `.yml` | `#` |
| `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.swift`, `.kt` | `//` |
| `.html`, `.xml`, `.svg` | `<!-- -->` |
| `.css`, `.scss` | `/* */` |
| `.lua`, `.sql`, `.hs` | `--` |

For unknown extensions, use `//` as the default.

### Examples

Python (`.py`):
```python
# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
# concrete-manifest:shared/fastapi-async.impl.md:7f2e1b8a9c04,src/core/pool.py.impl.md:b3d5a1f8e290
```

TypeScript (`.ts`):
```typescript
// @unslop-managed — do not edit directly. Edit src/api-client.ts.spec.md instead.
// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
```

HTML (`.html`):
```html
<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->
<!-- spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z -->
```

CSS (`.css`):
```css
/* @unslop-managed — do not edit directly. Edit src/styles.css.spec.md instead. */
/* spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z */
```

### Write Order

When generating a file, follow this exact sequence:
1. Generate the file body (everything below the header)
2. Apply Python `str.strip()` to the body, then compute its SHA-256 hash truncated to 12 hex chars → `output-hash`
3. Read the spec file content and compute its SHA-256 hash truncated to 12 hex chars → `spec-hash`
3b. If `.unslop/principles.md` exists, hash its content → `principles-hash`
3c. If a permanent concrete spec (`*.impl.md`) exists with `concrete-dependencies` or `extends`, compute the manifest: call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py concrete-deps <impl-path> --root .` and use the `manifest_header` field from the JSON output
4. Write header line 1 (spec path — unchanged)
5. Write header line 2: `spec-hash:<hash> output-hash:<hash> [principles-hash:<hash>] generated:<ISO8601 UTC timestamp>`. **The timestamp MUST be computed via shell command** (`date -u +%Y-%m-%dT%H:%M:%SZ`), not approximated. If shell access is unavailable, omit the `generated:` field entirely rather than emitting `T00:00:00Z`.
5b. If manifest was computed in step 3c, write header line 3: `concrete-manifest:<manifest_header>`
6. Write the body

This ordering ensures the output-hash is computed before the header is written — the header is NOT included in the hash. The concrete-manifest enables surgical ghost-staleness detection: when an upstream dependency changes, `check_freshness()` can identify the exact culprit instead of flagging all deps as suspects.

---

## 3. TDD Integration

Use the superpowers test-driven-development skill. Write tests that validate the spec's constraints first, then implement. The tests ARE the acceptance criteria.

The discipline:
1. Read the spec and the existing test file
2. Identify any spec constraints not yet covered by existing tests — add them
3. Run the test suite; confirm it is red (or confirm existing tests pass before you begin)
4. Write the implementation to make the tests green
5. Refactor within the green state without breaking tests

Do not write implementation code before the tests exist. Do not skip this step because the spec "seems clear enough." The tests are the executable form of the spec's intent.

**Test-writing policy (enforced via `{test_policy}` in Builder prompt):**
- **Takeover:** Builder may write or extend tests for newly explicit constraints.
- **Generate/Sync:** Builder uses existing tests for validation only. Does NOT create or modify test files. This prevents the Builder from weakening assertions to make bad code pass.
- **Change (tactical):** Builder may extend tests for new constraints but must not modify existing assertions.

---

## 4. Idiomatic Output

Generated code should be idiomatic for its language. Do not transliterate the spec into code. The spec says what; you decide how — within the constraints.

This means:
- Use the language's standard library and conventions, not generic patterns ported from elsewhere
- Follow the project's existing style (infer from the test file and surrounding code)
- Do not add comments that restate the spec line-by-line; the header points to the spec, and the tests document behavior
- Do not add `TODO` markers or placeholder stubs — the generated file must be complete and passing

The spec constrains observable behavior. Implementation choices that satisfy the tests and are idiomatic for the language are correct choices. There is no single correct implementation.

---

## 5. Config Awareness

Read `.unslop/config.json` (or `.unslop/config.md` as legacy fallback) for the project's test command before running tests.

If `.unslop/config.json` does not exist or does not specify a test command, infer it from the project's conventional tooling (e.g., `pytest` for Python projects with `pyproject.toml`, `npm test` for Node projects with `package.json`). Do not guess blindly — look at the project root before choosing a fallback.

Always run the test suite after generation to confirm the output is green before declaring the task complete.

---

## 6. Multi-File Generation (Per-Unit Specs)

When a spec has a `## Files` section listing multiple output files, you are generating an entire unit from a single spec.

**Rules:**
- Generate each file listed in the `## Files` section separately
- Apply the `@unslop-managed` header to EVERY generated file
- ALL files reference the unit spec path in their header (e.g., `Edit src/auth/auth.unit.spec.md instead.`)
- Generate files in the order listed in the `## Files` section — earlier files may define types/interfaces that later files use
- Each file must be complete and independently parseable — no stubs or forward references that require manual assembly
- The spec describes the whole unit's behavior; distribute implementation across files according to the responsibilities listed in `## Files`

**Worktree context:** For unit specs, the Builder generates all files listed in `## Files` within the same worktree session. The worktree captures all changes as a single atomic diff.

---

## 7. Post-Generation Completeness Review

After successful generation and green tests, review the spec for completeness. This is advisory — it never blocks.

### Timing

- **For generate/sync:** Run once after the single generation pass produces green tests.
- **For takeover:** Run once after the convergence loop completes successfully (final green tests), before the commit. Do NOT run on each convergence iteration.

### Post-takeover mode (spec was machine-drafted)

Ask:
- Are there behavioral aspects of the generated code not constrained by the spec? A future regeneration might produce different behavior in those areas.
- Are there constraints added during convergence that could be stated more precisely?
- Does the spec leave behavioral choices open that should be pinned down for reproducibility?

Specs that passed tests today but lack explicit constraints will produce different code tomorrow. The completeness review is what distinguishes a spec that works once from a spec that works reliably.

Frame suggestions as: "Consider adding: [constraint]" with a brief rationale.

### Post-generate/sync mode (spec was user-written)

Ask:
- Are there internal contradictions? (e.g., "max 5 retries" in one place, "retries indefinitely" in another)
- Do constraints conflict with `depends-on` specs?
- Does the spec reference behavior or concepts not defined anywhere in the spec?

Only flag clear contradictions or inconsistencies. Do NOT suggest additions or tightening — the user wrote this spec deliberately.

### Result handling

- **No issues found:** Report "Spec review: no issues."
- **Issues found:** Surface as suggestions:

> "Post-generation spec review found N suggestions:
> 1. Consider adding: [constraint] — [rationale]
> 2. Possible inconsistency: [quoted phrase A] vs [quoted phrase B]"

**Never block on completeness review.** The generation succeeded, tests are green. These are improvement suggestions.

---

## 8. Adversarial Quality Integration Point

When `adversarial: true` is set in `.unslop/config.json`, the adversarial quality pipeline (mutation testing, black-box test generation, test quality validation) can run after the Builder succeeds and before the commit.

**Current status:** Integration point -- invoked by `/unslop:adversarial`, not auto-triggered during generation. The user must explicitly run `/unslop:adversarial <spec-path>` after a successful generation to validate test quality. Auto-trigger after Stage B is a planned future enhancement.
