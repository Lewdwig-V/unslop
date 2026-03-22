---
description: Initialize unslop in the current project
---

Check if `.unslop/` already exists in the current working directory.

If it exists: inform the user that unslop is already initialized and ask if they want to re-detect the test command. If yes, skip to the detection step and overwrite `.unslop/config.json`. If no, stop.

If it does not exist, proceed with the following steps:

**1. Create directories**

Create `.unslop/` and `.unslop/archive/`.

**2. Create `.unslop/.gitignore`**

Contents:
```
archive/
feedback.md
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
  "exclude_patterns": [],
  "exclude_patterns_note": "Additional directory patterns to exclude from discovery, beyond defaults"
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

3. Copy the orchestrator script to `.unslop/scripts/` for CI availability:
   - Copy `orchestrator.py` from the plugin to `.unslop/scripts/orchestrator.py`
   - Add a version marker comment at the top: `# unslop orchestrator v0.9.0 -- vendored for CI`
   - Note: Only `orchestrator.py` needs to be vendored -- `validate_spec.py` is used by the generation skill during interactive sessions, not by CI. The `check-freshness` command does not import from `validate_spec.py`.

   If `.unslop/scripts/orchestrator.py` already exists (from a previous init), read its first line to check the version marker. If the version is older than `v0.9.0`, offer to update it. If the user agrees, overwrite the file with the current version. If the user declines, leave it unchanged.

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
