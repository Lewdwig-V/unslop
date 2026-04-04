# Prunejuice Phase 5: Command Migration + Python Retirement -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch all unslop commands from Python orchestrator CLI / `unslop_*` MCP tools to `prunejuice_*` MCP tools, remove the Python MCP server, and bump the unslop plugin version.

**Architecture:** Each command file is updated independently: `orchestrator.py` CLI invocations and `unslop_*` references become `prunejuice_*` MCP tool calls. The Python `unslop` MCP server entry is removed from `.mcp.json` (only the `prunejuice` server remains). Python orchestrator scripts stay in the repo as reference but are no longer executed. The unslop plugin version bumps for the first time since v0.52.0.

**Tech Stack:** Markdown (command files), JSON (plugin config), Python tests (verify no regressions)

---

## Migration Map

Before writing tasks, here's the complete mapping of what changes where:

### Tool Name Mapping

| Python tool | Prunejuice tool |
|-------------|-----------------|
| `unslop_check_freshness` / `orchestrator.py check-freshness` | `prunejuice_check_freshness` |
| `unslop_build_order` / `orchestrator.py build-order` | `prunejuice_build_order` |
| `unslop_ripple_check` / `orchestrator.py ripple-check` | `prunejuice_ripple_check` |
| `unslop_discover` / `orchestrator.py discover` | `prunejuice_discover_files` |
| `unslop_resolve_deps` / `orchestrator.py deps` | `prunejuice_resolve_deps` |
| `unslop_deep_sync_plan` / `orchestrator.py deep-sync-plan` | `prunejuice_deep_sync_plan` |
| `unslop_bulk_sync_plan` / `orchestrator.py bulk-sync-plan` | `prunejuice_bulk_sync_plan` |
| `orchestrator.py resume-sync-plan` | `prunejuice_resume_sync_plan` |
| `orchestrator.py file-tree` | No prunejuice equivalent (use Glob/LS directly) |
| `orchestrator.py concrete-deps` | `prunejuice_ripple_check` (concrete layer) |
| `orchestrator.py graph` | No prunejuice equivalent (use `prunejuice_build_order` + `prunejuice_ripple_check`) |

### Commands That Reference Python Tools

| Command | References |
|---------|-----------|
| `generate.md` | `unslop_check_freshness`, `unslop_build_order`, `unslop_ripple_check`, `orchestrator.py build-order`, `orchestrator.py ripple-check` |
| `status.md` | `unslop_check_freshness`, `orchestrator.py check-freshness`, `orchestrator.py concrete-deps` |
| `change.md` | `unslop_ripple_check`, `orchestrator.py ripple-check`, `orchestrator.py file-tree` |
| `elicit.md` | `unslop_ripple_check`, `unslop_discover`, `orchestrator.py ripple-check`, `orchestrator.py discover` |
| `sync.md` | `orchestrator.py deps`, `orchestrator.py deep-sync-plan`, `orchestrator.py bulk-sync-plan`, `orchestrator.py resume-sync-plan` |
| `graph.md` | `orchestrator.py graph` |
| `coherence.md` | `orchestrator.py deps` |
| `init.md` | `orchestrator.py check-freshness` (in hook template), `orchestrator.py` reference in file list |

---

## File Structure

| File | Change |
|------|--------|
| **Modify:** `unslop/commands/generate.md` | Replace `unslop_*` and `orchestrator.py` references with `prunejuice_*` |
| **Modify:** `unslop/commands/status.md` | Replace `unslop_check_freshness` and `orchestrator.py` with `prunejuice_*` |
| **Modify:** `unslop/commands/change.md` | Replace `unslop_ripple_check` and `orchestrator.py` with `prunejuice_*` |
| **Modify:** `unslop/commands/elicit.md` | Replace `unslop_ripple_check`, `unslop_discover` and `orchestrator.py` with `prunejuice_*` |
| **Modify:** `unslop/commands/sync.md` | Replace `orchestrator.py` CLI calls with `prunejuice_*` MCP tool calls |
| **Modify:** `unslop/commands/graph.md` | Replace `orchestrator.py graph` with `prunejuice_build_order` + `prunejuice_ripple_check` |
| **Modify:** `unslop/commands/coherence.md` | Replace `orchestrator.py deps` with `prunejuice_resolve_deps` |
| **Modify:** `unslop/commands/init.md` | Update hook template and file list references |
| **Modify:** `unslop/.claude-plugin/.mcp.json` | Remove `unslop` server entry |
| **Modify:** `unslop/.claude-plugin/plugin.json` | Bump version to 0.53.0 |

---

### Task 1: Migrate `generate.md`

**Files:**
- Modify: `unslop/commands/generate.md`

