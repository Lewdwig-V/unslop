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
                                                                    │ Prosecutor  │
                                                                    │ (Phase 3b)  │
                                                                    │             │
                                                                    │ Classifies  │
                                                                    │ surviving   │
                                                                    │ mutants     │
                                                                    └─────────────┘
```

### Model Selection

Before dispatching any adversarial agent, read `.unslop/config.json`. If a `models` block exists and contains a key matching the agent role, pass that value as the `model` parameter when dispatching via `Agent()`. If the `models` block is missing or the role key is absent, use the hardcoded default. Note: the adversarial agents are dispatched by the controlling session -- no `Agent()` code block exists in this skill. The controlling session must set the `model` parameter when creating each agent.

| Role | Default |
|---|---|
| archaeologist | sonnet |
| mason | haiku |
| saboteur | haiku |
| prosecutor | sonnet |

The `model` parameter controls which Claude model runs the subagent. Valid values: `sonnet`, `opus`, `haiku`, or a full model ID (e.g., `claude-sonnet-4-6`). In the dispatch annotations below, `config.models.<role>` refers to the value at `.unslop/config.json` -> `models` -> `<role>`.

### Phase 1: Archaeologist (Intent Extraction)

**Dispatch model:** `config.models.archaeologist` (default: sonnet)

The Archaeologist reads source code and extracts behavioural intent into the
**Behaviour DSL** — a structured YAML format that captures constraints, invariants,
and error conditions without implementation detail.

**Input:** Source code + existing specs
**Output:** `*.behaviour.yaml` file

The Archaeologist must NOT write tests. It only writes declarative behaviour specs.

### Phase 2: Mason (Spec-Blind Test Construction)

**Dispatch model:** `config.models.mason` (default: haiku)

The Mason receives ONLY the behaviour YAML. It is **denied access to source code**.
This is the critical information asymmetry — the "firewall" — that forces black-box
test generation.

**Input:** `*.behaviour.yaml` (NO source code access)
**Output:** `test_*.py` file

**Chinese Wall exception (Cover Mode):** During `/unslop:cover`, the Mason may receive surviving mutant descriptions (original/mutated line pairs) as test guidance. This is a controlled leak -- the Mason sees *what changed* but not the surrounding implementation. The mutant description helps the Mason write assertions that specifically catch the mutation, without exposing the full source code.

The Mason's tests are validated by the **Mock Budget Linter** before they can proceed
to Phase 3. Tests that mock internal modules are Hard Rejected.

### Phase 3: Saboteur (Mutation Validation)

**Dispatch model:** `config.models.saboteur` (default: haiku)

The Saboteur runs the Mason's tests against mutated versions of the source code.
If a mutant survives (tests still pass despite a code change), it indicates either:

1. **Weak Assertions** — the Mason's tests don't cover a critical behaviour
2. **Spec Failure** — the Archaeologist failed to extract a constraint

The Saboteur classifies each surviving mutant and routes feedback to the correct phase.

### Phase 3b: Prosecutor (Equivalent Mutant Classification)

**Dispatch model:** `config.models.prosecutor` (default: sonnet)

Not all surviving mutants are test failures. Some are **equivalent mutants** —
mutations that change code but not behaviour (e.g., `i < 10` → `i <= 9`).

The Prosecutor uses heuristic-first classification:

1. **Heuristic filter:** Common patterns (off-by-one equivalences, dead code, redundant conditions)
2. **Semantic check:** If heuristics are inconclusive, an LLM call classifies the mutant
3. **Verdicts:** `equivalent` (ignore), `weak_test` (Mason retries), `spec_gap` (Archaeologist retries)

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

On failure, the Saboteur feedback routes to:
- **Weak test** → Mason retries with surviving mutant as guidance
- **Spec gap** → Archaeologist retries, adding the missing constraint
- **Equivalent mutant** → Prosecutor filters, no retry needed

Maximum iterations: 3 (configurable in `.unslop/config.json` as `adversarial_max_iterations`).

## Prosecutor Routing (Cover Mode)

In `/unslop:cover`, the Prosecutor's verdict determines routing:

- **equivalent**: Discarded. Does not consume the mutation budget.
- **weak_test**: Routes directly to the Mason with the existing behaviour.yaml constraint and the surviving mutant as guidance. The Archaeologist is skipped -- the constraint already exists, the test just needs strengthening.
- **spec_gap**: Routes to the Archaeologist for diff-mode discovery. A genuinely missing constraint needs to be identified and added to the behaviour.yaml before the Mason can write a test.

This routing split prevents the Archaeologist from hallucinating duplicate constraints for mutants that are already covered by existing behaviour.yaml entries but weakly tested.

## Archaeologist Diff-Mode (Cover Mode)

When invoked from `/unslop:cover`, the Archaeologist operates differently from takeover mode:

| Aspect | Takeover (N) | Cover (O) |
|---|---|---|
| **Who invokes** | The Architect (during Double-Lift) | The cover pipeline (after Saboteur) |
| **Input** | Source code + spec (extraction from scratch) | spec_gap mutants + existing behaviour.yaml + spec + source + existing tests |
| **Goal** | Extract ALL behavioural intent | Find ONLY the uncovered constraints |
| **Output** | Complete behaviour.yaml | Delta: new constraints appended to existing behaviour.yaml |

For each `spec_gap` surviving mutant, the Archaeologist answers one question:

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

The Saboteur uses a mutation budget (default 20, configurable as `mutation_budget` in config.json). Equivalent mutants classified by the Prosecutor do not count against the budget.

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
Stage A (Architect) → Stage A.2 (Strategist) → Stage B (Builder)
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

**On stall:** The takeover skill triggers **Radical Spec Hardening** -- a one-shot rewrite of the behaviour.yaml using the Prosecutor's surviving mutant summary as guidance:

1. Prosecutor summarizes ALL surviving mutants as a batch
2. Architect rewrites behaviour.yaml from scratch using: original abstract spec + Prosecutor's summary + previous behaviour.yaml as reference (not template)
3. Mason generates tests from the rewritten behaviour.yaml
4. If this also stalls: DONE_WITH_CONCERNS -- report surviving mutants, commit with partial coverage

The entropy threshold is configurable in `.unslop/config.json` as `entropy_threshold`. Set to 0 to disable.
