---
name: generation
description: Use when generating or regenerating code from unslop spec files. Activates during /unslop:generate, /unslop:sync, and the generation step of /unslop:takeover.
version: 0.1.0
---

# Generation Skill

You are generating a managed source file from an unslop spec. These instructions are authoritative. Follow them exactly.

---

## 0. Pre-Generation Validation

Before generating any code, validate the spec. This section runs first — if validation fails, no code is written.

### Phase 0a: Structural Validation

Call the structural validator script:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_spec.py <spec-path>
```

Read the JSON output:
- **`"status": "pass"`** — proceed to Phase 0b.
- **`"status": "warn"`** — surface warnings to the user, then proceed to Phase 0b.
- **`"status": "fail"`** — **stop immediately.** Report the issues to the user. Do not generate code. Tell them: "Spec failed structural validation. Fix the issues above and re-run."

There is no override for structural validation failures.

### Phase 0b: Ambiguity Detection

After structural validation passes, review the spec for semantic ambiguity.

**Before reviewing**, scan the spec for Open Question exemptions:
1. Collect all lines containing `[open]` — these phrases are exempt
2. Collect all items listed under a `## Open Questions` section — these topics are exempt

Before running ambiguity detection, check if `.unslop/principles.md` exists. If it does, read it and use it as additional context:

1. **Principle conflict check**: If the spec directly contradicts a principle (e.g., spec says "use module-level mutable state" but principles say "no global mutable state"), **stop generation** and report the conflict. Tell the user: "Spec contradicts project principle: [quote spec] vs [quote principle]. Edit the spec to comply with principles, or update principles if the constraint no longer applies."

2. **Ambiguity resolution**: A spec phrase that would be ambiguous without principles may be unambiguous with them (e.g., "handle errors" is ambiguous alone, but if principles say "errors must be typed", the ambiguity is resolved). Use principles to narrow the interpretation space.

**Then review the spec** with this focus:

> Review this spec for semantic ambiguity — places where a reasonable implementer could make two substantively different choices that both satisfy the spec text. Be specific: quote the ambiguous phrase and describe the two interpretations.
>
> Do NOT flag:
> - Implementation choices left deliberately open (data structures, algorithms, variable names) — these are correctly vague
> - Items marked with `[open]` inline
> - Items listed in the `## Open Questions` section
> - Topics that overlap with Open Questions items (match by topic, not exact string)
>
> DO flag:
> - Behavioral ambiguity: "retries on failure" — what counts as failure?
> - Constraint ambiguity: "handles large inputs" — what is large? No bound specified.
> - Contract ambiguity: "returns an error" — what kind? Exception? Error code? None/null?

**Result handling:**

- **No ambiguities found:** Report "Spec passed ambiguity review." Proceed to Section 1.
- **Ambiguities found, all covered by Open Questions:** Report "Spec has N open questions acknowledged. Proceeding." Proceed to Section 1.
- **Ambiguities found, some NOT covered:**
  - If `--force-ambiguous` was passed: report ambiguities as warnings, proceed to Section 1.
  - Otherwise: **stop generation.** Report each uncovered ambiguity with the quoted phrase and two interpretations. Tell the user:

> "Found N ambiguities not marked as open questions. Either:
> 1. Resolve them by editing the spec to be more specific
> 2. Mark them as intentionally open with `[open]` or add to `## Open Questions`
> 3. Override with `--force-ambiguous` (not recommended)"

---

### Phase 0c: Change Request Consumption

After validation passes, check for a `*.change.md` sidecar file for the target managed file (same directory, same base name with `.change.md` extension).

If no change file exists, skip to Phase 0d.

If change entries exist:

**1. Conflict detection (model-driven):** Before processing, review each entry's intent against the current spec. If any entry contradicts the spec (e.g., spec says "backoff base is 2", entry says "change to 1.5"), surface the conflict to the user:

> "Change request conflicts with current spec: [quote entry] vs [quote spec]. Resolve by editing the spec or the change entry before proceeding."