This command has the most Python references -- the "Preferred MCP" note and several `orchestrator.py` CLI calls.

- [ ] **Step 1: Read the current file**

Read `unslop/commands/generate.md` to understand the current structure.

- [ ] **Step 2: Replace the MCP preference note (around line 52)**

Find:
```
**Preferred:** If available, use MCP tools (`unslop_check_freshness`, `unslop_build_order`, `unslop_ripple_check`) instead of shelling out to `orchestrator.py`. Fall back to CLI if MCP is not available.
```

Replace with:
```
Use MCP tools `prunejuice_check_freshness`, `prunejuice_build_order`, `prunejuice_ripple_check` for freshness classification, build ordering, and ripple analysis.
```

- [ ] **Step 3: Replace `orchestrator.py build-order` (around line 56)**

Find the line referencing `orchestrator.py build-order` and replace with:
```
1. Call MCP tool `prunejuice_build_order` with `{ cwd: "." }` to get the full build order across all specs.
```

- [ ] **Step 4: Replace `orchestrator.py ripple-check` (around line 99)**

Find the line referencing `orchestrator.py ripple-check` and replace with:
```
2. Call MCP tool `prunejuice_ripple_check` with `{ specPaths: [<affected-spec-paths>], cwd: "." }` to compute the blast radius.
```

- [ ] **Step 5: Remove any remaining "Fall back to CLI" language**

Search for remaining `orchestrator.py` references in the file and replace with MCP equivalents.

- [ ] **Step 6: Verify no `unslop_` or `orchestrator.py` references remain**

Run: `grep -n "unslop_\|orchestrator\.py" unslop/commands/generate.md`
Expected: No matches

- [ ] **Step 7: Commit**

```bash
git add unslop/commands/generate.md
git commit -m "migrate(unslop): generate.md -- switch to prunejuice MCP tools"
```

---

### Task 2: Migrate `status.md`

**Files:**
- Modify: `unslop/commands/status.md`

- [ ] **Step 1: Read the current file**

Read `unslop/commands/status.md`.

- [ ] **Step 2: Replace `unslop_check_freshness` reference (around line 64)**

Find the "Preferred" note about `unslop_check_freshness` and replace with:
```
Call MCP tool `prunejuice_check_freshness` with `{ cwd: "." }` to get freshness state for all managed files.
```

- [ ] **Step 3: Replace `orchestrator.py check-freshness` CLI call (around line 66)**

Replace the `orchestrator.py check-freshness` invocation with the MCP tool call above. Remove the "Fall back to CLI" pattern -- MCP is now the only path.

- [ ] **Step 4: Replace `orchestrator.py concrete-deps` (around line 68)**

The `concrete-deps` CLI has no direct prunejuice equivalent. Replace with:
```
For files classified as fresh, check for ghost staleness by calling MCP tool `prunejuice_ripple_check` with `{ specPaths: [<spec-path>], cwd: "." }` and inspecting `layers.concrete.ghostStaleImpls`.
```

- [ ] **Step 5: Verify no `unslop_` or `orchestrator.py` references remain**

Run: `grep -n "unslop_\|orchestrator\.py" unslop/commands/status.md`
Expected: No matches

- [ ] **Step 6: Commit**

```bash
git add unslop/commands/status.md
git commit -m "migrate(unslop): status.md -- switch to prunejuice MCP tools"
```

---

### Task 3: Migrate `change.md`

**Files:**
- Modify: `unslop/commands/change.md`

- [ ] **Step 1: Read the current file**

Read `unslop/commands/change.md`.

- [ ] **Step 2: Replace `unslop_ripple_check` and `orchestrator.py ripple-check` (around line 62)**

Replace:
```
Call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ripple-check <spec-path> --root .` (or use MCP `unslop_ripple_check` if available).
```

With:
```
Call MCP tool `prunejuice_ripple_check` with `{ specPaths: ["<spec-path>"], cwd: "." }`.
```

- [ ] **Step 3: Replace `orchestrator.py file-tree` (around line 158)**

Replace:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py file-tree .
```

With a direct tool call:
```
Use Glob or LS to read the file tree.
```

(`file-tree` just calls `git ls-files` -- no MCP tool needed, the agent has direct access.)

- [ ] **Step 4: Verify no `unslop_` or `orchestrator.py` references remain**

Run: `grep -n "unslop_\|orchestrator\.py" unslop/commands/change.md`
Expected: No matches

- [ ] **Step 5: Commit**

```bash
git add unslop/commands/change.md
git commit -m "migrate(unslop): change.md -- switch to prunejuice MCP tools"
```

---

### Task 4: Migrate `elicit.md`

**Files:**
- Modify: `unslop/commands/elicit.md`

- [ ] **Step 1: Read the current file**

