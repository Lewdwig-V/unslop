# MCP Server: Plugin-Bundled Orchestrator Tools

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this spec.

**Goal:** Expose the orchestrator's core functions as MCP tools so the Architect can call them directly instead of shelling out to `python orchestrator.py`.

**Motivation:** Every command that checks freshness, resolves dependencies, or plans a sync currently shells out via the Bash tool: `python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py check-freshness .`. This is fragile (depends on Python being on PATH with the right version), noisy (raw CLI output in conversation), and opaque (the Architect can't see tool schemas or get validation). An MCP server wrapping the same functions gives typed inputs, structured JSON outputs, and auto-discovery.

---

## 1. Transport and Packaging

**Transport:** stdio (standard for plugin-bundled MCP servers).

**Plugin declaration** (`.mcp.json` at `unslop/.claude-plugin/.mcp.json`, adjacent to `plugin.json`):

```json
{
  "mcpServers": {
    "unslop": {
      "command": "python3",
      "args": ["-m", "unslop.scripts.mcp_server"],
      "cwd": "${PROJECT_ROOT}"
    }
  }
}
```

The server is invoked as a package module (`-m`) to ensure relative imports work correctly. This avoids the bootstrap hack needed by `orchestrator.py` for direct execution. Claude Code starts the server automatically on session start. The server runs in the project's working directory, so tools default to `.` for project root.

**Note:** `${CLAUDE_PLUGIN_ROOT}` is supported in command strings in plugin commands/skills. Verify it is also expanded in `.mcp.json` `args` arrays. If not, use the `-m` invocation pattern above which works regardless (Python resolves the module from the installed package or `PYTHONPATH`).

**Dependency:** The `mcp` Python package (official MCP SDK). Pure Python, no native extensions. If not installed, the server fails to start and the Architect falls back to the CLI (which still works). The init command should check for the package and suggest `pip install mcp` if missing.

**Graceful degradation:** The plugin works without the MCP server. The CLI is the fallback. No functionality is lost, only convenience.

---

## 2. Tool Set

10 tools grouped by function. Each maps to an existing orchestrator function -- no new logic, just structured dispatch.

### 2.1 Freshness & Status

| Tool | Description |
|---|---|
| `unslop_check_freshness` | Check freshness of all managed files. Returns staleness state, blocked constraints, pending changes, ghost-staleness. |
| `unslop_classify_file` | Classify a single managed file's staleness (fresh/stale/modified/conflict). |

### 2.2 Dependency Resolution

| Tool | Description |
|---|---|
| `unslop_build_order` | Topologically sorted spec list from `depends-on` frontmatter. |
| `unslop_resolve_deps` | Transitive dependency list for a single spec. |

### 2.3 Planning

| Tool | Description |
|---|---|
| `unslop_ripple_check` | Blast radius analysis across abstract specs, concrete specs, and managed files. |
| `unslop_deep_sync_plan` | Single-file sync plan with dependency ordering. |
| `unslop_bulk_sync_plan` | All-stale-files sync plan with parallel batches. |

### 2.4 Validation

| Tool | Description |
|---|---|
| `unslop_symbol_audit` | Compare public symbols between spec and managed source file. |
| `unslop_check_drift` | Symbol-level drift between two files. |

### 2.5 Discovery

| Tool | Description |
|---|---|
| `unslop_discover` | Find source files and test files in a directory. |

### 2.6 Not exposed

- `concrete-order`, `concrete-deps` -- internal to ghost-staleness
- `file-tree` -- subsumed by `unslop_discover`
- `graph` -- Mermaid rendering, better as a command
- `resume-sync-plan` -- niche, can be added later
- `spec-diff` -- internal to surgical mode
- Validation scripts (`validate_spec.py`, `validate_behaviour.py`, `validate_mocks.py`) -- used by subagents, not by the Architect

---

## 3. Tool Schemas

Each tool has a typed JSON Schema input. Optional parameters have defaults. Required parameters are marked.

### `unslop_check_freshness`

```json
{
  "name": "unslop_check_freshness",
  "description": "Check freshness of all managed files. Returns staleness state, blocked constraints, pending changes, and ghost-staleness.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "directory": { "type": "string", "description": "Project root directory", "default": "." },
      "exclude_dirs": { "type": "array", "items": { "type": "string" }, "description": "Directories to exclude", "default": [".unslop", "node_modules"] }
    }
  }
}
```

### `unslop_classify_file`

```json
{
  "name": "unslop_classify_file",
  "description": "Classify a single managed file's staleness state.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "managed_path": { "type": "string", "description": "Path to the managed file" },
      "spec_path": { "type": "string", "description": "Path to the spec file" },
      "project_root": { "type": "string", "description": "Project root for principles check", "default": "." }
    },
    "required": ["managed_path", "spec_path"]
  }
}
```

### `unslop_build_order`

```json
{
  "name": "unslop_build_order",
  "description": "Topologically sorted spec list from depends-on frontmatter.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "directory": { "type": "string", "description": "Project root directory", "default": "." }
    }
  }
}
```

### `unslop_resolve_deps`

```json
{
  "name": "unslop_resolve_deps",
  "description": "Transitive dependency list for a single spec file.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "spec_path": { "type": "string", "description": "Path to the spec file" },
      "project_root": { "type": "string", "description": "Project root directory", "default": "." }
    },
    "required": ["spec_path"]
  }
}
```

### `unslop_ripple_check`

```json
{
  "name": "unslop_ripple_check",
  "description": "Analyze the blast radius of spec changes across abstract specs, concrete specs, and managed files.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "spec_paths": { "type": "array", "items": { "type": "string" }, "description": "Spec files that changed" },
      "project_root": { "type": "string", "description": "Project root directory", "default": "." }
    },
    "required": ["spec_paths"]
  }
}
```

### `unslop_deep_sync_plan`

```json
{
  "name": "unslop_deep_sync_plan",
  "description": "Compute a sync plan for a single spec file with dependency ordering.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "spec_path": { "type": "string", "description": "Path to the spec file" },
      "project_root": { "type": "string", "description": "Project root directory", "default": "." },
      "force": { "type": "boolean", "description": "Include modified/conflict files", "default": false }
    },
    "required": ["spec_path"]
  }
}
```

### `unslop_bulk_sync_plan`

```json
{
  "name": "unslop_bulk_sync_plan",
  "description": "Compute a sync plan for all stale files with parallel batch grouping.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_root": { "type": "string", "description": "Project root directory", "default": "." },
      "force": { "type": "boolean", "description": "Include modified/conflict files", "default": false },
      "max_batch_size": { "type": "integer", "description": "Maximum files per parallel batch", "default": 8 }
    }
  }
}
```

### `unslop_symbol_audit`

**Parameter mapping:** `original_path` -> the original/pre-change file, `generated_path` -> the generated/post-change file. The MCP tool uses clearer names but maps to `audit_symbols(original_path, generated_path, removed)`.

```json
{
  "name": "unslop_symbol_audit",
  "description": "Compare public symbols between two versions of a file. Returns added, removed, and matched symbols.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "original_path": { "type": "string", "description": "Path to the original file (before changes)" },
      "generated_path": { "type": "string", "description": "Path to the generated file (after changes)" },
      "removed": { "type": "array", "items": { "type": "string" }, "description": "Symbols expected to be removed (not flagged as missing)" }
    },
    "required": ["original_path", "generated_path"]
  }
}
```

### `unslop_check_drift`

**Parameter mapping:** Maps to `check_drift(old_path, new_path, affected_symbols)`. `affected_symbols` is the list of symbols the caller *intended* to change -- drift is flagged for anything outside that set.

```json
{
  "name": "unslop_check_drift",
  "description": "Check symbol-level drift between two file versions. Flags changes to symbols NOT in the affected list.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "old_path": { "type": "string", "description": "Path to the old version of the file" },
      "new_path": { "type": "string", "description": "Path to the new version of the file" },
      "affected_symbols": { "type": "array", "items": { "type": "string" }, "description": "Symbols expected to change (drift outside this set is flagged)" }
    },
    "required": ["old_path", "new_path", "affected_symbols"]
  }
}
```

### `unslop_discover`

```json
{
  "name": "unslop_discover",
  "description": "Find source files and test files in a directory.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "directory": { "type": "string", "description": "Directory to scan" },
      "extensions": { "type": "array", "items": { "type": "string" }, "description": "File extensions to include (e.g., [\".py\", \".rs\"])" },
      "extra_excludes": { "type": "array", "items": { "type": "string" }, "description": "Additional directory names to exclude (exact match, not glob)" }
    },
    "required": ["directory"]
  }
}
```

---

## 4. Output Shapes

All tools return JSON strings. Key output structures:

**`unslop_check_freshness`:** `{ "status": "pass"|"fail", "files": [{ "managed": str, "spec": str, "state": str, "hint"?: str, "blocked_constraints"?: [...], "pending_changes"?: {...}, "concrete_staleness"?: {...} }], "summary": str, "pending_intent_files"?: [...] }`

**`unslop_ripple_check`:** `{ "changed_specs": [str], "affected_specs": [str], "concrete_regen": [str], "ghost_stale": [str], "managed_regen": [str], "build_order": [str] }`

**`unslop_classify_file`:** `{ "managed": str, "spec": str, "state": "fresh"|"stale"|"modified"|"conflict"|"unmanaged"|"old_format"|"error", "hint"?: str }`

**`unslop_build_order`:** `[str]` -- list of spec paths in dependency order (leaves first)

**`unslop_resolve_deps`:** `[str]` -- transitive dependency spec paths (not including the target)

**`unslop_symbol_audit`:** `{ "status": "match"|"mismatch", "added": [str], "removed": [str], "matched": [str] }`

**`unslop_discover`:** `[str]` -- sorted list of file paths relative to the scanned directory (tests and build artifacts excluded)

All error responses: `{ "error": str }`

---

## 5. Implementation Pattern

Each tool follows the same pattern -- receive typed params, call the existing function, return JSON:

```python
@server.tool()
async def unslop_check_freshness(
    directory: str = ".",
    exclude_dirs: list[str] | None = None,
) -> str:
    """Check freshness of all managed files."""
    try:
        exclude = exclude_dirs or [".unslop", "node_modules"]
        result = check_freshness(directory, exclude_dirs=exclude)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
```

**Error handling:** Tools catch all exceptions and return `{ "error": "<message>" }`. The server never crashes from a tool call. The server process stays alive for subsequent calls.

**No state:** Each tool call reads from disk, computes, returns. No caching, no sessions.

**Imports:** The server is invoked as a package module (`python3 -m unslop.scripts.mcp_server`), so relative imports work naturally (`from .core.hashing import ...`, `from .freshness.checker import ...`). This matches the import pattern used by the rest of the `scripts/` package. No bootstrap hack needed (unlike `orchestrator.py` which supports direct `python orchestrator.py` execution).

---

## 6. Implementation Surface

### 6.1 Files touched

| File | Change |
|---|---|
| `scripts/mcp_server.py` | New -- the MCP server (single file, ~200 lines) |
| `.claude-plugin/.mcp.json` | New -- plugin MCP server declaration (adjacent to `plugin.json`) |
| `commands/init.md` | Add `mcp` dependency check |
| `commands/status.md` | Note MCP tool as preferred over CLI |
| `commands/generate.md` | Note MCP tool as preferred over CLI |
| `.claude-plugin/plugin.json` | Version bump 0.31.0 -> 0.32.0 |
| `tests/test_mcp_server.py` | Tests for tool dispatch and error handling |

### 6.2 Not in scope

- Removing the CLI (`orchestrator.py` stays for CI and direct use)
- Caching or stateful sessions
- Authentication or multi-user
- Exposing validation scripts as MCP tools

### 6.3 Version

Plugin version: 0.31.0 -> 0.32.0
