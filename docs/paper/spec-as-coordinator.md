# The Spec as Coordinator: Durable State for Multi-Agent Code Generation

*Lewdwig-V, April 2026 (revised from March 2026)*

---

## 1. The Result

A test-generation agent that has never seen the source code produced 70 black-box tests that caught 88% of injected mutations in the implementation. The implementation itself was regenerated from a spec by a different agent that never saw the tests. The regenerated code was structurally different from the original -- different function decomposition, different control flow, different variable names -- but behaviourally identical. Every test passed against both versions.

No shared runtime state held the handoffs together. A typed library dispatched the agents in sequence and passed data between them, but that library holds nothing in memory across invocations: every generation cycle rebuilds its state from files on disk. The durable coordination mechanism -- the thing that encodes the system's claims about a module across sessions, across agents, across regenerations -- is the spec artifact: spec files, their frontmatter, the behaviour contract, and the hash chains that connect them to generated code.

This paper describes that architecture and why the coordination layer is the load-bearing part.

## 2. The Problem

Every team using LLM code generation will eventually discover that regenerating a file produces different code than last time. The function still passes its tests, but the implementation changed -- different error messages, different internal structure, different edge-case behaviour in areas the tests don't cover. The intent that produced the original was never recorded anywhere durable. It lived in a prompt, in a conversation, in someone's head. When the model ran again, it made different choices, because it had no memory of the choices it made before.

This is the fundamental problem: **code is a lossy encoding of intent**. You can read code and infer what it does, but not why it does it that way, what alternatives were considered, or what behaviour is accidental versus deliberate. When a human writes code, the intent lives in their head and degrades gracefully -- they remember the important parts, forget the details, and the code mostly stays stable because the same person maintains it. When an LLM writes code, the intent lives nowhere. Every generation is a fresh inference from whatever context is available.

The conventional solution is "better prompts" -- more detailed instructions, more examples, more constraints in the system message. This works until it doesn't. Prompts are ephemeral. They don't compose across sessions. They can't be versioned, diffed, or validated. They don't tell you when the code has drifted from what was intended. They are, fundamentally, the wrong abstraction for durable intent.

The solution I stumbled into is older than LLMs: **specs**. Not specs in the enterprise-waterfall sense -- thousand-page documents nobody reads. Specs in the design-by-contract sense: structured declarations of what code should do, written in behaviour language, versioned alongside the code, and mechanically validated against it.

The contribution of this paper is not "specs are good" -- that's been known since Bertrand Meyer. The contribution is a specific architectural observation that I arrived at by accident and had to rebuild the system to make explicit: **multi-agent code generation has two orthogonal coordination problems, and they want different solutions.**

One problem is *runtime orchestration*: within a single generation cycle, how do five agents hand off typed artifacts to each other without stepping on the working tree? This is a conventional software engineering problem. A typed library with well-defined interfaces solves it.

The other problem is *durable coordination*: across sessions, across regenerations, across human memory, how do you preserve the intent that produced the code so the next cycle makes the same choices? This is not a conventional problem. Prompts don't solve it. Git commits don't solve it. What solves it is a structured spec artifact -- versioned, hash-chained, annotated with epistemic metadata -- that any future cycle can reconstruct state from.

The insight is that these two problems look the same at first glance (both are "getting agents to agree on what to do") but have different shapes. The first wants speed, type safety, and testability. The second wants durability, legibility, and auditability. The first should live in code. The second must live in the spec.

## 3. The Architecture

### 3.1 Two Layers, Five Agents

The system has five agents, each with a specific role and specific information access:

| Agent | Role | Sees | Doesn't See |
|-------|------|------|-------------|
| **Architect** | Intent elicitation, spec design | Everything | -- |
| **Archaeologist** | Spec inference from code, strategy projection | Code + spec | Tests (during generate) |
| **Mason** | Test generation from behavioural contracts | `BehaviourContract` only | Source code, specs |
| **Builder** | Implementation from spec + tests | Spec + concrete spec + tests | Mason's derivation logic |
| **Saboteur** | Mutation testing, constitutional compliance | Code + spec + tests | Builder's generation logic |

These agents run in sequence inside a runtime orchestrator (a TypeScript library called `prunejuice`). The orchestrator dispatches each agent with a tool-restricted context, passes the output to the next agent via typed function calls, and runs the convergence loop. It is, unambiguously, an orchestrator -- it's just not the coordination mechanism.

