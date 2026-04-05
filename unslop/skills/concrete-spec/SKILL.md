---
name: concrete-spec
description: Use when generating, reviewing, or promoting concrete specs — the implementation strategy layer between abstract specs (intent) and generated code. Activates during Stage B.1 of generation, during /unslop:harden --promote, and during takeover raising.
version: 0.20.0
---

# Concrete Spec Skill

## What a Concrete Spec Is

Unslop's spec-driven pipeline mirrors a compiler's multi-stage lowering:

| Compiler Layer | Unslop Layer | Artifact | Owns |
|---|---|---|---|
| Source Language | User Intent | Change request / conversation | The "Why" |
| High-Level IR | Abstract Spec (`*.spec.md`) | Intent-focused constraints | The "What" |
| **Mid-Level IR** | **Concrete Spec (`*.impl.md`)** | **Implementation strategy** | **The "How" (algorithm/pattern level)** |
| Low-Level IR / Target | Generated Code | Language-specific source | The "With What" |

The Abstract Spec describes **observable behavior** -- what the code must do. The Concrete Spec describes **what the Builder would get wrong** without guidance -- the non-obvious implementation decisions where a wrong choice is silent (memory layout, unsafe preconditions, type migrations, competing definitions) rather than loud (wrong return value, missing error case).

**The concrete spec is a correction layer, not a complete implementation strategy.** The Builder already knows how to implement standard algorithms (retry loops, CRUD operations, request routing). Pseudocode for these adds noise. The concrete spec's value is in the parts where getting it wrong is silent: memory layout that causes corruption under load, unsafe operations with implicit preconditions, type changes from takeover that the Builder might regress, concurrency orderings where "stronger to be safe" introduces contention.

Focus the concrete spec on what's surprising about this implementation. If the Builder would produce correct code from the abstract spec alone, the concrete spec can be minimal or omitted (ephemeral).

---

## File Naming

- Per-file: `<file>.impl.md` (e.g., `src/retry.py.impl.md`)
- Per-unit: `<dir>.unit.impl.md` (e.g., `src/auth/auth.unit.impl.md`)

---

## Frontmatter Schema

```yaml
---
source-spec: src/retry.py.spec.md
target-language: python
ephemeral: true
complexity: standard
extends: shared/fastapi-async.impl.md
concrete-dependencies:
  - src/core/connection_pool.py.impl.md
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning -- needs cfg-gate"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    affects: "Scanning<RustVM> impl"
protected-regions:
  - marker: "compile-time test conditional"
    position: tail
    semantics: test-suite
    starts-at: "line 847"
---
```

For **multi-target lowering** (one spec to multiple languages), use `targets` instead of `target-language`:

```yaml
---
source-spec: src/auth/auth_logic.spec.md
ephemeral: false
complexity: high
targets:
  - path: src/api/auth.py
    language: python
    notes: "Use FastAPI HTTPException with structured detail"
  - path: frontend/src/api/auth.ts
    language: typescript
    notes: "Use Axios interceptors for error code mapping"
---
```

| Field | Required | Description |
|---|---|---|
| `source-spec` | yes | Cwd-relative path to the abstract spec this concretizes |
| `target-language` | yes* | Target language/platform for lowering. *Mutually exclusive with `targets` |
| `targets` | no* | List of target files for multi-target lowering. *Mutually exclusive with `target-language` |
| `targets[].path` | yes | Cwd-relative path to the managed file this target produces |
| `targets[].language` | yes | Language for this target (e.g., `python`, `typescript`, `go`) |
| `targets[].notes` | no | Target-specific lowering hints (supplements `## Lowering Notes`) |
| `ephemeral` | no | Default `true`. Set `false` when promoted via `/unslop:promote` or when complexity meets the project's `promote-threshold` |
| `complexity` | no | `low`, `medium`, or `high`. Compared against the project's `promote-threshold` for auto-promotion |
| `extends` | no | Cwd-relative path to a base `*.impl.md` whose sections are inherited. Child sections override parent sections. See Strategy Inheritance |
| `concrete-dependencies` | no | Cwd-relative paths to upstream `*.impl.md` files whose strategy choices affect this spec's lowering. Changes in upstream concrete specs trigger ghost staleness |
| `blocked-by` | no | List of deferred constraints -- symbol-level blockers the spec wants to express but can't fulfill yet. Each entry requires `symbol`, `reason`, `resolution`, `affects`. Only meaningful on permanent specs (`ephemeral: false`) |
| `protected-regions` | no | List of contiguous tail blocks the Builder preserves verbatim. Each entry requires `marker`, `position` (always `tail`), `semantics` (`test-suite`, `entry-point`, `examples`, `benchmarks`), `starts-at` (1-indexed line reference). No mid-file regions -- split the file first |

