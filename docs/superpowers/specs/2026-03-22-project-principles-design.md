# Project Principles Design (Milestone D)

> A project-level principles document that defines non-negotiable generation constraints, tracked via hash in every managed file header.

**Closes:** Milestone D from the extended roadmap. Inspired by Spec Kit's constitution concept.

## Problem

The ambiguity linter (Phase 0b) catches per-spec ambiguity. But cross-project consistency -- constraints that apply to every managed file -- requires repeating the same rules in every spec. A spec that says "handle errors" is ambiguous without a project-wide rule saying "errors must be typed." Principles provide that project-wide context once, enforced everywhere.

## What

`.unslop/principles.md` -- a freeform markdown file defining non-negotiable generation constraints. Committed to git. Hashed and tracked in every managed file's `@unslop-managed` header.

### Format

```markdown
# Project Principles

## Architecture
- Favor composition over inheritance
- No global mutable state
- All modules must be independently testable

## Error Handling
- Errors must be typed -- no bare Exception catches
- Fail fast on invalid input at system boundaries

## Style
- All public functions must have docstrings
- Prefer immutable data structures where practical
```

No frontmatter, no required structure. Headings are for human organization. The model reads the entire file as context.

## Header Format Extension

The `@unslop-managed` header gains an optional `principles-hash` field:

```python
# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.
# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7f2e1b8a9c04 generated:2026-03-22T14:32:00Z
```

- `principles-hash`: SHA-256 of `.unslop/principles.md` content, truncated to 12 hex chars
- Computed at generation time, stored alongside `spec-hash` and `output-hash`
- If `principles.md` doesn't exist, the field is omitted (backwards compatible)

## Staleness Classification Update

The classification algorithm gains a principles dimension. A file's freshness now requires all three hashes to match:

```
is_fresh = spec_matches AND output_matches AND principles_matches
```

If `principles-hash` in the header doesn't match the current `principles.md` hash, the file is stale regardless of spec/output state. This is global -- every managed file with a mismatched `principles-hash` is stale.

### Display in status

```
Managed files:
  stale    src/retry.py        <- src/retry.py.spec.md (principles changed)
  stale    src/parser.py       <- src/parser.py.spec.md (principles changed)
  fresh    src/utils.py        <- src/utils.py.spec.md
```

When principles change, most/all managed files will show as stale. This is intentional -- a principle change is a project-wide event that requires re-evaluation.

### In check-freshness

`classify_file` computes a third hash comparison:

```python
principles_path = root / ".unslop" / "principles.md"
if principles_path.exists():
    current_principles_hash = compute_hash(principles_path.read_text(encoding="utf-8"))
    stored_principles_hash = header.get("principles_hash")
    if stored_principles_hash and current_principles_hash != stored_principles_hash:
        # File is stale due to principles change
```

Files without `principles-hash` in the header skip this check (backwards compatible with pre-Milestone-D files).

## Integration Points

### Generation skill

- **Phase 0b (ambiguity detection)**: Read `principles.md` as context before reviewing the spec. Check whether the spec contradicts any principle.
- **Sections 1-6 (generation)**: Inject `principles.md` content into the generation context alongside the spec. The model uses principles as additional constraints when generating code.
- **Header writing**: Compute `principles-hash` and include in the header alongside `spec-hash` and `output-hash`.

### `/unslop:change --tactical`

The tactical flow bypasses the generation skill. It must explicitly load and enforce `principles.md`:
- Read `principles.md` before patching the managed file
- Apply principles as constraints during the direct patch
- Include `principles-hash` when updating the header

### `/unslop:init`

- Creates a starter `.unslop/principles.md` with common defaults
- Asks the user: "Would you like to define project principles? These are non-negotiable constraints that apply to all generated code (e.g., error handling style, architecture patterns)."
- If yes: present a starter template, let the user edit
- If no: skip (principles are optional)

### `orchestrator.py`

- `classify_file`: Compare `principles-hash` from header against current `principles.md` hash
- `check-freshness`: Same principles check, global across all files
- `parse_header`: Extract `principles_hash` field from header line 2 (regex: `principles-hash:([0-9a-f]{12})`)

### `/unslop:status`

- Shows `(principles changed)` annotation when principles-hash mismatches
- Shows the count of principle-stale files in the summary

## Backwards Compatibility

- **Files without `principles-hash`**: Skip the principles check. These files were generated before principles existed. They become principle-stale on their next regeneration (which adds the hash).
- **Projects without `principles.md`**: Everything works as before. No principles context injected, no principles hash computed, no staleness check.
- **`init` on existing projects**: Offers to create principles.md but doesn't require it.
- **Old `parse_header` callers**: The `principles_hash` field is `None` when not present -- same pattern as `spec_hash`/`output_hash` for old-format headers.

## Plugin Structure Changes

```
unslop/
├── commands/
│   └── init.md               # MODIFIED -- creates principles.md
├── skills/
│   └── generation/
│       └── SKILL.md           # MODIFIED -- reads principles, writes principles-hash
├── commands/
│   ├── change.md              # MODIFIED -- loads principles in tactical flow
│   └── status.md              # MODIFIED -- shows principles-stale state
└── scripts/
    └── orchestrator.py        # MODIFIED -- principles-hash in parse_header, classify_file, check-freshness
```
