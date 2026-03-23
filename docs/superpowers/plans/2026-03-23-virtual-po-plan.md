# Virtual PO Intent Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 0a.0 Intent Lock to the generation pipeline -- forces the Architect to articulate user intent in product language before any spec mutation.

**Architecture:** New phase (0a.0) in the generation skill fires before structural validation whenever Stage A is active. The change command gains a step 0 for tactical flows. The freshness checker gets improved output formatting for pending-change failures in CI. No new Python modules -- all skill-level changes are in markdown; the only code change is output formatting in checker.py.

**Tech Stack:** Python (checker.py), Markdown (skills/commands)

**Spec:** `docs/superpowers/specs/2026-03-23-virtual-po-design.md`

---

### Task 1: Add Phase 0a.0 to the Generation Skill

**Files:**
- Modify: `unslop/skills/generation/SKILL.md:334-338` (insert before Phase 0a)

- [ ] **Step 1: Read the current Phase 0a section to confirm insertion point**

The new section goes between the `## 0. Pre-Generation Validation` header (line 334) and `### Phase 0a: Structural Validation` (line 338).

- [ ] **Step 2: Insert Phase 0a.0 section**

Insert the following after line 336 ("Before generating any code, validate the spec. This section runs first -- if validation fails, no code is written.") and before `### Phase 0a: Structural Validation`:

```markdown
### Phase 0a.0: Intent Lock (Stage A Only)

Before any spec validation or mutation, the Architect must articulate the user's goal and receive explicit approval. This phase runs ONLY in Stage A (Architect) -- the Builder skips it entirely.

**When Phase 0a.0 fires:**

| Entry point | Trigger |
|---|---|
| `/unslop:change --tactical` | Always (before Architect drafts spec patch) |
| `/unslop:takeover` | Always (after Discover, before Draft Spec) |
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

**Batched pending changes (generate/sync path):** When processing a file with multiple pending `*.change.md` entries, fire the Intent Lock **once per file** with an aggregated intent statement. If entries contain contradictory requirements, surface the conflict:

> "Pending changes for `[file]` contain conflicting intent: [Change A] requests [X], [Change B] requests [Y]. Which takes precedence?"

Phase 0a.0 approval is a prerequisite for entering Phase 0c for that file. Phase 0c's per-entry rejection still applies after Phase 0a.0 approval -- the Intent Lock validates combined direction; Phase 0c validates individual spec mutations.

**Rejection granularity:** Phase 0a.0 is all-or-nothing per file. Rejecting the aggregated intent retains all entries and skips the file. To remove a bad entry, edit `*.change.md` manually and re-run.

**Rejection protocol:**

- **Tactical (path a):** The entry remains in `*.change.md`. The Architect asks "Could you clarify the requirement?" and may reformulate in the same session. No limit on attempts.
- **Takeover (path b):** No spec is created. The Architect reformulates in the same session. If the user abandons (exits), no artifacts are left behind.
- **Pending changes (path c):** All entries retained. File skipped. Other files in the batch continue normally.

**No force-approve.** There is no force-approve or auto-approve mechanism for Phase 0a.0. The double-gate (Intent Lock + spec approval) is mandatory for all Architect-mediated changes.

**CI abort:** In non-interactive environments, Phase 0a.0 never fires because the Intent Lock requires a TTY. Interactive commands (`sync`, `generate`) will hang waiting for input -- the correct failure mode (timeout, not silent auto-approve). The `check-freshness` command surfaces pending changes as a distinct error class (see Task 4).
```

- [ ] **Step 3: Verify the insertion doesn't break Phase 0a numbering**

Read the file around the insertion point. Confirm Phase 0a.0 appears before Phase 0a and the section hierarchy is correct.

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Phase 0a.0 Intent Lock to generation skill"
```

---

### Task 2: Add Intent Lock to the Change Command

**Files:**
- Modify: `unslop/commands/change.md:110-115` (insert step 0 before Stage A step 1)

- [ ] **Step 1: Read the current Stage A block in change.md**

Lines 110-115 contain the tactical Stage A flow. The Intent Lock inserts as step 0 before step 1.

- [ ] **Step 2: Insert Intent Lock step**

Before line 111 ("1. Read the current spec..."), insert:

```markdown
0. **Intent Lock (Phase 0a.0):** Draft an Intent Statement from the change description in product language: "I understand you want to [goal]. To achieve this, I'll update [spec] to [constraint]." Present to the user and wait for approval. If rejected: ask "Could you clarify the requirement? I misunderstood [X] as [Y]." and reformulate. The entry remains in `<file>.change.md` until an Intent Lock succeeds. Only proceed to step 1 after explicit approval.
```

- [ ] **Step 3: Add a note about the double-gate**

After step 3 ("Present the draft spec update to the user for approval."), add a parenthetical:

```markdown
(Note: Step 0 validates "am I solving the right problem?" Step 3 validates "is this the right spec change?" These are independent gates -- see Phase 0a.0 in the generation skill.)
```

- [ ] **Step 4: Add path (c) cross-reference**

After the `**If [pending] (default, no --tactical flag)**` section at the end of the file, add:

```markdown
**Batched changes (path c):** When pending changes are processed via `/unslop:generate` or `/unslop:sync`, Phase 0a.0 fires once per file with an aggregated intent statement before Phase 0c processes individual entries. See the generation skill's Phase 0a.0 section for the batched intent protocol.
```

- [ ] **Step 5: Commit**

```bash
git add unslop/commands/change.md
git commit -m "feat: add Intent Lock step 0 to change command tactical flow"
```

---

### Task 3: Add Intent Lock to the Takeover Command

**Files:**
- Modify: `unslop/commands/takeover.md:42-44` (insert Intent Lock between Discover and Draft Spec)

- [ ] **Step 1: Read the current Stage A description in takeover.md**

Lines 42-44 describe Stage A as "Steps 1-3 of the takeover skill (Discover, Draft Spec, Archive)."

- [ ] **Step 2: Insert Intent Lock between Discover and Draft Spec**

Replace the Stage A description at line 43 with:

```markdown
- **Stage A (Architect -- current session):** Step 1 of the takeover skill (Discover) reads the existing code and tests. Then **Phase 0a.0 (Intent Lock)** fires: the Architect presents "From the existing code, I understand this module's purpose is [intent]. I'll draft a spec that captures [behaviors]. Does this match your understanding?" If rejected, the Architect reformulates in the same session; if the user abandons, no artifacts are left. After Intent Lock approval, Steps 2-3 (Draft Spec, Archive) proceed.
```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/takeover.md
git commit -m "feat: add Intent Lock to takeover command between Discover and Draft Spec"
```

