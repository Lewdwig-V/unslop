"""unslop validate-spec — deterministic structural validation for spec files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

IMPLEMENTATION_PATTERNS = [
    re.compile(r'^\s*(def |class |import |from .+ import |if |for |while |try:|except |return )'),
    re.compile(r'^\s*(function |const |let |var |export (default |{)|async )'),
    re.compile(r'^\s*(fn |pub |use |mod |impl |struct |enum )'),
    re.compile(r'^\s*(func |package |type .+ struct)'),
]


def validate_spec(content: str, spec_path: str) -> dict:
    issues = []
    warnings = []

    if not content.strip():
        return {"status": "fail", "spec_path": spec_path,
                "issues": [{"check": "empty_file",
                            "message": "Spec file is empty or contains only whitespace"}]}

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
        if end == -1:
            warnings.append({
                "check": "malformed_frontmatter",
                "message": "File starts with '---' but no closing '---' found. Frontmatter may be malformed."
            })

    body_lines = body.split("\n")
    non_blank = [line for line in body_lines if line.strip()]

    # Check 1: Minimum length (>3 non-blank lines)
    if len(non_blank) <= 3:
        issues.append({
            "check": "minimum_length",
            "message": f"Spec body has only {len(non_blank)} non-blank lines (minimum 4)"
        })

    # Check 2: Required sections — at least one ## heading with >1 non-blank
    # content lines anywhere below it (until the next ## heading).
    # Blank lines do NOT reset the count — multi-paragraph sections are valid.
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
    if current_heading and content_lines_under_heading > 1:
        has_substantive_section = True

    if not has_substantive_section:
        issues.append({
            "check": "required_sections",
            "message": (
                "No heading found with substantive content"
                " (need at least one ## heading with >1 non-blank line below it)"
            )
        })

    # Check 3: Code fence misuse
    in_fence = False
    fence_start = -1
    fence_lines_content = []
    for i, line in enumerate(body_lines):
        if line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = i
                fence_lines_content = []
            else:
                has_impl = any(
                    pat.search(fl) for fl in fence_lines_content
                    for pat in IMPLEMENTATION_PATTERNS
                )
                if has_impl:
                    warnings.append({
                        "check": "code_fence_misuse",
                        "message": (
                            f"Code fence at line {fence_start + 1} may contain"
                            " implementation code rather than a data example"
                        )
                    })
                in_fence = False
                fence_lines_content = []
        elif in_fence:
            fence_lines_content.append(line)

    # Warn on unclosed fence
    if in_fence:
        has_impl = any(
            pat.search(fl) for fl in fence_lines_content
            for pat in IMPLEMENTATION_PATTERNS
        )
        if has_impl:
            warnings.append({
                "check": "code_fence_misuse",
                "message": f"Unclosed code fence at line {fence_start + 1} may contain implementation code"
            })
        else:
            warnings.append({
                "check": "unclosed_code_fence",
                "message": f"Code fence opened at line {fence_start + 1} is never closed"
            })

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

    result = {"spec_path": spec_path}
    if issues:
        result["status"] = "fail"
        result["issues"] = issues
    elif warnings:
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    if warnings:
        result["warnings"] = warnings
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_spec.py <spec-path>", file=sys.stderr)
        sys.exit(1)

    spec_path = sys.argv[1]
    file_path = Path(spec_path)

    # Size guard — spec files should be small text documents
    MAX_SPEC_SIZE = 1_000_000  # 1 MB
    try:
        size = file_path.stat().st_size
        if size > MAX_SPEC_SIZE:
            msg = f"File is {size} bytes (max {MAX_SPEC_SIZE}). Spec files should be small text documents."
            result = {"status": "fail", "spec_path": spec_path,
                      "issues": [{"check": "file_too_large", "message": msg}]}
            print(json.dumps(result))
            sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "file_not_found",
                                      "message": f"Spec file not found: {spec_path}"}]}))
        sys.exit(1)
    except OSError as e:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "read_error",
                                      "message": f"Cannot read spec file: {e}"}]}))
        sys.exit(1)

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "encoding_error",
                                      "message": f"Cannot read spec file as text. Is this UTF-8? Detail: {e}"}]}))
        sys.exit(1)
    except OSError as e:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "read_error",
                                      "message": f"Cannot read spec file: {e}"}]}))
        sys.exit(1)

    if "\x00" in content:
        print(json.dumps({"status": "fail", "spec_path": spec_path,
                          "issues": [{"check": "binary_file",
                                      "message": "File appears to be binary, not a text spec"}]}))
        sys.exit(1)

    result = validate_spec(content, spec_path)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
