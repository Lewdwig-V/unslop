# CodeSpeak Gap Analysis & Roadmap

> How closely does unslop match CodeSpeak's output quality, where does it fall short, and what's the concrete path to closing those gaps?

---

## What CodeSpeak Is

CodeSpeak (codespeak.dev, v0.3.4, March 2026) is a spec-driven development tool by Andrey Breslav (Kotlin creator). Its philosophy is identical to unslop's: specs are the source of truth, code is derived. Key mechanics:

- Specs live in `.cs.md` files, written in plain structured Markdown
- `codespeak build` sends spec + existing code to Claude and applies incremental diffs
- `codespeak takeover <file>` extracts a spec from existing code and registers the file
- A "compiler" layer semantically checks specs for ambiguity before generation
- Code Change Requests (a `change-request.cs.md` file) handle surgical fixes too granular for spec edits
- Specs can import each other (v0.3.4); build order is resolved automatically
- GitHub Actions integration: edit spec in the GitHub UI → auto-build → generated code committed
- BYOK: uses Anthropic Claude API directly; model is configurable

---

## Capability Comparison

### Where unslop matches or exceeds CodeSpeak

| Capability | CodeSpeak | unslop | Notes |
|---|---|---|---|
| Spec format | `.cs.md` Markdown | `.spec.md` Markdown | Equivalent. unslop's vocabulary guide is more explicit. |
| Takeover pipeline | `codespeak takeover <file>` | `/unslop:takeover` | unslop's is richer: user approval gate, archive safety net |
| Convergence loop | None | 3-iteration spec enrichment loop | Significant unslop advantage |
| "No peeking" discipline | Incremental (reads existing code) | Full regeneration from spec alone | Philosophical difference — see Quality section |
| Test-driven validation | Tests run post-build | Tests run; convergence loop if red | unslop's loop is structurally enforced, not just hoped for |
| Multi-file support | Spec imports (v0.3.4) | `depends-on` frontmatter + orchestrator | Equivalent capability, different mechanics |
| Context persistence | None visible | Alignment summary + session hooks | unslop advantage |
| User approval gate | None (auto-generates) | Required before any takeover proceeds | unslop advantage for quality control |
| Self-improvement loop | None | `feedback.md` captured by hooks | Minor unslop advantage |
| Archive/safety net | None | `.unslop/archive/` | unslop advantage |

### Where CodeSpeak is ahead

| Capability | CodeSpeak | unslop | Impact |
|---|---|---|---|
| **Ambiguity detection** | Compiler checks specs, asks for clarification | None — model interprets silently | **High** — ambiguous specs silently produce wrong code |
| **Reproducibility** | Incremental diffs; bulk of code unchanged across rebuilds | Full regeneration; output varies run-to-run | **High** — unslop outputs are not reproducible |
| **Deterministic tooling** | `codespeak build` is a CLI with defined inputs/outputs | Generation is entirely prompt-driven | **High** — "no peeking" rule enforced only by prompt |
| **Code Change Requests** | `change-request.cs.md` for surgical patches | None — everything must go through spec edits | **Medium** — sometimes you need a targeted fix, not a spec rewrite |
| **CI/CD integration** | GitHub Actions workflow, generates code as commits | None (planned Phase 4) | **Medium** — blocks adoption in team/CI contexts |
| **Content-based staleness** | Implied by incremental approach | mtime comparison (fragile after git ops); proposed dual-hash fix must preserve modified-file detection | **Medium** — git checkouts, copies, and rebases break mtime |
| **Machine-readable config** | `codespeak.json` with structured fields | Freeform `.unslop/config.md` | **Low-Medium** — scripts must parse prose or rely on model |
| **Pre-build validation** | Config validation, API balance check | None | **Low** — fails mid-run instead of early |
| **Test generation** | Build pipeline generates and fixes tests | Assumes tests exist; convergence requires them | **Low** — unslop warns if tests missing, CodeSpeak creates them |
| **Pre-commit guard** | Not seen | Planned (Phase 3) | **Low** — both lack this |

---

## Quality: How Close Is unslop's Output to CodeSpeak's?

### Strengths of unslop's approach

**Spec fidelity is higher.** Full regeneration from spec alone means the generated code *truly reflects the spec* with no residue from a previous implementation. CodeSpeak's incremental approach is conservative but means old code can survive spec changes that should have replaced it. If the spec changes substantially, unslop's output is purer.

