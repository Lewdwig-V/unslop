# Virtual PO: Intent Lock for the Architect (v0.12.3)

**Status:** Design approved
**Scope:** Generation skill Phase 0a.0, change command integration, CI freshness audit
**Milestone:** v0.12.3 "Intent-Locked Architecture"

---

## Problem

The Architect (Stage A) can mutate specs without verifying that its interpretation matches the user's actual goal. Three failure modes:

1. **X-Y drift** -- the user asks for a code change (X) to solve a hidden requirement (Y). The Architect implements X without surfacing Y, producing technically correct but irrelevant spec updates.
2. **Takeover transcription** -- during `/unslop:takeover`, the Architect confuses "how it works" (engineering) with "how it should work" (product), codifying legacy bugs into new specs.
3. **Silent batch drift** -- pending `*.change.md` entries processed by `/unslop:generate` or `/unslop:sync` get interpreted without the human seeing the Architect's understanding of their intent.

## Solution: Phase 0a.0 -- Intent Lock

A new phase inserted before Phase 0a (structural validation) in the generation skill. The Architect must articulate the user's goal in product language and receive explicit approval before touching any spec.

### When it fires

Any time Stage A (Architect) is about to propose a spec mutation:

| Entry point | Trigger |
|---|---|
| `/unslop:change --tactical` | Always (before Architect drafts spec patch) |
| `/unslop:takeover` | Always (before Architect extracts intent from code) |
| `/unslop:generate` or `/unslop:sync` with pending `*.change.md` | Once per file with pending changes (Phase 0c precondition) |

### When it does NOT fire

- `/unslop:spec` -- manual authoring; user is sovereign
- `/unslop:generate` or `/unslop:sync` with no pending changes -- no Architect stage; Builder runs directly
- Stage B (Builder) -- never touches specs
- CI pipelines -- see CI Abort Protocol below

### The protocol

1. The Architect reads the change intent source (the `*.change.md` entry, the `--tactical` description, or the takeover target) and the current spec.
2. It drafts a one-sentence **Intent Statement**.
3. It presents this to the user and waits for explicit approval.
4. **Approved** -- proceed to Phase 0a (structural validation).
5. **Rejected** -- stop. See Rejection Protocol below.

### Intent Statement format

**Standard (tactical and pending changes):**

> "I understand you want to [abstract goal]. To achieve this, I'll update the [spec name] spec to [constraint-level description of the change]."

**Takeover variant:**

> "From the existing code, I understand this module's purpose is [extracted intent]. I'll draft a spec that captures [key behaviors]. Does this match your understanding of what this code should do?"

### Language constraint

The goal in the Intent Statement must be expressed in user/product language, not implementation language.

- **Pass:** "Ensure token expiration is strictly enforced"
- **Fail:** "Add a TTL check to the auth middleware"

If the Architect cannot explain the change without referencing implementation details, it has not extracted the requirement. It must reformulate before presenting.

---

## Change Command Integration

### Tactical path (a)

The change command's Stage A block gains a step 0 before the existing step 1:

0. **Intent Lock** -- Draft intent statement from the `--tactical` description. Present to user. Wait for approval.
1. Read spec, principles, file tree *(unchanged)*
2. Propose spec update *(unchanged)*
3. Present to user for approval *(unchanged)*
4. Apply if approved *(unchanged)*

The Intent Lock (step 0) and the spec approval (step 3) are not redundant. Step 0 validates "am I solving the right problem?" Step 3 validates "is this the right spec change to solve it?"

### Batched pending changes -- path (c)

When `/unslop:generate` or `/unslop:sync` processes a file with multiple pending `*.change.md` entries, the Intent Lock fires **once per file**, not once per entry. The Architect aggregates all pending entries and presents a single combined intent statement:

> "I understand you want to [combined goal from N pending changes]. I'll update [spec] to [summary of constraint changes]."

**Sequencing with Phase 0c:** Phase 0a.0 approval is a prerequisite for entering Phase 0c (change request consumption) for that file. The flow is: Phase 0a.0 presents the aggregated intent and gets a single y/n -- then Phase 0c processes entries individually, applying each to the spec. Phase 0c's per-entry rejection (skip an individual entry) still applies after Phase 0a.0 approval. The Intent Lock validates "is the combined direction correct?" while Phase 0c validates "is each specific spec mutation correct?" -- the double-gate principle operates at both levels.

**Rejection granularity:** Phase 0a.0 is all-or-nothing per file. If the user rejects the aggregated intent, all pending entries for that file are retained and the file is skipped. The user cannot partially approve at the Intent Lock level. To remove a bad entry before re-running, edit or delete the entry from `*.change.md` manually, then re-invoke the command.

### Conflicting intent detection

If pending entries contain contradictory requirements (e.g., "set timeout to 5s" and "set timeout to 10s"), the Architect must surface the conflict explicitly before asking for approval:

> "Pending changes for `[file]` contain conflicting intent: [Change A] requests [X], [Change B] requests [Y]. Which takes precedence?"