Stop generation until the conflict is resolved.

**2. Classify and order entries:**
- Process `[pending]` entries first (they update the spec)
- Then `[tactical]` entries (they patch code and propose spec updates)

**3. For each `[pending]` entry:**
- Propose a spec update that captures the entry's intent
- Present to the user: "This change request suggests updating the spec as follows: [diff]. Approve?"
- On approval: apply the spec update, then generate code from the updated spec
- On rejection: skip this entry, leave it in change.md

**4. For each `[tactical]` entry:**
- Patch the managed file via incremental mode (Mode B) based on the entry's intent
- Run tests
- If green: propose a spec update reflecting the code change
- Present to user: "I've patched the code and updated the spec to match. Review?"
- On approval: entry is promoted
- On rejection: revert code change, entry stays

**5. After processing:**
- Delete each successfully promoted entry from the change.md file
- If the file is now empty (no remaining entries), delete it entirely
- Compute final output-hash from the managed file body
- Each promoted entry is committed individually (sequential, not atomic)

---

### Phase 0d: Domain Skill Loading

After change request consumption, check for framework-specific domain skills to load as additional generation context.

**1. Check for explicit framework list:**
Read `.unslop/config.json`. If it has a `frameworks` field (e.g., `["fastapi", "sqlalchemy"]`), use that list.

**2. If no explicit list, auto-detect:**
Read any test files for the target module, and the existing managed source file (if it exists). Also scan the spec content for framework references (e.g., mentions of 'FastAPI', 'SQLAlchemy'). Identify framework imports:
- `from fastapi import` or `import fastapi` -- load `unslop/domain/fastapi`
- `from sqlalchemy import` or `import sqlalchemy` -- load `unslop/domain/sqlalchemy`
- `import React` or `from 'react'` -- load `unslop/domain/react`
- Other frameworks: check if a matching `unslop/domain/<name>/SKILL.md` exists

**3. Load matching skills:**
For each detected framework, read the corresponding `unslop/domain/<framework>/SKILL.md` as additional generation context. These skills provide framework-specific conventions, patterns, and constraints.

**4. Context priority:**
Domain skills are additive -- they augment the generation skill, not replace it. Priority order:
- Project Principles (highest -- non-negotiable)
- File Spec (file-specific requirements)
- Domain Skills (framework conventions -- defaults that the spec can override)
- Generation Skill defaults (lowest)

If no domain skills match, this phase is a no-op. Proceed to Section 1.

---

## 1. Generation Mode Selection

Generation operates in one of two modes. **The controlling agent or command selects the mode.** If no mode is specified, default to **full regeneration**.

### Mode A: Full Regeneration (default)

You MUST generate code from the spec file alone. Do not read the existing generated file — it is about to be overwritten. Do not read archived originals. The spec is the single source of truth.

This is not a stylistic preference. Reading the current generated file introduces anchoring bias: you will unconsciously reproduce its implementation choices rather than deriving fresh, idiomatic code from the spec's intent. The validation loop exists precisely to catch what the spec missed — that signal is destroyed if you peek at the previous output.

This rule was established after analyzing generation failures across multiple projects. Every case where the model read the existing file produced anchoring bias that degraded output quality. The rule is non-negotiable -- it has been validated by every successful takeover in unslop's history.

**Permitted reads:**
- The spec file
- The test file(s) for the target module
- `.unslop/config.json` or `.unslop/config.md` (for test command and project conventions)
- `.unslop/principles.md` (project-wide generation constraints, if it exists)
- Language/framework documentation as needed

**Prohibited reads:**
- The current generated source file
- `.unslop/archive/` (original pre-takeover files)

**When to use:** Takeover, major spec rewrites, periodic "defrag" regeneration (`/unslop:generate --force`), or whenever the controlling agent suspects accumulated implementation drift.

### Mode B: Incremental Generation

