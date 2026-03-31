# Prunejuice

Multi-agent coordinator harness built on the Claude Code SDK. SDK-native implementation of the spec-as-coordinator pattern described in the [unslop paper](https://github.com/Lewdwig-V/unslop/blob/main/docs/paper/spec-as-coordinator.md).

## Architecture

### Five Phases + Three Orchestrators

| Phase        | Function              | What it does                                            |
| ------------ | --------------------- | ------------------------------------------------------- |
| **Distill**  | `distill(cwd)`        | Infer spec from existing code                           |
| **Elicit**   | `elicit(intent, cwd)` | Create/amend spec from user intent                      |
| **Generate** | `generate(spec, cwd)` | Tests → implementation → mutation testing → convergence |
| **Cover**    | `cover(cwd)`          | Find and fill test coverage gaps                        |
| **Weed**     | `weed(cwd)`           | Detect intent drift between spec and code               |

| Orchestrator | Composition                 | Use case                             |
| ------------ | --------------------------- | ------------------------------------ |
| **Takeover** | distill → elicit → generate | Bring existing code under management |
| **Change**   | elicit (amend) → generate   | Record a change, regenerate          |
| **Sync**     | generate from stored spec   | Regenerate stale files               |

### Library API (`src/api.ts`)

The library surface is what external callers (e.g., unslop) import:

```typescript
import { distill, generate, weed, change } from "prunejuice";
```

Each phase accepts a `log` callback and optional `onDiscovery` handler. The CLI (`src/index.ts`) is a thin wrapper over the library.

### Agent Roles

| Agent                   | Role                                               | Tools                                   | Information Boundary                        |
| ----------------------- | -------------------------------------------------- | --------------------------------------- | ------------------------------------------- |
| Architect               | Intent → Spec                                      | Read, Grep, Glob, LS                    | Sees everything                             |
| Archaeologist           | Code analysis → Concrete spec + behaviour contract | Read, Grep, Glob, LS, Bash              | No tests during generate                    |
| Archaeologist (distill) | Code → inferred Spec                               | Read, Grep, Glob, LS, Bash              | No existing spec                            |
| Archaeologist (weed)    | Spec + code → DriftReport                          | Read, Grep, Glob, LS, Bash              | Sees both for comparison                    |
| Mason                   | Behaviour contract → Tests                         | None (prompt-only)                      | Only sees behaviour contract [Chinese Wall] |
| Builder                 | Spec + Tests → Implementation                      | Read, Grep, Glob, LS, Bash, Write, Edit | No Mason derivation logic                   |
| Saboteur                | Mutation testing + compliance                      | Read, Grep, Glob, LS, Bash              | No Builder generation logic                 |

### Pipeline Flow (Generate Phase)

```
Spec
  → Archaeologist (code + spec → ConcreteSpec + BehaviourContract + Discovered items)
  → Discovery Gate (callback to caller — interactive in CLI, programmatic in library)
  → Mason (BehaviourContract only → GeneratedTests) [Chinese Wall]
  → Builder (Spec + ConcreteSpec + Tests → Implementation)
  → Saboteur (Spec + Tests + Implementation → MutationReport with classifications)
  → Convergence loop (routes survivors: weak_test → Mason, spec_gap → Architect)
```

### Hash Chain

Generated files carry a managed header linking them to spec artifacts:

```
// @prunejuice-managed -- Edit .prunejuice/artifacts/concrete-spec.json instead
// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z
```

Eight-state freshness classifier with branded `TruncatedHash` types.

### Convergence Loop

- Survivors classified: `weak_test` → Mason, `spec_gap` → Architect, `equivalent` → skip
- Kill rate recomputed by pipeline (never trusted from LLM)
- Regression detection: rate got worse → abort
- Entropy stall: < 5% improvement → radical hardening
- Max 3 iterations + 1 radical hardening pass (`radicalHardeningAttempted` flag)

## Commands

```bash
npm run build    # TypeScript compile
npm run test     # Run vitest
npm run start    # Run CLI with tsx
npm run dev      # Watch mode
```

## CLI Usage

```bash
prunejuice distill                    # infer spec from existing code
prunejuice elicit "Add rate limiter"  # create spec from intent
prunejuice generate                   # tests + implementation from stored spec
prunejuice cover                      # fill test coverage gaps
prunejuice weed                       # detect intent drift

prunejuice takeover                   # distill → elicit → generate
prunejuice change "Add retry logic"   # elicit (amend) → generate
prunejuice sync                       # regenerate stale files
```

## Key Files

- `src/api.ts` — Library API: five phases + three orchestrators (the surface unslop imports)
- `src/types.ts` — Shared types, branded hashes, discriminated unions, `*Input` types
- `src/pipeline.ts` — `queryAgent()`, convergence logic, survivor routing, freshness checks
- `src/hashchain.ts` — SHA-256/12 hex, managed file headers, eight-state freshness classifier
- `src/store.ts` — Artifact persistence to `.prunejuice/`, managed file writing
- `src/agents/*.ts` — Agent definitions (system prompts + tool restrictions)
- `src/index.ts` — CLI wrapper over library API
- `test/*.test.ts` — 77 unit tests (vitest)

## Key Differences from Unslop

| Aspect                | Unslop (filesystem)                      | Prunejuice (SDK)                                            |
| --------------------- | ---------------------------------------- | ----------------------------------------------------------- |
| Control plane         | Filesystem — agents read headers and act | TypeScript — library functions dispatch agents              |
| Coordination          | Implicit (file existence + hash state)   | Explicit (composable phase functions + convergence loop)    |
| Information isolation | Prompt construction                      | Structural (`query()` calls with different tool sets)       |
| Interactive elicit    | Built-in (runs in Claude Code session)   | Callback-based (`DiscoveryHandler`, future `AsyncIterable`) |
| Integration           | Claude Code plugin                       | npm library (`import { generate } from "prunejuice"`)       |
| Context handoff       | Manual (structured handoff artifacts)    | Automatic (each `query()` call is a fresh context)          |
