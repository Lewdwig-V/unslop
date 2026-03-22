# Quality Gates Design (Milestone A)

> Pre-generation validation, ambiguity detection, and post-generation completeness review — three gates that catch spec problems before they produce wrong code.

## Problem

Ambiguous specs silently produce wrong code. Insufficient specs waste generation cycles. Under-specified machine-drafted specs produce inconsistent output across regenerations. There is no pre-flight check, no semantic review, and no post-generation tightening prompt. The gap analysis identifies these as the highest-leverage, lowest-cost improvements to unslop's output quality.

## Scope

Three quality gates added to the generation skill as a pre-flight checklist (Section 0) and a post-generation review (Section 7). No new commands, no new skills — this extends the existing generation skill with clearly demarcated subtasks. One new script (`validate-spec.py`) handles the deterministic checks.

## Architecture

The generation skill gains two new sections wrapping the existing pipeline:

```
Section 0: Pre-Generation Validation
  Phase 0a: Structural Validation (deterministic script)
  Phase 0b: Ambiguity Detection (LLM judgment)

Sections 1-6: Existing generation pipeline (unchanged)

Section 7: Post-Generation Review
  Completeness review (LLM judgment)
```

Every entry path (generate, sync, takeover) flows through the generation skill, so all three gates apply automatically.

## Phase 0a: Structural Validation

A deterministic Python script at `unslop/scripts/validate-spec.py`. Same pattern as `orchestrator.py` — pure function, JSON output, zero dependencies.

### Interface

```bash
python validate-spec.py <spec-path>
# Exit 0 + JSON: validation passed
# Exit 1 + JSON: validation failed
```

### Checks

| Check | Rule | Rationale |
|---|---|---|
| Minimum length | Spec body (below frontmatter) must have >3 non-blank lines | Catches empty saves, placeholder specs |
| Required sections | Must have at least one of: `## Behavior`, `## Constraints`, `## Purpose`, `## Requirements` | A spec with none of these has no testable content |
| Code fence misuse | Code fences not inside a section titled "Example" or "Examples" trigger a warning | Catches over-specified specs containing implementation code |
| Open Questions validity | If `## Open Questions` exists, it must have at least one list item | Empty Open Questions section is likely an editing artifact |

### Output format

Pass:
```json
{
  "status": "pass",
  "spec_path": "src/retry.py.spec.md"
}
```

Fail:
```json
{
  "status": "fail",
  "spec_path": "src/retry.py.spec.md",
  "issues": [
    {"check": "minimum_length", "message": "Spec body has only 2 non-blank lines (minimum 3)"},
    {"check": "required_sections", "message": "No Behavior, Constraints, Purpose, or Requirements section found"}
  ]
}
```

### Blocking behavior

**Always blocking. No override.** A spec that fails structural checks will produce bad code regardless. If the user disagrees with a check, they fix the spec — not bypass the gate.

### What the script does NOT check

- Ambiguity — that requires judgment (Phase 0b)
- Spec quality — whether constraints are good or sufficient
- Dependencies — that's the orchestrator's job

## Phase 0b: Ambiguity Detection

LLM-driven semantic review. Lives as instructions in the generation skill's new Section 0, after the structural validation passes.

### Review prompt

The generation skill reviews the spec with this focus:

> "Review this spec for semantic ambiguity — places where a reasonable implementer could make two substantively different choices that both satisfy the spec text. Be specific: quote the ambiguous phrase and describe the two interpretations.
>
> Do NOT flag:
> - Implementation choices left deliberately open (data structures, algorithms, variable names) — these are correctly vague per the spec-language skill
> - Items explicitly marked with `[open]` inline
> - Items listed in the `## Open Questions` section
>
> DO flag:
> - Behavioral ambiguity: "retries on failure" — what counts as failure?
> - Constraint ambiguity: "handles large inputs" — what is large? No bound specified.
> - Contract ambiguity: "returns an error" — what kind? Exception? Error code? None/null?"

### Open Question exemptions

Two patterns exempt an ambiguity from blocking:

**Inline marker:** `[open]` anywhere on the same line as the ambiguous text.
```markdown
Caching strategy uses an appropriate eviction policy [open]
```

