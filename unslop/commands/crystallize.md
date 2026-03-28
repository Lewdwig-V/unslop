---
description: Extract cross-cutting patterns from the spec corpus into project-local domain skills
argument-hint: "[directory] [--threshold N]"
---

Read the accumulated spec corpus and extract cross-cutting patterns into project-local skills. This is the inverse of distill (which reads code and produces specs) -- crystallize reads specs and produces skills.

## Prerequisites

Check that `.unslop/` exists in the current working directory. If not, abort with: "Run /unslop:init first."

## Argument Parsing

- **Optional positional argument:** A directory path to scope the analysis. If provided, only specs under that directory are scanned. If omitted, scan all specs in the project.
- **`--threshold N`:** Minimum number of specs exhibiting a pattern before crystallize proposes a skill. Overrides `config.crystallize_threshold`. Default: 3.

Read `config.crystallize_threshold` from `.unslop/config.json` as the fallback threshold if `--threshold` is not provided.

## Phase 1: Corpus Analysis (Archaeologist)

**Model:** `config.models.archaeologist` (opus for analytical pattern extraction).

The Archaeologist reads all abstract specs (or the targeted subset) and identifies:

1. **Repeated patterns:** Error handling approaches, dependency injection patterns, naming conventions, architectural layers that appear across multiple specs.
2. **Shared constraints:** Non-goals that appear in multiple specs. Dependencies that form consistent import patterns.
3. **Common language:** Terminology used consistently across specs that would benefit from a shared definition.

For each candidate pattern, the Archaeologist counts the number of specs that exhibit it.

## Phase 2: Threshold Filtering

A pattern must appear in `--threshold` or more specs (default from config or 3) to be proposed as a skill. Below the threshold, patterns are surfaced as informational findings but not proposed as skill files.

Output format:

```
Crystallize findings:

  Proposed skills (3+ occurrences):
    "typed-error-handling" -- Result<T, E> pattern in 8/12 specs
    "kafka-consumer-pattern" -- Consumer lifecycle in 4/5 consumer specs

  Informational (below threshold):
    "circuit-breaker" -- Seen in 2 specs. Not enough evidence to crystallize.
```

## Phase 3: Skill Drafting

For each proposed skill, the Archaeologist drafts a `SKILL.md` with the following structure:

```yaml
---
name: <skill-name>
description: <one-line description of the pattern>
enforcement: advisory
crystallized-from:
  - spec: <path-to-source-spec>
    pattern: "<key expression or signature from this spec>"
  - spec: <path-to-another-source-spec>
    pattern: "<key expression or signature from this spec>"
applies-to: []
---

# <Skill Title>

[Pattern description, examples, rationale extracted from the corpus]
```

The `crystallized-from:` provenance records which specs the pattern was extracted from. This is analogous to `distilled-from:` on specs -- it records epistemic origin.

Default `enforcement` is `advisory`. Default `applies-to` is `[]` (applies to all files). The user can change both during the review phase.

## Phase 4: User Review

Present each proposed skill for approval. MUST present one at a time and wait for the user's choice before proceeding.

```
Proposed skill: "typed-error-handling"
  Found in 8/12 specs. Enforcement: advisory.

  (a) Accept -- write to .unslop/skills/typed-error-handling/SKILL.md
  (p) Promote -- accept as constitutional (violations gate ratification)
  (e) Edit -- modify before accepting
  (s) Skip -- don't create this skill
```

**Option (a):** Write the skill as `advisory` to `.unslop/skills/<name>/SKILL.md`. Create the directory if it does not exist.
**Option (p):** Write the skill with `enforcement: constitutional`. This is equivalent to adding the pattern to `principles.md` but scoped via `applies-to`.
**Option (e):** Present the drafted skill content to the user for editing. After editing, write the modified version.
**Option (s):** Skip. The pattern is noted in the summary but no skill file is created.

## Re-run Semantics

If crystallize is run again after skills have already been created in `.unslop/skills/`:

- **Pattern matches an existing skill:** Offer an **amendment pass** instead of a creation pass. Show what has changed in the corpus since the skill was written -- new specs that follow the pattern, specs that no longer follow it, terminology shifts. The user can update the skill, leave it unchanged, or remove it.
- **New pattern not matching any existing skill:** Propose a new skill (normal creation flow from Phase 4).
- **Existing skill with no matching pattern in the corpus:** Flag it as a candidate for removal: "Skill '<name>' describes a pattern no longer found in the spec corpus. Remove? (y/n)"

The amendment pass updates `crystallized-from:` provenance to reflect the current corpus.

## Output

Crystallize produces:
1. Skill files in `.unslop/skills/<name>/SKILL.md` (new or amended)
2. A summary of what was proposed, accepted, amended, promoted, and skipped:

```
Crystallize complete:
  Created: typed-error-handling (advisory), kafka-consumer-pattern (advisory)
  Promoted: api-versioning (constitutional)
  Amended: existing-auth-pattern (updated provenance)
  Skipped: circuit-breaker
  Flagged for removal: stale-legacy-pattern (no corpus match)
```

Do NOT commit the created skill files. The user decides when to commit.
