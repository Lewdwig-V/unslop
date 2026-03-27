# Concrete Spec Enhancements v2: Deferred Constraints, Error Taxonomy, Test Seams

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this spec.

**Goal:** Extend the concrete spec layer with `blocked-by` frontmatter for deferred constraints and two new architectural invariant sections (Error Taxonomy, Test Seams) that correct specific Builder failure modes.

**Motivation:** Field-tested during a real Rust GC takeover. The roots.rs blackwall migration revealed that the abstract spec can express intent ("use compat types for blackwall compliance") but the implementation layer can't fulfill it yet because an upstream type alias (`VMScanning = RustScanning`) hasn't been cfg-gated. Without structured tracking, the Builder either silently violates the spec or fails trying to fulfill an unfulfillable constraint. Separately, Builder error handling and testability mistakes recur across files -- the same failure modes that the existing architectural invariant sections (Safety Contracts, Concurrency Model, etc.) were designed to prevent.

---

## 1. `blocked-by` Frontmatter

### 1.1 What it is

A structured list in concrete spec frontmatter that declares **deferred constraints** -- things the abstract spec wants but the implementation layer can't fulfill yet because of an upstream dependency that hasn't changed.

### 1.2 How it differs from `depends-on` and `concrete-dependencies`

| Property | `depends-on` | `concrete-dependencies` | `blocked-by` |
|---|---|---|---|
| Lives in | Abstract spec | Concrete spec | Concrete spec |
| Granularity | File-level | File-level | Symbol-level |
| Semantics | "I use things from here" | "My strategy depends on their strategy" | "I can't do X until Y changes in Z" |
| Effect on generation | Determines build order | Determines ghost-staleness | Deviation permit (informational) |
| Resolution | Passive (always present) | Passive (always present) | Directed action item (removable) |

### 1.3 Ephemeral spec restriction

`blocked-by` is only meaningful on permanent concrete specs (`ephemeral: false`). The tracking value requires persistence across generation cycles -- an ephemeral spec is discarded after each generation, so blocked entries would never be seen by status or coherence.

