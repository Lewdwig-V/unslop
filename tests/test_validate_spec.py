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
