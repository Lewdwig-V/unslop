# Quality Gates Implementation Plan (Milestone A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three quality gates to the generation pipeline — structural validation (script), ambiguity detection (LLM), and post-generation completeness review (LLM) — that catch spec problems before they produce wrong code.

**Architecture:** A new `validate-spec.py` script handles deterministic structural checks. The generation skill gains Section 0 (pre-generation: structural + ambiguity) and Section 7 (post-generation: completeness review). The spec-language skill gains Open Questions guidance. Three commands get minor `--force-ambiguous` flag support.

**Tech Stack:** Python 3.8+ (stdlib only), Claude Code plugin markdown.

**Spec:** `docs/superpowers/specs/2026-03-22-quality-gates-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `unslop/scripts/validate-spec.py` | Create | Deterministic structural spec validation |
| `tests/test_validate_spec.py` | Create | Unit tests for validate-spec.py |
| `unslop/skills/generation/SKILL.md` | Modify | Add Section 0 (pre-gen) and Section 7 (post-gen) |
| `unslop/skills/spec-language/SKILL.md` | Modify | Add Open Questions section + skeleton update |
| `unslop/commands/generate.md` | Modify | Accept `--force-ambiguous` |
| `unslop/commands/sync.md` | Modify | Accept `--force-ambiguous` |
| `unslop/commands/takeover.md` | Modify | Accept `--force-ambiguous` |

---

### Task 1: Structural Validator — Core Checks

**Files:**
- Create: `unslop/scripts/validate-spec.py`
- Create: `tests/test_validate_spec.py`

- [ ] **Step 1: Write failing tests for all four checks**

```python
# tests/test_validate_spec.py
from __future__ import annotations

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from validate_spec import validate_spec


def test_pass_valid_spec():
    content = """# retry.py spec

## Purpose
Exponential backoff retry wrapper with jitter.

## Behavior
Retries failed operations up to 5 times with exponential backoff.
Jitter is added to prevent thundering herd.

## Constraints
Maximum 5 attempts. Base delay 1 second. Max delay 30 seconds.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "pass"


def test_fail_too_short():
    content = """# spec

Short.
"""
    result = validate_spec(content, "src/short.py.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "minimum_length" for i in result["issues"])


def test_fail_exactly_three_non_blank_lines():
    content = """# spec

## Purpose
Does stuff.
"""
    result = validate_spec(content, "src/edge.py.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "minimum_length" for i in result["issues"])


def test_pass_exactly_four_non_blank_lines():
    content = """# spec

## Purpose
Does stuff.
More detail here.
"""
    result = validate_spec(content, "src/edge.py.spec.md")
    assert result["status"] in ("pass", "warn")


def test_fail_no_substantive_section():
    content = """# retry.py spec

This is just a title with some prose underneath it but no
actual headings with content. It goes on for several lines
but none of them are under a ## heading.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "required_sections" for i in result["issues"])


def test_fail_heading_with_only_one_content_line():
    content = """# retry.py spec

## Error Handling
Raises RetryExhausted.

This line is outside all headings so doesn't count.
And this one too. And another to pass minimum length.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "required_sections" for i in result["issues"])


def test_pass_any_heading_with_content():
    content = """# retry.py spec

## Error Handling
Raises RetryExhausted after max attempts.
Surface the original exception as the cause.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] in ("pass", "warn")


def test_warn_code_fence_with_implementation():
    content = """# retry.py spec

## Behavior
Retries failed operations.

```python
def retry(fn, max_attempts=5):
    for i in range(max_attempts):
        try:
            return fn()
        except Exception:
            time.sleep(2**i)
```
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "warn"
    assert any(w["check"] == "code_fence_misuse" for w in result["warnings"])


def test_pass_code_fence_with_data_example():
    content = """# api.py spec

## Behavior
Returns JSON responses.

## Examples
```json
{"status": "ok", "data": [1, 2, 3]}
```
"""
    result = validate_spec(content, "src/api.py.spec.md")
    assert result["status"] == "pass"


def test_fail_empty_open_questions():
    content = """# retry.py spec

## Behavior
Retries failed operations up to 5 times.

## Open Questions
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "open_questions_empty" for i in result["issues"])


def test_pass_open_questions_with_items():
    content = """# retry.py spec

## Behavior
Retries failed operations up to 5 times.

## Open Questions
- Whether to use linear or exponential backoff — will benchmark
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] in ("pass", "warn")


def test_frontmatter_excluded_from_body():
    content = """---
depends-on:
  - src/other.py.spec.md
---

# retry.py spec

