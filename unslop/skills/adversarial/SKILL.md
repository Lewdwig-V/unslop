---
name: adversarial
description: "Adversarial Quality framework — three-agent pipeline (Archaeologist → Mason → Saboteur) for mutation-gated test generation"
version: "0.12.0"
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

### Phase 1: Archaeologist (Intent Extraction)

The Archaeologist reads source code and extracts behavioural intent into the
**Behaviour DSL** — a structured YAML format that captures constraints, invariants,
and error conditions without implementation detail.

**Input:** Source code + existing specs
**Output:** `*.behaviour.yaml` file

The Archaeologist must NOT write tests. It only writes declarative behaviour specs.

### Phase 2: Mason (Spec-Blind Test Construction)

The Mason receives ONLY the behaviour YAML. It is **denied access to source code**.
This is the critical information asymmetry — the "firewall" — that forces black-box
test generation.

**Input:** `*.behaviour.yaml` (NO source code access)
**Output:** `test_*.py` file

The Mason's tests are validated by the **Mock Budget Linter** before they can proceed
to Phase 3. Tests that mock internal modules are Hard Rejected.

### Phase 3: Saboteur (Mutation Validation)

The Saboteur runs the Mason's tests against mutated versions of the source code.
If a mutant survives (tests still pass despite a code change), it indicates either:

1. **Weak Assertions** — the Mason's tests don't cover a critical behaviour
2. **Spec Failure** — the Archaeologist failed to extract a constraint

The Saboteur classifies each surviving mutant and routes feedback to the correct phase.

### Phase 3b: Prosecutor (Equivalent Mutant Classification)

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