**Path convention:** every path-valued frontmatter field (`source-spec`, `concrete-dependencies`, `extends`, `targets[].path`) is **cwd-relative**: paths are interpreted relative to the project root regardless of where the `.impl.md` file itself lives. An impl at `src/nested/foo.impl.md` that concretizes `src/nested/foo.spec.md` writes `source-spec: src/nested/foo.spec.md` -- the full cwd-relative path, not just `foo.spec.md`. This matches `depends-on` in abstract specs and keeps cross-file refactoring simple (grep the repo for the path).

**Ephemeral restriction:** `blocked-by` is only meaningful on permanent concrete specs. If present on an ephemeral spec, entries are parsed but ignored by the freshness checker and coherence command. Promote to permanent first via `/unslop:promote`.

---

## Section Conventions

### `## Strategy` (required)

The core of the concrete spec. Describes the algorithm, data flow, and structural pattern. This is the "how" at the algorithmic level, not the abstract spec's "what."

Pseudocode is optional. Use pseudocode blocks for non-standard algorithms where the logic is genuinely complex. For standard patterns (retry with backoff, CRUD operations, request routing), a brief prose description or a reference to the Pattern section is sufficient. See the **Pseudocode Convention** section below for the full specification and examples.

For files with structural constraints (memory layout, unsafe operations, concurrency), the Strategy section can be minimal -- the architectural invariant sections carry the load-bearing information.

### `## Pattern`

Name the design pattern or architectural approach. This is the "Rosetta Stone" -- the part that stays the same when switching languages.

```markdown
## Pattern

- **Retry strategy**: Exponential backoff with jitter (decorrelated)
- **Concurrency model**: Single-threaded async with cooperative yielding
- **Error propagation**: Typed error wrapping with cause chain
- **State management**: Immutable config, mutable attempt counter (loop-scoped)
```

### `## Type Sketch`

Structural type signatures without language-specific syntax. Use generic type notation:

```markdown
## Type Sketch

RetryConfig {
    max_retries: int (> 0)
    base_delay: duration (> 0)
    max_delay: duration (>= base_delay)
    jitter_factor: float (0.0..1.0)
    retryable_errors: set<error_type>
}

RetryResult<T> = Success(value: T) | Failure(error: error, attempts: int)
```

### `## Lowering Notes` (optional)

Language-specific considerations that the Builder should know. This is the only section that is NOT portable across languages.

```markdown
## Lowering Notes

### Python
- Use `asyncio.sleep()` for delay in async context
- `RetryConfig` as a frozen dataclass
- Jitter via `random.uniform()`

### Go
- Use `time.Sleep()` for delay
- `RetryConfig` as a struct with exported fields
- Jitter via `math/rand`
```

### Optional Sections: Architectural Invariants

These sections document **non-observable constraints** -- things that are load-bearing but invisible to tests. A wrong return value fails a test; a wrong memory layout causes silent corruption under load. Include these sections when the file has structural constraints the Builder must respect but the abstract spec cannot express.

**When to include:** If the file involves memory layout, unsafe operations, concurrency primitives, or protocol state machines. If the file is pure business logic with no structural constraints, skip these -- the Strategy and Type Sketch are sufficient.

#### `## Representation Invariants` (optional)

Memory layout, alignment, field offsets, and size constraints. Essential for FFI, cache-line optimization, and any code where the physical structure matters. Use fields: `LAYOUT`, `ALIGN`, `SIZE`, `FIELD_OFFSET <n>`.

#### `## Safety Contracts` (optional)

Preconditions, postconditions, and violation consequences for unsafe operations. Use fields per operation: `REQUIRES`, `ENSURES`, `VIOLATED_BY`.

