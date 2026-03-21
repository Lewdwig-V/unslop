---
name: spec-language
description: Use when writing, drafting, reviewing, or editing unslop spec files (*.spec.md). Activates for spec creation, takeover spec drafting, and spec editing guidance.
version: 0.1.0
---

# Spec-Language Skill

## Core Principle

Specs describe **intent**, not implementation. A spec defines what a file must do, what constraints it must satisfy, and what behavior it must exhibit — not how to achieve any of those things. Code is disposable; specs are the source of truth.

## Vocabulary Guide

Specs are written in terms of observable behavior, contracts, and constraints. They are not written in terms of data structures, algorithms, or control flow.

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

## Suggested Headings

These are not required, but they cover the ground most specs need:

- **Purpose** — What this file does and why it exists
- **Behavior** — The observable contract: inputs, outputs, side effects
- **Constraints** — Bounds, limits, invariants, error conditions
- **Dependencies** — External services, libraries, or other managed files it relies on
- **Error Handling** — Failure modes and how they are surfaced

Use all of them, some of them, or none — structure the spec to match the complexity of the file it describes. A 20-line utility doesn't need five headings.

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
```