## Behavior
Retries failed operations up to 5 times.
Backoff with jitter.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] in ("pass", "warn")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_validate_spec.py -v`
Expected: FAIL — `validate_spec` module not found

- [ ] **Step 3: Implement validate_spec**

Create `unslop/scripts/validate-spec.py`:

```python
"""unslop validate-spec — deterministic structural validation for spec files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Patterns that suggest implementation code rather than data examples
IMPLEMENTATION_PATTERNS = [
    re.compile(r'^\s*(def |class |import |from .+ import |if |for |while |try:|except |return )'),
    re.compile(r'^\s*(function |const |let |var |export |async )'),
    re.compile(r'^\s*(fn |pub |use |mod |impl |struct |enum )'),
    re.compile(r'^\s*(func |package |type .+ struct)'),
]


def validate_spec(content: str, spec_path: str) -> dict:
    """Validate a spec file's structure.

    Returns dict with:
      status: "pass" | "warn" | "fail"
      spec_path: the input path
      issues: list of blocking issues (on fail)
      warnings: list of non-blocking warnings (on warn)
    """
    issues = []
    warnings = []

    # Strip frontmatter
    body = content
    lines = content.split("\n")
    if lines and lines[0].strip() == "---":
        end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end != -1:
            body = "\n".join(lines[end + 1:])

    body_lines = body.split("\n")
    non_blank = [l for l in body_lines if l.strip()]

    # Check 1: Minimum length
    if len(non_blank) <= 3:
        issues.append({
            "check": "minimum_length",
            "message": f"Spec body has only {len(non_blank)} non-blank lines (minimum 4)"
        })

    # Check 2: Required sections — at least one ## heading with >1 line of content
    has_substantive_section = False
    current_heading = None
    content_lines_under_heading = 0
    for line in body_lines:
        if re.match(r'^## ', line):
            if current_heading and content_lines_under_heading > 1:
                has_substantive_section = True
            current_heading = line
            content_lines_under_heading = 0
        elif current_heading and line.strip():
            content_lines_under_heading += 1
    # Check last heading
    if current_heading and content_lines_under_heading > 1:
        has_substantive_section = True

    if not has_substantive_section:
        issues.append({
            "check": "required_sections",
            "message": "No heading found with substantive content (need at least one ## heading with >1 non-blank line below it)"
        })

    # Check 3: Code fence misuse
    in_fence = False
    fence_start = -1
    fence_lines = []
    for i, line in enumerate(body_lines):
        if line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = i
                fence_lines = []
            else:
                # Check if fence content looks like implementation
                has_impl = any(
                    pat.search(fl) for fl in fence_lines
                    for pat in IMPLEMENTATION_PATTERNS
                )
                if has_impl:
                    warnings.append({
                        "check": "code_fence_misuse",
                        "message": f"Code fence at line {fence_start + 1} may contain implementation code rather than a data example"
                    })
                in_fence = False
                fence_lines = []
        elif in_fence:
            fence_lines.append(line)

    # Check 4: Open Questions validity
    in_open_questions = False
    has_oq_items = False
    for line in body_lines:
        if re.match(r'^## Open Questions', line):
            in_open_questions = True
            continue
        if in_open_questions:
            if re.match(r'^## ', line):
                break
            if re.match(r'^\s*-\s+\S', line):
                has_oq_items = True
    if in_open_questions and not has_oq_items:
        issues.append({
            "check": "open_questions_empty",
            "message": "## Open Questions section exists but has no list items"
        })

    # Build result
    if issues:
        return {"status": "fail", "spec_path": spec_path, "issues": issues}
    elif warnings:
        return {"status": "warn", "spec_path": spec_path, "warnings": warnings}
    else:
        return {"status": "pass", "spec_path": spec_path}


def main():
    if len(sys.argv) < 2:
        print("Usage: validate-spec.py <spec-path>", file=sys.stderr)
        sys.exit(1)

    spec_path = sys.argv[1]
    try:
        content = Path(spec_path).read_text()
    except (OSError, UnicodeDecodeError) as e:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "read_error", "message": str(e)}]}))
        sys.exit(1)

    result = validate_spec(content, spec_path)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
```

Note: The import in tests uses `validate_spec` (underscore) as the module name, but the file is `validate-spec.py` (hyphen). The test's `sys.path.insert` handles this, but the import statement needs the module name with underscores. The implementer should name the module file `validate_spec.py` (with underscore) for importability, or adjust the test import accordingly. **Use `validate_spec.py` as the filename** for Python import compatibility.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_validate_spec.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Test CLI**

```bash
echo '# short spec' | python unslop/scripts/validate_spec.py /dev/stdin
```
Expected: JSON with `"status": "fail"`, exit code 1

- [ ] **Step 6: Commit**

```bash
git add unslop/scripts/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: add structural spec validator with tests"
```

---

### Task 2: Update spec-language Skill — Open Questions

**Files:**
- Modify: `unslop/skills/spec-language/SKILL.md`

- [ ] **Step 1: Add Open Questions section after "Register Check"**

Insert the following after the "Register Check" section (after line 52 of the current file) and before "Suggested Headings":

```markdown
## Open Questions

When a spec intentionally leaves a decision open, mark it explicitly. This prevents the ambiguity linter from blocking generation on deliberate flexibility.

Two mechanisms:

**Inline marker** — add `[open]` on the same line as the flexible statement:

```
Caching strategy uses an appropriate eviction policy [open]
```

**Dedicated section** — list broader open questions with rationale:

```markdown
## Open Questions
- Whether to use LRU or LFU eviction — will benchmark after first deployment
- Error retry backoff curve — depends on upstream SLA negotiations
```

Use Open Questions for decisions that:
- Depend on information not yet available (benchmarks, SLA negotiations, API design not finalized)
- Are genuinely implementation-preference (any reasonable choice is fine)
- Will be resolved in a future spec revision

Do NOT use Open Questions to dodge spec writing. If a constraint is knowable now, specify it. The ambiguity linter will flag abusive use of `[open]` on constraints that clearly need pinning down.
```

- [ ] **Step 2: Add Open Questions to the skeleton template**

Append to the skeleton template, after `## Error Handling`:

```markdown

## Open Questions
[Decisions intentionally deferred — remove this section if none]
```

- [ ] **Step 3: Commit**

```bash
git add unslop/skills/spec-language/SKILL.md
git commit -m "feat: add Open Questions guidance and skeleton section to spec-language skill"
```

---

### Task 3: Update Generation Skill — Section 0 (Pre-Generation Validation)

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Add Section 0 before existing Section 1**

Insert the following between the introductory text ("You are generating a managed source file...") and the existing "## 1. Generation Mode Selection":

```markdown
## 0. Pre-Generation Validation

Before generating any code, validate the spec. This section runs first — if validation fails, no code is written.

### Phase 0a: Structural Validation

Call the structural validator script:

```
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_spec.py <spec-path>
```

Read the JSON output:
- **`"status": "pass"`** — proceed to Phase 0b.
- **`"status": "warn"`** — surface warnings to the user, then proceed to Phase 0b.
- **`"status": "fail"`** — **stop immediately.** Report the issues to the user. Do not generate code. Tell them: "Spec failed structural validation. Fix the issues above and re-run."

There is no override for structural validation failures.

### Phase 0b: Ambiguity Detection

After structural validation passes, review the spec for semantic ambiguity.

**Before reviewing**, scan the spec for Open Question exemptions:
1. Collect all lines containing `[open]` — these phrases are exempt
2. Collect all items listed under a `## Open Questions` section — these topics are exempt

**Then review the spec** with this focus:

> Review this spec for semantic ambiguity — places where a reasonable implementer could make two substantively different choices that both satisfy the spec text. Be specific: quote the ambiguous phrase and describe the two interpretations.
>
> Do NOT flag:
> - Implementation choices left deliberately open (data structures, algorithms, variable names) — these are correctly vague
> - Items marked with `[open]` inline
> - Items listed in the `## Open Questions` section
> - Topics that overlap with Open Questions items (match by topic, not exact string)
>
> DO flag:
> - Behavioral ambiguity: "retries on failure" — what counts as failure?
> - Constraint ambiguity: "handles large inputs" — what is large? No bound specified.
> - Contract ambiguity: "returns an error" — what kind? Exception? Error code? None/null?

**Result handling:**

- **No ambiguities found:** Report "Spec passed ambiguity review." Proceed to Section 1.
- **Ambiguities found, all covered by Open Questions:** Report "Spec has N open questions acknowledged. Proceeding." Proceed to Section 1.
- **Ambiguities found, some NOT covered:**
  - If `--force-ambiguous` was passed: report ambiguities as warnings, proceed to Section 1.
  - Otherwise: **stop generation.** Report each uncovered ambiguity with the quoted phrase and two interpretations. Tell the user:

> "Found N ambiguities not marked as open questions. Either:
> 1. Resolve them by editing the spec to be more specific
> 2. Mark them as intentionally open with `[open]` or add to `## Open Questions`
> 3. Override with `--force-ambiguous` (not recommended)"

---
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Section 0 pre-generation validation to generation skill"
```

---

### Task 4: Update Generation Skill — Section 7 (Post-Generation Review)

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

- [ ] **Step 1: Append Section 7 at the end of the file**

Add after the existing Section 6 (Multi-File Generation):

```markdown

---

## 7. Post-Generation Completeness Review

After successful generation and green tests, review the spec for completeness. This is advisory — it never blocks.

### Timing

- **For generate/sync:** Run once after the single generation pass produces green tests.
- **For takeover:** Run once after the convergence loop completes successfully (final green tests), before the commit. Do NOT run on each convergence iteration.

### Post-takeover mode (spec was machine-drafted)

Ask:
- Are there behavioral aspects of the generated code not constrained by the spec? A future regeneration might produce different behavior in those areas.
- Are there constraints added during convergence that could be stated more precisely?
- Does the spec leave behavioral choices open that should be pinned down for reproducibility?

Frame suggestions as: "Consider adding: [constraint]" with a brief rationale.

### Post-generate/sync mode (spec was user-written)

Ask:
- Are there internal contradictions? (e.g., "max 5 retries" in one place, "retries indefinitely" in another)
- Do constraints conflict with `depends-on` specs?
- Does the spec reference behavior or concepts not defined anywhere in the spec?

Only flag clear contradictions or inconsistencies. Do NOT suggest additions or tightening — the user wrote this spec deliberately.

### Result handling

- **No issues found:** Report "Spec review: no issues."
- **Issues found:** Surface as suggestions:

> "Post-generation spec review found N suggestions:
> 1. Consider adding: [constraint] — [rationale]
> 2. Possible inconsistency: [quoted phrase A] vs [quoted phrase B]"

**Never block on completeness review.** The generation succeeded, tests are green. These are improvement suggestions.
```

- [ ] **Step 2: Commit**

```bash
git add unslop/skills/generation/SKILL.md
git commit -m "feat: add Section 7 post-generation completeness review to generation skill"
```

---

### Task 5: Update Commands — `--force-ambiguous` Flag

**Files:**
- Modify: `unslop/commands/generate.md`
- Modify: `unslop/commands/sync.md`
- Modify: `unslop/commands/takeover.md`

- [ ] **Step 1: Update generate.md frontmatter and body**

Change the YAML frontmatter description to include the flag:
```yaml
---
description: Regenerate all stale managed files from their specs
argument-hint: "[--force-ambiguous] [--incremental]"
---
```

Add after the "Load context" section (after the line that loads the generation skill):

```markdown
**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When this flag is present, the generation skill's ambiguity detection (Section 0, Phase 0b) reports ambiguities as warnings instead of blocking generation.
```

- [ ] **Step 2: Update sync.md frontmatter and body**

Change the YAML frontmatter:
```yaml
---
description: Regenerate one specific managed file from its spec
argument-hint: <file-path> [--force-ambiguous] [--incremental]
---
```

Add after the "Verify prerequisites" section:

```markdown
**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When present, ambiguity detection reports warnings instead of blocking.
```

- [ ] **Step 3: Update takeover.md frontmatter and body**

Change the YAML frontmatter:
```yaml
---
description: Run the takeover pipeline on an existing file, directory, or glob
argument-hint: <file-path|directory|glob> [--force-ambiguous]
---
```

Add after the "Verify prerequisites" section:

```markdown
**Check for `--force-ambiguous` flag:** If `$ARGUMENTS` contains `--force-ambiguous`, note this for the generation skill. When present, ambiguity detection reports warnings instead of blocking.
```

- [ ] **Step 4: Commit**

```bash
git add unslop/commands/generate.md unslop/commands/sync.md unslop/commands/takeover.md
git commit -m "feat: add --force-ambiguous flag to generate, sync, and takeover commands"
```

---

### Task 6: Bump Plugin Version

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version from 0.2.0 to 0.3.0**

Update the `version` field in `unslop/.claude-plugin/plugin.json` to `"0.3.0"`.

- [ ] **Step 2: Commit**

```bash
git add unslop/.claude-plugin/plugin.json
git commit -m "chore: bump plugin version to 0.3.0"
```

---

### Task 7: Verify and Integration Test

- [ ] **Step 1: Run all validator tests**

Run: `python -m pytest tests/test_validate_spec.py -v`
Expected: all tests PASS

- [ ] **Step 2: Run all orchestrator tests (regression check)**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all 28 tests PASS (no regression)

- [ ] **Step 3: Test validator CLI on a real spec**

```bash
python unslop/scripts/validate_spec.py docs/superpowers/specs/2026-03-22-quality-gates-design.md
```
Expected: `"status": "pass"` (the design spec has headings with content, is long enough, and has no code fences with implementation)

- [ ] **Step 4: Verify all command frontmatter is valid**

```bash
for f in unslop/commands/*.md; do echo "=== $f ==="; head -4 "$f"; echo; done
```

- [ ] **Step 5: Verify generation skill has Sections 0 through 7**

```bash
grep '^## [0-9]' unslop/skills/generation/SKILL.md
```
Expected output should show sections 0 through 7.

- [ ] **Step 6: Verify spec-language skill has Open Questions section**

```bash
grep '## Open Questions' unslop/skills/spec-language/SKILL.md
```
Expected: at least two matches (the guidance section and the skeleton template)

- [ ] **Step 7: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address verification issues" || echo "Nothing to fix"
```