If the parser encounters `blocked-by` on an ephemeral concrete spec, it emits a stderr warning: `"Warning: blocked-by on ephemeral concrete spec has no effect -- promote to permanent first"`. The entries are still parsed (so promotion doesn't lose data) but the freshness checker ignores them.

### 1.4 Schema

```yaml
---
source-spec: src/roots.rs.spec.md
target-language: Rust
ephemeral: false
blocked-by:
  - symbol: "binding::vm_impl::RustVM::VMScanning"
    reason: "unconditionally aliases RustScanning -- needs cfg-gate for blackwall"
    resolution: "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    affects: "Scanning<RustVM> impl"
  - symbol: "another::module::Symbol"
    reason: "reason this blocks"
    resolution: "what needs to change upstream"
    affects: "which part of this file is constrained"
---
```

**Fields (all required):**

- **`symbol`** -- the upstream symbol that blocks. Fully qualified path using the language's native convention (e.g., `crate::module::Type` for Rust, `package.module.Class` for Python).
- **`reason`** -- why this blocks. Human-readable, one line.
- **`resolution`** -- what needs to change upstream to unblock. A pointer, not an implementation. Describes the action needed in the upstream file, not how to do it.
- **`affects`** -- which part of *this* file's spec is constrained. Scopes the deviation so the Builder knows what's blocked and what isn't. The rest of the spec is implementable normally.

All four fields are required. A `blocked-by` entry without a resolution is just a comment -- the structured tracking is the whole point.

### 1.5 Pipeline integration

#### 1.5.1 Status display (`/unslop:status`)

Blocked constraints appear as informational annotations on the file entry. They do NOT change the file's staleness state -- a file with blockers can still be `fresh`.

```
Managed files:
  fresh      src/roots.rs             <- src/roots.rs.spec.md
             ⊘ 1 blocked constraint: Scanning<RustVM> impl
               waiting on binding::vm_impl::RustVM::VMScanning
  fresh      src/handshake.rs         <- src/handshake.rs.spec.md
```

The `⊘` indicator is a new annotation type parallel to `Δ` (pending changes). It appears regardless of staleness state. A file can show both `⊘` and `Δ` simultaneously.

#### 1.5.2 Generation (`generation/SKILL.md`)

The Builder reads `blocked-by` entries from the concrete spec and treats them as **explicit deviation permits**:

- The `affects` field tells the Builder which part of the abstract spec can't be fulfilled yet
- The `reason` field explains why
- The Builder proceeds with the unblocked parts normally
- For the blocked scope, the Builder handles pragmatically (e.g., keeping existing imports, using compatibility shims, preserving legacy code paths)
- The Builder MUST NOT silently deviate on *unblocked* constraints -- `blocked-by` is a scalpel, not a blanket
- The Builder SHOULD add a code comment at the deviation site referencing the blocker

#### 1.5.3 Coherence (`/unslop:coherence`)

**Lookup boundary:** The coherence command discovers concrete spec pairs as a byproduct of abstract spec `depends-on` relationships (Step 5a in coherence.md: "For each spec pair checked in Step 3, look for corresponding permanent concrete specs"). `blocked-by` annotations are surfaced only within these derived pairs -- coherence does NOT scan all `.impl.md` files in the project looking for symbol matches, and does NOT use `concrete-dependencies` or `extends` edges for pair discovery. If spec A has a `blocked-by` entry whose symbol lives in a file with no abstract-level `depends-on` edge, the blocker is invisible to coherence (it still appears in `/unslop:status`). This is intentional -- coherence operates on declared dependency relationships, not on the entire symbol space. No changes to coherence's pairing logic are required.

**Within a checked pair:** If spec A has a `blocked-by` entry and spec B is in the same coherence pair:

- Flag it with `⊘` (known blocker), not `✗` (incoherence)
- Do not count it toward the incoherence total

```
Concrete spec coherence:
  src/roots.rs.impl.md <-> binding/vm_impl.rs.impl.md
    ⊘ blocked constraint: Scanning<RustVM> impl (known -- tracked in blocked-by)
```

**Resolution hint:** The `⊘` annotation always appears when a `blocked-by` entry exists in a checked pair. No change detection is needed -- the annotation is unconditional. The user decides when to verify resolution and remove the entry. If the upstream concrete spec in the pair is ghost-stale (already detected by existing ghost-staleness logic), coherence appends an advisory:

```
    ⊘ blocked constraint: Scanning<RustVM> impl (known -- tracked in blocked-by)
      ℹ upstream binding/vm_impl.rs.impl.md is ghost-stale -- blocker may be resolved
```

#### 1.5.4 Resolution detection

**Phase 1 (manual -- this design):** The user sees the blocker in status/coherence, verifies the upstream change happened, removes the `blocked-by` entry from the concrete spec, and resyncs. No automation needed.

**Phase 2 (LSP-assisted -- future, not in scope):** When LSP symbol queries land, `/unslop:coherence` could use `workspaceSymbol` to check whether the blocking symbol still exists in its original form. This is explicitly deferred.

### 1.6 What `blocked-by` is NOT

- **Not a hard gate.** If it prevents generation, it's just a more granular `depends-on`. The value is in documenting known deviations, not in blocking work.
- **Not for every type dependency.** Most type relationships are derivable from the code (`cargo check`, `tsc`, etc. catch them). `blocked-by` is only for constraints the spec wants to express but can't yet fulfill -- the exception, not the rule.
- **Not an implementation plan.** The `resolution` field describes what needs to change elsewhere. It's a pointer, not an implementation. The actual change happens when the upstream file is taken over.

### 1.7 The deeper pattern

`blocked-by` is the mechanism for **deferred constraints** -- specs that are intentionally aspirational. The abstract spec says what the design *should* be. The concrete spec says what the implementation *can* be right now. `blocked-by` bridges the gap: "this is the plan, here's why we're not there yet, and here's what unblocks it."

It's the spec equivalent of a `// TODO` comment, except it's structured, tracked, and resolvable.

---

## 2. `## Error Taxonomy` Section

### 2.1 Builder failure mode

The Builder over-handles errors (catches everything, swallows errors, adds unnecessary fallbacks) or under-handles them (lets panics propagate where recoverable errors are expected, ignores error variants). Without explicit guidance, the Builder defaults to "catch and log" which silently corrupts error propagation chains.

### 2.2 Format

```markdown
## Error Taxonomy

ERROR AllocationFailure:
  CATEGORY: recoverable
  HANDLE: return GcResult::Err, caller retries after GC cycle
  NEVER: panic, log-and-ignore, retry internally

ERROR CorruptedHeader:
  CATEGORY: fatal
  HANDLE: panic immediately with diagnostic
  NEVER: attempt recovery, return default header

ERROR MutatorNotRegistered:
  CATEGORY: propagated
  HANDLE: return Result::Err to caller, do not log at this layer
  NEVER: register a default mutator, silently succeed
```

**Fields per error:**

- **`CATEGORY`** -- one of: `recoverable` (caller can retry or fallback), `fatal` (invariant violation, crash immediately), `propagated` (pass to caller without handling at this layer)
- **`HANDLE`** -- what the Builder MUST do when this error occurs
- **`NEVER`** -- what the Builder MUST NOT do. Explicit anti-patterns prevent the most common Builder mistakes

### 2.3 When to include

When the file has multiple error paths and the abstract spec's error handling description is ambiguous enough that the Builder might choose wrong. Pure business logic with a single error type doesn't need this section.

### 2.4 Inheritance

`STRICT_CHILD_ONLY` -- error taxonomy is specific to each file's error surface. A parent concrete spec's error categories do not propagate to children.

---

## 3. `## Test Seams` Section

### 3.1 Builder failure mode

The Builder generates tightly-coupled code with hardcoded dependencies (no injection points), global state that leaks between tests, or tests that depend on execution order. Without explicit seam declarations, the Builder doesn't know which boundaries need to be injectable and which are fine as concrete dependencies.

### 3.2 Format

```markdown
## Test Seams

INJECTABLE allocator:
  INTERFACE: trait Allocator
  PRODUCTION: BumpAllocator
  TEST: MockAllocator (tracks allocation count, zero-cost)
  ISOLATION: per-test instance, no shared state

INJECTABLE time_source:
  INTERFACE: fn() -> Instant
  PRODUCTION: Instant::now
  TEST: deterministic clock (fixed or manually advanced)
  ISOLATION: thread-local, reset in test setup

BOUNDARY gc_trigger:
  OBSERVABLE_VIA: callback count on MockAllocator
  NOT_OBSERVABLE_VIA: internal GC state (opaque to tests)
```

**Entry types:**

- **`INJECTABLE`** -- a dependency that must have a test double
  - `INTERFACE` -- the abstraction boundary (trait, interface, function signature)
  - `PRODUCTION` -- the real implementation
  - `TEST` -- the test double and its key properties
  - `ISOLATION` -- how test instances are scoped (per-test, thread-local, process-wide)

- **`BOUNDARY`** -- a testability boundary that constrains how tests observe behavior
  - `OBSERVABLE_VIA` -- how tests verify this behavior
  - `NOT_OBSERVABLE_VIA` -- what tests must NOT depend on (internal state, timing, etc.)

### 3.3 When to include

When the file has external dependencies (I/O, time, allocators, registries, network) that must be injectable for testing, or when test isolation requires specific patterns the Builder wouldn't infer from the abstract spec alone. Pure functions with no external dependencies don't need this section.

### 3.4 Inheritance

`STRICT_CHILD_ONLY` -- test seam declarations are specific to each file's dependency surface. A parent's injectable boundaries don't propagate to children.

---

## 4. Implementation Surface

### 4.1 Files touched

| File | Change |
|---|---|
| `scripts/core/frontmatter.py` | Parse `blocked-by` in `parse_concrete_frontmatter`; update docstring return contract |
| `scripts/freshness/checker.py` | Surface `blocked_constraints` in file result dicts |
| `scripts/dependencies/concrete_graph.py` | Add `"Error Taxonomy"` and `"Test Seams"` to `STRICT_CHILD_ONLY` set |
| `commands/status.md` | Display `⊘` annotation for blocked constraints |
| `commands/coherence.md` | Known-blocker annotation, resolution hint |
| `skills/generation/SKILL.md` | Add deviation permit paragraph to Builder's concrete spec interpretation section |
| `skills/concrete-spec/SKILL.md` | Add `blocked-by` to frontmatter fields table; add Error Taxonomy and Test Seams to the architectural invariant sections alongside the existing five; add ephemeral restriction note |
| `skills/spec-language/SKILL.md` | Add `blocked-by` to the concrete spec frontmatter documentation in the "Dependencies Between Specs" section |
| `tests/test_frontmatter.py` (or equivalent) | Parser tests for `blocked-by` |
| `.claude-plugin/plugin.json` | Version bump to 0.24.0 |

### 4.2 Parser design

`blocked-by` parsing uses its own independent state variables, parallel to the existing `in_targets` / `current_target` pair. The two blocks do NOT share state -- they are structurally identical but completely separate code paths.

- **State variables:** `in_blocked_by: bool`, `current_blocker: dict | None` (parallel to `in_targets`, `current_target`)
- **Entry delimiter regex:** `r"^  - symbol:"` (matches `r"^  - path:"` for targets)
- **Sub-field regex:** `r"^    \w"` at 4-space indent, parsed as `key: value` pairs
- **Accepted sub-fields:** `reason`, `resolution`, `affects`
- **Flush:** on next `- symbol:` entry, after frontmatter end (post-loop), or when a non-matching line is encountered. A "non-matching line" is any line that is not `  - symbol:` and not `    \w` (4-space-indented sub-field). This includes top-level keys at zero indent (e.g., `concrete-dependencies:`) which terminate the `in_blocked_by` state. This matches the existing `in_targets` exit logic exactly.
- **Result:** `result["blocked_by"]` as `list[dict]` with keys `symbol`, `reason`, `resolution`, `affects`
- **Validation:** entries missing any of the four required fields emit a stderr warning and are skipped
- **Docstring:** update `parse_concrete_frontmatter`'s docstring to include `blocked_by` in the return contract (alongside the existing `source_spec`, `target_language`, etc.)

### 4.3 Freshness checker design

For each managed file with a permanent concrete spec containing `blocked_by` entries, the checker adds a `"blocked_constraints"` key to the file's result dict:

```python
"blocked_constraints": [
    {
        "symbol": "binding::vm_impl::RustVM::VMScanning",
        "affects": "Scanning<RustVM> impl",
        "reason": "unconditionally aliases RustScanning -- needs cfg-gate",
        "resolution": "cfg-gate VMScanning alias in binding/vm_impl.rs takeover"
    }
]
```

This is a read-through from the concrete spec -- all four fields are included so downstream consumers (status, coherence) don't need to re-parse the concrete spec. No hashing, no staleness logic. The status command reads this key and displays the `⊘` annotation.

### 4.4 Not in scope

- `blocked-by` in abstract spec frontmatter
- Automated resolution detection (LSP-assisted, deferred)
- Hard gating (blocked-by never prevents generation)
- Tracking every type dependency
- Resolution instructions in the blocked file

### 4.5 Version

Plugin version: 0.23.0 -> 0.24.0