The coordination mechanism is the spec. Prunejuice holds no in-memory state across invocations; between cycles, everything it knows about the module must be reconstructible from durable artifacts on disk. There are four kinds of coordination artifact:

1. The **abstract spec** (`*.spec.md` and its mirror in `.prunejuice/artifacts/spec.json`): intent, constraints, frontmatter metadata
2. The **concrete spec** (`.prunejuice/artifacts/concrete-spec.json`): implementation strategy, pseudocode, inheritance chain. The hash chain on implementation files anchors against this artifact.
3. The **behaviour contract** (`.prunejuice/artifacts/behaviour-contract.json`): given/when/then scenarios, invariants, preconditions. The hash chain on test files anchors against this artifact; deleting it breaks test freshness.
4. The **managed file headers**: per-file hash chain comments linking each generated file back to the coordination artifacts it was derived from.

Between cycles (no pipeline in flight), these four artifacts plus the managed files are sufficient to reconstruct the entire coordination state -- prunejuice can start a fresh generation with no memory of prior runs. Mid-cycle crash recovery uses an additional set of memoized artifacts (Stage 1-3 outputs cached in `.prunejuice/artifacts/`), but those are derivable from the coordination artifacts by re-running the agents. Section 3.4 covers the distinction in detail.

That property -- the existence of a small, well-defined set of artifacts sufficient to reconstruct state -- is what makes the spec the coordinator rather than the library. The library can be torn down and rebuilt; the spec cannot.

### 3.2 The Hash Chain

Every generated file carries a header:

```
# @prunejuice-managed -- Edit retry.py.spec.md instead
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

This classifier is the entry point for all coordination. A fresh orchestrator run starts by reading the managed file headers, computing current hashes, and classifying every file in the project. The resulting state dictates what work is needed. No in-memory state from prior sessions is consulted -- the filesystem is the input, and it's sufficient.

For concrete specs with inheritance chains or cross-impl dependencies, the hash chain extends further: the managed file header also stores a `concrete-manifest` line with per-dependency hashes, enabling ghost-staleness detection when an upstream concrete spec changes without a direct abstract spec edit.

### 3.3 The Spec as Communication Protocol

The spec is not documentation. It's a communication protocol between two kinds of agents with different memory architectures.

The human has persistent memory, rich context, and ambiguous intent. The model has precise execution, no persistent memory, and needs structured state to reconstruct what the human meant. The spec frontmatter -- around a dozen distinct fields parsed by the system -- solves that mismatch. Not by making English more precise, but by making the human's mental state legible to a context-free reader.

Key frontmatter fields and what they solve:

- **`intent` + `intent-hash`**: Tamper detection. If the spec body changes but `intent-approved` doesn't reset, the hash won't match. This catches accidental spec drift.
- **`distilled-from`**: Epistemic provenance. "Was this spec written by a human or inferred by a machine?" Different trust level, different review protocol.
- **`non-goals`**: Machine-readable exclusions. "This module does NOT cache results" prevents a future regeneration from adding caching because it "seems like a good idea."
- **`discovered`**: Transient correctness requirements. The Archaeologist found something the spec doesn't cover. It must be resolved (promoted to the spec or dismissed) before generation proceeds.
- **`rejected`**: Closed design decisions with rationale. Prevents agents from re-proposing approaches the human already considered and rejected.
- **`depends-on`** + **`concrete-dependencies`** + **`extends`**: Graph structure. Abstract specs declare module dependencies; concrete specs declare strategy dependencies and inheritance chains.

Each field exists because a specific failure mode was observed in practice. `rejected` was added after an agent proposed the same architectural approach three sessions in a row, each time being told no. `non-goals` was added after a regeneration introduced input validation that the original intentionally omitted. `discovered` was added after a concrete spec silently absorbed a correctness requirement that should have been a human decision.

### 3.4 Three Kinds of State

An earlier version of this system coordinated agents through the filesystem exclusively: each stage wrote its output to a file, the next stage read it, and synchronization was "check if the file exists." That worked as a proof of concept but had a cost: every handoff incurred a filesystem round-trip and the coordination state was smeared across intermediate files (`behaviour.yaml`, temporary JSON outputs) whose lifetime and purpose weren't clearly separated.

Extracting the orchestrator into a typed library exposed a three-way split that the earlier architecture had conflated. Every pipeline artifact ends up on disk, but for three different reasons, with three different lifetimes:

| Artifact | Category | Why it's on disk |
|----------|----------|------------------|
| `Spec` | **Durable coordination** | Encodes human intent. Source of truth. Must survive across sessions. Persisted as `.spec.md` (human-edited) + `.prunejuice/artifacts/spec.json` (machine-readable mirror). |
| `ConcreteSpec` | **Durable coordination** | Encodes implementation strategy decisions. Persisted as `.prunejuice/artifacts/concrete-spec.json`. The managed file hash chain for implementation files anchors against this artifact. |
| `BehaviourContract` | **Durable coordination** | Persisted as `.prunejuice/artifacts/behaviour-contract.json`. The managed file hash chain for test files anchors against this artifact -- without it persisted, test freshness has nothing to chain to. Also the Chinese Wall artifact that Mason sees. |
| `GeneratedTests` | **Resumability cache** | Persisted as `.prunejuice/artifacts/tests.json`. Derivable from `BehaviourContract` via Mason re-run, but cached so a mid-pipeline crash can skip re-invoking Mason. Deleting the cache and re-running produces equivalent tests (modulo LLM nondeterminism). |
| `Implementation` | **Resumability cache** | Persisted as `.prunejuice/artifacts/implementation.json`. Derivable from `Spec + ConcreteSpec + Tests` via Builder re-run. Cached for crash recovery. |
| `SaboteurReport` | **Resumability cache** | Persisted as `.prunejuice/artifacts/saboteur-report.json`. Derivable from `Implementation + Tests` via Saboteur re-run. Cached for crash recovery. |
| Managed file header (`@prunejuice-managed` + hash chain + optional concrete manifest) | **Durable generated output** | Comment in the generated file itself. Links the file body to the coordination artifacts it was derived from. |

**Durable coordination artifacts** encode human decisions. They must survive across sessions or the system loses coherence: regenerating from a deleted `ConcreteSpec` or `BehaviourContract` produces different code and different tests, breaking the hash chain linking old outputs to anything meaningful. The three coordination artifacts plus the managed file headers are what the spec-as-coordinator claim rests on.

**Resumability cache artifacts** are memoized agent outputs. They persist so a mid-pipeline crash can resume without re-running expensive LLM calls, but they're conceptually disposable -- deleting `.prunejuice/artifacts/{tests,implementation,saboteur-report}.json` and re-running the pipeline produces equivalent results. The pipeline treats them as a cache, not ground truth.

**Durable generated output** is the actual code on disk. The managed file header links each output file back to its coordination artifacts via hash pointers. For implementation files, the pointer is to `ConcreteSpec`; for test files, it's to `BehaviourContract`. The hash chain is how freshness checks work across sessions.

The important consequence: to reconstruct prunejuice's state after a crash or fresh checkout, it's sufficient to have the three coordination artifacts plus the managed files. The resumability cache can be rebuilt from them by re-running the pipeline. But **neither category can be eliminated**: the coordination artifacts are load-bearing because the hash chains anchor against them, and the cache is load-bearing for crash-resilience.

This is the observation that the earlier filesystem-only architecture was obscuring. It looked like every file was equally load-bearing. It wasn't -- but "runtime only" vs "durable" is too coarse a split. The real distinction is between artifacts whose existence is semantic (coordination) and artifacts whose existence is operational (cache).

## 4. The Chinese Wall

The most counterintuitive design decision is the information asymmetry between Mason (the test generator) and Builder (the code generator). Mason generates tests from a `BehaviourContract` that describes what the code should do -- given/when/then constraints, invariants, error conditions. Mason never sees the source code, the abstract spec, or the concrete spec. Builder generates code from the spec and concrete spec, validated against Mason's tests. Builder never sees how Mason derived the tests.

This is the Chinese Wall, borrowed from financial regulation. The purpose is to prevent **tautological tests** -- tests that pass because they were derived from the same implementation they're testing, rather than from an independent specification of correct behaviour.

### 4.1 Why This Matters

If Mason sees the source code, it will write tests that exercise the code paths that exist, not the code paths that should exist. Missing branches won't be tested because Mason doesn't know they're missing. Edge cases the implementation handles incorrectly will be tested against the incorrect behaviour, because Mason treats the implementation as ground truth.

By restricting Mason to `BehaviourContract` only, the tests become a genuinely independent check. They test what the code *should* do according to the behavioural contract, not what it *happens* to do according to the current implementation.

### 4.2 Structural Enforcement

The original system enforced the Chinese Wall by prompt construction -- Mason's context was built from a `behaviour.yaml` file and nothing else. This worked but was fragile: a bug in the prompt-building code, or a future developer "helpfully" adding more context, could break the wall without anyone noticing.

The typed orchestrator enforces the wall structurally via a `MasonInput` interface whose only field is `behaviourContract`. Mason literally cannot receive source code or specs because its function signature does not have parameters for them. The information asymmetry is now a type error rather than a convention.

```typescript
export interface MasonInput {
  behaviourContract: BehaviourContract;
}
```

Compare to Builder's input, which legitimately receives everything:

```typescript
export interface BuilderInput {
  spec: Spec;
  concreteSpec: ConcreteSpec;
  tests: GeneratedTests;
  cwd: string;
}
```

A developer who later tries to add `spec: Spec` to `MasonInput` has to make a deliberate choice to violate the wall. The type system surfaces the decision rather than hiding it.

### 4.3 Empirical Validation

In the adversarial-hashing stress test, Mason generated 70 tests from a `BehaviourContract` for a 154-line hashing module (3 public functions, 2 sentinel constants). Mason never saw the module's source code.

All 70 tests passed against the original code.

Then the Builder regenerated the module from the spec. The Builder also never saw Mason's tests during generation -- it received them only for validation after producing its implementation. The regenerated code was structurally different:

- Different function decomposition (Builder extracted helper functions the original didn't have)
- Different control flow (Builder used early returns where the original used nested conditionals)
- Different variable names throughout

All 70 tests passed against the regenerated code.

This is the strongest possible evidence that the spec captured **behaviour, not implementation**. Two agents, with no shared information except the spec artifacts, independently produced compatible work.

### 4.4 Mutation Testing as Verification

The Saboteur then injected 20 mutations into the regenerated code and ran Mason's tests against each mutant:

- **15 killed** (tests caught the mutation)
- **3 survived, classified as equivalent** (the mutation didn't change observable behaviour -- e.g., removing a `break` from a loop over a non-overlapping list)
- **2 survived, classified as genuine gaps:**
  - A test checked that a result was non-None but not that it had the correct value (weak assertion)
  - A test checked that blank lines were treated as header but didn't verify the body excluded subsequent header lines (imprecise assertion)

The adjusted kill rate was 88.2% (15/17 non-equivalent mutants killed). The two genuine gaps are exactly the kind of finding the adversarial pipeline is designed to surface -- places where the behavioural specification was under-constrained, producing tests that are correct but not precise enough.

## 5. The Pipeline

The full generation pipeline has five stages. Each stage is a function call in the runtime orchestrator; each stage reads and writes specific artifacts. **Coordination** artifacts are marked (C), **cache** artifacts (resumability-only) are marked (Ca), and **durable output** is marked (O):

```
Stage 0:  Archaeologist reads Spec (C), produces ConcreteSpec (C) + BehaviourContract (C)
          All three artifacts persist to .prunejuice/artifacts/ before Stage 1.
