---
description: Initialize unslop in the current project
---

Check if `.unslop/` already exists in the current working directory.

If it exists: check `.unslop/.gitignore` for missing entries (`last-failure/`). If any are missing, append them silently. Then inform the user that unslop is already initialized and ask if they want to re-detect the test command. If yes, skip to the detection step and overwrite `.unslop/config.json`. If no, stop.

If it does not exist, proceed with the following steps:

**1. Create directories**

Create `.unslop/` and `.unslop/archive/`.

**2. Create `.unslop/.gitignore`**

Contents:
```
archive/
last-failure/
feedback.md
errors.log
```

**3. Detect the test command**

Check for the following files in order:
- `package.json` — if it contains a `"test"` key under `"scripts"`, use `npm test`
- `pyproject.toml` or `pytest.ini` — use `pytest`
- `Makefile` — if it contains a `test:` target, use `make test`
- `Cargo.toml` — use `cargo test`
- `go.mod` — use `go test ./...`

If multiple indicators are found, or none are found, ask the user which test command to use before continuing.

**4. Write `.unslop/config.json`**

```json
{
  "test_command": "<detected or user-provided command>",
  "test_command_note": "Detected from <source>",
  "models": {
    "architect": "opus",
    "builder": "sonnet",
    "archaeologist": "sonnet",
    "mason": "sonnet",
    "saboteur": "haiku"
  },
  "models_note": "Model selection per agent role. architect is not dispatched as a subagent -- it runs inline in the controlling session. This entry documents the intended model tier, not a dispatch parameter. Valid values: opus, sonnet, haiku, or a full model ID.",
  "exclude_patterns": [],
  "exclude_patterns_note": "Additional directory patterns to exclude from discovery, beyond defaults",
  "promote-threshold": "high",
  "promote-threshold_note": "Complexity level at which concrete specs (.impl.md) are auto-promoted to permanent. Options: low, medium, high",
  "adversarial": true,
  "adversarial_note": "Enable adversarial quality pipeline for testless takeover and quality validation. Disable with false or use --skip-adversarial per-file.",
  "adversarial_max_iterations": 3,
  "adversarial_max_iterations_note": "Maximum convergence iterations before requiring manual review",
  "mutation_tool": "builtin",
  "mutation_tool_note": "Mutation engine: 'mutmut' for full mutation testing, 'builtin' for lightweight AST mutator",
  "entropy_threshold": 0.05,
  "entropy_threshold_note": "Minimum mutation kill rate improvement per iteration. Below this, convergence stalls and triggers radical spec hardening. Set to 0 to disable.",
  "mutation_budget": 20,
  "mutation_budget_note": "Maximum actionable mutations per /unslop:cover run. Equivalent mutants don't count. Set to 0 for exhaustive mode."
}
```

**Migration:** If `.unslop/config.md` exists, read its test command value, migrate to `config.json`, then delete `config.md`. Include the deletion in the commit.

**5. Create `.unslop/principles.md` (optional)**

Ask the user: 'Would you like to define project principles? These are non-negotiable constraints that apply to all generated code (e.g., error handling style, architecture patterns).'

If yes, create `.unslop/principles.md` with a starter template:

```markdown
# Project Principles

<!-- Define non-negotiable constraints for all generated code. -->
<!-- These are enforced during every generation cycle. -->

## Architecture
- [Add architectural constraints here]

## Error Handling
- [Add error handling rules here]

## Style
- [Add style requirements here]
```

Present the template to the user for editing.

If no, skip. Principles are optional.

**6. Detect frameworks (optional)**

Scan the project for known framework indicators:
- `pyproject.toml` or `requirements.txt`: look for `fastapi`, `flask`, `django`, `sqlalchemy`, `pydantic`
- `package.json`: look for `react`, `vue`, `next`, `express`
- `Cargo.toml`: note `rust` as the ecosystem
- `go.mod`: note `go` as the ecosystem
- Terraform files (`.tf`): note `terraform`

Only include frameworks that have a corresponding `unslop/domain/<framework>/SKILL.md` skill file. Currently shipped: `fastapi`. Other detected frameworks should be noted to the user but not added to `config.json` until their domain skill is available.

Present detected frameworks to the user:
> "Detected frameworks: [list]. Domain-specific generation rules will be loaded for these. Edit the `frameworks` field in `.unslop/config.json` to adjust."

Add the following fields to the existing `.unslop/config.json` object:
```json
"frameworks": ["fastapi"],
"frameworks_note": "Domain skills loaded for these frameworks during generation"
```
These are fields to merge into the existing config object, not a standalone file.

If no frameworks detected, skip. The `frameworks` field is optional.

**7. Generate CI workflow (optional)**

Ask the user: "Would you like to generate a GitHub Actions workflow that checks managed file freshness on every PR?"

If yes:

1. Create `.github/workflows/` directory if it doesn't exist
2. Write `.github/workflows/unslop-freshness.yml`:

```yaml
name: unslop freshness check
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Set up Python
        run: uv python install 3.11
      - name: Check managed file freshness
        run: uv run python .unslop/scripts/orchestrator.py check-freshness .
```

3. Copy the orchestrator scripts directory to `.unslop/scripts/` for CI availability:
   - Recursively copy the following from `${CLAUDE_PLUGIN_ROOT}/scripts/` to `.unslop/scripts/`:
     - `orchestrator.py` (CLI entry point)
     - `core/` directory (hashing, frontmatter, spec_discovery)
     - `dependencies/` directory (graph, concrete_graph, unified_dag)
     - `freshness/` directory (checker, manifest)
     - `planning/` directory (ripple, deep_sync, bulk_sync, resume, graph_renderer)
     - `validation/` directory (placeholder for future symbol_audit)
   - Do NOT copy `validate_spec.py`, `validate_behaviour.py`, `validate_mocks.py`, or `pseudocode_linter.py` -- these are used by the generation skill during interactive sessions, not by CI.
   - Write a `version.txt` file at `.unslop/scripts/version.txt` containing the current plugin version (e.g. `0.13.0`). This allows the orchestrator to warn the user if their vendored CI logic is out of sync with their installed unslop plugin.

   If `.unslop/scripts/version.txt` already exists (from a previous init), read it and compare against the current plugin version. If the vendored version is older, offer to update. If the user agrees, overwrite the entire `.unslop/scripts/` directory with the current version. If the user declines, leave it unchanged.

4. Inform the user: "CI workflow created at `.github/workflows/unslop-freshness.yml`. Commit it alongside `.unslop/scripts/` to enable freshness checks on PRs."

If no, skip. The workflow is optional.

**8. Create `.unslop/alignment-summary.md`**

```markdown
# unslop alignment summary
<!-- Auto-generated by unslop. Do not edit manually. -->

## Managed files

No managed files yet. Use /unslop:takeover or /unslop:spec to get started.
```

**9. Commit**

Stage the entire `.unslop/` directory. If the CI workflow was generated in step 7, also stage `.github/workflows/unslop-freshness.yml`. Create a commit with the message: `chore: initialize unslop`