You read the spec, the current generated file, and an optional change description. You produce a **targeted diff** — the minimal set of edits that brings the generated file into conformance with the updated spec (or applies the described change).

**Permitted reads:**
- The spec file
- The current generated source file
- The test file(s) for the target module
- `.unslop/config.json` or `.unslop/config.md` (legacy fallback)
- `*.change.md` sidecars (if any)
- `.unslop/principles.md` (project-wide generation constraints, if it exists)
- Language/framework documentation as needed

**Prohibited reads:**
- `.unslop/archive/` (original pre-takeover files)

**Discipline in incremental mode:**
- Change only what the spec delta or change description requires. Do not reformat, rename, or restructure code that is unrelated to the change.
- Do not "improve" surrounding code. Gratuitous churn is a defect, not a feature.
- If the change description is ambiguous about scope, default to the narrower interpretation.
- Update the `@unslop-managed` header with new `output-hash`, `spec-hash`, and timestamp after applying edits. Re-hash the full body content for the output-hash.
- You have already committed to incremental mode by reading the existing file. Honor that commitment -- change only what the spec delta requires. Expanding scope mid-generation is the single most common cause of incremental mode failures.

**When to use:** Small spec amendments, added constraints, absorbed change requests, bug fixes discovered during convergence — any case where the scope of the spec change is well-understood and localized.

### Drift management

Incremental mode accumulates implementation drift over many small changes. The controlling agent should periodically trigger a full regeneration to reset drift — analogous to a compaction or defrag. Signs that a full regen is warranted:

- The file has been incrementally updated more than ~5 times since its last full regen
- Test failures suggest the implementation has drifted from spec intent in ways that aren't covered by the change history
- The controlling agent or user explicitly requests it (`--force` flag on generate/sync)

---

## 2. Write the @unslop-managed Header

Every generated file MUST begin with a two-line header using the correct comment syntax for the file's extension.

**Line 1:** `@unslop-managed — do not edit directly. Edit <spec-path> instead.`
**Line 2:** `spec-hash:<12hex> output-hash:<12hex> generated:<ISO8601>`

Use UTC for the timestamp. Format: `2026-03-20T14:32:00Z`

### Comment Syntax by Extension

| Extension | Comment syntax |
|---|---|
| `.py`, `.rb`, `.sh`, `.yaml`, `.yml` | `#` |
| `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.swift`, `.kt` | `//` |
| `.html`, `.xml`, `.svg` | `<!-- -->` |
| `.css`, `.scss` | `/* */` |
| `.lua`, `.sql`, `.hs` | `--` |

For unknown extensions, use `//` as the default.

### Examples

Python (`.py`):
```python
# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
```

TypeScript (`.ts`):
```typescript
// @unslop-managed — do not edit directly. Edit src/api-client.ts.spec.md instead.
// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z
```

HTML (`.html`):
```html
<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->
<!-- spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z -->
```

CSS (`.css`):
```css
/* @unslop-managed — do not edit directly. Edit src/styles.css.spec.md instead. */
/* spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7c4d9e1f2a05 generated:2026-03-20T14:32:00Z */
```

### Write Order

When generating a file, follow this exact sequence:
1. Generate the file body (everything below the header)
2. Apply Python `str.strip()` to the body, then compute its SHA-256 hash truncated to 12 hex chars → `output-hash`
3. Read the spec file content and compute its SHA-256 hash truncated to 12 hex chars → `spec-hash`
3b. If `.unslop/principles.md` exists, hash its content → `principles-hash`
4. Write header line 1 (spec path — unchanged)
5. Write header line 2: `spec-hash:<hash> output-hash:<hash> [principles-hash:<hash>] generated:<ISO8601 UTC timestamp>`
6. Write the body

This ordering ensures the output-hash is computed before the header is written — the header is NOT included in the hash.

---

## 3. TDD Integration

Use the superpowers test-driven-development skill. Write tests that validate the spec's constraints first, then implement. The tests ARE the acceptance criteria.