Read `unslop/commands/elicit.md`.

- [ ] **Step 2: Replace `unslop_ripple_check` and `orchestrator.py ripple-check` (around line 68)**

Replace:
```
call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ripple-check <spec-path> --root .` (or use MCP `unslop_ripple_check` if available)
```

With:
```
call MCP tool `prunejuice_ripple_check` with `{ specPaths: ["<spec-path>"], cwd: "." }`
```

- [ ] **Step 3: Replace `unslop_discover` and `orchestrator.py discover` (around line 104)**

Replace:
```
Use `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py discover .` (or MCP `unslop_discover`) to show existing managed files.
```

With:
```
Use MCP tool `prunejuice_discover_files` with `{ directory: "." }` to show existing managed files.
```

- [ ] **Step 4: Verify no `unslop_` or `orchestrator.py` references remain**

Run: `grep -n "unslop_\|orchestrator\.py" unslop/commands/elicit.md`
Expected: No matches

- [ ] **Step 5: Commit**

```bash
git add unslop/commands/elicit.md
git commit -m "migrate(unslop): elicit.md -- switch to prunejuice MCP tools"
```

---

### Task 5: Migrate `sync.md`

**Files:**
- Modify: `unslop/commands/sync.md`

This command has the most `orchestrator.py` CLI calls (deps, deep-sync-plan, bulk-sync-plan, resume-sync-plan).

- [ ] **Step 1: Read the current file**

Read `unslop/commands/sync.md`.

- [ ] **Step 2: Replace `orchestrator.py deps` (around line 50)**

Replace:
```
call `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py deps <spec-path> --root .` to find transitive dependencies.
```

With:
```
call MCP tool `prunejuice_resolve_deps` with `{ specPath: "<spec-path>", cwd: "." }` to find transitive dependencies.
```

- [ ] **Step 3: Replace `orchestrator.py deep-sync-plan` (around line 71)**

Replace the CLI invocation with:
```
Call MCP tool `prunejuice_deep_sync_plan` with `{ filePath: "<file-path>", cwd: ".", force: false }`.
```

- [ ] **Step 4: Replace `orchestrator.py bulk-sync-plan` (around line 124)**

Replace the CLI invocation with:
```
Call MCP tool `prunejuice_bulk_sync_plan` with `{ cwd: ".", force: false, maxBatchSize: 8 }`.
```

- [ ] **Step 5: Replace `orchestrator.py resume-sync-plan` (around line 193)**

Replace the CLI invocation with:
```
Call MCP tool `prunejuice_resume_sync_plan` with `{ cwd: ".", failedFiles: [<f1>, <f2>], succeededFiles: [<s1>, <s2>], force: false, maxBatchSize: 8 }`.
```

- [ ] **Step 6: Verify no `unslop_` or `orchestrator.py` references remain**

Run: `grep -n "unslop_\|orchestrator\.py" unslop/commands/sync.md`
Expected: No matches

- [ ] **Step 7: Commit**

```bash
git add unslop/commands/sync.md
git commit -m "migrate(unslop): sync.md -- switch to prunejuice MCP tools"
```

---

### Task 6: Migrate `graph.md`, `coherence.md`, `init.md`

**Files:**
- Modify: `unslop/commands/graph.md`
- Modify: `unslop/commands/coherence.md`
- Modify: `unslop/commands/init.md`

These three commands have fewer references and can be done together.

- [ ] **Step 1: Read all three files**

Read `unslop/commands/graph.md`, `unslop/commands/coherence.md`, `unslop/commands/init.md`.

- [ ] **Step 2: Migrate `graph.md`**

Replace `orchestrator.py graph` with MCP tool calls:
```
Call MCP tool `prunejuice_build_order` with `{ cwd: "." }` for topological spec ordering, and `prunejuice_ripple_check` with `{ specPaths: [<specs>], cwd: "." }` for dependency analysis.
```

Update the CLI example block at line 25 to show MCP tool calls instead.

- [ ] **Step 3: Migrate `coherence.md`**

Replace `orchestrator.py deps` with:
```
Call MCP tool `prunejuice_resolve_deps` with `{ specPath: "<spec-path>", cwd: "." }` to resolve upstream dependencies.
```

- [ ] **Step 4: Migrate `init.md`**

Two changes:
1. Update the hook template (around line 201) that references `orchestrator.py check-freshness` -- replace with `prunejuice_check_freshness` MCP tool call or remove the Python-specific hook example.
2. Remove `orchestrator.py` from the "files created" list (around line 206) if it's listed there.

- [ ] **Step 5: Verify no `unslop_` or `orchestrator.py` references remain in any of the three files**

Run:
```bash
grep -n "unslop_\|orchestrator\.py" unslop/commands/graph.md unslop/commands/coherence.md unslop/commands/init.md
```
Expected: No matches

- [ ] **Step 6: Commit**

```bash
git add unslop/commands/graph.md unslop/commands/coherence.md unslop/commands/init.md
git commit -m "migrate(unslop): graph.md, coherence.md, init.md -- switch to prunejuice MCP tools"
```

---

### Task 7: Remove Python MCP Server + Version Bumps

**Files:**
- Modify: `unslop/.claude-plugin/.mcp.json`
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Remove the `unslop` MCP server from `.mcp.json`**

Change `unslop/.claude-plugin/.mcp.json` from:

```json
{
  "mcpServers": {
    "unslop": {
      "command": "python3",
      "args": ["-m", "unslop.scripts.mcp_server"],
      "cwd": "${PROJECT_ROOT}",
      "env": {
        "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/.."
      }
    },
    "prunejuice": {
      "command": "npx",
      "args": ["tsx", "${CLAUDE_PLUGIN_ROOT}/../prunejuice/src/mcp.ts"],
      "cwd": "${PROJECT_ROOT}"
    }
  }
}
```

To:

```json
{
  "mcpServers": {
    "prunejuice": {
      "command": "npx",
      "args": ["tsx", "${CLAUDE_PLUGIN_ROOT}/../prunejuice/src/mcp.ts"],
      "cwd": "${PROJECT_ROOT}"
    }
  }
}
```

- [ ] **Step 2: Bump unslop plugin version**

Change `unslop/.claude-plugin/plugin.json` version from `"0.52.0"` to `"0.53.0"`.

- [ ] **Step 3: Bump prunejuice version**

Change `prunejuice/package.json` version from `"1.4.0"` to `"1.5.0"`.

- [ ] **Step 4: Final sweep -- verify no `unslop_` or `orchestrator.py` references remain in any command**

Run:
```bash
grep -rn "unslop_\|orchestrator\.py" unslop/commands/ unslop/skills/
```
Expected: No matches in commands. Skills may reference the orchestrator pattern in documentation context (acceptable).

- [ ] **Step 5: Run Python tests**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: All tests pass (Python scripts remain as reference, tests still validate them)

- [ ] **Step 6: Run prunejuice tests**

Run: `cd prunejuice && npm run test`
Expected: All tests pass

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd prunejuice && npm run build`
Expected: Clean compile

