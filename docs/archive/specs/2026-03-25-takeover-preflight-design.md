# Takeover Pre-flight: Large File Splitting and Protected Regions

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this spec.

**Goal:** Add a Step 0 pre-flight phase to the takeover pipeline that analyzes file complexity, proposes and executes splits for large files, and detects protected regions that the Builder must preserve verbatim during generation.

**Motivation:** Field-tested during a Rust GC takeover. Large source files (>1000 lines) cause context pressure that degrades spec quality and generation accuracy. Files with inline test blocks (common in Rust, C, C++) need a mechanism to preserve the test block during generation without including it in the spec. Both problems are solvable with a pre-flight analysis phase that runs before the Architect begins spec drafting.

---

## 1. Pre-flight Analysis (Step 0a)

Step 0 runs before the current Step 1 (Discover) in the takeover pipeline. Step 0a is the analysis phase.

### 1.1 Inputs

The target file path (or glob/directory for multi-file takeover). For multi-file takeover, Step 0a runs per-file.

### 1.2 Metrics

For each target file, the Architect computes:

1. **Line count** -- total lines in the file
2. **Public symbol count** -- using `get_symbol_manifest()` from `lsp_queries.py` (LSP-first, AST fallback for Python, guidance for other languages). Counts exported functions, public types, module-level constants.
3. **Estimated token weight** -- `file_size_bytes / 4` (rough approximation, no tokenizer needed)
4. **Protected region scan** -- detect language-conventional tail blocks (see Section 4)

### 1.3 Thresholds

Dual-trigger: either condition trips the threshold.

| Metric | Suggest split | Require split |
|---|---|---|
| Line count | >1000 | >2000 |
| Public symbols | >30 | >60 |
| Token weight | >8000 | >16000 |

**Suggest** means the Architect recommends splitting but accepts user override. **Require** means the Architect will not proceed without splitting. The user can pass `--force` to override a required split, but the skill warns that generation quality will degrade.

Thresholds are configurable in `.unslop/config.json`. Token weight thresholds are also configurable:

```json
{
  "preflight": {
    "suggest_split_lines": 1000,
    "suggest_split_symbols": 30,
    "suggest_split_tokens": 8000,
    "require_split_lines": 2000,
    "require_split_symbols": 60,
    "require_split_tokens": 16000
  }
}
```

### 1.4 No-op path

If the file is below all thresholds and has no protected regions, Step 0 is a no-op. The pipeline continues to Step 1 (Discover) unchanged.

---

## 2. Split Planning (Step 0b)

When the analysis triggers a split suggestion or requirement, the Architect drafts an interactive split plan. No files are touched until the user approves.

### 2.1 Plan presentation

```
Pre-flight analysis for src/lib.rs:
  2,247 lines | 42 public symbols | ~12k tokens
  ⚠ Exceeds suggest threshold (>1000 lines, >30 symbols)
  1 protected region detected: test block (tail, 180 lines)

Proposed split into 3 submodules + facade:

  src/parser.rs    (~800 lines, 15 symbols) -- parsing and AST construction
  src/emitter.rs   (~700 lines, 12 symbols) -- code emission and formatting
  src/utils.rs     (~400 lines, 10 symbols) -- shared helpers and constants
  src/lib.rs       (facade) -- re-exports preserving current public API

  Protected region: test block stays in src/lib.rs (tests integration scope)

  Proceed with split? (y/n/edit)
```

### 2.2 Split plan rules

- **API preservation is the prime directive.** Every public symbol that was accessible via the original module path MUST remain accessible after the split. The facade file re-exports everything.
- **The Architect groups by cohesion**, not by size. Symbols that call each other heavily belong in the same submodule. The Architect reads the file's internal call graph to make this determination.
- **Protected regions stay in the facade** by default. The test block typically needs access to all re-exports -- the facade is the right home. The user can override this during the "edit" step.
- **Naming follows language convention.** The Architect proposes submodule names that match the language's idiomatic module naming (snake_case for Rust/Python, camelCase for JS/TS, etc.).
- **The user can edit the plan.** "edit" lets the user rename modules, move symbols between groups, or exclude symbols from the split. The Architect regenerates the plan after edits.

### 2.3 What the plan does NOT do

- Change any logic, signatures, or behavior
- Rename any public symbols
- Add or remove functionality
- Touch files outside the target

---

## 3. Split Execution (Step 0c)

After the user approves the plan, the Architect executes the physical refactor. This is purely mechanical -- move code blocks, write re-exports, verify compilation.

### 3.1 Execution sequence

1. **Create submodule files** -- For each proposed submodule, create the file and move the assigned symbol blocks into it. Preserve internal ordering within each group.

2. **Write the facade** -- Replace the original file's implementation content with re-exports. The facade imports from each submodule and re-exports every public symbol at the original path. Internal (non-public) symbols that are shared across submodules get appropriate internal visibility in their new home (e.g., `pub(crate)` in Rust, module-level in Python).

3. **Update internal references** -- If submodule A calls a function that moved to submodule B, add the appropriate import. The Architect traces internal call dependencies from the split plan.