Stage 0b: Discovery gate -- if Archaeologist found correctness requirements
          the spec doesn't cover, pause and ask the human (resolution updates Spec (C))
Stage 1:  Mason receives BehaviourContract only (via MasonInput interface),
          produces GeneratedTests (Ca). Chinese Wall enforced structurally.
          Test files materialize to disk (O) with @prunejuice-managed headers
          whose output-hash anchors against .prunejuice/artifacts/behaviour-contract.json.
Stage 2:  Builder receives Spec + ConcreteSpec + GeneratedTests, produces
          Implementation (Ca). Implementation files materialize to disk (O) with
          @prunejuice-managed headers whose output-hash anchors against
          .prunejuice/artifacts/concrete-spec.json.
Stage 3:  Saboteur receives Spec + Tests + Implementation, produces SaboteurReport
          (Ca), persisted to .prunejuice/artifacts/saboteur-report.json.
```

The three "Ca" artifacts (Tests, Implementation, SaboteurReport) are cache rather than coordination because they are derivable from the coordination artifacts by re-running the agents. Deleting them and re-running the pipeline produces equivalent outputs. They persist only so a crash mid-pipeline can resume without re-invoking expensive LLM calls.

### 5.1 Stage 0: The Archaeologist

The Archaeologist reads the abstract spec and produces two artifacts:

1. **ConcreteSpec**: Implementation strategy -- algorithm choices, type sketches, language-specific lowering notes, pseudocode. This is the "how" layer that the abstract spec's "what" layer doesn't specify. Persists to `.prunejuice/artifacts/concrete-spec.json`; the managed file hash chain for implementation files anchors against this artifact.

2. **BehaviourContract**: Machine-readable behavioural contract as a TypeScript interface containing given/when/then scenarios, preconditions, postconditions, and invariants. Persists to `.prunejuice/artifacts/behaviour-contract.json`; the managed file hash chain for test files anchors against this artifact. This is also the Chinese Wall artifact -- the only thing Mason sees (via the `MasonInput` TypeScript interface, which has exactly one field).

The Archaeologist also performs a discovery check: are there correctness requirements implied by the strategy that the abstract spec doesn't explicitly state? If so, they're surfaced as `discovered:` frontmatter entries and the pipeline pauses at Stage 0b. The human promotes them into the spec or dismisses them. The concrete spec is never a back-channel for ratifying constraints the human didn't approve.

### 5.2 Stage 1: The Mason

Mason receives a `BehaviourContract` via its `MasonInput` parameter -- a TypeScript interface with exactly one field. It produces a `GeneratedTests` object containing test code, file paths, and coverage targets.

Mason has no tool access. It is prompt-only: its entire context is the behaviour contract, the project's boundary configuration, and the test framework conventions. It cannot read the source code, the abstract spec, or the concrete spec -- not because a prompt tells it not to, but because there is no code path by which those artifacts reach it.

The tests import only the public API. There are no internal helpers, no private functions, no implementation details.

### 5.3 Stage 2: The Builder

The Builder receives the abstract spec, concrete spec, and Mason's tests via its `BuilderInput` parameter. It generates code, writes it to disk with a `@prunejuice-managed` header containing the hash chain, and runs the tests against the result.

If the tests pass, the generation is complete and the managed file is persisted. If the tests fail, the Builder can iterate (retry with error context) or the cycle can surface the failure to the convergence loop (Section 6).

Every write is atomic at the file level -- the hash chain header is written before the body, and the generated file replaces its target in a single operation. If generation is interrupted mid-cycle, the worst case is a file with an out-of-date hash chain, which the next freshness check will detect as `modified` or `conflict` and flag for manual review.

### 5.4 Stage 3: The Saboteur

After the Builder succeeds, the Saboteur runs as the final pipeline stage. It applies mutations to the generated code, runs the tests against each mutant, and classifies survivors:

- **equivalent**: The mutation doesn't change observable behaviour (dead code, redundant checks)
- **weak_test**: The tests should catch this but don't (imprecise assertions, missing edge cases)
- **spec_gap**: The spec doesn't constrain this behaviour (ambiguous or underspecified)

The Saboteur also checks constitutional compliance (does the generated code violate project-wide principles?) and probes for edge cases (adversarial inputs the spec didn't anticipate).

Results are returned as a `SaboteurReport` object. If convergence is enabled, survivors feed back into the convergence loop (Section 6). An audit copy of the report is optionally written to `.prunejuice/verification/<hash>.json` for later inspection.

### 5.5 Sprint Contracts

For re-generations (spec changed since last generate), a sprint contract adds a pre-generation handshake:

1. The **Architect** reads the spec diff and writes expected outcomes: what behaviours should change, what should remain invariant.
2. The **Saboteur** reads the expected outcomes and writes a verification strategy: which outcomes it can verify, which are partially verifiable, and which are **unverifiable** (with explicit explanation of why).

The `unverifiable-gaps` list is the contract's key contribution. It surfaces Goodhart's Law risk *before* the generation pass: "the Architect says timing should be invariant, but we have no clock mock in the test structure, so I can only verify retry count, not timing." Better to know this before generating than to discover it in a post-hoc mutation report.

Sprint contracts are persisted as `.contract.yaml` files on disk so they remain legible across sessions. The Saboteur reads them during verification and deletes them on success.

### 5.6 Saboteur Calibration

The Saboteur's mutation classifications are LLM judgments -- they can drift across runs. A project-local calibration file (`.unslop/saboteur-calibration.md`) provides few-shot examples of correct classifications and, more importantly, corrections of past misclassifications.

The examples are anchors, not rules. The Saboteur reads them as context for its classification decisions but can disagree if the current case is genuinely different. This avoids overfitting to past examples while reducing classification variance.

Correction examples are more valuable than confirmation examples. A single "you classified this as equivalent but it was actually a spec gap because..." teaches more than ten "yes, this was correctly equivalent."

## 6. The Convergence Loop

When the Saboteur's kill rate falls below 80%, the pipeline enters a convergence loop:

1. **Classify survivors**: Each surviving mutant is routed to the responsible agent
   - `weak_test` → Mason strengthens assertions
   - `spec_gap` → Architect enriches behaviour contract
   - `equivalent` → no action
2. **Re-run**: Updated tests + updated behaviour contract → re-mutation
3. **Entropy check**: If kill rate improved by less than 5%, the loop is stalling

Maximum 3 normal iterations. If entropy stalls, a radical spec hardening pass fires: the Architect rewrites the behaviour contract from scratch using the surviving mutant analysis as input. One shot. If that also stalls, the system commits what it has with a warning annotation.

This is not a "retry until it works" loop. Each iteration is targeted -- the surviving mutant classifications tell the system exactly what to fix and who should fix it. The entropy threshold prevents infinite loops where marginal improvements consume unbounded compute.

The kill rate is computed by the orchestrator from the Saboteur's mutant results. Crucially, the LLM's self-reported kill rate is *not* trusted -- every iteration recomputes the rate from ground truth (how many mutants the tests actually caught) rather than relying on the Saboteur's count. This avoids a Goodhart failure mode where the model learns to report optimistic numbers.

## 7. Where This Breaks Down

### 7.1 Parallel Fan-Out

A single spec can target multiple languages or multiple files via the `targets:` field in the concrete spec. This introduces a fan-out pattern: one Archaeologist, then N parallel Builders, then one fan-in gate (all N must pass).

The runtime orchestrator handles this via topological batch computation: specs at the same depth in the dependency graph run in parallel within a batch; the next batch only starts after the previous batch's results are reconciled. This works, but it adds coordination complexity that pure sequential pipelines don't have.

Collision detection is a related wart: if two concrete specs claim the same target file, that's a spec-level conflict that has to be resolved by human ratification (via a `preferSpec` option) before generation can proceed. Implicit resolution by build order would be non-deterministic, so the orchestrator refuses to guess. This is the right answer but it adds a friction point for multi-target workflows.

### 7.2 Context Anxiety

Long adversarial runs -- multiple convergence iterations, each involving multiple agent dispatches -- can hit context limits. The distinction between **compaction** (same agent, shortened history) and **handoff** (fresh agent, structured context) matters: compaction preserves whatever anxiety or confusion accumulated in the context, while handoff resets it.

The natural handoff boundary for adversarial runs is between convergence iterations. Writing a structured handoff artifact (current kill rate, surviving mutant classifications, spec state) and dispatching a fresh agent is more reliable than compacting a long context and hoping the important parts survive.

The runtime orchestrator makes this mechanical: at the start of every convergence iteration, a fresh agent is dispatched with a freshly-constructed context built from the spec artifacts plus the survivor analysis. Prior iteration context is not carried forward. The spec layer's runtime-statelessness is what makes this clean -- the orchestrator doesn't have to remember how the previous iteration reasoned, because the durable spec + the survivor report are sufficient to reconstruct it.

### 7.3 Harness Assumptions

Every component in the harness encodes an assumption about what the model can't do on its own:

- **Chinese Wall enforced structurally** assumes Mason will couple to implementation details if it sees source code
- **Intent lock** assumes specs will drift without tamper detection
- **Convergence loop** assumes single-pass generation misses edge cases
- **Runtime statelessness** assumes in-memory orchestration state is a liability, not an asset, because it creates a gap between what's in the model's context and what's on disk

These assumptions are worth stress-testing on each model improvement. Some may become unnecessary overhead as models get better -- the right response is to remove the scaffolding, not to keep it as ritual. The runtime-statelessness assumption is the one I'd stress-test first: it added significant engineering complexity (re-reading files on every cycle, type-checking artifacts at every boundary) and may be over-engineered for models with better context discipline.

## 8. Related Work

**Design by Contract** (Meyer, 1986): The intellectual ancestor. Eiffel's preconditions, postconditions, and invariants are the same idea as spec constraints -- but embedded in the implementation language, not externalised as a coordination artifact. The key difference: in design by contract, the contract and the code are written by the same agent. Here, they're written by different agents with different information access, and the contract must outlive any single generation cycle.

**Property-Based Testing** (Claessen & Hughes, 2000): QuickCheck and its descendants generate test inputs from properties. Mason generates test *cases* from behavioural constraints. The distinction: property-based testing validates a single implementation against abstract properties; the adversarial pipeline validates that two independent agents (Mason and Builder) agree on behaviour without sharing information.

**Formal Verification**: TLA+, Alloy, and model checkers verify that implementations satisfy formal specifications. The spec layer is less rigorous -- it's natural language parsed by LLMs, not formal logic checked by theorem provers. The trade-off is accessibility: any developer can write a behaviour spec; few can write TLA+. The mutation testing compensates for the lack of formal guarantees with empirical coverage.

**LLM Agent Frameworks** (AutoGen, CrewAI, LangGraph): These focus on runtime process coordination -- routing messages between agents, managing tool calls, handling failures. Prunejuice, the runtime orchestrator, does a similar job but with fewer features and stronger type constraints. The difference from those frameworks is not in the orchestration code but in the relationship between the orchestrator and the coordination state: prunejuice owns no coordination state of its own -- every cross-session claim about the module is stored in the coordination artifacts on disk, and prunejuice can be torn down and replaced without losing the module's history. The frameworks typically hold the coordination state themselves (workflow state, thread history, agent memory), which means the framework becomes the system.

**Agentic Coding Harnesses** (SWE-bench, OpenHands, Devin): Evaluation frameworks for coding agents. They measure whether an agent can solve a task end-to-end. The spec layer is orthogonal -- it's not about whether a single agent can solve a task, but about how the task's intent is preserved across multiple agents and multiple generations.

## 9. Conclusion

I didn't set out to build a formal verification pipeline, and I didn't set out to build an orchestrator. I set out to stop my AI from producing slop. The spec was a workaround for the model forgetting what it was supposed to do between sessions. The Chinese Wall was a workaround for tests that passed because they tested the wrong thing. The mutation testing was a workaround for not being able to tell whether the tests were actually good. Each layer was added because the previous layer wasn't enough.

The first working version coordinated everything through the filesystem -- markdown commands invoking Python scripts that read and wrote files. I mistook the filesystem for the coordination mechanism because it was the only thing visible. When I extracted the runtime orchestration into a typed TypeScript library, I expected to discover that the filesystem was load-bearing and the library was just a convenience layer. What I actually discovered was subtler: the filesystem was still load-bearing, but it was doing two different jobs that the original architecture had conflated into one.

The first job was **coordination** -- persisting the spec, concrete spec, and behaviour contract so that the managed file hash chains have something to anchor against, and so that the system's claims about a module survive across sessions. The second job was **resumability caching** -- persisting intermediate agent outputs (tests, implementation, saboteur report) so that a crashed pipeline can resume without re-running expensive LLM calls. In the original architecture, both kinds of file lived in the same directory with no indication of which was which. Pulling the runtime into TypeScript didn't eliminate the files; it made the distinction between them explicit.

What was actually load-bearing for coordination was a small set of artifacts: the abstract spec, the concrete spec, the behaviour contract, and the managed file headers that link generated code back to them via hash chains. These are the coordination mechanism. The rest of the on-disk state is a cache -- still important for operations, but conceptually disposable: delete it and the system rebuilds it from the coordination artifacts by re-running the pipeline.

The result is a layered architecture with three categories of durable state. The coordination layer (spec + concrete spec + behaviour contract + managed file headers) is the source of truth. The cache layer (tests, implementation, saboteur report) is memoized agent output. The output layer is the generated code itself. Prunejuice, the runtime library, holds nothing in memory across sessions -- it is a pure function of the coordination layer and whatever inputs it receives during a run.

The empirical validation is modest -- one stress test, one module, 70 tests, 20 mutations. But the structural result is strong: two agents with no shared information except the spec artifacts independently produced compatible work. The Builder's code passed Mason's tests, and Mason never saw the code. That's not a fluke of the specific module or the specific model. That's a property of the architecture.

The spec is the source of truth. The code is a disposable artifact derived from it. The runtime orchestrator is a disposable artifact derived from the spec's implied coordination protocol. And the coordination artifact -- the thing that makes all of this work across sessions, across agents, across regenerations -- is just a markdown file with frontmatter.

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
extends: null                            # single-parent inheritance, max depth 3
targets: []                              # optional multi-target override
---

## Strategy
[Algorithm and decomposition choices]

## Type Sketch
[Function signatures and data structures]

## Representation Invariants
[Internal consistency rules]

## Safety Contracts
[Error handling guarantees]

## Pattern
[Cross-cutting patterns, overridable by children]

## Lowering Notes
[Language-specific implementation guidance, additive across children]
```

