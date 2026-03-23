"""unslop validate-pseudocode — structural linting for pseudocode in concrete specs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Language-specific keywords that should not appear in pseudocode
LANGUAGE_KEYWORDS = re.compile(
    r'\b(def |func |fn |let |var |const |lambda |pub |use |mod |impl |struct |enum |package |async |await )'
)
LANGUAGE_KEYWORD_EXACT = re.compile(
    r'\b(def|func|fn|let|var|const|lambda|=>)\b'
)

# Dot-notation method calls (potential library puns)
# Matches: word.word( — e.g., time.sleep(, random.uniform(
# Excludes: config.field (no parens) and common pseudocode like result.success
LIBRARY_CALL = re.compile(r'\b[a-z_]\w*\.[a-z_]\w*\s*\(')

# Bare assignment: x = y (but not x == y, x <= y, x >= y, x != y)
# Must not match ←, :=, or comparison operators
BARE_ASSIGNMENT = re.compile(r'(?<![<>!=:])=(?!=)')

# Multi-statement lines (semicolons as separators, not inside strings)
MULTI_STATEMENT = re.compile(r';')

# Single-char variable names (excluding i, j, k loop counters and math symbols)
# Matches SET x ← or standalone single-char identifiers used as variables
SINGLE_CHAR_VAR = re.compile(r'\bSET\s+([a-z])\s*[←:=]')

# FUNCTION without END FUNCTION tracking
FUNCTION_START = re.compile(r'^\s*FUNCTION\b', re.IGNORECASE)
FUNCTION_END = re.compile(r'^\s*END\s+FUNCTION\b', re.IGNORECASE)


def extract_pseudocode_blocks(content: str) -> list[dict]:
    """Extract all ```pseudocode fenced blocks with their line offsets."""
    blocks = []
    lines = content.split("\n")
    in_block = False
    block_start = -1
    block_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```pseudocode"):
            in_block = True
            block_start = i + 1  # 1-indexed
            block_lines = []
        elif in_block and stripped.startswith("```"):
            blocks.append({
                "start_line": block_start,
                "lines": block_lines,
            })
            in_block = False
            block_lines = []
        elif in_block:
            block_lines.append((i + 1, line))  # (1-indexed line number, content)

    if in_block:
        # Unclosed block — still lint what we have
        blocks.append({
            "start_line": block_start,
            "lines": block_lines,
            "unclosed": True,
        })

    return blocks


def lint_pseudocode(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Lint extracted pseudocode blocks. Returns (violations, advisories)."""
    violations = []
    advisories = []

    for block in blocks:
        function_stack = []

        for line_num, line in block["lines"]:
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("//"):
                continue

            # Check 1: Bare assignment (= instead of ← or :=)
            # Exclude lines that are clearly comparisons or contain ← already
            if "←" not in line and ":=" not in line:
                # Remove string literals and comments before checking
                code_part = re.sub(r'"[^"]*"', '', stripped)
                code_part = re.sub(r'//.*$', '', code_part)
                if BARE_ASSIGNMENT.search(code_part):
                    # Double-check it's not inside a function call or comparison
                    if not re.search(r'[<>!]=', code_part):
                        violations.append({
                            "line": line_num,
                            "check": "bare_assignment",
                            "text": stripped,
                            "message": "Bare assignment `=` — use `SET ... ←` or `... := ...`",
                        })

            # Check 2: Language-specific keywords
            if LANGUAGE_KEYWORD_EXACT.search(stripped):
                match = LANGUAGE_KEYWORD_EXACT.search(stripped)
                violations.append({
                    "line": line_num,
                    "check": "language_keyword",
                    "text": stripped,
                    "message": (
                        f"Language-specific keyword `{match.group()}` — "
                        "use capitalized pseudocode keywords (FUNCTION, SET, IF, etc.)"
                    ),
                })

            # Check 3: Multi-statement lines
            code_part = re.sub(r'"[^"]*"', '', stripped)
            code_part = re.sub(r'//.*$', '', code_part)
            if MULTI_STATEMENT.search(code_part):
                violations.append({
                    "line": line_num,
                    "check": "multi_statement",
                    "text": stripped,
                    "message": "Multiple statements on one line (`;` separator) — use one statement per line",
                })

            # Check 4: Library calls (dot-notation with parens)
            if LIBRARY_CALL.search(stripped):
                match = LIBRARY_CALL.search(stripped)
                violations.append({
                    "line": line_num,
                    "check": "library_call",
                    "text": stripped,
                    "message": (
                        f"Potential library call `{match.group().strip()}` — "
                        "use a generic operation name instead (e.g., `WAIT` not `time.sleep()`)"
                    ),
                })

            # Check 5: Single-character variable names
            char_match = SINGLE_CHAR_VAR.search(stripped)
            if char_match:
                char = char_match.group(1)
                if char not in ('i', 'j', 'k', 'n', 'm', 'x', 'y'):
                    advisories.append({
                        "line": line_num,
                        "check": "abbreviated_name",
                        "text": stripped,
                        "message": f"Single-character variable `{char}` — use a descriptive name",
                    })

            # Track FUNCTION / END FUNCTION scope
            if FUNCTION_START.search(stripped):
                function_stack.append(line_num)
            if FUNCTION_END.search(stripped):
                if function_stack:
                    function_stack.pop()
                else:
                    violations.append({
                        "line": line_num,
                        "check": "unmatched_end_function",
                        "text": stripped,
                        "message": "END FUNCTION without matching FUNCTION",
                    })

        # Check 6: Unclosed FUNCTION blocks
        for fn_line in function_stack:
            violations.append({
                "line": fn_line,
                "check": "unclosed_function",
                "text": f"(FUNCTION opened at line {fn_line})",
                "message": "FUNCTION without matching END FUNCTION",
            })

        # Check for unclosed pseudocode fence
        if block.get("unclosed"):
            violations.append({
                "line": block["start_line"],
                "check": "unclosed_fence",
                "text": "(pseudocode block)",
                "message": "Pseudocode fence opened but never closed",
            })

    return violations, advisories


def validate_pseudocode(content: str, impl_path: str) -> dict:
    blocks = extract_pseudocode_blocks(content)

    if not blocks:
        return {
            "status": "warn",
            "impl_path": impl_path,
            "warnings": [{
                "check": "no_pseudocode",
                "message": "No ```pseudocode blocks found in concrete spec",
            }],
        }

    violations, advisories = lint_pseudocode(blocks)

    result = {"impl_path": impl_path}

    if violations:
        result["status"] = "fail"
        result["violations"] = violations
    elif advisories:
        result["status"] = "warn"
    else:
        result["status"] = "pass"

    if advisories:
        result["advisories"] = advisories

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_pseudocode.py <impl-path>", file=sys.stderr)
        sys.exit(1)

    impl_path = sys.argv[1]
    file_path = Path(impl_path)

    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(json.dumps({"status": "fail", "impl_path": impl_path,
                          "violations": [{"check": "file_not_found",
                                          "message": f"File not found: {impl_path}"}]}))
        sys.exit(1)
    except (UnicodeDecodeError, OSError) as e:
        print(json.dumps({"status": "fail", "impl_path": impl_path,
                          "violations": [{"check": "read_error",
                                          "message": f"Cannot read file: {e}"}]}))
        sys.exit(1)

    result = validate_pseudocode(content, impl_path)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
