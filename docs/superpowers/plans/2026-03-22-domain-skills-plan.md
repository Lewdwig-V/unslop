# Domain Skill Infrastructure Implementation Plan (Milestone E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `unslop/domain/` directory with auto-discovering domain skills, Phase 0d in the generation skill, framework detection in init, and a FastAPI proof-of-concept skill.

**Architecture:** Domain skills are standard SKILL.md files in `unslop/domain/<name>/`. The generation skill gains Phase 0d for loading them. Init detects frameworks from project dependencies. No new Python code — pure plugin markdown.

**Tech Stack:** Claude Code plugin markdown only. No Python changes.

**Spec:** `docs/superpowers/specs/2026-03-22-domain-skills-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/domain/fastapi/SKILL.md` | Create | FastAPI generation priors |
| `unslop/skills/generation/SKILL.md` | Modify | Add Phase 0d |
| `unslop/commands/init.md` | Modify | Framework detection |

---

### Task 1: FastAPI Domain Skill

**Files:**
- Create: `unslop/domain/fastapi/SKILL.md`

- [ ] **Step 1: Write the FastAPI domain skill**

Create `unslop/domain/fastapi/SKILL.md` with frontmatter and three non-negotiable sections plus a few-shot example.

Frontmatter:
```yaml
---
name: fastapi-domain
description: Use when generating code for FastAPI applications. Provides generation priors for dependency injection, schema enforcement, and async patterns.
version: 0.1.0
---
```

Content should cover:

**Section 1: Dependency Injection**
- Always use `Annotated[T, Depends(...)]` (not the legacy `param = Depends(...)` style)
- Show a positive example (Annotated) and a negative example (legacy)

**Section 2: Schema Enforcement**
- All endpoints must define `response_model`
- Request bodies must use Pydantic `BaseModel` subclasses
- Show a spec-to-code mapping example

**Section 3: Async Patterns**
- Routes are `async def` by default unless spec says otherwise
- Use `BackgroundTasks` for non-blocking side effects
- Blocking I/O in async routes must use `run_in_executor`

**Section 4: Few-Shot Example**
- A complete spec example for a typical CRUD endpoint
- The corresponding generated code showing all three non-negotiables applied

- [ ] **Step 2: Commit**

```bash
git add unslop/domain/fastapi/SKILL.md
git commit -m "feat: add FastAPI domain skill -- dependency injection, schemas, async patterns"
```

---

### Task 2: Generation Skill -- Phase 0d

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add Phase 0d after Phase 0c**

Insert between Phase 0c and Section 1:

```markdown
### Phase 0d: Domain Skill Loading

After change request consumption, check for framework-specific domain skills to load as additional generation context.

**1. Check for explicit framework list:**
Read `.unslop/config.json`. If it has a `frameworks` field (e.g., `["fastapi", "sqlalchemy"]`), use that list.

**2. If no explicit list, auto-detect:**
Read the spec file and any test files for the target module. Identify framework imports:
- `from fastapi import` or `import fastapi` -- load `unslop/domain/fastapi`
- `from sqlalchemy import` or `import sqlalchemy` -- load `unslop/domain/sqlalchemy`
- `import React` or `from 'react'` -- load `unslop/domain/react`
- Other frameworks: check if a matching `unslop/domain/<name>/SKILL.md` exists

**3. Load matching skills:**
For each detected framework, read the corresponding `unslop/domain/<framework>/SKILL.md` as additional generation context. These skills provide framework-specific conventions, patterns, and constraints.

**4. Context priority:**
Domain skills are additive -- they augment the generation skill, not replace it. Priority order for conflicting guidance:
- Project Principles (highest -- non-negotiable)
- Domain Skills (framework conventions)
- File Spec (file-specific requirements)
- Generation Skill defaults (lowest)

If no domain skills match, this phase is a no-op. Proceed to Section 1.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Phase 0d domain skill loading to generation skill"
```

---

### Task 3: Init Command -- Framework Detection

**Files:**
- Modify: `unslop/commands/init.md`

- [ ] **Step 1: Add framework detection**

After the principles creation step and before the alignment-summary step, add:

```markdown
**6. Detect frameworks (optional)**

Scan the project for known framework indicators:
- `pyproject.toml` or `requirements.txt`: look for `fastapi`, `flask`, `django`, `sqlalchemy`, `pydantic`
- `package.json`: look for `react`, `vue`, `next`, `express`
- `Cargo.toml`: note `rust` as the ecosystem
- `go.mod`: note `go` as the ecosystem
- `terraform` files (`.tf`): note `terraform`

Present detected frameworks to the user:
> "Detected frameworks: FastAPI, SQLAlchemy. Domain-specific generation rules will be loaded for these. Edit the `frameworks` field in `.unslop/config.json` to adjust."

Add the confirmed list to `config.json`:
```json
{
  "frameworks": ["fastapi", "sqlalchemy"],
  "frameworks_note": "Domain skills loaded for these frameworks during generation"
}
```

If no frameworks detected, skip this step. The `frameworks` field is optional.
```

Renumber subsequent steps.

- [ ] **Step 2: Commit**

```bash
git add unslop/commands/init.md
git commit -m "feat: add framework detection to init command"
```

---

### Task 4: Bump Version + Verify

- [ ] **Step 1: Bump version to 0.7.0**

- [ ] **Step 2: Verify domain skill exists**

```bash
head -5 unslop/domain/fastapi/SKILL.md
```

- [ ] **Step 3: Verify Phase 0d in generation skill**

```bash
grep 'Phase 0d' unslop/skills/generation/SKILL.md
```

- [ ] **Step 4: Verify framework detection in init**

```bash
grep -i 'framework' unslop/commands/init.md | head -3
```

- [ ] **Step 5: Run all tests (regression)**

```bash
python -m pytest tests/ -q && uv run ruff check unslop/scripts/ tests/
```

- [ ] **Step 6: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.7.0"
```
