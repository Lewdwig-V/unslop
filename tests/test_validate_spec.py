from __future__ import annotations

import subprocess
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
    assert result["status"] == "pass"


def test_pass_multi_paragraph_section():
    """Blank lines between paragraphs should NOT break section content counting."""
    content = """# retry.py spec

## Behavior
First paragraph about retry behavior.

Second paragraph with more detail about jitter.

Third paragraph about error conditions.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    assert result["status"] == "pass"


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

## Another Section
Also just one line.

## Yet Another
Single line here too.
And one more line to pass minimum length.
"""
    result = validate_spec(content, "src/retry.py.spec.md")
    # Each heading has only 1 content line, except the last which has 2
    # The last section ("Yet Another") has 2 lines, so it passes
    # But let's make ALL have exactly 1:
    content = """# retry.py spec

## Error Handling
Raises RetryExhausted.

## Dependencies
Uses stdlib only.

## Purpose
A thing.

## Constraints
None yet.
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
Backoff with jitter to prevent thundering herd.

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


def test_empty_file():
    result = validate_spec("", "empty.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "empty_file" for i in result["issues"])


def test_whitespace_only_file():
    result = validate_spec("   \n\n  \n", "ws.spec.md")
    assert result["status"] == "fail"
    assert any(i["check"] == "empty_file" for i in result["issues"])


def test_unclosed_code_fence():
    content = """# spec

## Behavior
Does things with stuff.
More detail here.

```python
def broken():
    pass
"""
    result = validate_spec(content, "test.spec.md")
    # Should warn about unclosed fence with implementation code
    assert result["status"] in ("warn", "fail")
    all_checks = [w["check"] for w in result.get("warnings", [])]
    all_checks += [i["check"] for i in result.get("issues", [])]
    assert "code_fence_misuse" in all_checks or "unclosed_code_fence" in all_checks


def test_warnings_preserved_with_issues():
    content = """# spec

Short.

```python
def impl():
    return True
```
"""
    result = validate_spec(content, "test.spec.md")
    assert result["status"] == "fail"
    assert "issues" in result
    # Warnings should also be present (not dropped)
    assert "warnings" in result


def test_malformed_frontmatter_no_closing():
    content = """---
depends-on:
  - foo.spec.md

# spec

## Behavior
Does stuff well.
More detail here.
"""
    result = validate_spec(content, "test.spec.md")
    all_checks = [w["check"] for w in result.get("warnings", [])]
    assert "malformed_frontmatter" in all_checks


def test_shell_export_not_flagged():
    content = """# deploy spec

## Behavior
Sets up environment variables.

```bash
export DATABASE_URL=postgres://localhost/mydb
export DEBUG=true
```
"""
    result = validate_spec(content, "deploy.spec.md")
    assert result["status"] == "pass"


def test_cli_exit_code_pass(tmp_path):
    spec = tmp_path / "good.spec.md"
    spec.write_text("# spec\n\n## Purpose\nDoes stuff.\nMore detail.\n")
    r = subprocess.run([sys.executable, "unslop/scripts/validate_spec.py", str(spec)],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_cli_exit_code_fail(tmp_path):
    spec = tmp_path / "bad.spec.md"
    spec.write_text("# short\n")
    r = subprocess.run([sys.executable, "unslop/scripts/validate_spec.py", str(spec)],
                       capture_output=True, text=True)
    assert r.returncode == 1


def test_cli_file_not_found():
    r = subprocess.run([sys.executable, "unslop/scripts/validate_spec.py", "/nonexistent/spec.md"],
                       capture_output=True, text=True)
    assert r.returncode == 1
    output = json.loads(r.stdout)
    assert output["status"] == "fail"