This is not a new phase -- it is the Intent Lock doing its job. If a coherent one-sentence intent cannot be written, the requirements are not coherent.

---

## Rejection Protocol

### Path (a) -- tactical

- No side effects. The file remains in its previous state.
- The entry remains in `*.change.md` for future resolution.
- The Architect asks: "Could you clarify the requirement? I misunderstood [X] as [Y]."
- The user can clarify in the same session; the Architect reformulates and re-presents the Intent Statement. No limit on reformulation attempts.

### Path (b) -- takeover

- No side effects. No spec is created.
- The Architect reformulates in the same session based on user feedback: "Could you clarify the requirement? I understood this module's purpose as [X], but that doesn't match your intent."
- The Architect may re-present the Intent Statement after reformulation. No limit on attempts.
- If the user abandons (exits the session), no artifacts are left behind.

### Path (c) -- pending changes

- The `*.change.md` entries are retained.
- The sync for that specific file is skipped.
- The file stays stale (pending changes).
- Other files in the same batch continue processing normally.

Persistence prevents the "amnesia" problem: the intent is not deleted because the Architect's first interpretation was wrong. It stays in the sidecar until a successful Intent Lock is achieved in a future session.

---

## CI Abort Protocol

### Principle

CI is for compilation and audit, not architecture. Spec mutations require interactive human approval. CI never performs architectural lowering.

### Mechanism

The existing `check-freshness` command already detects pending `*.change.md` sidecars and includes them in the freshness determination (see `checker.py` `check_freshness` function). The new behavior extends the **output formatting** to surface a distinct error class with actionable guidance, rather than adding detection from scratch.

**Current output on staleness:**
```
FAIL: src/auth.py is stale (spec-hash mismatch)
```

**New output on pending changes:**
```
FAIL: src/auth.py has 2 pending change(s) requiring interactive approval.
  Run 'unslop:sync src/auth.py' locally to approve the spec update.
  CI cannot perform architectural lowering (Phase 0a.0 requires human approval).
```

### Design decisions

- **No `--ci` flag.** The Intent Lock is interactive by nature -- it always requires a TTY. If someone wires `sync` into a CI script, it hangs waiting for input, which is the correct failure mode (timeout, not silent auto-approve).
- **No pre-commit hooks.** Pre-commit hooks are fragile (`--no-verify`), don't survive `git clone`, and add friction to every commit. The CI freshness check is the audit layer.
- **No changes to `unslop:init`.** The CI workflow template already runs `check-freshness`. The new pending-changes check is additive -- existing setups get it for free.

---

## The Double-Gate Guarantee

The Intent Lock (Phase 0a.0) and spec approval (Stage A step 3) are both mandatory for all Architect-mediated changes. There is no force-approve mechanism.

| Gate | Question | Failure mode caught |
|---|---|---|
| Phase 0a.0 (Intent) | "Am I solving the right problem?" | X-Y drift, takeover transcription |
| Stage A approval (Spec) | "Is this the right spec change?" | Incorrect lowering, over-scoped constraints |

A perfect blueprint for the wrong bridge is still a failure. These gates are independent.

---

## Pipeline Summary

The Symphony-Lite pipeline with Intent Lock:

```
User Intent
    |
    v
Phase 0a.0: Virtual PO (Intent Lock)
    |  "I understand you want to [goal]. Proceed?"
    v
Phases 0a-0e.1: Validation Gates
    |  Structural, pseudocode, ambiguity, coherence checks
    v
Stage A.1: Architect (Intent -> Spec)
    |  Drafts *.spec.md patch, user approves
    v
Stage A.2: Strategist (Spec -> Concrete)
    |  Lowers to *.impl.md
    v
Stage B: Builder (Concrete -> Code)
    |  Isolated worktree, zero conversation history
    v
Verification: Tests pass -> atomic merge
    |
    v
CI: check-freshness (Spec-to-Code audit)
```

Each stage sees only what it needs. The Virtual PO looks backward at conversation context. The Architect looks at specs and principles. The Builder looks at specs only. CI looks at hashes only.

---

## Files to modify

1. **`unslop/skills/generation/SKILL.md`** -- Add Phase 0a.0 section before Phase 0a. Add "When Phase 0a.0 fires" guard conditions. Add Intent Statement format and language constraint.
2. **`unslop/commands/change.md`** -- Insert Intent Lock as step 0 in the tactical flow (Stage A block). Add batched intent synthesis for path (c) cross-reference.
3. **`unslop/skills/triage/SKILL.md`** -- No changes needed. Triage routes to commands; the commands enforce the gate.
4. **`unslop/scripts/orchestrator.py`** -- Add pending-changes detection to `check-freshness` subcommand. New error class for pending intent.
5. **`unslop/commands/generate.md`** / **`unslop/commands/sync.md`** -- Add cross-reference to Phase 0a.0 for the "pending changes trigger Architect stage" path.
6. **`unslop/commands/takeover.md`** -- Insert Intent Lock (takeover variant) before Stage A step 1 (Discover). The Architect must present the takeover intent statement before reading existing code to extract intent.
