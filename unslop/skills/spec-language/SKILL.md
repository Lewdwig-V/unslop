---
name: spec-language
description: Use when writing, drafting, reviewing, or editing unslop spec files (*.spec.md). Activates for spec creation, takeover spec drafting, and spec editing guidance.
version: 0.1.0
---

# Spec-Language Skill

## Core Principle

The two spec layers have different stances. **Abstract Specs** describe **intent** — what a file must do, what constraints it must satisfy, what behavior it must exhibit. **Concrete Specs** describe **strategy** — what algorithm, pattern, or type structure delivers those guarantees, in language-agnostic terms. Neither layer contains target-language code; code is disposable, specs are the source of truth.

## The Two-Layer Spec Model

Unslop uses a compiler-inspired two-layer spec architecture:

| Layer | File | Describes | Analogy |
|---|---|---|---|
| **Abstract Spec** | `*.spec.md` | Observable behavior, constraints, contracts | High-Level IR (the "What" and "Why") |
| **Concrete Spec** | `*.impl.md` | Algorithm, patterns, type structure | Mid-Level IR (the "How") |

**This skill primarily governs Abstract Specs.** The Pseudocode Discipline section below also applies to Concrete Specs. For broader Concrete Spec writing guidance (Strategy, Lowering Notes, Type Sketch), see the `unslop/concrete-spec` skill.

The boundary between the two layers follows a simple rule: **if it's observable from outside the module, it belongs in the Abstract Spec. If it's an internal strategy choice, it belongs in the Concrete Spec (or nowhere — most strategy choices are ephemeral).**

Examples of the boundary:

| Abstract Spec (*.spec.md) | Concrete Spec (*.impl.md) |
|---|---|
| "Retries with exponential backoff, max 5 attempts" | "Full Jitter algorithm: `sleep = cap * random()`" |
| "Results are sorted by relevance score" | "Uses a min-heap for top-K selection, O(n log k)" |
| "Deduplicates within a 5-minute window" | "Sliding window with a hash set, pruned on insert" |
| "Responses cached for 5 minutes" | "LRU cache with TTL, max 1000 entries" |

The Abstract Spec says **what guarantee the caller gets**. The Concrete Spec says **what algorithm delivers that guarantee**. The generated code says **how that algorithm is expressed in the target language**.

## Vocabulary Guide

Abstract specs are written in terms of observable behavior, contracts, and constraints — not data structures, algorithms, or control flow. (Concrete specs intentionally use algorithm and pattern vocabulary; the restrictions below apply to `*.spec.md` files.)

| Good (intent) | Bad (implementation) |
|---|---|
| Messages are stored in SQLite with a monotonic sequence ID | Use INSERT OR REPLACE with a rowid alias column |
| Retries use exponential backoff with jitter, max 5 attempts | `sleep(2**attempt + random.uniform(0,1))` |
| Validation rejects inputs over 1MB | `if len(data) > 1_048_576: raise ValueError` |
| HTTP responses are cached for 5 minutes | Use a dict with `time.time()` keys and prune entries older than 300 |

The right column belongs in code, not specs. If you find yourself writing it in a spec, delete it and replace it with the observable guarantee it was trying to achieve.

## When to Be Specific

Nail down the details that constrain the implementation space and that callers or operators will depend on:

- **Constraints**: size limits, rate limits, timeouts, retry counts, max concurrency
- **Invariants**: ordering guarantees, uniqueness requirements, atomicity expectations
- **Error behavior**: what conditions are errors, what is returned or raised, whether errors are retried or surfaced
- **Boundary conditions**: empty input, zero values, maximum values, missing fields
- **Concurrency guarantees**: thread-safety expectations, whether operations are idempotent, ordering between concurrent callers

## When to Be Vague

Leave these to the implementation:

- **Data structures**: arrays vs linked lists, hash maps vs trees, schema column types beyond what the behavior requires
- **Algorithms**: sort algorithms, search strategies, parse approaches
- **Variable names**: internal identifiers, local bindings, private field names
- **Internal control flow**: loop structures, branching logic, function decomposition