---

### Task 4: Improve check-freshness Output for Pending Changes

**Files:**
- Modify: `unslop/scripts/freshness/checker.py:767-771` (improve output for pending-change failures)
- Test: `tests/test_orchestrator.py` (add test for new output format)

- [ ] **Step 1: Write the failing test**

Add a test that verifies the new output structure when pending changes cause a failure. The test checks that the result includes a `pending_intent_files` list in the top-level response:

```python
def test_check_freshness_pending_intent_summary(tmp_path):
    """check-freshness result includes pending_intent_files for CI messaging."""
    from unslop.scripts.orchestrator import check_freshness, compute_hash

    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nAdd a feature.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"
    assert "pending_intent_files" in result
    assert len(result["pending_intent_files"]) == 1
    pif = result["pending_intent_files"][0]
    assert pif["managed"] == "thing.py"
    assert pif["count"] == 1
```

Add a negative test verifying the key is absent for clean results:

```python
def test_check_freshness_no_pending_intent_files_when_clean(tmp_path):
    """pending_intent_files should not appear when there are no pending changes."""
    from unslop.scripts.orchestrator import check_freshness, compute_hash

    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "pass"
    assert "pending_intent_files" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::test_check_freshness_pending_intent_summary tests/test_orchestrator.py::test_check_freshness_no_pending_intent_files_when_clean -v`
Expected: FAIL with KeyError on `pending_intent_files`

- [ ] **Step 3: Implement pending_intent_files in check_freshness**

In `unslop/scripts/freshness/checker.py`, after line 769 (`summary = ...`) and before the `return` on line 771, add:

```python
    # Collect files with pending changes for CI messaging
    pending_intent_files = [
        {"managed": f["managed"], "count": f["pending_changes"]["count"]}
        for f in files
        if "pending_changes" in f
    ]
```

Then update the return statement on line 771 to:

```python
    result = {"status": "pass" if all_fresh else "fail", "files": files, "summary": summary}
    if pending_intent_files:
        result["pending_intent_files"] = pending_intent_files
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py::test_check_freshness_pending_intent_summary -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -v`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add unslop/scripts/freshness/checker.py tests/test_orchestrator.py
git commit -m "feat: add pending_intent_files to check-freshness output for CI messaging"
```

---

### Task 5: Add Cross-References to Generate and Sync Commands

**Files:**
- Modify: `unslop/commands/generate.md:52-59` (add Phase 0a.0 note to Step 3c)
- Modify: `unslop/commands/sync.md:242-245` (add Phase 0a.0 note to Stage A block)

- [ ] **Step 1: Add Phase 0a.0 cross-reference to generate.md Step 3c**

In `generate.md`, after line 53 ("Before dispatching any Builders, run Phase 0c for ALL files that have pending `*.change.md` entries:"), insert:

```markdown
**Phase 0a.0 gate:** Before running Phase 0c for a file, the generation skill's Phase 0a.0 (Intent Lock) fires -- the Architect presents an aggregated intent statement for all pending entries on that file and waits for approval. Only after approval does Phase 0c process individual entries. See the generation skill's Phase 0a.0 section for the full protocol.
```

- [ ] **Step 2: Add Phase 0a.0 cross-reference to sync.md Stage A block**

In `sync.md`, after line 242 ("**Stage A (Architect -- if pending changes exist):**"), insert:

```markdown
**Phase 0a.0 gate:** Before processing pending entries, the generation skill's Phase 0a.0 (Intent Lock) fires -- the Architect presents an aggregated intent statement and waits for approval. See the generation skill's Phase 0a.0 section.
```

- [ ] **Step 3: Commit**

```bash
git add unslop/commands/generate.md unslop/commands/sync.md
git commit -m "feat: add Phase 0a.0 cross-references to generate and sync commands"
```

---

### Task 6: Bump Plugin Version

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json` (bump version to 0.14.0)

- [ ] **Step 1: Bump version**

Update `plugin.json` version from `"0.13.0"` to `"0.14.0"`.

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.14.0 for Intent Lock feature"
```

---

### Verification

After all tasks are complete:

- [ ] Run `python -m pytest tests/ -v` -- all tests green
- [ ] Verify Phase 0a.0 appears before Phase 0a in `generation/SKILL.md`
- [ ] Verify change.md has step 0 before step 1 in Stage A
- [ ] Verify takeover.md inserts Intent Lock between Discover and Draft Spec
- [ ] Verify generate.md and sync.md reference Phase 0a.0
- [ ] Verify plugin.json is at 0.14.0
