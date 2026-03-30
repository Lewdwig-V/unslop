# The Spec as Coordinator: Multi-Agent Code Generation Without an Orchestrator

*Lewis V., March 2026*

---

## 1. The Result

A test-generation agent that has never seen the source code produced 70 black-box tests that caught 88% of injected mutations in the implementation. The implementation itself was regenerated from a spec by a different agent that never saw the tests. The regenerated code was structurally different from the original -- different function decomposition, different control flow, different variable names -- but behaviourally identical. Every test passed against both versions.

No orchestrator coordinated these agents. No SDK managed the handoffs. No shared memory held the state. Five agents -- Architect, Archaeologist, Mason, Builder, Saboteur -- read files, did work, and wrote files. The coordination mechanism was a markdown spec with YAML frontmatter.

This paper describes how that works and why it matters.

## 2. The Problem

Every team using LLM code generation will eventually discover that regenerating a file produces different code than last time. The function still passes its tests, but the implementation changed -- different error messages, different internal structure, different edge-case behaviour in areas the tests don't cover. The intent that produced the original was never recorded anywhere durable. It lived in a prompt, in a conversation, in someone's head. When the model ran again, it made different choices, because it had no memory of the choices it made before.

This is the fundamental problem: **code is a lossy encoding of intent**. You can read code and infer what it does, but not why it does it that way, what alternatives were considered, or what behaviour is accidental versus deliberate. When a human writes code, the intent lives in their head and degrades gracefully -- they remember the important parts, forget the details, and the code mostly stays stable because the same person maintains it. When an LLM writes code, the intent lives nowhere. Every generation is a fresh inference from whatever context is available.

The conventional solution is "better prompts" -- more detailed instructions, more examples, more constraints in the system message. This works until it doesn't. Prompts are ephemeral. They don't compose across sessions. They can't be versioned, diffed, or validated. They don't tell you when the code has drifted from what was intended. They are, fundamentally, the wrong abstraction for durable intent.

The solution I stumbled into is older than LLMs: **specs**. Not specs in the enterprise-waterfall sense -- thousand-page documents nobody reads. Specs in the design-by-contract sense: structured declarations of what code should do, written in behaviour language, versioned alongside the code, and mechanically validated against it.

The contribution of this paper is not "specs are good" -- that's been known since Bertrand Meyer. The contribution is that specs solve a coordination problem that didn't exist before LLMs: **how do you get multiple AI agents to collaborate on code generation without an external orchestrator managing the transitions?**

## 3. The Architecture

### 3.1 Five Agents, No Orchestrator

The system has five agents, each with a specific role and specific information access:

| Agent | Role | Sees | Doesn't See |
|-------|------|------|-------------|
| **Architect** | Intent elicitation, spec design | Everything | -- |
| **Archaeologist** | Spec inference from code, strategy projection | Code + spec | Tests (during generate) |
| **Mason** | Test generation from behavioural contracts | `behaviour.yaml` only | Source code, specs |
| **Builder** | Implementation from spec + tests | Spec + concrete spec + tests | Mason's derivation logic |
| **Saboteur** | Mutation testing, constitutional compliance | Code + spec + tests | Builder's generation logic |

These agents don't talk to each other. They don't share memory. They don't run in a managed process. They read files from the filesystem, do their work, and write files back. The "coordination" is the file format -- specifically, the spec's frontmatter fields and the hash chain that connects specs to generated code.

### 3.2 The Hash Chain

Every generated file carries a header:

```
# @unslop-managed -- Edit retry.py.spec.md instead
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z
```

`spec-hash` is the SHA-256 (truncated to 12 hex characters) of the spec file at the time of generation. `output-hash` is the SHA-256 of the generated code body (below the header). Together, they form a bidirectional link: the spec knows what code it produced, and the code knows what spec produced it.

This hash chain enables an eight-state freshness classifier:

| State | Meaning | Action |
|-------|---------|--------|
| **fresh** | Both hashes match | Nothing to do |
| **stale** | Spec changed, code unchanged | Regenerate |
| **modified** | Code edited, spec unchanged | Investigate |
| **conflict** | Both changed | Manual resolution |
| **pending** | Spec exists, no code yet | Generate |
| **structural** | Spec exists, code disappeared | Lifecycle issue |
| **ghost-stale** | Upstream dependency changed | Cascade regeneration |
| **test-drifted** | Spec changed since tests generated | Regenerate tests |

This is the coordination mechanism. No agent needs to know what the other agents are doing. Each agent reads the hash chain, determines the current state, does its work, and updates the chain. The filesystem is the message bus.

### 3.3 The Spec as Communication Protocol

The spec is not documentation. It's a communication protocol between two kinds of agents with different memory architectures.

The human has persistent memory, rich context, and ambiguous intent. The model has precise execution, no persistent memory, and needs structured state to reconstruct what the human meant. The spec frontmatter -- 16 distinct fields parsed by the system -- solves that mismatch. Not by making English more precise, but by making the human's mental state legible to a context-free reader.

Key frontmatter fields and what they solve:

- **`intent` + `intent-hash`**: Tamper detection. If the spec body changes but `intent-approved` doesn't reset, the hash won't match. This catches accidental spec drift.
- **`distilled-from`**: Epistemic provenance. "Was this spec written by a human or inferred by a machine?" Different trust level, different review protocol.
- **`non-goals`**: Machine-readable exclusions. "This module does NOT cache results" prevents a future regeneration from adding caching because it "seems like a good idea."
- **`discovered`**: Transient correctness requirements. The Archaeologist found something the spec doesn't cover. It must be resolved (promoted to the spec or dismissed) before generation proceeds.
- **`rejected`**: Closed design decisions with rationale. Prevents agents from re-proposing approaches the human already considered and rejected.

Each field exists because a specific failure mode was observed in practice. `rejected` was added after an agent proposed the same architectural approach three sessions in a row, each time being told no. `non-goals` was added after a regeneration introduced input validation that the original intentionally omitted. `discovered` was added after a concrete spec silently absorbed a correctness requirement that should have been a human decision.

## 4. The Chinese Wall

The most counterintuitive design decision is the information asymmetry between Mason (the test generator) and Builder (the code generator). Mason generates tests from a `behaviour.yaml` file that describes what the code should do -- given/when/then constraints, invariants, error conditions. Mason never sees the source code, the abstract spec, or the concrete spec. Builder generates code from the spec and concrete spec, validated against Mason's tests. Builder never sees how Mason derived the tests.

This is the Chinese Wall, borrowed from financial regulation. The purpose is to prevent **tautological tests** -- tests that pass because they were derived from the same implementation they're testing, rather than from an independent specification of correct behaviour.

### 4.1 Why This Matters

If Mason sees the source code, it will write tests that exercise the code paths that exist, not the code paths that should exist. Missing branches won't be tested because Mason doesn't know they're missing. Edge cases the implementation handles incorrectly will be tested against the incorrect behaviour, because Mason treats the implementation as ground truth.

By restricting Mason to `behaviour.yaml` only, the tests become a genuinely independent check. They test what the code *should* do according to the behavioural contract, not what it *happens* to do according to the current implementation.

### 4.2 Empirical Validation

In the adversarial-hashing stress test, Mason generated 70 tests from `behaviour.yaml` for a 154-line hashing module (3 public functions, 2 sentinel constants). Mason never saw the module's source code.

All 70 tests passed against the original code.

Then the Builder regenerated the module from the spec. The Builder also never saw Mason's tests during generation -- it received them only for validation after producing its implementation. The regenerated code was structurally different:

- Different function decomposition (Builder extracted helper functions the original didn't have)
- Different control flow (Builder used early returns where the original used nested conditionals)
- Different variable names throughout

All 70 tests passed against the regenerated code.

This is the strongest possible evidence that the spec captured **behaviour, not implementation**. Two agents, with no shared information except the spec artifacts, independently produced compatible work.

### 4.3 Mutation Testing as Verification

The Saboteur then injected 20 mutations into the regenerated code and ran Mason's tests against each mutant:

- **15 killed** (tests caught the mutation)
- **3 survived, classified as equivalent** (the mutation didn't change observable behaviour -- e.g., removing a `break` from a loop over a non-overlapping list)
- **2 survived, classified as genuine gaps:**
  - A test checked that a result was non-None but not that it had the correct value (weak assertion)
  - A test checked that blank lines were treated as header but didn't verify the body excluded subsequent header lines (imprecise assertion)

The adjusted kill rate was 88.2% (15/17 non-equivalent mutants killed). The two genuine gaps are exactly the kind of finding the adversarial pipeline is designed to surface -- places where the behavioural specification was under-constrained, producing tests that are correct but not precise enough.

## 5. The Pipeline

The full generation pipeline has five stages:

```
Stage 0:  Archaeologist reads spec, produces concrete spec + behaviour.yaml
Stage 0b: Discovery gate -- if Archaeologist found correctness requirements
          the spec doesn't cover, pause and ask the human
Stage 1:  Mason generates tests from behaviour.yaml (Chinese Wall)
Stage 2:  Builder generates code from spec, validated against Mason's tests
Stage 3:  Saboteur runs mutation testing async (fire-and-forget)
```

### 5.1 Stage 0: The Archaeologist

The Archaeologist reads the abstract spec and produces two artifacts:

1. **Concrete spec** (`*.impl.md`): Implementation strategy -- algorithm choices, type sketches, language-specific lowering notes. This is the "how" layer that the abstract spec's "what" layer doesn't specify.

2. **`behaviour.yaml`**: Machine-readable behavioural contract in given/when/then format. This is the Chinese Wall artifact -- the only thing Mason sees.

The Archaeologist also performs a discovery check: are there correctness requirements implied by the strategy that the abstract spec doesn't explicitly state? If so, they're surfaced as `discovered:` frontmatter entries and the pipeline pauses at Stage 0b. The human promotes them into the spec or dismisses them. The concrete spec is never a back-channel for ratifying constraints the human didn't approve.

### 5.2 Stage 1: The Mason

Mason reads `behaviour.yaml` and nothing else. It produces a test file with one test per given/when/then constraint plus invariant tests. The tests import only the public API -- no internal helpers, no private functions, no implementation details.

The Chinese Wall is enforced by prompt construction: Mason's context contains only `behaviour.yaml`, the project's boundary configuration (which external dependencies can be mocked), and the test framework conventions. The source code, abstract spec, and concrete spec are not provided.

### 5.3 Stage 2: The Builder

The Builder receives the abstract spec, concrete spec, and Mason's tests. It generates code in a worktree (isolated git branch), runs the tests, and reports success or failure. If successful, the worktree merges automatically. If failed, the worktree is discarded and no files are modified.

The worktree isolation is critical: the Builder cannot corrupt the working tree even if it produces wrong code. Every generation is atomic -- it either succeeds completely or fails completely.

### 5.4 Stage 3: The Saboteur

After the Builder succeeds, the Saboteur runs asynchronously in a separate worktree. It applies mutations to the generated code, runs the tests against each mutant, and classifies survivors:

- **equivalent**: The mutation doesn't change observable behaviour (dead code, redundant checks)
- **weak_test**: The tests should catch this but don't (imprecise assertions, missing edge cases)
- **spec_gap**: The spec doesn't constrain this behaviour (ambiguous or underspecified)

The Saboteur also checks constitutional compliance (does the generated code violate project-wide principles?) and probes for edge cases (adversarial inputs the spec didn't anticipate).

Results are written to a JSON file. The user is never blocked -- Stage 3 is fire-and-forget. Findings surface in the status command.

### 5.5 Sprint Contracts

For re-generations (spec changed since last generate), a sprint contract adds a pre-generation handshake:

1. The **Architect** reads the spec diff and writes expected outcomes: what behaviours should change, what should remain invariant.
2. The **Saboteur** reads the expected outcomes and writes a verification strategy: which outcomes it can verify, which are partially verifiable, and which are **unverifiable** (with explicit explanation of why).

The `unverifiable-gaps` list is the contract's key contribution. It surfaces Goodhart's Law risk *before* the generation pass: "the Architect says timing should be invariant, but we have no clock mock in the test structure, so I can only verify retry count, not timing." Better to know this before generating than to discover it in a post-hoc mutation report.

### 5.6 Saboteur Calibration

The Saboteur's mutation classifications are LLM judgments -- they can drift across runs. A project-local calibration file (`.unslop/saboteur-calibration.md`) provides few-shot examples of correct classifications and, more importantly, corrections of past misclassifications.

The examples are anchors, not rules. The Saboteur reads them as context for its classification decisions but can disagree if the current case is genuinely different. This avoids overfitting to past examples while reducing classification variance.

Correction examples are more valuable than confirmation examples. A single "you classified this as equivalent but it was actually a spec gap because..." teaches more than ten "yes, this was correctly equivalent."

## 6. The Convergence Loop

When the Saboteur's kill rate falls below 80%, the testless takeover path enters a convergence loop:

1. **Classify survivors**: Each surviving mutant is routed to the responsible agent
   - `weak_test` → Mason strengthens assertions
   - `spec_gap` → Architect enriches `behaviour.yaml`
   - `equivalent` → no action
2. **Re-run**: Updated tests + updated behaviour spec → re-mutation
3. **Entropy check**: If kill rate improved by less than 5%, the loop is stalling

Maximum 3 normal iterations. If entropy stalls, a radical spec hardening pass fires: the Architect rewrites `behaviour.yaml` from scratch using the surviving mutant analysis as input. One shot. If that also stalls, the system commits what it has with a warning annotation.

This is not a "retry until it works" loop. Each iteration is targeted -- the surviving mutant classifications tell the system exactly what to fix and who should fix it. The entropy threshold prevents infinite loops where marginal improvements consume unbounded compute.

## 7. Where This Breaks Down

### 7.1 Sequential Coordination

File-system coordination is inherently sequential. Agent B can't start until Agent A's output file exists. For the current pipeline (Archaeologist → Mason → Builder → Saboteur), this is fine -- each stage depends on the previous stage's output.

But multi-target generation (one spec → N language implementations) requires fan-out: N Builders running in parallel, followed by a fan-in gate (all N must succeed for the merge to proceed). The spec layer can express fan-out (the `targets` field in the concrete spec) but can't coordinate fan-in without either polling or an external joiner. This is the one place where an SDK-based orchestrator would add genuine value.

### 7.2 Context Anxiety

Long adversarial runs -- multiple convergence iterations, each involving multiple agent dispatches -- can hit context limits. The distinction between **compaction** (same agent, shortened history) and **handoff** (fresh agent, structured context) matters: compaction preserves whatever anxiety or confusion accumulated in the context, while handoff resets it.

The natural handoff boundary for adversarial runs is between convergence iterations. Writing a structured handoff artifact (current kill rate, surviving mutant classifications, spec state) and dispatching a fresh agent is more reliable than compacting a long context and hoping the important parts survive.

### 7.3 Harness Assumptions

Every component in the harness encodes an assumption about what the model can't do on its own:

- **Worktree isolation** assumes the Builder can't be trusted not to pollute the main working tree
- **Chinese Wall** assumes Mason will couple to implementation details if it sees source code
- **Intent lock** assumes specs will drift without tamper detection
- **Convergence loop** assumes single-pass generation misses edge cases

These assumptions are worth stress-testing on each model improvement. Some may become unnecessary overhead as models get better -- the right response is to remove the scaffolding, not to keep it as ritual.

## 8. Related Work

**Design by Contract** (Meyer, 1986): The intellectual ancestor. Eiffel's preconditions, postconditions, and invariants are the same idea as spec constraints -- but embedded in the implementation language, not externalised as a coordination artifact. The key difference: in design by contract, the contract and the code are written by the same agent. Here, they're written by different agents with different information access.

**Property-Based Testing** (Claessen & Hughes, 2000): QuickCheck and its descendants generate test inputs from properties. Mason generates test *cases* from behavioural constraints. The distinction: property-based testing validates a single implementation against abstract properties; the adversarial pipeline validates that two independent agents (Mason and Builder) agree on behaviour without sharing information.

**Formal Verification**: TLA+, Alloy, and model checkers verify that implementations satisfy formal specifications. The spec layer is less rigorous -- it's natural language parsed by LLMs, not formal logic checked by theorem provers. The trade-off is accessibility: any developer can write a behaviour spec; few can write TLA+. The mutation testing compensates for the lack of formal guarantees with empirical coverage.

**LLM Agent Frameworks** (AutoGen, CrewAI, LangGraph): These focus on process coordination -- routing messages between agents, managing tool calls, handling failures. The spec layer focuses on *state* coordination -- each agent reads the current state from files and writes its contribution back. The frameworks solve "how do agents talk to each other"; the spec layer solves "how do agents work on the same artifacts without stepping on each other."

**Agentic Coding Harnesses** (SWE-bench, OpenHands, Devin): Evaluation frameworks for coding agents. They measure whether an agent can solve a task end-to-end. The spec layer is orthogonal -- it's not about whether a single agent can solve a task, but about how the task's intent is preserved across multiple agents and multiple generations.

## 9. Conclusion

I didn't set out to build a formal verification pipeline. I set out to stop my AI from producing slop. The spec was a workaround for the model forgetting what it was supposed to do between sessions. The Chinese Wall was a workaround for tests that passed because they tested the wrong thing. The mutation testing was a workaround for not being able to tell whether the tests were actually good. Each layer was added because the previous layer wasn't enough.

The result is a system where five agents collaborate on code generation using markdown files as their coordination mechanism. No orchestrator manages the transitions. No SDK handles the message passing. The spec's frontmatter fields, hash chain, and behavioural contract are the state machine. Each agent reads the current state, does its work, and advances the state. The filesystem is the message bus.

The empirical validation is modest -- one stress test, one module, 70 tests, 20 mutations. But the structural result is strong: two agents with no shared information except the spec artifacts independently produced compatible work. The Builder's code passed Mason's tests, and Mason never saw the code. That's not a fluke of the specific module or the specific model. That's a property of the architecture.

The spec is the source of truth. The code is a disposable artifact derived from it. And the coordination mechanism is just files on disk.

---

## Appendix A: Spec Artifact Schema

### Abstract Spec (`*.spec.md`)

```yaml
---
intent: >
  One-line description of what this module does
intent-approved: 2026-03-28T00:01:00Z    # ISO 8601 timestamp, not boolean
intent-hash: a6c4fdfc6106                # SHA-256 of intent text, 12 hex chars
distilled-from:                          # epistemic provenance (persists)
  - path: src/hashing.py
    hash: b91506f9fe1f
non-goals:
  - Does not cache results across calls
  - Does not validate input encoding
uncertain:                               # resolved during elicit
  - title: Truncation collision risk
    observation: 48-bit hash has birthday paradox threshold
    question: Deliberate trade-off or should hash be longer?
discovered:                              # resolved before generate
  - title: Missing boundary check
    observation: No validation on empty input
    question: Should empty input return error or hash of empty string?
rejected:                                # closed design decisions
  - title: Longer hash
    rationale: 12 chars is sufficient for the project scale
depends-on:
  - src/utils.spec.md
spec-changelog:
  - intent-hash: a6c4fdfc6106
    timestamp: 2026-03-28T00:00:00Z
    operation: distill
    prior-intent-hash: null
---

## Purpose
[Behaviour-language description]

## Behavior
[Observable contracts]

## Constraints
[Invariants, preconditions, postconditions]

## Error Handling
[Error propagation semantics]
```

### Concrete Spec (`*.impl.md`)

```yaml
---
source-spec: hashing.py.spec.md
target-language: python
complexity: low
concrete-dependencies: []
---

## Strategy
[Algorithm and decomposition choices]

## Type Sketch
[Function signatures and data structures]

## Representation Invariants
[Internal consistency rules]

## Safety Contracts
[Error handling guarantees]

## Lowering Notes
[Language-specific implementation guidance]
```

### Managed File Header

```python
# @unslop-managed -- Edit hashing.py.spec.md instead
# spec-hash:8e43c7b51522 output-hash:0086857549bd generated:2026-03-28T00:00:00Z
```

### Verification Result (`.unslop/verification/<hash>.json`)

```json
{
  "managed_path": "src/hashing.py",
  "spec_path": "src/hashing.py.spec.md",
  "timestamp": "2026-03-28T00:00:00Z",
  "status": "pass",
  "mutants_total": 20,
  "mutants_killed": 15,
  "mutants_survived": 5,
  "mutants_equivalent": 3,
  "source_hash": "9008d90fd34e",
  "spec_hash": "09ca16ffb0e1",
  "surviving_mutants": [...],
  "constitutional_violations": [],
  "edge_case_findings": [...],
  "contract_compliance": null
}
```

## Appendix B: Mutation Testing Results

### Stress Test: adversarial-hashing

**Target:** `hashing.py` (154 lines original, 209 lines regenerated)
**Functions:** `compute_hash()`, `parse_header()`, `get_body_below_header()`
**Tests generated by Mason:** 70 (from `behaviour.yaml`, Chinese Wall)
**Mutations applied by Saboteur:** 20

| ID | Location | Category | Description | Status | Classification |
|----|----------|----------|-------------|--------|----------------|
| M5 | hashing.py:26-28 | logic | Remove break after prefix match | survived | equivalent |
| M6 | hashing.py:30-32 | logic | Remove break after suffix match | survived | equivalent |
| M12 | hashing.py:195 | boundary | Change `end_line < 1` to `end_line < 0` | survived | equivalent |
| M15 | hashing.py:162 | logic | Return `{}` instead of `None` for empty manifest | survived | weak_test |
| M19 | hashing.py:186 | deletion | Remove blank-line skipping in header scan | survived | weak_test |

**Equivalent mutants (3):** All involve dead code paths. M5/M6 remove breaks from loops over non-overlapping lists -- the break is unreachable after the first match. M12 changes a boundary check that's already covered by an adjacent condition.

**Weak test mutants (2):** Both are real gaps. M15 reveals a missing test case (no test exercises a manifest line where all entries are malformed, so the empty-dict vs None return is unchecked). M19 reveals an imprecise assertion (test checks blank lines are treated as header but doesn't verify the body excludes subsequent header lines).

**Edge cases probed:** 10 (100KB string, emoji, RTL text, null bytes, regex patterns, whitespace equivalence, malformed spec-hash, mixed comment styles, negative end_line, BOM prefix). All handled correctly.

**Kill rate:** 75% raw, 88.2% adjusted (excluding equivalent mutants).

## Appendix C: Freshness State Machine

```
                    +-------+
          spec      |       |      code
         changed    | fresh |    changed
        +---------->+       +----------+
        |           +---+---+          |
        v               ^             v
    +-------+           |         +--------+
    | stale |      both |         |modified|
    +-------+     match |         +--------+
        |           +---+---+          |
        +---------->+       +<---------+
          generate  |conflict|   investigate
                    +--------+

    +-------+                    +----------+
    |pending|  no code, no prov  |structural|  no code, has prov
    +-------+                    +----------+
        |                              |
     generate                    lifecycle fix
                                (absorb/exude)

    +-----------+                +------------+
    |ghost-stale|  upstream dep  |test-drifted|  spec changed
    +-----------+    changed     +------------+  since tests gen
```

## Appendix D: Tool and Version Information

- **unslop plugin:** v0.51.0
- **Commands:** 20
- **Skills:** 6 (methodology) + project-local domain skills
- **Agents:** 5 (Architect, Archaeologist, Mason, Builder, Saboteur)
- **Orchestrator tests:** 408
- **Stress tests:** 70
- **Frontmatter fields parsed:** 16
- **Freshness states:** 8
- **Python compatibility:** 3.8--3.14
- **Platform:** Claude Code CLI plugin (pure markdown + Python orchestrator scripts)