#### `## Concurrency Model` (optional)

Atomic operations with memory orderings and rationale. Locks with their contention model. The "why" matters as much as the "what" -- a Builder that changes `Relaxed` to `SeqCst` "to be safe" may introduce unnecessary contention. Use fields: `TYPE`, `ORDERING`, `RATIONALE`, `CONTENTION`.

#### `## State Machine` (optional)

Formal state transitions for protocol implementations. Use: `STATES`, `TRANSITIONS` (with `[ON: event]` triggers), `INVALID` (forbidden transitions), `INITIAL`, `TERMINAL`.

#### `## Migration Notes` (optional)

Intentional type changes, API shifts, or signature corrections the Builder must apply when regenerating from a spec that describes the new contract while the old code used a different one. Use `CHANGED`, `REMOVED` entries with `FROM`, `TO`, `REASON`.

**When to include:** During takeover when the Architect corrects types or signatures. During `/unslop:change` when a spec change intentionally alters a public interface. Not for internal refactoring that doesn't change types or signatures.

#### `## Error Taxonomy` (optional)

Error classification hierarchy. Prevents over-handling (catching everything, swallowing errors) or under-handling. Fields per error: `CATEGORY` (recoverable/fatal/propagated), `HANDLE` (what the Builder MUST do), `NEVER` (what the Builder MUST NOT do).

#### `## Test Seams` (optional)

Testability boundaries and injectable dependencies. Use `INJECTABLE` entries (with `INTERFACE`, `PRODUCTION`, `TEST`, `ISOLATION`) and `BOUNDARY` entries (with `OBSERVABLE_VIA`, `NOT_OBSERVABLE_VIA`).

---

## Pseudocode Convention

Pseudocode appears in Concrete Specs inside ` ```pseudocode ` fenced blocks. It is the Middle-End IR -- a human-readable blueprint for logic that bridges high-level intent and machine execution.

### Structural Rules

1. **One statement per line.** Each line represents a single logical action. Multi-statement lines obscure control flow.

2. **Capitalized keywords for flow control.** Use a consistent set:
   - Control flow: `IF`, `ELSE IF`, `ELSE`, `WHILE`, `FOR`, `REPEAT UNTIL`
   - Operations: `SET`, `RETURN`, `RAISE`, `CALL`, `EMIT`, `WAIT`
   - Exception handling: `TRY`, `CATCH`
   - Scope: `FUNCTION ... END FUNCTION`, `BEGIN ... END` for non-function blocks

3. **Indentation-based hierarchy.** Mandatory indentation (2 or 4 spaces, consistent within a block) to show scope and nesting. No braces, no `end` keywords for control flow.

4. **Operator discipline is context-sensitive:**
   - **Assignment contexts** (`SET`, `FOR`, `INCREMENT`, `DECREMENT`): MUST use `←` (or `:=` as fallback). Never bare `=`. Example: `FOR i ← 0 TO 9`, not `FOR i = 0 TO 9`.
   - **Comparison contexts** (`IF`, `ELSE IF`, `WHILE`, `UNTIL`, `WHEN`, `ASSERT`): bare `=` is allowed as equality comparison. `UNTIL status = DONE` is correct -- it's a boolean test, not an assignment.
   - **All other lines**: bare `=` is a violation (use `SET ... ←` to make intent explicit).

5. **Descriptive names, not abbreviations.** Use `delay`, `attempts`, `upper_bound` -- not `d`, `a`, `ub`. Named constants for magic numbers: `MAX_RETRY_ATTEMPTS` not `5`.

### Level of Abstraction (The Goldilocks Rule)

Pseudocode must be detailed enough to be unambiguous but abstract enough to stay portable.

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

- **No library calls.** Instead of `auth_lib.verify(token)`, write `VERIFY token_signature AGAINST public_key`. Instead of `random.uniform(0, n)`, write `random_uniform(0, n)` -- a mathematical operation, not a library invocation.
- **No language-specific syntax.** No `def`, `func`, `fn`, `let`, `var`, `const`, `:=` (Go-style), `->` (Rust/Haskell), `lambda`, `=>`. Use the capitalized keywords above.
- **Mathematical notation over prose** where it is more precise: `delay ← MIN(base × 2^attempt, cap)` is clearer than "set the delay to the smaller of the exponential value and the cap."
- **Generic data operations.** Use `APPEND item TO collection`, `REMOVE item FROM collection`, `LOOKUP key IN map` -- not language-specific method syntax.

### Compliant Example

```pseudocode
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
```

### Common Violations

| Violation | Example | Fix |
|---|---|---|
| Language-specific keyword | `def retry(...)` | `FUNCTION retry(...)` |
| Library call | `time.sleep(delay)` | `WAIT delay` |
| Bare assignment | `delay = x` | `SET delay ← x` |
| FOR with bare `=` | `FOR i = 0 TO 9` | `FOR i ← 0 TO 9` |
| Abbreviated names | `d`, `cfg`, `e` | `delay`, `config`, `error` |
| Missing edge case | No error branch | Add `CATCH` / `IF error` |
| Magic number | `IF attempts > 5` | `IF attempts > MAX_RETRY_ATTEMPTS` |
| Multi-statement line | `x ← 1; y ← 2` | Two separate lines |

**Validation:** prunejuice's pseudocode validator (`src/validators.ts`) enforces these rules during Phase 0a.1 pre-generation validation. Use `--force-pseudocode` to bypass linter false positives when language-flavored notation is unavoidable.

---

## Strategy Inheritance

Concrete specs can **extend** a base concrete spec to inherit shared sections. This eliminates duplication of `## Lowering Notes` and `## Pattern` across modules that share the same architectural approach.