4. **Verify compilation** -- Run the project's build check command (from `.unslop/config.json`, e.g., `cargo check`, `tsc --noEmit`, `python -m py_compile`). If the build check command is not configured, ask the user for it.

5. **Verify test pass** -- If tests exist, run them. The split MUST be behavior-preserving -- any test failure means the split broke something. If tests fail, the Architect reports the failure and rolls back.

6. **Commit the split** -- Atomic commit with message: `refactor: split <file> into submodules (pre-takeover)`. This is a standalone commit -- separate from the takeover commits that follow. If the split needs to be reverted later, it's one `git revert`.

### 3.2 Rollback on failure

If compilation or tests fail at step 4 or 5:

- Delete all created submodule files
- Restore the original file from git (`git checkout -- <file>`)
- Report the failure with the compiler/test error
- Offer options:

```
Split failed: <error>

Options:
  1. Fix the issue and retry
  2. Proceed with takeover on the unsplit file (quality may degrade)
  3. Abort
```

Option 2 is only available if the file is below the "require" threshold. Above it, only options 1 and 3 are offered.

### 3.3 Post-split handoff

After successful split, the Architect queues the submodules for individual takeover:

```
Split complete. 3 submodules created, build check passes, 47 tests pass.
Committed: refactor: split src/lib.rs into submodules (pre-takeover)

Queuing takeover for 4 files:
  1. src/parser.rs (800 lines)
  2. src/emitter.rs (700 lines)
  3. src/utils.rs (400 lines)
  4. src/lib.rs (facade, ~30 lines -- re-exports only)

Proceeding with src/parser.rs...
```

The facade file is taken over last, since its spec is trivial (re-exports only) and its concrete spec may reference the submodule specs. The Architect queues the facade last explicitly, regardless of `build-order` output. The facade spec SHOULD declare `depends-on` entries for each submodule spec so that future `build-order` runs respect the dependency naturally.

---

## 4. Protected Regions

Protected regions are contiguous blocks within a file that the spec does not describe and the Builder does not touch. They survive generation verbatim.

### 4.1 Discovery

During Step 0a analysis, the Architect identifies protected regions by reading the file. The detection is semantic, not syntactic -- the Architect looks for "a tail block that serves a different purpose than the implementation above it" rather than pattern-matching specific tokens.

Common patterns (language-agnostic descriptions):

| Pattern | Position | Semantics | Typical languages |
|---|---|---|---|
| Compile-time test conditional | tail | test-suite | Rust, C, C++ |
| Main entry guard | tail | entry-point | Python |
| Example/benchmark blocks | tail | examples | Go, Rust |

The skill describes these as "tail blocks gated by a compile-time or runtime conditional that separates implementation from a conventionally co-located concern." No language-specific syntax appears in the skill prose -- the Architect identifies them by reading the file.

### 4.2 Concrete spec frontmatter

```yaml
protected-regions:
  - marker: "compile-time test conditional"
    position: tail
    semantics: test-suite
    starts-at: "line 847"
```

**Fields (all required):**

- **`marker`** -- human-readable description of what delineates the region. Language-agnostic.
- **`position`** -- `tail` (end of file). No mid-file regions -- that's a sign the file should be split instead.
- **`semantics`** -- what the region is for. One of: `test-suite`, `entry-point`, `examples`, `benchmarks`.
- **`starts-at`** -- line reference so the Builder knows where implementation ends. Updated on each generation.

### 4.3 Generation behavior

When the Builder sees `protected-regions` in the concrete spec:

1. **Read the existing file and extract the protected region into memory** -- MUST read and hold the protected region before writing any output. Extract everything from `starts-at` to EOF for `tail` position. This step is a hard ordering invariant -- the existing file is about to be overwritten.
2. Generate the implementation portion normally
3. Append the protected region verbatim after the generated code
4. **Verify the protected region is present** -- Confirm the protected region appears in the output file. If the region is missing or truncated, report BLOCKED. Do not report DONE with a partial file.
5. **Compute line boundary** -- Count the 1-indexed line number where the protected region starts in the final output. Write this as `managed-end-line` in the `@unslop-managed` header.
6. **Update `starts-at`** -- Write the same line number back to the concrete spec frontmatter's `starts-at` field. This keeps the concrete spec in sync for the next generation cycle. This is a separate write to the concrete spec file after the managed file is written.
7. Compute `output-hash` over the implementation portion only (lines from below the header to `managed-end-line - 1`, excluding the protected region)

### 4.4 `output-hash` boundary

The `output-hash` exclusion is critical. If we hash the protected region, then any manual edit to an inline test would show the file as "modified" in `/unslop:status`, even though the managed implementation hasn't changed. The protected region is explicitly outside unslop's management scope.

To communicate the boundary to the freshness checker, the Builder writes a `managed-end-line` field in the `@unslop-managed` header:

```
// @unslop-managed -- do not edit directly. Edit src/foo.rs.spec.md instead.
// spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 managed-end-line:846 generated:2026-03-25T12:00:00Z
```