The discipline:
1. Read the spec and the existing test file
2. Identify any spec constraints not yet covered by existing tests — add them
3. Run the test suite; confirm it is red (or confirm existing tests pass before you begin)
4. Write the implementation to make the tests green
5. Refactor within the green state without breaking tests

Do not write implementation code before the tests exist. Do not skip this step because the spec "seems clear enough." The tests are the executable form of the spec's intent.

**Note:** During takeover, write or extend tests as needed. During generate/sync, use existing tests for validation — do not create or modify test files.

---

## 4. Idiomatic Output

Generated code should be idiomatic for its language. Do not transliterate the spec into code. The spec says what; you decide how — within the constraints.

This means:
- Use the language's standard library and conventions, not generic patterns ported from elsewhere
- Follow the project's existing style (infer from the test file and surrounding code)
- Do not add comments that restate the spec line-by-line; the header points to the spec, and the tests document behavior
- Do not add `TODO` markers or placeholder stubs — the generated file must be complete and passing

The spec constrains observable behavior. Implementation choices that satisfy the tests and are idiomatic for the language are correct choices. There is no single correct implementation.

---

## 5. Config Awareness

Read `.unslop/config.json` (or `.unslop/config.md` as legacy fallback) for the project's test command before running tests.

If `.unslop/config.json` does not exist or does not specify a test command, infer it from the project's conventional tooling (e.g., `pytest` for Python projects with `pyproject.toml`, `npm test` for Node projects with `package.json`). Do not guess blindly — look at the project root before choosing a fallback.

Always run the test suite after generation to confirm the output is green before declaring the task complete.

---

## 6. Multi-File Generation (Per-Unit Specs)

When a spec has a `## Files` section listing multiple output files, you are generating an entire unit from a single spec.

**Rules:**
- Generate each file listed in the `## Files` section separately
- Apply the `@unslop-managed` header to EVERY generated file
- ALL files reference the unit spec path in their header (e.g., `Edit src/auth/auth.unit.spec.md instead.`)
- Generate files in the order listed in the `## Files` section — earlier files may define types/interfaces that later files use
- Each file must be complete and independently parseable — no stubs or forward references that require manual assembly
- The spec describes the whole unit's behavior; distribute implementation across files according to the responsibilities listed in `## Files`

---

## 7. Post-Generation Completeness Review

After successful generation and green tests, review the spec for completeness. This is advisory — it never blocks.

### Timing

- **For generate/sync:** Run once after the single generation pass produces green tests.
- **For takeover:** Run once after the convergence loop completes successfully (final green tests), before the commit. Do NOT run on each convergence iteration.

### Post-takeover mode (spec was machine-drafted)

Ask:
- Are there behavioral aspects of the generated code not constrained by the spec? A future regeneration might produce different behavior in those areas.
- Are there constraints added during convergence that could be stated more precisely?
- Does the spec leave behavioral choices open that should be pinned down for reproducibility?

Specs that passed tests today but lack explicit constraints will produce different code tomorrow. The completeness review is what distinguishes a spec that works once from a spec that works reliably.

Frame suggestions as: "Consider adding: [constraint]" with a brief rationale.

### Post-generate/sync mode (spec was user-written)

Ask:
- Are there internal contradictions? (e.g., "max 5 retries" in one place, "retries indefinitely" in another)
- Do constraints conflict with `depends-on` specs?
- Does the spec reference behavior or concepts not defined anywhere in the spec?

Only flag clear contradictions or inconsistencies. Do NOT suggest additions or tightening — the user wrote this spec deliberately.

### Result handling

- **No issues found:** Report "Spec review: no issues."
- **Issues found:** Surface as suggestions:

> "Post-generation spec review found N suggestions:
> 1. Consider adding: [constraint] — [rationale]
> 2. Possible inconsistency: [quoted phrase A] vs [quoted phrase B]"

**Never block on completeness review.** The generation succeeded, tests are green. These are improvement suggestions.