**Section listing:**
```markdown
## Open Questions
- Whether to use LRU or LFU eviction — will benchmark after first deployment
- Error retry backoff curve — depends on upstream SLA negotiations
```

The linter scans for both patterns before running the ambiguity review. Ambiguities that match an Open Question (by topic overlap, not exact string match) are excluded from the block list.

### Result handling

- **No ambiguities found:** Proceed. Report: "Spec passed ambiguity review."
- **Ambiguities found, all covered by Open Questions:** Proceed with a note: "Spec has N open questions acknowledged. Proceeding."
- **Ambiguities found, some NOT covered:** Block generation. Report each uncovered ambiguity with the quoted phrase and two interpretations. Tell the user:

> "Found N ambiguities not marked as open questions. Either:
> 1. Resolve them by editing the spec to be more specific
> 2. Mark them as intentionally open with `[open]` or add to `## Open Questions`
> 3. Override with `--force-ambiguous` (not recommended)"

### The `--force-ambiguous` escape hatch

Commands pass this flag through to the generation skill. When set, ambiguities are reported as warnings but don't block. Exists for cases where the user knows the spec is good enough and doesn't want to annotate every flexibility point.

## Section 7: Post-Generation Completeness Review

Runs after successful generation and green tests. Advisory only — never blocks.

### Two modes

**Post-takeover mode** (spec was machine-drafted):

The review asks:
- Are there behavioral aspects of the generated code not constrained by the spec? A future regeneration might produce different behavior in those areas.
- Are there constraints added during convergence that could be stated more precisely?
- Does the spec leave behavioral choices open that should be pinned down for reproducibility?

Suggestions are framed as: "Consider adding: [constraint]" with a brief rationale.

**Post-generate/sync mode** (spec was user-written):

The review asks:
- Are there internal contradictions? (e.g., "max 5 retries" in one place, "retries indefinitely" in another)
- Do constraints conflict with `depends-on` specs?
- Does the spec reference behavior or concepts not defined anywhere in the spec?

Only flags clear contradictions or inconsistencies. Does NOT suggest additions or tightening — the user wrote this spec deliberately.

### Result handling

- **No issues found:** Report "Spec review: no issues" and proceed.
- **Issues found:** Surface as suggestions:

> "Post-generation spec review found N suggestions:
> 1. Consider adding: [constraint] — [rationale]
> 2. Possible inconsistency: [quoted phrase A] vs [quoted phrase B]"

**Never blocks.** The generation succeeded, tests are green — the spec is functionally correct.

### Future: `/unslop:harden`

A natural companion command that runs the post-takeover completeness review on demand, on any spec. Not part of this milestone — but the skill infrastructure supports it directly.

## Spec-Language Skill Updates

The spec-language skill gains one new section and a skeleton template update.

### New section: "Open Questions"

Added after the existing "Register Check" section. Teaches spec authors when and how to mark intentional ambiguity:

- **Inline:** `[open]` on the same line as the flexible statement
- **Section:** `## Open Questions` with listed items and rationale
- Guidance: use for decisions that depend on unavailable information or are genuinely implementation-preference. Do NOT use to dodge spec writing.

### Skeleton template update

Add an optional `## Open Questions` section:
```markdown
## Open Questions
[Decisions intentionally deferred — remove this section if none]
```

## Plugin Structure Changes

```
unslop/
├── scripts/
│   ├── orchestrator.py       # unchanged
│   └── validate-spec.py      # new — structural spec validation
├── skills/
│   ├── generation/
│   │   └── SKILL.md          # updated — Section 0 (pre-gen) + Section 7 (post-gen)
│   └── spec-language/
│       └── SKILL.md          # updated — Open Questions guidance
├── commands/                  # unchanged — gates are in the skill, not commands
└── hooks/                     # unchanged
```

## Backwards Compatibility

- All existing specs continue to work. Specs without Open Questions are reviewed normally.
- Structural validation may flag very minimal existing specs — but those specs would produce bad code anyway.
- The `--force-ambiguous` flag is additive to existing commands.
- No changes to commands, hooks, or the orchestrator.