The `managed-end-line` value is the 1-indexed line number where the protected region starts (the first line of the protected region). The freshness checker hashes only lines from below the header up to but not including `managed-end-line` (i.e., `lines[body_start : managed_end_line - 1]`). The Builder computes `output-hash` over the same range. Lines from `managed-end-line` onward are the protected region -- invisible to the freshness system.

If `managed-end-line` is absent (no protected regions), the checker hashes the entire body as it does today. Fully backward-compatible.

### 4.5 What protected regions are NOT

- **Not for mid-file blocks.** If the implementation is interleaved with tests or examples, that's a structural problem -- split the file first.
- **Not for code the Builder should conditionally generate.** That's what `blocked-by` is for.
- **Not for imports or headers.** The `@unslop-managed` header is a separate mechanism.
- **Not editable by the Builder.** The Builder copies the protected region verbatim. Never modifies, reformats, or reorders.

### 4.6 Interaction with split

If a file is split in Step 0c, protected regions are assigned to the appropriate submodule:

- Test blocks typically stay in the facade (they test integrated behavior via re-exports)
- Entry-point guards stay in the file that contains the entry point
- The user can override assignment during the "edit" step of the split plan

---

## 5. Implementation Surface

### 5.1 Files touched

| File | Change |
|---|---|
| `skills/takeover/SKILL.md` | Add Step 0 (0a, 0b, 0c) before current Step 1 |
| `skills/generation/SKILL.md` | Protected region handling in Builder instructions; `managed-end-line` header field |
| `skills/concrete-spec/SKILL.md` | Document `protected-regions` frontmatter field |
| `scripts/core/frontmatter.py` | Parse `protected-regions` in `parse_concrete_frontmatter` |
| `scripts/core/hashing.py` | `get_body_below_header` gains optional `end_line` parameter for `managed-end-line` support |
| `scripts/freshness/checker.py` | Parse `managed-end-line` from header; hash only up to that line |
| `tests/test_orchestrator.py` | Parser tests for `protected-regions`; freshness tests for `managed-end-line` |
| `.claude-plugin/plugin.json` | Version bump |

### 5.2 Parser design

`protected-regions` parsing follows the same pattern as `targets` and `blocked-by` in `parse_concrete_frontmatter`:

- **State variables:** `in_protected_regions: bool`, `current_region: dict | None`
- **Entry delimiter regex:** `r"^  - marker:"`
- **Sub-fields:** `position`, `semantics`, `starts-at` at 4-space indent
- **Result:** `result["protected_regions"]` as `list[dict]` with keys `marker`, `position`, `semantics`, `starts_at`
- **Validation:** entries missing any required field emit a stderr warning and are skipped. If `semantics` contains a value not in the allowed set (`test-suite`, `entry-point`, `examples`, `benchmarks`), emit a stderr warning but keep the entry -- the value is informational for the Builder and does not affect mechanical behavior

### 5.3 Freshness checker design

**`parse_header` changes:** Returns a new key `managed_end_line: int | None`, extracted via `re.search(r"managed-end-line:(\d+)", stripped)`. The value is a 1-indexed line number in the original file content.

**`get_body_below_header` changes:** Gains an optional `end_line: int | None` parameter. When provided, returns `"\n".join(lines[body_start : end_line - 1])` (non-inclusive of the end line itself, which is the first line of the protected region). The `end_line` value is 1-indexed, matching the convention in the header.

**Checker wiring:** `classify_file` reads `header.get("managed_end_line")` and passes it to `get_body_below_header` when computing `current_output_hash`. If `managed_end_line` is `None` (no protected regions), behavior is identical to today -- hash the full body. Fully backward-compatible.

**Key invariant:** `managed-end-line` in the managed file header and `starts-at` in the concrete spec frontmatter refer to the same 1-indexed line number. The Builder writes both during generation (see section 4.3 steps 5-6). The checker uses only `managed-end-line` from the header -- it never reads the concrete spec during freshness checks.

### 5.4 Test scenarios

Required test cases for the implementation:

1. **`protected-regions` parse round-trip** -- frontmatter with all four required fields parses correctly; result contains `marker`, `position`, `semantics`, `starts_at`
2. **`protected-regions` missing field** -- entry missing a required field emits stderr warning and is skipped
3. **`protected-regions` unknown semantics** -- entry with invalid `semantics` value emits warning but is kept in result
4. **`managed-end-line` present** -- freshness checker hashes only lines from below header to `managed-end-line - 1`; edits to lines after `managed-end-line` do not change the hash
5. **`managed-end-line` absent** -- behavior is identical to current (full body hash, backward compat)
6. **Protected region edited manually** -- file has `managed-end-line`, user edits lines after it; checker reports `fresh` (not `modified`)

### 5.5 Not in scope

- Mid-file protected regions
- Automatic split without user approval
- Changes to the abstract spec format (protected regions live in concrete spec only)
- Protected region editing by the Builder
- Automated detection of optimal split boundaries (the Architect uses judgment informed by metrics)

### 5.6 Version

Plugin version: 0.24.0 -> 0.25.0