## Register Check

> If your spec reads like commented-out code, it's over-specified.
> If it reads like a product brief with no constraints, it's under-specified.

Over-specified specs break regeneration — every implementation detail becomes load-bearing, so the model can't choose a better approach. Under-specified specs break validation — there's nothing to check the generated code against.

Aim for the middle: the spec should be testable without being prescriptive.

## Open Questions

When a spec intentionally leaves a decision open, mark it explicitly. This prevents the ambiguity linter from blocking generation on deliberate flexibility.

Two mechanisms:

**Inline marker** — add `[open]` on the same line as the flexible statement:

```
Caching strategy uses an appropriate eviction policy [open]
```

**Dedicated section** — list broader open questions with rationale:

```markdown
## Open Questions
- Whether to use LRU or LFU eviction — will benchmark after first deployment
- Error retry backoff curve — depends on upstream SLA negotiations
```

Use Open Questions for decisions that:
- Depend on information not yet available (benchmarks, SLA negotiations, API design not finalized)
- Are genuinely implementation-preference (any reasonable choice is fine)
- Will be resolved in a future spec revision

Do NOT use Open Questions to dodge spec writing. If a constraint is knowable now, specify it. The ambiguity linter will flag abusive use of `[open]` on constraints that clearly need pinning down.

## Suggested Headings

These are not required, but they cover the ground most specs need:

- **Purpose** — What this file does and why it exists
- **Behavior** — The observable contract: inputs, outputs, side effects
- **Constraints** — Bounds, limits, invariants, error conditions
- **Dependencies** — External services, libraries, or other managed files it relies on
- **Error Handling** — Failure modes and how they are surfaced

Use all of them, some of them, or none — structure the spec to match the complexity of the file it describes. A 20-line utility doesn't need five headings.

## Spec Naming Conventions

Specs are named `<file>.spec.md` and placed alongside the managed file:

- `src/retry.py` -> `src/retry.py.spec.md`
- `src/api/handler.ts` -> `src/api/handler.ts.spec.md`

**Directory modules (e.g., Rust `mod.rs`, Python `__init__.py`):** Use the directory name for the spec, not the file name. Add a `managed-file` field to the frontmatter so the resolver knows which file the spec manages:

- `src/dispatch/mod.rs` -> `src/dispatch/dispatch.spec.md` with `managed-file: src/dispatch/mod.rs`
- `src/auth/__init__.py` -> `src/auth/auth.spec.md` with `managed-file: src/auth/__init__.py`

```markdown
---
managed-file: src/dispatch/mod.rs
depends-on:
  - src/dispatch/omnibar.spec.md
intent: >
  Pure state machine core. dispatch(&mut AppState, Action) -> Vec<Effect>
  processes every user action and returns effects for I/O.
intent-approved: 2026-03-26T14:32:00Z
intent-hash: a1b2c3d4e5f6
---

# dispatch spec
```

The `managed-file` field overrides the default filename-stripping heuristic. When absent, the resolver falls back to stripping `.spec.md` from the spec filename (the legacy behavior). The same convention applies to concrete specs.

## Intent

The `intent` field records the human-approved summary of what the spec governs -- the compressed, reviewable statement of purpose that the user confirmed during the intent lock.

| Field | Description |
|---|---|
| `intent` | The approved intent statement. Single-line or YAML folded scalar (`>`). This is the reviewable surface -- "what's this module for?" in 2-3 sentences. |
| `intent-approved` | ISO 8601 timestamp of when the user approved the intent. |
| `intent-hash` | 12-char hex hash of the intent text. Computed by the tooling. If someone edits the intent without re-approving, the hash mismatch is a hard error. |

**Lifecycle:**
- Written during `/unslop:takeover` Step 1b (Intent Lock) after user approval
- Checked during `/unslop:sync` and `/unslop:generate` -- if the spec change alters the module's stated intent, the Architect flags it for re-lock
- The intent is metadata about the spec, not part of the spec body. The Architect/Builder/Strategist never touches anything between the `---` fences during regeneration. Frontmatter is a protected region.

