# CLAUDE.md

Read `AGENTS.md` for architecture, invariants, conventions, and file layout.

## Build & Test

```bash
cd prunejuice && npx vitest run    # prunejuice test suite
cd prunejuice && npx tsc --noEmit  # type check
```

The plugin is markdown commands/skills; prunejuice is the TypeScript MCP server that handles orchestration.

## Process Rules

- **Version bump on every PR** that touches `unslop/commands/`, `unslop/skills/`, or `unslop/hooks/`. Claude Code caches plugins by version -- unchanged version means users stay on stale code.
- **Command is the execution surface.** Critical constraints MUST be in the command file with HARD RULE format, not only in skills. Skills are reference material -- the LLM may not load them.
- **Prescriptive language for load-bearing steps.** Use MUST, NEVER, CRITICAL for steps where skipping produces wrong output. Use "consider" or "may" for nice-to-have steps.
- **No em-dashes in machine-parsed formats.** Use `--` instead of `--`. (Frontmatter, YAML, config files, spec bodies.)
- **Design spec -> plan -> subagent execution** for features touching more than ~2 files. Small changes go straight to implementation.