```yaml
---
source-spec: src/api/users.py.spec.md
target-language: python
extends: shared/fastapi-async.impl.md
---
```

The `extends` field points to a base concrete spec -- a `.impl.md` file that defines shared patterns and lowering conventions. A child's `## Strategy` and `## Type Sketch` are always its own -- silent fallback to the parent's algorithm is a bug, not a feature.

### Section-Specific Inheritance Policies

| Policy | Sections | Behavior |
|---|---|---|
| **Strict Child-Only** | `## Strategy`, `## Type Sketch`, `## Representation Invariants`, `## Safety Contracts`, `## Concurrency Model`, `## State Machine`, `## Migration Notes` | Parent section is purged during resolution. If the child omits it, the resolved spec has no such section. For Strategy and Type Sketch, absence triggers Phase 0a.1 validation failure. For architectural invariant and migration sections, absence is valid. |
| **Additive** | `## Lowering Notes` | Parent and child are merged. Child entries override matching parent entries (keyed by language heading). Non-conflicting parent entries are preserved. |
| **Overridable** | `## Pattern` | Child replaces parent if present. If the child omits `## Pattern`, the parent's version persists. |

### Resolution Algorithm

```pseudocode
FUNCTION resolve_inherited_sections(parent_sections, child_sections)
    SET STRICT_CHILD_ONLY ← {"Strategy", "Type Sketch"}

    // 1. Start with parent sections
    SET resolved ← COPY(parent_sections)

    // 2. Purge strict child-only sections from the parent copy
    FOR EACH section IN STRICT_CHILD_ONLY
        REMOVE section FROM resolved

    // 3. Apply child overrides/additions
    FOR EACH (title, content) IN child_sections
        IF title = "Lowering Notes" AND title EXISTS IN parent_sections
            SET resolved[title] ← parent_sections[title] + "\n" + content
        ELSE
            SET resolved[title] ← content

    RETURN resolved
END FUNCTION
```

**Key invariant:** After resolution, `## Strategy` and `## Type Sketch` can only contain content the child explicitly defined. If the child omitted them, they are absent -- and the existing Phase 0a.1 linter catches the missing mandatory `## Strategy` section.

### The "Forgetful Child" Failure Mode

The strict policy prevents this scenario:

1. **Parent** (`base_api.impl.md`) defines a generic fetch strategy
2. **Child** (`user_api.impl.md`) extends `base_api` but omits its own `## Strategy`
3. **Resolution:** `resolve_inherited_sections()` purges the parent's generic fetch. The resolved spec has no `## Strategy`
4. **Validation:** Phase 0a.1 aborts with: `FATAL: user_api.impl.md is missing mandatory ## Strategy section`