**Test grounding is structurally enforced.** unslop's convergence loop makes the spec prove itself against tests. CodeSpeak runs tests post-build but has no loop — if tests fail, you fix the code manually or edit the spec and rebuild. unslop's loop surfaces exactly which semantic constraint was missing from the spec, which CodeSpeak leaves entirely to the developer to figure out.

**The approval gate prevents bad specs from propagating.** CodeSpeak's takeover auto-generates a spec and immediately starts managing the file. unslop requires the user to confirm the spec before archiving the original. This catches spec drafting errors before they destroy information.

### Weaknesses of unslop's approach

**Ambiguous specs fail silently.** This is the largest quality gap. When a spec can be interpreted two ways, CodeSpeak asks. unslop generates — and the model picks an interpretation, possibly the wrong one, without flagging it. The user won't notice until tests fail or, worse, until the code behaves unexpectedly in production.

**The "no peeking" rule is enforced only by prompt.** The generation skill says not to read the archived original. A distracted model, a mid-context-window instruction, or a future model with different defaults can violate this silently. CodeSpeak's incremental approach makes "no peeking" structurally impossible to violate because the input is always the spec + the existing generated file.

**Regenerated output is not reproducible.** Running `/unslop:generate` twice on an unchanged spec can produce two different implementations. Both might pass tests. But they differ — different variable names, different internal structure, different edge case handling. This is unsettling in production and breaks the premise that "the spec determines the code." CodeSpeak's incremental approach produces nearly identical output on re-runs because only spec diffs are applied.

**No surgical repair path.** When a managed file needs a targeted fix — a performance patch, a one-line correctness fix, a third-party API call that changed — unslop forces you to either edit the spec (which then regenerates everything) or manually edit the managed file (which breaks the invariant). CodeSpeak's Change Request mechanism handles exactly this case.

**mtime staleness is fragile.** `git checkout`, file copies, CI runners that clone fresh, and timezone differences all corrupt mtime-based staleness detection. A file can appear fresh when it isn't, or stale when it is.

### Net quality assessment

For straightforward adapter/glue code with good test coverage, unslop produces **comparable quality** to CodeSpeak. The convergence loop and approval gate are genuine advantages that CodeSpeak lacks.

For complex specs, ambiguous requirements, or code that needs surgical fixes between regenerations, CodeSpeak's output is **meaningfully more reliable**. The ambiguity detection and incremental approach catch failure modes that unslop only discovers at test time — if at all.

---

## Roadmap to Close the Gaps

Ordered by impact vs. implementation cost.

---

### Gap 1: Ambiguity Detection (High Impact, Medium Cost)

**Problem:** Ambiguous specs silently produce wrong or inconsistent code.

**Solution:** A pre-generation spec linter implemented as a skill + hook.

**Mechanism:** Before any generation step (generate, sync, takeover), invoke the spec-language skill in "review mode" with the following prompt:

> "Review this spec for ambiguity. List any aspect that could be interpreted in two or more substantially different ways — places where a reasonable implementer might make opposite choices and both seem consistent with the spec text. Be specific: quote the ambiguous phrase and describe the two interpretations. If you find no significant ambiguities, say so explicitly."

If ambiguities are found, surface them to the user before generating. Require explicit resolution (edit the spec and re-run) or explicit override (`--force-ambiguous`).

**What's needed:**
- Add a "Spec Review" section to the `spec-language` skill with review-mode instructions and worked examples of ambiguous vs. unambiguous spec text
- Add a pre-generation check step to the `generation` skill that calls the review before writing any code
- Consider a `/unslop:lint <spec>` command for on-demand use

**Quality improvement:** Catches the largest class of silent failures before they produce wrong code. This is the single highest-leverage change.

---

### Gap 2: Content-Based Staleness (High Impact, Low Cost)

**Problem:** mtime is fragile. Git operations, CI runners, and file copies silently corrupt staleness detection.

**Solution:** Store a **dual hash** in the managed file header: one for the spec content (detects staleness) and one for the generated output (detects direct edits).

