# `rejected:` Frontmatter, Constitutional Principles, and Adversarial Loop Tightening

**Date:** 2026-03-27
**Status:** Draft

## Motivation

The spec is a communication protocol between two stateful agents with different memory architectures. The human has persistent memory, rich context, and ambiguous intent. The model has precise execution, no persistent memory, and needs structured state to reconstruct what the human meant. Everything in the frontmatter solves that mismatch -- not making English more precise, but making the human's mental state more legible to a context-free reader.

Three gaps remain:

1. **Closed questions have no durable form.** `uncertain:` handles open questions ("was this accidental?"), `discovered:` handles correctness requirements ("does your intent require this?"), but there's no place for *closed* questions -- "we considered X and rejected it because Y." Without this, the model re-proposes rejected approaches every time context evaporates, and the human re-litigates decisions that were already made. The elicit dialogue naturally produces this reasoning, but it evaporates when the session ends.

2. **Principles are advisory, not constitutional.** `.unslop/principles.md` exists and generation checks for direct contradictions, but the Saboteur doesn't verify principles compliance in generated code. Principles erode under implementation pressure because violations surface in status as informational findings, not as blocking failures. They should be invariants, not guidelines.

3. **The Saboteur is reactive, not adversarial.** The current post-generate async pass checks "does the code satisfy the spec?" via mutation testing. It doesn't ask "what inputs would make the code fail the spec?" -- proactively hunting for edge cases the spec didn't anticipate and checking whether the implementation handles them gracefully or silently fails. This gap-finding work is assigned to cover, but running it inline during the async Saboteur pass would tighten the feedback loop.

## Part 1: `rejected:` Frontmatter Field

### Spec Language Addition

```yaml
---
rejected:
  - title: "Database-backed storage"
    rationale: "Zero runtime dependencies required. SQLite adds a binary dependency and complicates deployment to Lambda."
  - title: "Global retry counter"
    rationale: "Per-request isolation is a hard requirement. A shared counter creates contention under concurrent load."
---
```

### Semantics

Each entry has two required fields: `title` and `rationale`.

- **Written by:** `/unslop:elicit` during creation, amendment, or distillation review mode. When the Architect explores an approach and the user explicitly rejects it, the Architect records the rejected alternative with the user's reasoning.
- **Written by:** `/unslop:distill` when the Archaeologist identifies plausible alternatives the code didn't take. These enter as `uncertain:` items first ("why doesn't this use a database?"), and if the user dismisses them during elicit with a reason, they move to `rejected:`.
- **Consumed by:** `/unslop:elicit` in amendment mode -- the Architect reads `rejected:` before proposing changes to avoid re-proposing rejected approaches. If the Architect considers proposing something that matches a rejected entry, it must acknowledge the prior decision: "This was previously rejected because [rationale]. Has anything changed?"
- **Consumed by:** `/unslop:generate` Stage 0 (Archaeologist) -- when projecting the concrete spec, the Archaeologist reads `rejected:` and avoids strategies that align with rejected approaches. If the Archaeologist's preferred strategy matches a rejected entry, it must surface this as a `discovered:` item: "The most natural implementation strategy aligns with a previously rejected approach [title]. Should I proceed differently?"
- **Persists after ratification.** Like `distilled-from:`, rejected alternatives are permanent records. The reasoning that led to a decision is as important as the decision itself, and removing it recreates the context evaporation problem.
- **Can be removed explicitly.** If circumstances change ("we now have a database dependency anyway"), the user can remove a rejected entry during an elicit amendment pass. This is an explicit action, never automatic.

### Recording Boundary: Explicit vs Implicit Dismissal

The Architect records a `rejected:` entry only when the user provides a reason. Three cases:

1. **User gives a reason:** "Let's not do that -- we need zero runtime dependencies." The Architect records `title: "Database-backed storage"`, `rationale: "Zero runtime dependencies required."` Recorded.
2. **User dismisses without reason:** "Let's not do that." The Architect prompts once for a rationale: "Can you say briefly why not? This helps avoid re-proposing it in future sessions." If the user provides one, record it. If the user declines ("just move on"), do not record. The decision is dismissed but not durable.
3. **User ignores or changes topic.** Do not record. Do not prompt.