### Managed File Header

```python
# @prunejuice-managed -- Edit hashing.py.spec.md instead
# spec-hash:8e43c7b51522 output-hash:0086857549bd generated:2026-03-28T00:00:00Z
```

For concrete specs with dependencies, an additional `concrete-manifest` line stores per-dependency hashes:

```python
# @prunejuice-managed -- Edit hashing.py.spec.md instead
# spec-hash:8e43c7b51522 output-hash:0086857549bd generated:2026-03-28T00:00:00Z
# concrete-manifest:src/utils.impl.md:a3f8c2e9b7d1,shared/base.impl.md:7f2e1b8a9c04
```

### Verification Result (`.prunejuice/verification/<hash>.json`)

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
**Tests generated by Mason:** 70 (from `BehaviourContract`, Chinese Wall)
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

- **unslop plugin:** v0.54.0
- **Runtime orchestrator:** prunejuice (TypeScript MCP server)
- **Commands:** 20
- **Skills:** 6 (domain reference) + project-local domain skills
- **Agents:** 5 (Architect, Archaeologist, Mason, Builder, Saboteur)
- **Prunejuice tests:** 316 (vitest)
- **Stress tests:** 70
- **Frontmatter fields parsed:** ~16 (abstract spec) + ~8 (concrete spec)
- **Freshness states:** 8
- **Runtime language:** TypeScript 6 / Node 20
- **Platform:** Claude Code CLI plugin (markdown commands + TypeScript MCP orchestrator)

