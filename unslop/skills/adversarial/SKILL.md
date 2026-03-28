---
name: adversarial
description: "Adversarial Quality framework — three-agent pipeline (Archaeologist → Mason → Saboteur) for mutation-gated test generation"
version: "0.14.0"
---

# Adversarial Quality Skill

This skill implements the **Adversarial Quality** pipeline: a three-agent architecture
that structurally prevents implementation-coupled tests through information asymmetry,
mock budgets, and mutation-gated validation.

## Architecture

The pipeline has three independent agents with a **Chinese Wall** between them:

```
┌──────────────┐     behaviour.yaml     ┌──────────┐     test_*.py     ┌───────────┐
│ Archaeologist │ ─────────────────────► │  Mason   │ ───────────────► │ Saboteur  │
│ (Phase 1)     │                        │ (Phase 2) │                  │ (Phase 3)  │
│               │                        │           │                  │            │
│ Reads: source │                        │ Reads:    │                  │ Reads: src │
│ Writes: spec  │                        │  spec ONLY│                  │ + tests    │
│               │                        │ No source │                  │ Mutates    │
│               │                        │ access!   │                  │ code       │
└──────────────┘                        └──────────┘                  └────────────┘
                                                                           │
                                                                    ┌──────┴──────┐
                                                                    │ Archaeologist│
                                                                    │ (classify + │
                                                                    │  constrain) │
                                                                    └─────────────┘
```

### Model Selection

Before dispatching any adversarial agent, read `.unslop/config.json`. If a `models` block exists and contains a key matching the agent role, pass that value as the `model` parameter when dispatching via `Agent()`. If the key is absent, use the default from the config template in `init.md`. See AGENTS.md for the canonical model/role mapping and rationale.

Valid model values: `sonnet`, `opus`, `haiku`, or a full model ID (e.g., `claude-sonnet-4-6`). In the dispatch annotations below, `config.models.<role>` refers to the value at `.unslop/config.json` -> `models` -> `<role>`.

### Phase 1: Archaeologist (Intent Extraction + Strategic Projection)

**Dispatch model:** `config.models.archaeologist`. The calling command sets the model based on context (see model defaults in `init.md` config template and AGENTS.md).

The Archaeologist operates in two distinct modes depending on its invocation context:

**Distill mode (inferential):** Reads source code and existing tests, then produces a candidate abstract spec by inferring behavioural intent from the implementation. This is the mode invoked by `/unslop:distill`. The output is an abstract spec (`.spec.md`) suitable for review and promotion. The Archaeologist must not write tests in this mode -- only declarative specs.

**Generate mode (projective):** Reads an abstract spec, a principles file, and the project file tree, then produces a concrete spec (`.impl.md`) and a `behaviour.yaml` in a single pass. This replaces the former Strategist role. Because the Archaeologist has full context of both implementation strategy and test constraints, it can produce a coherent concrete spec where the behaviour contract and the generation plan are derived from the same source of intent.

In both modes, the Archaeologist must NOT write tests. It writes specs and behaviour contracts only.

**Input (distill mode):** Source code + existing tests
**Output (distill mode):** Abstract spec (`*.spec.md`)

**Input (generate mode):** Abstract spec + principles file + file tree
**Output (generate mode):** Concrete spec (`*.impl.md`) + `*.behaviour.yaml`

