"""unslop prosecutor — classify surviving mutants as equivalent, weak_test, or spec_gap.

The Prosecutor is Phase 3b of the Adversarial Quality pipeline. It decides
whether a surviving mutant is:

  - equivalent:  mutation doesn't change observable behaviour (ignore)
  - weak_test:   Mason's tests should catch this but don't (Mason retries)
  - spec_gap:    Archaeologist didn't specify this constraint (Archaeologist retries)

Uses heuristic-first classification to minimize cost. LLM fallback is
represented as a structured report for the calling agent to classify.
"""
from __future__ import annotations

import re
import sys
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Heuristic equivalence patterns
# ---------------------------------------------------------------------------

class EquivalencePattern:
    """A pattern that identifies equivalent mutants heuristically."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def matches(self, original: str, mutated: str, context: dict) -> bool:
        raise NotImplementedError


class OffByOneEquivalence(EquivalencePattern):
    """Detects i < N ↔ i <= N-1 and similar off-by-one equivalences."""

    def __init__(self):
        super().__init__(
            "off_by_one",
            "Off-by-one equivalence: comparison boundary shift with constant adjustment",
        )

    def matches(self, original: str, mutated: str, context: dict) -> bool:
        # Pattern: "x < 10" → "x <= 9" or "x >= 10" → "x > 9"
        orig = original.strip()
        mut = mutated.strip()

        pairs = [
            (r"(\w+)\s*<\s*(\d+)", r"(\w+)\s*<=\s*(\d+)"),
            (r"(\w+)\s*<=\s*(\d+)", r"(\w+)\s*<\s*(\d+)"),
            (r"(\w+)\s*>\s*(\d+)", r"(\w+)\s*>=\s*(\d+)"),
            (r"(\w+)\s*>=\s*(\d+)", r"(\w+)\s*>\s*(\d+)"),
        ]

        for orig_pat, mut_pat in pairs:
            orig_m = re.match(orig_pat, orig)
            mut_m = re.match(mut_pat, mut)
            if orig_m and mut_m:
                if orig_m.group(1) == mut_m.group(1):
                    orig_val = int(orig_m.group(2))
                    mut_val = int(mut_m.group(2))
                    if abs(orig_val - mut_val) == 1:
                        return True
        return False


class RedundantBooleanEquivalence(EquivalencePattern):
    """Detects `if True and X` → `if X` style equivalences."""

    def __init__(self):
        super().__init__(
            "redundant_boolean",
            "Boolean simplification: redundant condition removal",
        )

    def matches(self, original: str, mutated: str, context: dict) -> bool:
        # Simple case: "True and X" → "X" or "X or False" → "X"
        orig = original.strip()
        mut = mutated.strip()

        trivial_patterns = [
            (r"True\s+and\s+(.+)", None),
            (r"(.+)\s+and\s+True", None),
            (r"False\s+or\s+(.+)", None),
            (r"(.+)\s+or\s+False", None),
        ]

        for pat, _ in trivial_patterns:
            m = re.match(pat, orig)
            if m and m.group(1).strip() == mut:
                return True
            m = re.match(pat, mut)
            if m and m.group(1).strip() == orig:
                return True

        return False


class StringLiteralEquivalence(EquivalencePattern):
    """Detects mutations to strings that are never compared (e.g., error messages)."""

    def __init__(self):
        super().__init__(
            "string_literal",
            "String literal mutation in non-compared context (e.g., error message text)",
        )

    def matches(self, original: str, mutated: str, context: dict) -> bool:
        # If the only change is inside a raise/log statement's string, likely equivalent
        orig = original.strip()
        mut = mutated.strip()

        raise_pat = re.compile(r'raise\s+\w+\((["\'])')
        log_pat = re.compile(r'(logger?\.\w+|print)\((["\'])')

        if (raise_pat.search(orig) and raise_pat.search(mut)) or \
           (log_pat.search(orig) and log_pat.search(mut)):
            # Check that only the string content differs
            # Strip string literals and compare structure
            def strip_strings(s):
                return re.sub(r'(["\']).*?\1', '""', s)
            if strip_strings(orig) == strip_strings(mut):
                return True

        return False


class DeadCodeEquivalence(EquivalencePattern):
    """Detects mutations in code paths that are unreachable."""

    def __init__(self):
        super().__init__(
            "dead_code",
            "Mutation in unreachable code path",
        )

    def matches(self, original: str, mutated: str, context: dict) -> bool:
        # Heuristic: if the line comes after a bare `return` or `raise` in the same block
        # We check context for surrounding lines
        # Only match if return/raise has equal or less indentation (same or outer block)
        preceding = context.get("preceding_lines", [])
        raw_mutated = context.get("mutated_line_raw", original)
        mutated_indent = len(raw_mutated) - len(raw_mutated.lstrip())
        for line in reversed(preceding):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            prev_indent = len(line) - len(line.lstrip())
            if prev_indent <= mutated_indent and (
                stripped.startswith("return ") or stripped == "return" or stripped.startswith("raise ")
            ):
                return True
            if stripped:
                break
        return False


# All registered heuristic patterns
HEURISTIC_PATTERNS: list[EquivalencePattern] = [
    OffByOneEquivalence(),
    RedundantBooleanEquivalence(),
    StringLiteralEquivalence(),
    DeadCodeEquivalence(),
]


# ---------------------------------------------------------------------------
# Mutant classification
# ---------------------------------------------------------------------------

def classify_mutant(
    original_line: str,
    mutated_line: str,
    line_number: int,
    file_path: str,
    source_lines: list[str] | None = None,
) -> dict:
    """Classify a surviving mutant.

    Returns a dict with:
      - verdict: "equivalent" | "weak_test" | "spec_gap" | "inconclusive"
      - pattern: name of matched heuristic pattern (if equivalent)
      - description: human-readable explanation
      - line: the line number
      - original: the original code
      - mutated: the mutated code
    """
    # Build context for heuristics
    context = {}
    if source_lines and line_number > 0:
        start = max(0, line_number - 5)
        context["preceding_lines"] = source_lines[start:line_number - 1]
        if line_number - 1 < len(source_lines):
            context["mutated_line_raw"] = source_lines[line_number - 1]

    # Try heuristic patterns first
    for pattern in HEURISTIC_PATTERNS:
        if pattern.matches(original_line, mutated_line, context):
            return {
                "verdict": "equivalent",
                "pattern": pattern.name,
                "description": pattern.description,
                "line": line_number,
                "original": original_line.rstrip(),
                "mutated": mutated_line.rstrip(),
                "confidence": "heuristic",
            }

    # Heuristics inconclusive — build a structured report for LLM classification
    # The calling agent decides whether to invoke an LLM or treat as weak_test
    return {
        "verdict": "inconclusive",
        "pattern": None,
        "description": (
            f"Surviving mutant at line {line_number}: "
            f"`{original_line.strip()}` → `{mutated_line.strip()}`. "
            f"Heuristics could not determine equivalence. "
            f"Needs semantic classification."
        ),
        "line": line_number,
        "original": original_line.rstrip(),
        "mutated": mutated_line.rstrip(),
        "confidence": "needs_review",
        "classification_prompt": (
            f"Does this mutation change observable behaviour?\n"
            f"Original: {original_line.strip()}\n"
            f"Mutated:  {mutated_line.strip()}\n"
            f"File: {file_path}:{line_number}\n"
            f"If the mutation changes a return value, side effect, or exception "
            f"that a caller could observe, classify as 'weak_test'.\n"
            f"If the mutation only changes internal state that cannot be observed "
            f"through the public interface, classify as 'equivalent'.\n"
            f"If the mutation reveals a behaviour not covered by any spec constraint, "
            f"classify as 'spec_gap'."
        ),
    }


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------

def classify_surviving_mutants(mutants: list[dict], source_path: str) -> dict:
    """Classify a batch of surviving mutants.

    Each mutant dict should have: original, mutated, line.
    Returns a summary with classified mutants grouped by verdict.
    """
    source_lines = None
    source_file = Path(source_path)
    if source_file.exists():
        source_lines = source_file.read_text(encoding="utf-8").split("\n")

    results = {
        "equivalent": [],
        "weak_test": [],
        "spec_gap": [],
        "inconclusive": [],
        "error": [],
    }

    required_keys = {"original", "mutated", "line"}
    for i, mutant in enumerate(mutants):
        missing = required_keys - set(mutant.keys())
        if missing:
            results["error"].append({
                "original": mutant.get("original", ""),
                "mutated": mutant.get("mutated", ""),
                "line": mutant.get("line", 0),
                "verdict": "error",
                "pattern": None,
                "reason": f"Mutant #{i} missing keys: {', '.join(sorted(missing))}",
            })
            continue
        classification = classify_mutant(
            original_line=mutant["original"],
            mutated_line=mutant["mutated"],
            line_number=mutant["line"],
            file_path=source_path,
            source_lines=source_lines,
        )
        results[classification["verdict"]].append(classification)

    total = len(mutants)
    equivalent = len(results["equivalent"])

    return {
        "source_path": source_path,
        "total_surviving": total,
        "equivalent": equivalent,
        "weak_test": len(results["weak_test"]),
        "spec_gap": len(results["spec_gap"]),
        "inconclusive": len(results["inconclusive"]),
        "errors": len(results["error"]),
        "effective_surviving": total - equivalent,
        "details": results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI for batch classification.

    Reads a JSON array of mutants from stdin or a file argument.
    Each mutant: {"original": "...", "mutated": "...", "line": N}
    """
    if len(sys.argv) < 2:
        print(
            "Usage: prosecutor.py <source-file> [mutants.json]\n"
            "  Reads mutants from stdin if no file argument given.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_path = sys.argv[1]

    if len(sys.argv) >= 3:
        try:
            mutants_data = Path(sys.argv[2]).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError) as e:
            print(json.dumps({"error": f"Cannot read mutants file: {e}"}))
            sys.exit(1)
    else:
        mutants_data = sys.stdin.read()

    try:
        mutants = json.loads(mutants_data)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    result = classify_surviving_mutants(mutants, source_path)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