## Appendix E: What Changed Between the Original Paper and This Revision

The original March 2026 paper described a Python-based orchestrator that coordinated agents through shell scripts invoking markdown commands, with all inter-agent state passed through the filesystem. That architecture was real and worked, but it conflated three different concerns: *runtime orchestration* (how agents hand off artifacts within a single pipeline run), *durable coordination* (the subset of on-disk state that encodes human intent and anchors hash chains), and *resumability caching* (the subset of on-disk state that exists only to let a crashed pipeline resume). In the original architecture, all three lived in the same directory with no indication of which was which.

Between March and April 2026, the runtime layer was extracted into a typed TypeScript library (prunejuice) with explicit interface boundaries. The migration happened across three phases:

- **Phase 6:** Ripple correctness foundation (concrete deps hashing, ghost staleness diagnostics)
- **Phase 7:** Inheritance flattening and multi-target collision detection
- **Phase 8:** Python retirement and skill restructuring

What didn't change: the spec schema, the hash chain, the Chinese Wall, the convergence loop, the empirical stress-test results. What did change: the paper's framing. The original paper claimed "no orchestrator" to emphasize that agents didn't share runtime state through a framework. That was misleading -- there was always orchestration, it was just embedded in markdown prompts that invoked Python scripts, which gave the appearance of statelessness because the prompts themselves were stateless between invocations. The extraction made the orchestration layer explicit and forced an honest accounting of what was actually load-bearing.

The insight that survived the migration: the spec is the coordinator because it's the artifact the rest of the system anchors against. Not the only file that persists -- the resumability cache also persists -- but the only file whose persistence is *semantically required*. Delete the cache and re-run the pipeline, you get equivalent results. Delete the coordination artifacts and the hash chains break; the system has no durable record of what the code was supposed to be. The Python scripts, the filesystem handoffs, the YAML files, the typed TS interfaces -- all are implementations of a coordination protocol whose ground truth lives in the spec. The implementation can change (and did, several times). The spec is what makes the system coherent across generations.