The Strategist persona (v0.24.0-v0.34.0) has been subsumed by the Archaeologist as of v0.35.0. The Archaeologist produces both concrete specs (formerly Strategist's responsibility) and behaviour.yaml in a single pass, providing a coherent view of how implementation strategy and test constraints relate.

### Phase 2: Mason (Spec-Blind Test Construction)

**Dispatch model:** `config.models.mason`

The Mason receives ONLY the behaviour YAML. It is **denied access to source code**.
This is the critical information asymmetry — the "firewall" — that forces black-box
test generation.

**Input:** `*.behaviour.yaml` (NO source code access)
**Output:** `test_*.py` file

**Chinese Wall exception (Cover Mode):** During `/unslop:cover`, the Mason may receive surviving mutant descriptions (original/mutated line pairs) as test guidance. This is a controlled leak -- the Mason sees *what changed* but not the surrounding implementation. The mutant description helps the Mason write assertions that specifically catch the mutation, without exposing the full source code.

The Mason's tests are validated by the **Mock Budget Linter** before they can proceed
to Phase 3. Tests that mock internal modules are Hard Rejected.

### Phase 3: Saboteur (Mutation Validation)

**Dispatch model:** `config.models.saboteur`

**HARD RULE: The Saboteur MUST run in a worktree (`isolation: "worktree"`).** Mutations are applied to source files in the worktree copy, never to the main working tree. The worktree is discarded after verification -- the Saboteur's output is a JSON report, not code changes. This eliminates the mutation leak failure mode where an unrevetted mutation corrupts the source file.

The Saboteur operates in two contexts:

**Verify mode (post-generate):** Runs async mutation testing as a fidelity check after the generate pipeline completes. Results are stored in `.unslop/verification/`. This mode is triggered automatically by `/unslop:generate` and on-demand by `/unslop:verify`. It validates that the generated code matches the behavioural contract defined in the behaviour.yaml.

**Cover mode:** Gap analysis on existing tests, integrated with Archaeologist classification and Mason gap-filling (same as before). See "Archaeologist Classification + Diff-Mode (Cover Mode)" below.

In both modes, if a mutant survives (tests still pass despite a code change), it indicates either:

1. **Weak Assertions** -- the Mason's tests don't cover a critical behaviour
2. **Spec Failure** -- the Archaeologist failed to extract a constraint

The Saboteur classifies each surviving mutant and routes feedback to the correct phase.

### Constitutional Compliance (Post-Generate Verification)

When the Saboteur runs as async post-generate verification (Stage 3 of the unified generate pipeline) or via `/unslop:verify`, it executes a constitutional compliance phase after mutation testing.

**Input:** `.unslop/principles.md` + managed source file (full content)

**Process:** For each principle in `principles.md`, the Saboteur assesses whether the generated code violates it. This is LLM-native analysis -- principles are natural language and violations require judgment about intent, not pattern matching.

**Output:** `constitutional_violations` array in the verification JSON. Each entry: `principle`, `location`, `violation`, `required`.

**Severity:** Constitutional violations cause verification `status: "fail"` even if all mutants were killed. They soft-block ratification in `/unslop:elicit` -- the user must fix, override (`--force-constitutional` with rationale), or defer.

The Saboteur checks both `.unslop/principles.md` and any loaded `constitutional` project-local skills. Constitutional skills are functionally equivalent to scoped principles -- violations produce the same finding structure and soft-block ratification.

**Not applicable to:** The adversarial pipeline (Phase 1-2-3 in cover mode). Constitutional checking runs only in verification context, not during mutation-driven test generation.

### Edge Case Probing (Post-Generate Verification)

After constitutional checking, the Saboteur probes the code's attack surface for inputs the spec didn't anticipate.

**Input:** Abstract spec + managed source file (full content)

**Process:** Generate adversarial inputs derived from the code's attack surface (not from the spec): boundary values, malformed data, null/empty/oversized inputs, concurrent access patterns, resource exhaustion. For each, assess whether the code handles it gracefully or fails silently.

**Budget:** Maximum `config.edge_case_budget` findings (default: 10). Ranked by severity: silent data corruption > unhandled exception > resource leak > unexpected behaviour.

**Output:** `edge_case_findings` array in the verification JSON. Each entry: `input`, `expected`, `actual`, `severity`, `spec_gap`.

**Severity:** Informational only. Edge case findings do NOT affect verification `status` and do NOT block ratification. They surface in `/unslop:status` as a count with a hint to investigate.

**Relationship to cover:** Edge case probing is a lightweight, automatic version of cover's gap analysis. If findings exist, the user can run `/unslop:cover` for deep investigation. The probing phase never writes tests -- it only identifies gaps.

### Mutant Classification (Archaeologist)

After the Saboteur produces surviving mutants, the Archaeologist classifies each one as part of its analysis:

- **equivalent** -- mutation changes code but not behaviour. Discard.
- **weak_test** -- behaviour.yaml already has a constraint, but no test exercises it. Queue for Mason with the existing constraint.
- **spec_gap** -- genuinely missing constraint. The Archaeologist writes a new behaviour.yaml entry.

This classification was previously a separate Prosecutor step (heuristic script). Field testing showed the heuristics classified everything as `inconclusive`, making the Archaeologist do the real work anyway. The Archaeologist has full context (source + spec + behaviour.yaml) and produces accurate classifications in a single pass.

## Mock Budget Enforcement

The Mock Budget is enforced at the AST level — not by prompt engineering.

### Boundary Manifest

Every project declares its external boundaries in `.unslop/boundaries.json`:

```json
["requests", "boto3", "psycopg2", "redis", "stripe"]
```

### Rules

1. **Stdlib mocks are always allowed:** `time.sleep`, `os.environ`, `random.uniform`, etc.
2. **Boundary mocks are allowed:** Anything matching a prefix in `boundaries.json`
3. **Internal mocks are HARD REJECTED:** `patch("src.internal_logic")` → test rejected
4. **The linter is an AST check, not a regex:** It parses the test file and extracts all `patch()` targets

### Rationale

Mocks of internal modules create implementation coupling. When the implementation changes,
the test breaks — not because behaviour changed, but because the mock target moved. This
is the primary vector for "test scum" and must be blocked at the harness level.

## Behaviour DSL Reference

```yaml
behaviour: "transfer_funds"
interface: "finance.ops:transfer"
constraints:
  - given: "auth_token.valid == True"
  - when: "amount <= account.balance"
  - then: "account.balance == PREVIOUS(account.balance) - amount"
  - invariant: "total_system_value == PREVIOUS(total_system_value)"
  - error: "InsufficientFunds if amount > account.balance"
  - property: "transfer is idempotent for same transaction_id"
errors:
  - "InsufficientFunds: raised when amount exceeds balance"
  - "InvalidToken: raised when auth_token is expired or revoked"
invariants:
  - "System total value is conserved across all transfers"
depends_on:
  - "auth.validate_token"
  - "ledger.record_transaction"
```

### Constraint Types

| Type | Purpose | Example |
|------|---------|---------|
| `given` | Precondition | `"auth_token.valid == True"` |
| `when` | Trigger condition | `"amount <= account.balance"` |
| `then` | Postcondition | `"balance decreased by amount"` |
| `invariant` | Always-true property | `"total_value conserved"` |
| `error` | Error condition + exception | `"InsufficientFunds if overdraw"` |
| `property` | General behavioural property | `"idempotent for same txn_id"` |

## Convergence Loop

The adversarial pipeline is iterative. A single pass is:

```
Archaeologist → Mason → Saboteur → [pass/fail]
```

On failure, the Archaeologist classifies survivors and routes to:
- **Weak test** -> Mason retries with surviving mutant as guidance
- **Spec gap** -> Archaeologist adds the missing constraint, Mason writes a test
- **Equivalent mutant** -> discarded, no retry needed

Maximum iterations: 3 (configurable in `.unslop/config.json` as `adversarial_max_iterations`).

## Archaeologist Classification + Diff-Mode (Cover Mode)

When invoked from `/unslop:cover`, the Archaeologist operates differently from takeover mode:

| Aspect | Takeover (N) | Cover (O) |
|---|---|---|
| **Who invokes** | The Architect (during Double-Lift) | The cover pipeline (after Saboteur) |
| **Input** | Source code + spec (extraction from scratch) | ALL surviving mutants + existing behaviour.yaml + spec + source + existing tests |
| **Goal** | Extract ALL behavioural intent | Classify survivors + find uncovered constraints |
| **Output** | Complete behaviour.yaml | Classification (equivalent/weak_test/spec_gap) + delta constraints |

The Archaeologist first classifies each surviving mutant, then for each `spec_gap` answers one question:

> "What constraint, if it existed in the behaviour.yaml, would have forced the Mason to write a test that kills this mutant?"

**Input per mutant:**
- The mutation (original line, mutated line, line number)
- The source file (to understand surrounding context)
- The existing behaviour.yaml (to avoid duplicating existing constraints)
- The existing tests (to confirm the constraint is genuinely untested)
- The spec (to ground the new constraint in the project's intent language)

**Output per mutant:**
- A new `given`/`when`/`then`, `error`, `invariant`, or `property` entry for the behaviour.yaml
- A one-line semantic summary (for the triage report)

## Strategic Mutation Selection (Cover Mode)

The Saboteur uses a mutation budget (default 20, configurable as `mutation_budget` in config.json). Equivalent mutants classified by the Archaeologist do not count against the budget.

**Prioritisation (high-entropy areas):**
1. **Boundary conditions** (`<` vs `<=`, `>` vs `>=`, `==` vs `!=`)
2. **Logical inversions** (`not x` vs `x`, `and` vs `or`)
3. **Empty blocks** (removing a side-effect call, replacing function body with `pass`)
4. **Error handling paths** (removing `raise`, swapping exception types, removing `except` blocks)

**Distribution:** For files with multiple functions, distribute the budget across the most complex functions (by branch count). For a budget of 20 with 4+ functions, allocate ~5 mutations per function. Single-function files get the full budget.

**CLI override:** `--budget N` sets a custom budget. `--exhaustive` removes the budget limit.

## Integration with Generation Pipeline

The adversarial pipeline runs AFTER code generation (Stage B) and BEFORE the final
quality gate. It replaces simple test-run validation with mutation-gated validation:

```
Stage A (Architect) → Stage A.2 (Archaeologist, generate mode) → Stage B (Builder)
    → Adversarial Pipeline [Archaeologist → Mason → Saboteur]
    → Final quality gate
```

The adversarial pipeline is optional and enabled per-project via `.unslop/config.json`:

```json
{
  "adversarial": true,
  "adversarial_max_iterations": 3,
  "mutation_tool": "mutmut"
}
```

## Takeover Mode

When invoked from the testless takeover pipeline (not directly by the user), the adversarial skill operates with these differences:

1. **The Architect writes the behaviour.yaml, not the Archaeologist.** During testless takeover, the Architect already reads the code and drafts the spec -- it produces the behaviour.yaml in the same pass (takeover Step 2c). The Archaeologist is reserved for post-takeover use (e.g., `/unslop:cover`).

2. **The Mason receives the behaviour.yaml from the takeover pipeline.** It does not extract its own. The Chinese Wall is still enforced -- the Mason sees only the behaviour.yaml, never the source code.

3. **Convergence crosses three stages.** In normal adversarial runs, only the Mason retries. In takeover mode, the Architect may enrich the behaviour.yaml and the Builder may re-generate code, creating a three-way convergence loop managed by the takeover skill (Step 7).

## Integration Pass (Takeover Mode)

During testless takeover, the Mason may encounter internal dependencies. The mock budget normally rejects these, but:

- **Managed dependencies** (files with `@unslop-managed` header) may be used directly in tests without mocking. Their behaviour is contractual -- the spec guarantees their interface.
- **Unmanaged dependencies** trigger a cascade recommendation: "Take over `{dep}` first, then retry."
- **User escape hatch:** Add the blocking module to `boundaries.json` as an explicit internal boundary. This is a conscious trade-off, not an automatic bypass.

## Entropy Threshold (Takeover Mode)

Each Saboteur iteration tracks the mutation kill rate. If the improvement between iterations drops below the project's `entropy_threshold` (default 0.05 = 5%), convergence has stalled.

**Success exemption:** If kill rate is already 100%, skip the entropy check -- there's nothing left to improve.

**On stall:** The takeover skill triggers **Radical Spec Hardening** -- a one-shot rewrite of the behaviour.yaml using the Archaeologist's surviving mutant summary as guidance:

1. Archaeologist summarizes ALL surviving mutants as a batch with classifications
2. Architect rewrites behaviour.yaml from scratch using: original abstract spec + Archaeologist's summary + previous behaviour.yaml as reference (not template)
3. Mason generates tests from the rewritten behaviour.yaml
4. If this also stalls: DONE_WITH_CONCERNS -- report surviving mutants, commit with partial coverage

The entropy threshold is configurable in `.unslop/config.json` as `entropy_threshold`. Set to 0 to disable.