**Tamper detection:** The tooling computes `intent-hash` from the `intent` text. If the hash doesn't match (someone edited the intent without re-running the intent lock), the pipeline stops with a hard error before any semantic analysis runs.

## Non-Goals

The `non_goals` field records explicit exclusions -- things the spec deliberately does NOT cover. Non-goals are generated during `/unslop:elicit` and ratified by the user.

```yaml
---
non_goals:
  - Circuit breaker or load shedding (handled by upstream proxy)
  - Request deduplication (caller's responsibility)
  - Retry of non-idempotent methods (POST, PATCH)
---
```

Each entry is a plain text statement. Non-goals are:
- **Human-approved:** Generated by elicit, confirmed by the user. Never auto-generated without ratification.
- **Durable:** Persist across spec updates. Removing a non-goal requires explicit acknowledgment during an elicit amendment.
- **Enforceable:** `/unslop:generate` surfaces tension if generated code implements a non-goal. `/unslop:weed` flags `code-drifted` findings where code implements something in `non_goals`.

Non-goals complement the spec's positive constraints. Constraints say "the code MUST do X." Non-goals say "the code MUST NOT do Y, and here's why."

## Downstream Review Flags

When an upstream spec changes via `/unslop:change`, downstream specs that depend on it are flagged with `needs-review` to prevent silent intent corruption.

| Field | Description |
|---|---|
| `needs-review` | Intent-hash of the upstream spec at the time of flagging. Identifies which change triggered the review obligation. |
| `review-acknowledged` | Intent-hash of the upstream change that was consciously dismissed. Proves the user reviewed and decided the change doesn't affect this spec. |

**Lifecycle:**
- `needs-review` is written by `/unslop:change` after a spec mutation, for each downstream dependent the user did not immediately review.
- `needs-review` causes a soft-block in `/unslop:generate` and `/unslop:sync` -- the user must acknowledge or address the flag before code generation proceeds.
- `review-acknowledged` is written when the user chooses to acknowledge and proceed past the soft-block.
- Both fields are cleared when the spec goes through its own `/unslop:elicit` amendment pass (the new intent-hash proves the spec was reviewed).
- If the upstream spec changes again, a new `needs-review` overwrites both fields.

**Why the hash?** A naked boolean flag would tell you "something upstream changed" but not what. The hash lets you diff against the specific upstream change, and it lets the system distinguish "flagged and ignored" from "flagged and consciously dismissed."

## Uncertainties

The `uncertain` field records items flagged by `/unslop:distill` as potentially accidental behaviour rather than deliberate design. Each entry gives `/unslop:elicit` a structured question to ask the user.

```yaml
---
uncertain:
  - title: "Unbounded retry loop"
    observation: "Code retries indefinitely with no cap. No test covers this path."
    question: "Is the missing cap intentional or an oversight?"
---
```

Each entry has three required fields: `title`, `observation`, `question`.

- **Written by:** `/unslop:distill` during spec inference.
- **Consumed by:** `/unslop:elicit` in distillation review mode.
- **Cleared when:** Elicit completes its review. Each item is resolved into the spec body, added as a non-goal, or explicitly dismissed.
- **If entries remain:** Informational warnings. Generate proceeds but the spec is less trustworthy.

## Distillation Provenance

The `distilled-from` field records which source file(s) a spec was inferred from and their content hash at distillation time.

```yaml
---
distilled-from:
  - path: src/retry.py
    hash: a3f8c2e9b7d1
---
```

Each entry has two required fields: `path` and `hash`.

- **Written by:** `/unslop:distill`.
- **Persists after ratification.** Provenance records how the spec was produced, not whether it's been reviewed. A spec with `distilled-from:` and `intent-approved: <timestamp>` means "machine-inferred, then human-ratified." Clearing the provenance would destroy the audit trail.
- **Used by elicit:** Triggers distillation review mode (aggressive interrogation of inferred content).
- **Used by weed:** If the source file's current hash doesn't match the `distilled-from` hash, the spec may be out of date relative to the code it was inferred from.

## Dependencies Between Specs

When a managed file imports from or relies on another managed file, declare the dependency in YAML frontmatter:

```markdown
---
depends-on:
  - src/auth/tokens.py.spec.md
  - src/auth/errors.py.spec.md
---

# handler.py spec
...
```

Declare `depends-on` when:
- The file imports from another managed file
- The file calls functions or uses types defined in another managed file
- The file's behavior depends on contracts established by another managed file

Do NOT declare dependencies on:
- Test files (tests are not managed)
- Third-party libraries (not managed by unslop)
- Files that are not under unslop management

Paths are relative to the project root. Only list direct dependencies — the orchestrator resolves transitive dependencies automatically.

## Deferred Constraints in Concrete Specs

When a concrete spec (`*.impl.md`) needs to track symbol-level blockers -- constraints the abstract spec wants to express but the implementation can't fulfill yet -- use `blocked-by` in the concrete spec frontmatter:

```markdown
---
source-spec: src/roots.rs.spec.md
target-language: Rust
ephemeral: false
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning -- needs cfg-gate"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    affects: "Scanning<RustVM> impl"
---
```

All four fields (`symbol`, `reason`, `resolution`, `affects`) are required. `blocked-by` is only meaningful on permanent concrete specs (`ephemeral: false`).

Unlike `depends-on` (file-level, passive), `blocked-by` is symbol-level and names a specific resolution action. It's a directed action item that can be removed once the upstream change happens.

## Per-Unit Specs

For tightly coupled files that form a logical unit (a Python module, a Rust crate), you can write a single spec that describes the entire unit.

Unit specs are named `<directory-name>.unit.spec.md` and placed inside the directory (e.g., `src/auth/auth.unit.spec.md`).

A unit spec MUST include a `## Files` section listing each output file and its responsibility:

```markdown
# auth module spec

## Files
- `__init__.py` — public API re-exports
- `tokens.py` — JWT token creation and verification
- `middleware.py` — request authentication middleware
- `errors.py` — authentication error types

## Behavior
...
```

Use unit specs when:
- Files share internal APIs and cannot be meaningfully described independently
- The unit has a clear public interface and internal implementation details
- Per-file specs would repeat the same cross-file contracts in every file

Use per-file specs when:
- Files are loosely coupled and can be described independently
- The unit has more than ~10 files (context limits)
- Different files have different dependency chains

## Pseudocode Discipline

Pseudocode appears in Concrete Specs (`*.impl.md`) inside ` ```pseudocode ` fenced blocks. It is the Middle-End IR — a human-readable blueprint for logic that bridges high-level intent and machine execution. These constraints ensure pseudocode remains a high-fidelity lowering target that the Builder can reliably "compile."

### Definition

- **What it IS**: A structured, language-agnostic representation of an algorithm's essential logic. It describes *how the math or logic works*, not how a language's library handles it.
- **What it IS NOT**: Compilable code. It must avoid language-specific syntax (semicolons, curly braces, strict imports, type annotations with language-specific notation).

### Structural Rules

These rules ensure unambiguous parsing by both humans and the Builder:

1. **One statement per line.** Each line represents a single logical action. Multi-statement lines obscure control flow.

2. **Capitalized keywords for flow control.** Use a consistent set:
   - Control flow: `IF`, `ELSE IF`, `ELSE`, `WHILE`, `FOR`, `REPEAT UNTIL`
   - Operations: `SET`, `RETURN`, `RAISE`, `CALL`, `EMIT`
   - Exception handling: `TRY`, `CATCH`
   - Scope: `FUNCTION ... END FUNCTION`, `BEGIN ... END` for non-function blocks

3. **Indentation-based hierarchy.** Mandatory indentation (2 or 4 spaces, consistent within a block) to show scope and nesting. No braces, no `end` keywords for control flow (scope is implicit from indentation, like Python but without the colon).

4. **Operator discipline is context-sensitive.** The linter enforces different rules depending on the statement type:
   - **Assignment contexts** (`SET`, `FOR`, `INCREMENT`, `DECREMENT`): MUST use `←` (or `:=` as fallback). Never bare `=`. These statements initialize or mutate state — `FOR i ← 0 TO 9`, not `FOR i = 0 TO 9`.
   - **Comparison contexts** (`IF`, `ELSE IF`, `WHILE`, `UNTIL`, `WHEN`, `ASSERT`): bare `=` is allowed as equality comparison. `UNTIL status = DONE` is correct — it's a boolean test, not an assignment.
   - **All other lines**: bare `=` is flagged as a violation (use `SET ... ←` to make intent explicit).

5. **Descriptive names, not abbreviations.** `delay`, `attempts`, `upper_bound` — not `d`, `a`, `ub`. Named constants for magic numbers: `MAX_RETRY_ATTEMPTS` not `5`.

### Level of Abstraction (The Goldilocks Rule)

Pseudocode must be detailed enough to be unambiguous but abstract enough to stay portable:

**Elide:**
- Boilerplate: memory allocation, imports, variable declarations (unless safety-critical)
- Type annotations (these belong in `## Type Sketch`)
- Library initialization and teardown

