---
name: generation
description: Use when generating or regenerating code from unslop spec files. Activates during /unslop:generate, /unslop:sync, and the generation step of /unslop:takeover.
version: 0.1.0
---

# Generation Skill

You are generating a managed source file from an unslop spec. These instructions are authoritative. Follow them exactly.

---

## 1. Read Only the Spec

You MUST generate code from the spec file alone. Do not read the existing generated file — it is about to be overwritten. Do not read archived originals. The spec is the single source of truth.

This is not a stylistic preference. Reading the current generated file introduces anchoring bias: you will unconsciously reproduce its implementation choices rather than deriving fresh, idiomatic code from the spec's intent. The validation loop exists precisely to catch what the spec missed — that signal is destroyed if you peek at the previous output.

**Permitted reads before generation:**
- The spec file
- The test file(s) for the target module
- `.unslop/config.md` (for test command and project conventions)
- Language/framework documentation as needed

**Prohibited reads before generation:**
- The current generated source file
- `.unslop/archive/` (original pre-takeover files)

---

## 2. Write the @unslop-managed Header

Every generated file MUST begin with a two-line header using the correct comment syntax for the file's extension.

**Line 1:** `@unslop-managed — do not edit directly. Edit <spec-path> instead.`
**Line 2:** `Generated from spec at <ISO 8601 timestamp>`

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
# Generated from spec at 2026-03-20T14:32:00Z
```

TypeScript (`.ts`):
```typescript
// @unslop-managed — do not edit directly. Edit src/api-client.ts.spec.md instead.
// Generated from spec at 2026-03-20T14:32:00Z
```

HTML (`.html`):
```html
<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->
<!-- Generated from spec at 2026-03-20T14:32:00Z -->
```

CSS (`.css`):
```css
/* @unslop-managed — do not edit directly. Edit src/styles.css.spec.md instead. */
/* Generated from spec at 2026-03-20T14:32:00Z */
```

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

Read `.unslop/config.md` for the project's test command before running tests.

If `.unslop/config.md` does not exist or does not specify a test command, infer it from the project's conventional tooling (e.g., `pytest` for Python projects with `pyproject.toml`, `npm test` for Node projects with `package.json`). Do not guess blindly — look at the project root before choosing a fallback.

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