- [ ] **Step 8: Commit**

```bash
git add unslop/.claude-plugin/.mcp.json unslop/.claude-plugin/plugin.json prunejuice/package.json
git commit -m "chore: remove Python MCP server, bump unslop to 0.53.0, prunejuice to 1.5.0"
```

---

## Notes for the Implementer

### Key Invariants

1. **Every `orchestrator.py` CLI call must become a `prunejuice_*` MCP tool call.** There is no fallback path. The Python MCP server is being removed -- if a command still references `orchestrator.py`, it will break.

2. **Tool name mapping is not 1:1.** `unslop_discover` maps to `prunejuice_discover_files` (different name). `orchestrator.py file-tree` has no MCP equivalent (use Glob/LS). `orchestrator.py concrete-deps` maps to `prunejuice_ripple_check`'s concrete layer. `orchestrator.py graph` maps to `prunejuice_build_order` + `prunejuice_ripple_check`.

3. **MCP tool calls use JSON params, not CLI flags.** Replace `--root .` with `cwd: "."`. Replace `--force` with `force: true`. Replace positional args with named fields.

4. **The "Preferred: MCP / Fall back: CLI" pattern is eliminated.** All commands now use MCP exclusively. Remove the dual-path language.

5. **Python scripts remain but are not executed.** `unslop/scripts/` stays in the repo as reference. The tests in `tests/test_orchestrator.py` continue to validate the Python code (it's still correct, just no longer on the execution path). Do NOT delete the Python files.

6. **Version bumps:** Unslop goes from 0.52.0 → 0.53.0 (first bump since the pre-prunejuice era). Prunejuice goes from 1.4.0 → 1.5.0.

### What NOT to Do

- Do NOT delete `unslop/scripts/` or `mcp_server.py`. They remain as reference.
- Do NOT modify Python test files. They test Python code that still works.
- Do NOT change the command semantics. Only change the tool invocation mechanism (CLI → MCP). The steps, HARD RULEs, and workflow remain identical.
- Do NOT add new features. This is a pure migration -- same behavior, different execution surface.

### Verification

After all tasks, run this comprehensive check:
```bash
# No Python tool references in commands
grep -rn "unslop_\|orchestrator\.py" unslop/commands/
# Prunejuice tests pass
cd prunejuice && npm run test && npm run build
# Python tests still pass
python -m pytest tests/test_orchestrator.py -q
```