**Why dual hash is required:** A spec-hash-only scheme collapses the "modified" state into "fresh." If someone hotfixes a managed file, the spec hash in the header still matches the current spec, so a naive check reports "fresh" on drifted code. This silently removes the modified-file safeguard currently enforced by `status.md:34-39` and violates the invariant documented in `README.md:145` that direct edits must be treated as out-of-band.

**New header format:**
```python
# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9... output-hash:b7d1e4f3... generated:2026-03-22T14:32:00Z
```

The `spec-hash` is the SHA-256 of the spec file content at generation time. The `output-hash` is the SHA-256 of the managed file content *below the header* at generation time. The timestamp is retained for human readability and relative-time display in status output.

**Three-state staleness check:**
1. Hash the current spec content. Compare to `spec-hash` in header.
2. Hash the current managed file content below the header. Compare to `output-hash` in header.
3. Classify:
   - **Fresh**: spec hash matches AND output hash matches
   - **Stale**: spec hash does NOT match (spec was edited; doesn't matter whether output was also edited)
   - **Modified**: spec hash matches but output hash does NOT match (managed file was edited directly while spec is unchanged)

This preserves all three states from the current mtime scheme while eliminating mtime fragility. The "modified" detection is strictly stronger: mtime can miss edits that restore the original mtime (e.g., `touch -r`), but content hashing catches any byte-level change.

**Edge case — stale AND modified:** If the spec changed AND the managed file was also edited directly, classify as `stale (modified)`. The status display should warn that regenerating will overwrite direct edits. The generate command should require `--force` or user confirmation in this case.

**What's needed:**
- Update the `generation` skill header format to write both hashes
- Update the `status` command to compare dual hashes instead of mtime
- Update the `generate` and `sync` commands to check output-hash before overwriting (warn on modified files)
- Add hash computation to the orchestrator or a helper in `hooks/scripts/`
- The generation skill must compute the output hash *after* writing the file body but *before* finalizing the header — or write the header with a placeholder, hash the body, then patch the header

**What's unchanged:** The orchestrator's dependency logic is unaffected — it can use either hash or mtime for transitive staleness; hash is strictly more reliable.

---

### Gap 3: Generation Reproducibility via Spec Pinning (High Impact, Medium Cost)

**Problem:** Identical specs produce different code on re-runs. Not a correctness problem (tests pass) but a reliability and trust problem.

**Solution:** Two complementary approaches:

**3a. Explicit generation constraints in the generation skill.** Add a section emphasizing: generate the minimal idiomatic implementation. Prefer the simplest approach that satisfies the spec. Do not vary structure across regenerations. This reduces variance within a single session.

**3b. Spec completeness scoring.** After the convergence loop completes, score the spec for completeness: "Does this spec, as written, leave significant implementation choices open that should instead be constrained?" If yes, suggest additions. A spec that leaves fewer open choices produces more consistent code across runs.

**What's needed:**
- Skill update to `generation` with reproducibility-focused generation guidelines
- A "completeness review" prompt in the takeover skill, run after successful convergence
- Possibly a `/unslop:harden <spec>` command that reviews a passing spec and suggests tightening

---

### Gap 4: Code Change Requests (Medium Impact, Low Cost)

**Problem:** Sometimes a managed file needs a targeted fix that doesn't warrant a spec rewrite — a performance patch, a changed API call, a discovered edge case. Currently unslop has no path for this that doesn't break the spec-as-source-of-truth invariant.

**Solution:** A `/unslop:change <file> "<description>"` command and associated `*.change.md` sidecar files.

**Workflow:**
1. User runs `/unslop:change src/retry.py "change backoff base from 2 to 1.5 per ops request"`
2. Command creates `src/retry.py.change.md` with the description and timestamp
3. The model applies the change as a surgical edit to the managed file (permitted exception to the "do not edit managed files" rule)
4. If the change affects observable behavior, the model also proposes a spec update
5. Both files are committed together

**Invariant preservation:** The change file is a log of intentional deviations that must survive regeneration. This requires that **every regeneration entry point** — not just sync — consumes change-request state before writing output.

**Why this matters:** `/unslop:generate` is the primary bulk regeneration path (README.md:74-78). A user lands a change request, then later regenerates because the spec changed or an upstream dependency was rebuilt. If generate rewrites the managed file from the spec alone without reading the sidecar, the approved fix vanishes silently. The "changes are not lost" invariant holds only if all paths that produce managed files read the same change-request state.

**Change-request lifecycle:**

1. **Creation:** `/unslop:change` writes the sidecar and applies the surgical edit.
2. **Pending state:** The `.change.md` file exists alongside the managed file. `status` flags it.
3. **Absorption:** On any regeneration (generate, sync, or dependency-triggered rebuild), the generation skill reads all `*.change.md` sidecars for the target file, folds their intent into the generation context alongside the spec, and produces output that incorporates both the spec and the change requests.
4. **Promotion:** After successful regeneration, the generation skill proposes a spec update that captures the change request's intent permanently. If the user accepts, the `.change.md` file is deleted — the change is now part of the spec. If the user declines, the sidecar is retained and continues to be read on future regenerations.
5. **Conflict:** If a spec edit contradicts a pending change request (e.g., spec says "backoff base is 2", change request says "change to 1.5"), the generation skill flags the conflict and asks the user to resolve before proceeding.

**Implementation:** The change-request consumption logic lives in the `generation` skill itself — not in individual commands. Since generate, sync, and dependency rebuilds all invoke the generation skill to produce output, a single integration point covers all entry paths. Individual commands do not need separate change-request handling.

**What's needed:**
- New command: `commands/change.md`
- Update `generation` skill to read `*.change.md` sidecars for every managed file before generating — this is the single integration point that covers generate, sync, and dependency rebuilds
- Update `status` to flag files with pending change requests and show whether they've been promoted to the spec
- Add a `## Change Requests` context section to the generation skill instructions: "Before generating, check for `<managed-file>.change.md` sidecars. If present, read them and treat their described intent as additional constraints alongside the spec. After generation, propose a spec edit that captures each change request permanently."

---

### Gap 5: Pre-Generation Spec Validation (Medium Impact, Low Cost)

**Problem:** No pre-flight check catches obviously insufficient specs before wasting a generation cycle.

**Solution (original, flawed):** ~~A PostToolUse hook on spec file edits.~~ A PostToolUse hook only fires when Claude performs a Write/Edit inside the current session. It does not fire when a user runs `/unslop:generate` on a spec pulled from git, edits the spec in an external editor, or retries generation on a previously failing spec. In those common paths — which are the *majority* of generation triggers — the hook never runs, so the wasted cycle it's trying to prevent still happens.

**Corrected solution:** Spec validation runs inside the generation skill itself, as a pre-generation gate — the same pattern used for change-request consumption (Gap 4) and ambiguity detection (Gap 1). Since generate, sync, and takeover all flow through the generation skill before writing code, a single validation step there covers every entry path.

**Validation checks (fast, no LLM call needed):**
- Does the spec have at least one Behavior or Constraints section?
- Is it longer than 3 lines? (catches accidental empty saves or placeholder specs)
- Does it contain obviously over-specified content? Heuristic: code fences with non-example content, or lines that look like pseudocode rather than behavioral descriptions.

**What happens on failure:** Validation failures block generation and surface the specific issue to the user. The generation skill stops before any code is written and reports what needs to change. No `--force` override — a spec that fails these basic checks will produce bad code regardless.

**Optional editor-time warning (supplement, not replacement):** A PostToolUse hook on `*.spec.md` edits can *additionally* surface warnings at edit time as a convenience — catching problems earlier in the workflow. But this is a UX polish layer, not the validation gate. The gate lives in the generation skill.

**What's needed:**
- Add a "Spec Validation" section to the `generation` skill instructions, before the code generation step: "Before generating code, validate the spec. If it has fewer than 3 non-blank lines, has no Behavior/Constraints/Requirements section, or contains code fences that are not explicitly marked as examples, stop and report the issue. Do not generate."
- Optionally, a `hooks/scripts/validate-spec.sh` for edit-time warnings (same checks, `systemMessage` output) — but this is supplementary

---

### Gap 6: CI Integration (Medium Impact, High Cost)

**Problem:** No CI/CD path. Teams can't enforce that all managed files are fresh or that stale specs are caught before merge.

**Solution:** A GitHub Actions workflow template generated by `/unslop:init`.

**`unslop-ci.yml` generated at init:**
```yaml
name: unslop
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check for stale managed files
        run: python unslop/scripts/orchestrator.py build-order . | ...
      - name: Verify tests pass
        run: <test command from config.md>
```

In the short term: a simpler approach is a `pre-push` git hook (generated by `/unslop:init`) that runs `python orchestrator.py build-order .` and warns if any managed files are stale.

**What's needed:**
- Update `init` command to generate a pre-push hook
- Add a `scripts/ci-check.sh` that queries build order and staleness
- Later: GitHub Actions workflow template in `scripts/`

---

### Gap 7: Machine-Readable Configuration (Low Impact, Low Cost)

**Problem:** `config.md` is prose. Scripts must parse it with fragile regex or rely on the model to read it. Structured config enables reliable tooling.

**Solution:** Keep `config.md` for human readability but add a `config.json` sidecar that scripts use.

**`config.json` schema:**
```json
{
  "test_command": "pytest",
  "exclude_patterns": [".mypy_cache", "generated/"],
  "managed_extensions": [".py", ".ts", ".go"]
}
```

`config.md` remains the edit surface; the init and config-update commands write both files. Scripts always read `config.json`; the model always reads `config.md`.

**What's needed:**
- Update `init` command to write `config.json` alongside `config.md`
- Update orchestrator to read `config.json` for exclude patterns
- Update hooks scripts to read `config.json` for the test command (currently parsed from prose)

---

### Gap 8: Domain Skills (Medium Impact, High Cost, High Leverage)

**Problem:** Generic spec writing + generation produces code with high variance for common patterns. A FastAPI route handler, a React component, a Terraform module all have well-known shapes that the model should default to.

**Solution:** Domain skills in `unslop/domain/` providing:
- Few-shot spec examples for the pattern
- Generation priors (what framework constructs to reach for)
- Test scaffolding for the pattern

**Priority domains:** FastAPI, React, SQLAlchemy models, Terraform resources, dbt models, CLI commands.

**What's needed:**
- `unslop/domain/<name>/SKILL.md` for each domain
- `unslop:init` asks what domains the project uses and loads the relevant skills into `config.md`
- The `generation` skill references domain skills when the spec content suggests a pattern match

Domain skills are the highest-leverage single contribution to generation quality because they reduce variance for the exact code that benefits most from unslop management.

---

## Summary: What to Build and in What Order

| # | Change | Type | Closes Which Gap | Relative Effort |
|---|---|---|---|---|
| 1 | Spec ambiguity linter | Skill update + pre-gen check | Silent wrong code from ambiguous specs | Low |
| 2 | Dual-hash staleness (spec + output) | Header format + script | Fragile mtime detection + preserves modified-file detection | Low |
| 3 | Spec completeness review post-convergence | Skill update | Reproducibility | Low |
| 4 | Pre-generation spec validation | Generation skill gate | Insufficient specs wasting generation cycles | Low |
| 5 | Code Change Requests | New command + skill update | Surgical fixes without breaking invariant | Medium |
| 6 | Machine-readable config | Init update + `config.json` | Tooling reliability | Low |
| 7 | Pre-push staleness check | Hook script | CI gap (lightweight) | Low |
| 8 | Domain skills (FastAPI, React, etc.) | New skills | Generation variance for common patterns | High, ongoing |
| 9 | GitHub Actions template | Template + init update | CI/CD integration | Medium |
| 10 | `/unslop:harden` command | New command | Reproducibility across re-runs | Medium |

Items 1–4 and 6–7 are low-effort, high-impact, and can be done without touching the core pipeline. Items 5, 8–10 are medium-effort projects. All are achievable within the existing plugin architecture — no MCP server is needed for any of them.

---

## On the MCP Server Question

The current architecture — skills + hooks + orchestrator script — is sufficient for all gaps identified above. The question to ask before adding an MCP server is: **is there persistent state that the model needs to query across tool calls that can't be expressed as files on disk?**

Currently: no. The alignment summary, config, and spec files carry all the state the model needs. The orchestrator handles the structural computation (dependency graph, topological sort) as a pure function.

An MCP server becomes worth adding when:
- Cross-file staleness tracking needs to be fast (scanning 1000+ files on every tool call is too slow for a script)
- Real-time spec validation during editing is wanted (a language server protocol integration)
- Team-mode state is needed (who is editing which spec, distributed lock management)

None of these are current blockers. Defer the MCP server to Phase 4.
