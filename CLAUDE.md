# CLAUDE.md

Read `AGENTS.md` for architecture, invariants, conventions, and file layout.

## Build & Test

```bash
python -m pytest tests/test_orchestrator.py -q    # 405 tests, Python 3.8-3.14
```

No build step. Plugin is pure markdown commands/skills + Python orchestrator scripts.

## Process Rules

- **Version bump on every PR** that touches `unslop/commands/`, `unslop/skills/`, or `unslop/hooks/`. Claude Code caches plugins by version -- unchanged version means users stay on stale code.
- **Command is the execution surface.** Critical constraints MUST be in the command file with HARD RULE format, not only in skills. Skills are reference material -- the LLM may not load them.
- **Prescriptive language for load-bearing steps.** Use MUST, NEVER, CRITICAL for steps where skipping produces wrong output. Use "consider" or "may" for nice-to-have steps.
- **No em-dashes in machine-parsed formats.** Use `--` instead of `--`. (Frontmatter, YAML, config files, spec bodies.)
- **Design spec -> plan -> subagent execution** for features touching more than ~2 files. Small changes go straight to implementation.