The rule: **no rationale, no record.** A rejected entry without reasoning is noise -- it tells the model "don't do X" but not why, which means the model can't judge whether circumstances have changed. If the user won't articulate a reason, the rejection isn't durable enough to persist across sessions.

### Distinction from `non_goals:`

| | `non_goals:` | `rejected:` |
|---|---|---|
| **What it records** | Intent assertion: "we are not doing X" | Reasoning record: "we considered X and decided against it because Y" |
| **Why it exists** | Enforcement -- generate surfaces tension if code implements a non-goal | Context preservation -- prevents re-litigation of settled decisions |
| **Model behaviour** | Generate blocks or warns on violation | Elicit/Archaeologist reads before proposing, acknowledges prior decision |
| **Lifecycle** | Durable, removed only by explicit elicit amendment | Durable, removed only by explicit elicit amendment |

A non-goal with no rejected entry means "we're not doing X, full stop." A rejected entry with no corresponding non-goal means "we considered X and decided against it for now, but it's not fundamentally out of scope."

### Parser

Add `parse_rejected(content: str) -> list[dict]` to `frontmatter.py` via `_parse_nested_list_field`. Entry delimiter: `- title:`. Required fields: `{"title", "rationale"}`.

## Part 2: Constitutional Principles (Hard Gate)

### Current State

`.unslop/principles.md` is read by:
- The Architect (Stage A.1) as context for spec interpretation
- The Archaeologist (Stage 0) as input alongside the abstract spec
- The generation skill's ambiguity detection (Phase 0b) for principle-spec conflict checking

The principle-spec conflict check in generation already hard-blocks if the spec directly contradicts a principle. But there is no post-generation verification that the *code* complies with principles. The Saboteur checks spec-code fidelity via mutations but doesn't check principle-code compliance.

### The Gap

A principle says "all error handling must use typed Result types, never exceptions." The spec says "handle connection failures gracefully." The spec doesn't contradict the principle (no conflict at Phase 0b). But the Builder generates code that catches exceptions and returns None. The principle is violated in the implementation, and no gate catches it.

### The Fix: Saboteur as Constitutional Enforcer

The Saboteur's async verification pass gains a second phase: **constitutional compliance checking**.

**Current Saboteur pass:**
1. Mutation testing (does the code satisfy the spec?)

**New Saboteur pass:**
1. Mutation testing (does the code satisfy the spec?)
2. Constitutional compliance (does the code satisfy the principles?)

Constitutional compliance checking:
1. Read `.unslop/principles.md`.
2. For each principle, check whether the generated code violates it. This is LLM-native analysis, not mechanical -- principles are natural language, and violations require judgment.
3. Each violation is a finding with: `principle` (which principle), `location` (file + line range), `violation` (what the code does), `required` (what the principle requires).

### Verification Output Schema Extension

The verification JSON gains a `constitutional_violations` field:

```json
{
  "managed_path": "src/retry.py",
  "spec_path": "src/retry.py.spec.md",
  "status": "fail",
  "constitutional_violations": [
    {
      "principle": "All error handling must use typed Result types",
      "location": "src/retry.py:45-52",
      "violation": "Catches ConnectionError and returns None",
      "required": "Return Result[Response, ConnectionError]"
    }
  ],
  "mutants_total": 20,
  "mutants_killed": 18,
  ...
}
```

### Blocking Semantics

Constitutional violations are **distinct from mutation test failures** in severity:

- **Mutation test failures:** Informational. Surfaced in status. Do not block anything. The user can run `/unslop:cover` to investigate.
- **Constitutional violations:** **Block `intent-approved` promotion.** A spec with constitutional violations in its verification result cannot be ratified. The user must either fix the code (re-generate), update the principle (if it no longer applies), or explicitly override with `--force-constitutional`.