Without the strict policy, the child would silently inherit the parent's generic fetch algorithm -- producing code that "works" but doesn't match the child module's actual requirements.

### Base Spec Rules

Base concrete specs (`shared/*.impl.md`) have special properties:

- They **do not require `source-spec`** -- they are not tied to a specific abstract spec
- They **do not generate code** -- they exist only to be inherited
- They are **always permanent** (`ephemeral: false` implied)
- They **appear in `/unslop:status`** under a `Base strategies:` section
- Changes to a base spec make all children **ghost-stale** (tracked via `extends` as an implicit concrete dependency)

### Inheritance Chains

Concrete specs can form multi-level chains: child extends parent extends grandparent. Resolution applies bottom-up at each level. The strict child-only policy applies at every level -- a grandparent's `## Strategy` can never leak through to a grandchild, even transitively.

**Cycle detection:** A cycle in `extends` (A extends B extends A) raises `CIRCULAR_DEPENDENCY_ERROR` during Phase 0a.1.

**Maximum depth: 3 levels** (grandparent -> parent -> child). Deeper chains indicate over-abstraction. Flatten the hierarchy if more depth seems necessary.

---

## Ghost Staleness

### What It Means

A managed file is **ghost-stale** when:
- Its abstract spec hash matches (spec hasn't changed)
- Its output hash matches (code hasn't been manually edited)
- But an upstream `concrete-dependency` has changed its strategy

Ghost staleness is invisible to the standard staleness check (which only tracks abstract spec hashes). prunejuice walks upstream to detect it via `computeConcreteManifest` in `src/manifest.ts`.

### Why It's Called Ghost

The file looks fresh from every normal angle -- the spec is unchanged, the code is unchanged. But the implementation strategy it was generated from is now wrong. The file is haunted by an outdated strategy that isn't visible in any single diff.

### Detection

The managed file's `@unslop-managed` header stores a `concrete-manifest` -- a per-dependency hash map written at generation time:

```
# concrete-manifest:src/core/pool.py.impl.md:a3f8c2e9b7d1,shared/base.impl.md:7f2e1b8a9c04
```

During freshness classification, prunejuice compares each entry's stored hash against the current hash of that dependency file. This enables surgical diagnosis -- if `pool.py.impl.md` changed but `base.impl.md` didn't, only `pool.py.impl.md` is reported.

**Deep-chain tracing:** When a direct dependency has changed, prunejuice walks upstream to find the root cause. If `service.impl.md` changed because its own upstream `utils.impl.md` changed, the diagnostic reports:

> `upstream service.impl.md changed (via utils.impl.md)`

This prevents the user from being directed to check a file that appears untouched -- the chain trace points to the actual root cause.

### When Ghost Staleness Triggers

Declare `concrete-dependencies` when:
- This spec's `## Strategy` assumes a specific concurrency model from an upstream module (sync vs async)
- This spec's `## Type Sketch` references internal types defined in an upstream concrete spec
- This spec's `## Lowering Notes` depend on library choices made in an upstream concrete spec

Do NOT declare concrete dependencies for:
- Contract-level dependencies (those belong in the abstract spec's `depends-on`)
- Ephemeral concrete specs (they don't persist to be tracked)
- Dependencies where only the abstract contract matters (algorithm choice is irrelevant)

**Example:** A service handler's concrete spec depends on the connection pool's concrete spec because the handler's strategy must match the pool's concurrency model. If `connection_pool.py.impl.md` changes from synchronous to async, `handler.py.impl.md` becomes ghost-stale.

### In `/unslop:status`

Ghost-stale files appear as a distinct state with the root cause chain:

> `src/api/handler.py` -- **ghost-stale** (upstream `src/core/pool.py.impl.md` changed (via `src/db/connection.py.impl.md`))

### Resolution

Re-run generation. The Archaeologist re-derives the concrete spec from updated upstream strategies, and the Builder generates fresh code.

---

## Multi-Target Configuration

A single Abstract Spec can describe a contract that must be implemented in multiple languages simultaneously. The `targets` field enables this.

### The Coordination Problem

When `user_login.spec.md` says "return error code AUTH_EXPIRED on token expiry":
- The Python backend must `raise HTTPException(status_code=401, detail={"code": "AUTH_EXPIRED"})`
- The TypeScript frontend must `if (error.response.data.code === "AUTH_EXPIRED") { redirect("/login") }`

If these drift, the app breaks -- even if both files independently "pass" their spec-to-code tests. Multi-target lowering solves this by ensuring both implementations derive from the **same Strategy and Type Sketch**, differing only in `## Lowering Notes`.

### Schema

See the `targets` field in the Frontmatter Schema section for the full YAML. The `## Lowering Notes` section uses per-language headings:

```markdown
## Lowering Notes

### Python
- `raise HTTPException(status_code=401, detail={"code": "AUTH_EXPIRED"})`

### TypeScript
- Error codes as `const enum AuthErrorCode { ... }` for tree-shaking
```

### Staleness

When a multi-target concrete spec changes, **all** targets are marked stale simultaneously. `/unslop:status` shows them grouped under the concrete spec.

### When NOT to Use Multi-Target

Multi-target lowering is for **shared contracts** -- the same business logic implemented across language boundaries. Do NOT use it for:

- Unrelated files that happen to share a spec (use per-file specs instead)
- Frontend and backend communicating via a well-defined API (the API schema is the contract -- use separate specs)
- Different implementations of the same algorithm in the same language (use unit specs)

The right test: "If I change an error code in the abstract spec, must BOTH files update atomically?" If yes -- multi-target. If no -- separate specs.

---

## Ephemeral vs Permanent

### The Default: Ephemeral

The concrete spec is the Builder's **internal monologue** -- it exists to improve generation quality, not to create maintenance burden. By default, `ephemeral: true`.

Generation flow:
1. Builder reads the Abstract Spec
2. Builder drafts a Concrete Spec as an in-worktree artifact (Stage B.1)
3. Builder generates code from both the Abstract Spec (constraints) and Concrete Spec (strategy)
4. If tests pass and `ephemeral: true`: the concrete spec is discarded with the worktree -- it served its purpose
5. If tests pass and `ephemeral: false`: the concrete spec is merged with the generated code

### Complexity Scoring

| Score | Criteria | Examples |
|---|---|---|
| `low` | Single algorithm, linear control flow, few types | CRUD endpoint, config loader, simple validation |
| `medium` | Multiple interacting algorithms, branching control flow, moderate type structure | Pagination with cursor management, rate limiter, connection pool |
| `high` | Complex state machines, concurrent logic, intricate type hierarchies, non-obvious invariants | Jitter backoff, auth handshake, distributed lock, event sourcing |

Complexity is assessed by the Archaeologist, not declared by the author.

### Auto-Promotion Threshold

The project-level threshold in `.unslop/config.json` determines which complexity levels trigger auto-promotion:

```json
{
  "promote-threshold": "high"
}
```

| `promote-threshold` | `low` complexity | `medium` complexity | `high` complexity |
|---|---|---|---|
| `"high"` (default) | ephemeral | ephemeral | **auto-promoted** |
| `"medium"` | ephemeral | **auto-promoted** | **auto-promoted** |
| `"low"` | **auto-promoted** | **auto-promoted** | **auto-promoted** |

### Promotion Cases

A concrete spec is promoted from ephemeral to permanent when:

1. **Manual promotion**: User runs `/unslop:promote <spec-path>` (or `/unslop:harden --promote <spec-path>`)
2. **Auto-promotion**: Assessed complexity meets or exceeds the project's `promote-threshold`
3. **Cross-language projects**: When `target-language` differs across generations of the same abstract spec, concrete specs are retained to preserve language-specific lowering notes
4. **Builder-proposed upgrade**: If the Builder discovers during Stage B that the implementation is harder than assessed, it may propose a complexity upgrade in its DONE_WITH_CONCERNS report

### Permanent Concrete Spec Rules

When `ephemeral: false`:

- It lives alongside the abstract spec: `src/retry.py.spec.md` + `src/retry.py.impl.md`
- It is version-controlled and code-reviewed
- Changes to the abstract spec trigger a staleness check on the concrete spec
- The Builder reads it as additional input during generation (but the abstract spec wins on any conflict)
- It does NOT replace the abstract spec -- both are maintained
