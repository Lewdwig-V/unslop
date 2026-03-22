# Domain Skill Infrastructure Design (Milestone E)

> Framework-specific generation priors that inject architectural knowledge into the generation context without bloating individual specs.

**Closes:** Milestone E from the extended roadmap.

## What

A `unslop/domain/` directory where framework-specific skills live. Each skill provides generation priors — conventions, patterns, and constraints specific to a framework. Skills are standard Claude Code plugin skills (SKILL.md in named subdirectories) and auto-discover via the plugin system.

A minimal FastAPI skill ships as proof of concept.

## Structure

```
unslop/domain/
├── fastapi/
│   └── SKILL.md        # FastAPI generation priors
└── ...                  # future: react, sqlalchemy, terraform, etc.
```

Domain skills follow the same conventions as existing skills (`spec-language`, `generation`, `takeover`). They are auto-discovered by the Claude Code plugin system — no special loading code needed.

## Loading Mechanism

The generation skill gains **Phase 0d: Domain Skill Loading** between Phase 0c (change requests) and Section 1 (mode selection):

```
Section 0: Pre-Generation Validation
  Phase 0a: Structural Validation        -- existing
  Phase 0b: Ambiguity Detection          -- existing
  Phase 0c: Change Request Consumption   -- existing
  Phase 0d: Domain Skill Loading         -- NEW

Sections 1-6: Generation pipeline
Section 7: Post-Generation Review        -- existing
```

### How Phase 0d works

1. Check `config.json` for a `frameworks` field. If present, use it as the framework list.
2. If no `frameworks` field, detect frameworks from the target file's imports and the spec content (model-driven, not script-driven).
3. For each detected framework, load the matching `unslop/domain/<framework>` skill as additional generation context.
4. Multiple skills can be active simultaneously — they are additive context.

### Detection is model-driven, not script-driven

Consistent with our architecture principle: scripts for determinism, skills for judgment. Framework detection from imports requires interpreting code context, which is judgment. The model reads the spec and test file imports, identifies which frameworks are in use, and loads the corresponding domain skills.

## `config.json` Extension

```json
{
  "test_command": "pytest",
  "test_command_note": "...",
  "exclude_patterns": [],
  "exclude_patterns_note": "...",
  "frameworks": ["fastapi"],
  "frameworks_note": "Domain skills loaded for these frameworks during generation. Auto-detected if omitted."
}
```

- `frameworks` is optional. When present, it overrides auto-detection.
- When absent, the model auto-detects from imports.
- `/unslop:init` detects frameworks from project dependencies and populates the field.

## Init Integration

`/unslop:init` gains framework detection:

1. Check `pyproject.toml` / `requirements.txt` for known frameworks (fastapi, flask, django, sqlalchemy, etc.)
2. Check `package.json` for frontend frameworks (react, vue, next, etc.)
3. Check for `Cargo.toml`, `go.mod`, `terraform` files
4. Present detected frameworks to the user for confirmation
5. Write confirmed list to `config.json` `frameworks` field

## FastAPI Domain Skill (Proof of Concept)

`unslop/domain/fastapi/SKILL.md`:

### Frontmatter

```yaml
---
name: fastapi-domain
description: Use when generating code for FastAPI applications. Provides generation priors for dependency injection, schema enforcement, and async patterns.
version: 0.1.0
---
```

### Content -- Three Non-Negotiables

**1. Dependency Injection**
- Always use `Annotated[T, Depends(...)]` for dependencies
- Never use default parameter injection (the old `param = Depends(...)` style)
- Example in spec voice and generated code

**2. Schema Enforcement**
- All endpoints must have `response_model` defined
- Request bodies must use Pydantic schemas, not raw dicts
- Example showing spec-to-code mapping

**3. Async by Default**
- Routes are `async def` unless the spec explicitly says otherwise
- Use `BackgroundTasks` for non-blocking side effects
- Blocking I/O in async routes must use `run_in_executor`

### Few-Shot Spec Example

A worked example showing what a good FastAPI endpoint spec looks like and what the generated code should look like. Demonstrates the right register for spec-writing in a FastAPI context.

## Plugin Structure Changes

```
unslop/
├── domain/
│   └── fastapi/
│       └── SKILL.md           # NEW -- FastAPI generation priors
├── skills/
│   └── generation/
│       └── SKILL.md           # MODIFIED -- Phase 0d added
└── commands/
    └── init.md                # MODIFIED -- framework detection
```

## Backwards Compatibility

- Projects without `frameworks` in `config.json`: model auto-detects (no change in behavior)
- Projects with no matching domain skills: Phase 0d is a no-op
- Existing generation behavior is unchanged when no domain skills are loaded