The blocking mechanism:
- `/unslop:elicit` reads the verification result before allowing `intent-approved` promotion. If `constitutional_violations` is non-empty, elicit warns: "Generated code violates N principle(s). Ratifying the spec would approve code that violates project principles. Fix the violations first, or use `--force-constitutional` to override."
- This is a soft-block (the user can override), not a hard-block (which would prevent all progress). The override is explicit and auditable.

### Override Audit Trail

When the user passes `--force-constitutional`, the override is recorded in two places:

1. **`constitutional-overrides:` frontmatter** on the spec:
   ```yaml
   constitutional-overrides:
     - principle: "All error handling must use typed Result types"
       rationale: "Legacy API requires exception-based error handling for backward compatibility"
       timestamp: 2026-03-27T14:30:00Z
   ```
   Each entry has three required fields: `principle`, `rationale`, `timestamp`. The user must provide a rationale -- `--force-constitutional` without a reason is rejected.

2. **`## Changelog` prose entry** recording the override as part of the ratification narrative.

`constitutional-overrides:` persists after ratification. It's a permanent record that this spec knowingly deviates from a project principle. If the principle is later updated or removed, the override entry becomes stale but is not automatically cleaned -- the user should remove it during the next elicit amendment pass.

Weed can cross-reference `constitutional-overrides:` against current `principles.md` to detect stale overrides (principle was removed or changed since the override was recorded).

### Status Display

```
  fresh      src/retry.py           <- src/retry.py.spec.md
             ⚠ Constitutional violation: "All error handling must use typed Result types"
               src/retry.py:45-52 -- catches ConnectionError and returns None
```

Constitutional violations display alongside mutation test results in status. They use the same `⚠` icon but are labeled distinctly.

### Why the Saboteur, Not the Builder

The Builder could check principles during generation, but this conflates generation with verification. The Builder's job is mechanical: implement from spec + concrete spec. The Saboteur's job is adversarial: check whether the output satisfies constraints. Principles are constraints. Keeping the check in the Saboteur maintains the separation of concerns and means the check runs on the *merged* code (post-worktree), not on the in-progress code.

## Part 3: Adversarial Loop Tightening

### Current State

The Saboteur's post-generate async pass runs mutation testing: generate mutants, run tests, classify survivors. This checks "does the code satisfy the spec?" -- it verifies that the test suite catches deviations from specified behaviour.

Cover (a separate phase) runs the full adversarial pipeline: Saboteur generates mutations -> Archaeologist classifies survivors -> Mason writes targeted tests -> iterate. This is more thorough but requires explicit invocation.

### The Gap

The Saboteur doesn't ask "what inputs would break this code in ways the spec didn't anticipate?" Current mutation testing only checks paths the spec describes. Edge cases the spec didn't think of -- malformed input, resource exhaustion, unexpected type coercion -- are invisible until cover runs.

### The Fix: Edge Case Probing in Async Verification

The Saboteur's async pass gains a third phase after mutation testing and constitutional checking:

**New Saboteur pass:**
1. Mutation testing (does the code satisfy the spec?)
2. Constitutional compliance (does the code comply with principles?)
3. Edge case probing (what would break this code that the spec didn't anticipate?)

Edge case probing:
1. Read the spec and the generated code.
2. Generate adversarial inputs: boundary values, malformed data, null/empty/oversized inputs, concurrent access patterns, resource exhaustion scenarios. These are not derived from the spec -- they're derived from the *code's attack surface*.
3. For each adversarial input, assess: does the code handle this gracefully (explicit error, typed result, documented limitation), or does it fail silently (swallowed exception, undefined behaviour, data corruption)?
4. Silent failures become findings. Graceful handling is not a finding (even if the spec didn't mention it).

**Budget constraint:** Maximum 10 edge case findings per file. If the Saboteur identifies more than 10 potential findings, it ranks by severity (silent data corruption > unhandled exception > resource leak > unexpected behaviour) and reports only the top 10. This bounds the async pass runtime and keeps the status output signal-dense rather than noisy. The budget is configurable via `config.edge_case_budget` (default: 10).

### Finding Structure

Edge case findings use a distinct structure from mutation and constitutional findings:

```json
{
  "edge_case_findings": [
    {
      "input": "Empty string for retry URL",
      "expected": "Explicit error or validation rejection",
      "actual": "Passes through to HTTP client, which throws unhandled exception",
      "severity": "high",
      "spec_gap": true
    }
  ]
}
```

The `spec_gap` field distinguishes:
- `true`: The spec didn't mention this case. The finding suggests the spec should be enriched.
- `false`: The spec implies handling for this case but the code doesn't implement it. This is a regular verification failure.

### Non-Blocking Semantics

Edge case findings are **informational**, like mutation test results. They surface in status and suggest spec enrichment or cover runs but do not block anything.

```
  fresh      src/retry.py           <- src/retry.py.spec.md
             ✓ Verified (18/20 mutants killed, 2 equivalent)
             ⚠ 2 edge cases found (run /unslop:cover or enrich spec)
```

The rationale for non-blocking: edge case findings are speculative. The Saboteur is identifying *potential* problems, not verified violations. Blocking on speculation would make generate unpredictable and frustrating. The findings are a signal to the user: "there's something worth investigating here."

### Interaction with Cover

Cover already does thorough edge case analysis. The Saboteur's inline probing is a lightweight, fast version that runs automatically. If the Saboteur finds edge cases, the user can run cover for deep investigation. This is the same relationship as status (lightweight staleness check) vs weed (deep drift analysis) -- the lightweight version runs automatically, the deep version runs on demand.

## Part 4: AGENTS.md Meta-Point

Add the following to AGENTS.md under a new section "## Design Philosophy":

> The spec is a communication protocol between two stateful agents with different memory architectures. The human has persistent memory, rich context, and ambiguous intent. The model has precise execution, no persistent memory, and needs structured state to reconstruct what the human meant. Everything in the frontmatter solves that mismatch -- not making English more precise, but making the human's mental state more legible to a context-free reader.

This frames the entire frontmatter system and should be the first thing an agent reads about unslop's architecture.

## Part 5: Spec Changelog (Reviewable Intent Deltas)

### The Problem

When a spec changes, the *what* is captured (the new spec body, the new intent-hash) but the *why* evaporates. Git tracks code diffs; nothing tracks intent diffs. A reviewer looking at a spec can see what it says now but not how it got there, what was tried and discarded, or what reasoning drove each mutation.

### Two Layers, Linked but Separate

The changelog splits into a structured envelope (machine-queryable, in frontmatter) and a narrative body (human-readable, in the spec document).

#### Structured Layer: `spec-changelog:` Frontmatter

```yaml
---
spec-changelog:
  - hash: abc123def456
    timestamp: 2026-03-27T14:30:00Z
    operation: elicit-amend
    prior-hash: 9f8e7d6c5b4a
  - hash: 7a8b9c0d1e2f
    timestamp: 2026-03-27T10:15:00Z
    operation: absorb
    prior-hash: null
---
```

Each entry has four required fields:
- `hash` -- the intent-hash after this change
- `timestamp` -- ISO 8601 when the change was made
- `operation` -- what produced the delta (see vocabulary below)
- `prior-hash` -- the intent-hash before this change (null for the first entry)

**Operation vocabulary:**

| Operation | Produced by | Meaning |
|---|---|---|
| `elicit-create` | `/unslop:elicit` (creation mode) | Spec created from scratch via Socratic dialogue |
| `elicit-amend` | `/unslop:elicit` (amendment mode) | Existing spec modified via dialogue |
| `elicit-distill-review` | `/unslop:elicit` (distillation review) | Machine-inferred spec reviewed and ratified |
| `distill` | `/unslop:distill` | Candidate spec inferred from code |
| `absorb` | `/unslop:absorb` | Spec created/amended by merging file specs |
| `exude` | `/unslop:exude` | Spec created by partitioning a unit spec |
| `change-tactical` | `/unslop:change --tactical` | Narrow tactical change applied to spec |
| `change-pending` | `/unslop:change` (pending processing) | Pending change request absorbed into spec |

Operations that don't mutate the spec body (`/unslop:verify`, `/unslop:status`, `/unslop:weed`, `/unslop:cover`, `/unslop:generate`) do not produce changelog entries.

Append-only, same semantics as `provenance-history:`. Entries are never modified or removed. The structured layer answers: "show me all changes to this spec", "what was the spec state at hash X?", "which operation produced this delta?"

#### Narrative Layer: `## Changelog` Section in Spec Body

```markdown
## Changelog

### abc123 -- 2026-03-27
Narrowed retry scope after discovering the connection pool handles its own
backoff. Previous approach was double-retrying at two layers. Considered
making retry configurable per-caller but rejected it -- YAGNI, and it would
have leaked implementation detail into the public interface.

### 7a8b9c -- 2026-03-27
Initial spec created via absorb from retry.py.spec.md and backoff.py.spec.md.
Resolved conflict between retry.py's "retry indefinitely" and backoff.py's
"max 5 retries" in favour of bounded retries.
```

Each entry is keyed by the first 6 characters of the intent-hash (linking to the frontmatter entry) and contains free-form prose. The prose is written by the agent that produced the change (Architect during elicit, absorb/exude commands) at the moment of mutation, while the reasoning is still in context.

**Section position:** `## Changelog` is always the **last section** in the spec body, after all active spec content (goals, constraints, dependencies, non-goals, tests, files). Changelog is historical context, not active specification. Placing it at the bottom means a reader encounters the current spec first and the history second. The Architect appends new entries at the top of the Changelog section (reverse chronological -- most recent first), so the most relevant context is always immediately visible.

### Why Split?

Frontmatter is for active signals and structured metadata. Narrative reasoning is documentation. The structured layer lets tools query without parsing prose. The prose layer gives a human reading the spec file the full story immediately, in context, without tooling.

The hash link between the two layers means neither is orphaned: every frontmatter entry has a corresponding prose entry (or should), and every prose entry references a verifiable spec state.

### Lifecycle

- **Written by:** Any operation that mutates the spec body: elicit (all modes), absorb, exude, change (when processing pending entries). The writing agent appends both the frontmatter entry and the prose entry in the same mutation.
- **Consumed by:** Humans reviewing specs. Status (can report "N changes since last generation"). Weed (can correlate drift with specific intent changes).
- **Never modified.** Append-only. If a changelog entry is wrong, add a correction entry, don't edit the original.
- **Growth:** Monotonic. Long-lived specs accumulate entries. The structured layer is small (4 fields per entry). The prose layer can be trimmed by moving old entries to a `## Changelog (archived)` section at the bottom, but this is a human decision, never automated.

### Interaction with `rejected:`

When an elicit amendment adds a `rejected:` entry, the changelog prose records the rejection as part of the narrative: "Considered [approach]. Rejected -- [rationale]." The `rejected:` frontmatter entry is the durable, machine-readable record; the changelog prose is the contextual narrative of when and why.

### Parser

Add `parse_spec_changelog(content: str) -> list[dict]` to `frontmatter.py` via `_parse_nested_list_field`. Entry delimiter: `- hash:`. Required fields: `{"hash", "timestamp", "operation", "prior-hash"}`.

**Note:** `prior-hash` contains a hyphen. The parser's key extraction uses `stripped.partition(":")` which handles this correctly -- the key is everything before the first colon.

### Analysis Layer Exclusion

Like `provenance-history:`, the `spec-changelog:` frontmatter is an audit log. The freshness checker, weed, generate, and all analysis layers MUST filter it out before analysis. It is consumed only by display (status) and audit tooling.

## Part 6: Changes to Existing Commands and Skills

### `/unslop:elicit` (command)

- **Rejected alternatives recording:** During creation, amendment, and distillation review modes, when the user explicitly rejects an approach the Architect proposed, record it as a `rejected:` entry with the user's reasoning.
- **Rejected alternatives checking:** Before proposing changes in amendment mode, read `rejected:` and avoid re-proposing rejected approaches. If a proposal aligns with a rejected entry, acknowledge the prior decision.
- **Constitutional violation check before ratification:** Before setting `intent-approved`, read the verification result. If `constitutional_violations` is non-empty, warn and require `--force-constitutional` to override.
- **Changelog writing:** On every spec mutation (creation, amendment, distillation review), append a `spec-changelog:` frontmatter entry and a `## Changelog` prose entry describing what changed and why.

### `/unslop:generate` (command)

- **Stage 0 Archaeologist reads `rejected:`:** When projecting the concrete spec, the Archaeologist checks rejected entries. If the preferred strategy aligns with a rejected entry, surface as a `discovered:` item.
- **Stage 3 Saboteur gains two new phases:** Constitutional compliance checking and edge case probing, after existing mutation testing.

### `/unslop:change` (command)

- **Changelog writing:** When processing pending or tactical change entries into the spec, append changelog entries (both frontmatter and prose).

### `/unslop:absorb` and `/unslop:exude` (commands)

- **Changelog writing:** On spec creation/mutation from absorb or exude, append changelog entries to the output spec(s). The prose should note the structural operation and which specs were merged/partitioned.

### `/unslop:status` (command)

- **Display constitutional violations** as a distinct finding type with `⚠` icon.
- **Display edge case findings** with count and suggestion to run cover or enrich spec.
- **Display changelog count:** "N changes since last generation" when `spec-changelog:` entries exist after the last generation timestamp.

### `/unslop:verify` (command)

- Gains constitutional compliance and edge case probing (same three-phase pass as the async Saboteur, but synchronous).

### `skills/spec-language/SKILL.md`

- **Rejected Alternatives section:** Document `rejected:` field with semantics, distinction from non-goals, examples.
- **Spec Changelog section:** Document both layers (structured frontmatter + narrative body), linking mechanism, append-only semantics, analysis layer exclusion.

### `skills/adversarial/SKILL.md`

- **Constitutional compliance:** Document the Saboteur's new constitutional checking phase, finding structure, and blocking semantics.
- **Edge case probing:** Document the probing phase, finding structure, and non-blocking semantics.

### `skills/generation/SKILL.md`

- **Archaeologist reads `rejected:`:** Document that Stage 0 checks rejected entries before choosing implementation strategy.

### `scripts/core/frontmatter.py`

- Add `parse_rejected(content)` via `_parse_nested_list_field("rejected", "title", {"title", "rationale"})`.
- Add `parse_spec_changelog(content)` via `_parse_nested_list_field("spec-changelog", "hash", {"hash", "timestamp", "operation", "prior-hash"})`.
- Add `parse_constitutional_overrides(content)` via `_parse_nested_list_field("constitutional-overrides", "principle", {"principle", "rationale", "timestamp"})`.

### `scripts/orchestrator.py`

- Import and re-export `parse_rejected`, `parse_spec_changelog`, and `parse_constitutional_overrides`.

### `AGENTS.md`

- Add "Design Philosophy" section with the communication protocol framing.
- Add `rejected:`, `spec-changelog:`, and `constitutional-overrides:` to the frontmatter fields table.

### `.claude-plugin/plugin.json`

- Bump version.

## What This Does NOT Do

- **No automatic rejection recording.** The Architect records rejections only when the user explicitly dismisses a proposed approach with a reason. Implicit dismissals (user ignores a suggestion, changes topic) do not produce rejected entries.
- **No retroactive principle enforcement.** Constitutional checking runs on newly generated code. It does not retroactively check all existing managed files. Running `/unslop:verify` on an existing file will check it.
- **No blocking on edge case findings.** Edge cases are speculative. They inform, they don't gate.
- **No changes to the Chinese Wall.** The Mason still sees behaviour.yaml only. Constitutional checking is a Saboteur concern.
- **No automatic changelog prose.** The writing agent produces the prose at mutation time. If an operation doesn't write a prose entry (bug), the frontmatter entry still exists as a bare record. Missing prose is detectable (frontmatter entry with no matching `## Changelog` heading) but not enforced mechanically.

## Design Decisions

**Why `rejected:` persists after ratification rather than clearing like `uncertain:`?** `uncertain:` represents open questions that get answered. `rejected:` represents answered questions whose answers remain relevant. The reasoning behind a rejection doesn't become less important after the spec is approved -- it becomes more important, because it's the context a future session needs to avoid re-proposing the same approach.

**Why constitutional violations soft-block ratification rather than hard-block generation?** Generation must complete for the Saboteur to run. You can't check compliance on code that doesn't exist. Hard-blocking generation would create a deadlock. Soft-blocking ratification is the right gate: the code exists, the violation is identified, the user decides how to proceed.

**Why edge case probing is non-blocking while constitutional violations soft-block?** Constitutional violations are objective: the principle says X, the code does not-X. Edge case findings are speculative: the Saboteur *thinks* this input might cause a problem. Blocking on speculation makes the system unpredictable.

**Why the Saboteur does constitutional checking rather than a separate agent?** The Saboteur already runs post-generate and already produces verification results. Adding a finding category is simpler than adding an agent. The cognitive task (adversarial analysis of generated code) is the same -- the Saboteur is asking "what's wrong with this code?" from two angles (spec compliance and principle compliance).

**Why `rejected:` uses title/rationale rather than title/observation/question like `uncertain:`?** Rejected alternatives are statements, not questions. They record a decision and its reasoning. There's nothing to ask -- the question was already asked and answered. The two-field structure matches the semantics: what was rejected, and why.

**Why split the changelog into structured frontmatter and narrative prose?** They serve different consumers. The structured layer (hash, timestamp, operation, prior-hash) answers machine queries: "what changed when?", "what was the state at hash X?" The narrative layer answers human questions: "why did this change?", "what was considered and discarded?" Forcing narrative into frontmatter schema fights the shape of the data. Forcing timestamps into prose makes them unqueryable. The hash link between the two layers means neither is orphaned.

**Why is `spec-changelog:` excluded from analysis layers like `provenance-history:`?** Both are audit logs, not active signals. The freshness checker doesn't need to know *why* a spec changed -- it only needs to know *that* it changed (via hash comparison). The changelog is consumed by humans reviewing specs and by status for informational display, not by any decision-making pipeline.

**Why append-only for the changelog?** If you can edit history, you can't trust history. The changelog's value is that it's a complete, unedited record of a spec's evolution. If a changelog entry is wrong, the correct action is to add a correction entry, not to modify the original. This is the same principle as `provenance-history:` -- audit logs that can be modified are not audit logs.

**Why require a rationale for `--force-constitutional`?** An override without reasoning is indistinguishable from a mistake. The rationale serves the same purpose as `rejected:` -- it prevents re-litigation. Without it, the next session sees a constitutional violation, doesn't know it was consciously accepted, and flags it again. The rationale is the context that makes the override durable.

**Why "no rationale, no record" for rejected alternatives?** A rejection without reasoning is noise. It tells the model "don't do X" but not why, which means the model can't judge whether circumstances have changed. If the user can't articulate a reason, the rejection isn't confident enough to persist across sessions. The single prompt for rationale ("can you say briefly why not?") is a lightweight gate that separates considered decisions from passing preferences.

**Why cap edge case findings at 10?** Without a budget, the Saboteur's probing phase has unpredictable runtime and output volume. A file with 47 edge case findings is not 23x more useful than one with 2 -- it's noise. Severity-ranked selection ensures the most important findings surface. The budget is configurable for projects that want more thorough probing.

**Why is `## Changelog` the last section?** Changelog is historical context, not active specification. A reader encountering a spec for the first time needs the current intent (goals, constraints, dependencies), not the history of how it got there. Bottom placement means the spec is self-contained without the changelog, and the changelog is additive context for readers who want it. Reverse chronological order (most recent first) means the most relevant context is immediately visible without scrolling past years of history.