**Include:**
- Every conditional branch, especially error paths and edge cases
- The exact mathematical formula for computed values (e.g., `delay ← random_uniform(0, upper_bound)`)
- Loop bounds and termination conditions
- Named constants with their semantic meaning
- Complexity annotations where relevant: `// O(n log n)`, `// amortized O(1)`

### Implementation Invariance

The pseudocode must remain implementation-independent:

- **No library calls.** Instead of `auth_lib.verify(token)`, write `VERIFY token_signature AGAINST public_key`. Instead of `random.uniform(0, n)`, write `random_uniform(0, n)` — a mathematical operation, not a library invocation.
- **No language-specific syntax.** No `def`, `func`, `fn`, `let`, `var`, `const`, `:=` (Go-style), `->` (Rust/Haskell), `lambda`, `=>`. Use the capitalized keywords above.
- **Mathematical notation over prose** where it is more precise: `delay ← MIN(base × 2^attempt, cap)` is clearer than "set the delay to the smaller of the exponential value and the cap."
- **Generic data operations.** Use `APPEND item TO collection`, `REMOVE item FROM collection`, `LOOKUP key IN map` — not language-specific method syntax.

### Concrete Spec Example (Compliant)

````pseudocode
FUNCTION retry(operation, config)
    SET last_error ← null

    FOR attempt ← 0 TO config.max_retries - 1
        TRY
            SET result ← CALL operation()
            RETURN result
        CATCH error
            SET last_error ← error

            IF attempt < config.max_retries - 1
                SET upper_bound ← MIN(config.base_delay × 2^attempt, config.max_delay)
                SET delay ← random_uniform(0, upper_bound)    // Full Jitter
                WAIT delay

    RAISE MaxRetriesExceeded(config.max_retries, last_error)
END FUNCTION
````

### Common Violations

| Violation | Example | Fix |
|---|---|---|
| Language-specific keyword | `def retry(...)` | `FUNCTION retry(...)` |
| Library call | `time.sleep(delay)` | `WAIT delay` |
| Bare assignment | `delay = x` | `SET delay ← x` |
| FOR with bare `=` | `FOR i = 0 TO 9` | `FOR i ← 0 TO 9` |
| Abbreviated names | `d`, `cfg`, `e` | `delay`, `config`, `error` |
| Missing edge case | No error branch | Add `CATCH` / `IF error` |
| Magic number | `if attempts > 5` | `IF attempts > MAX_RETRY_ATTEMPTS` |
| Multi-statement line | `x = 1; y = 2` | Two separate lines |

## Skeleton Template

Use this when creating a spec for a file that has no existing spec. Fill in what is known; leave sections as stubs rather than omitting them.

```markdown
# [filename] spec

## Purpose
[What this file does and why it exists]

## Behavior
[What it should do — the observable contract]

## Constraints
[Bounds, limits, invariants, error conditions]

## Dependencies
[External services, libraries, or other managed files it relies on]

## Error Handling
[How errors are surfaced, what fails visibly vs silently, recovery behavior]

## Open Questions
[Decisions intentionally deferred — remove this section if none]
```
