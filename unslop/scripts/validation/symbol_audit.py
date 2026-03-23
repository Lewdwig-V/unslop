"""Symbol audit: AST-level check that public symbols survive generation."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _extract_public_symbols(source: str) -> set[str]:
    """Extract public symbol names from Python source.

    Tracks top-level:
    - ``FunctionDef`` and ``AsyncFunctionDef`` (not starting with ``_``)
    - ``ClassDef`` (not starting with ``_``)
    - ``Assign`` and ``AnnAssign`` targets that are ``UPPER_CASE``
    """
    tree = ast.parse(source)
    symbols: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    # UPPER_CASE: all alpha chars are uppercase, at least one alpha, not private
                    if not name.startswith("_") and name == name.upper() and any(c.isalpha() for c in name):
                        symbols.add(name)
        elif isinstance(node, ast.AnnAssign):
            # Annotated assignment: MAX_RETRIES: int = 3
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if not name.startswith("_") and name == name.upper() and any(c.isalpha() for c in name):
                    symbols.add(name)
    return symbols


def audit_symbols(
    original_path: str,
    generated_path: str,
    removed: list[str] | None = None,
) -> dict:
    """Compare public symbols between *original_path* and *generated_path*.

    Parameters
    ----------
    original_path:
        Path to the original (pre-takeover) file.
    generated_path:
        Path to the generated (post-takeover) file.
    removed:
        Symbol names intentionally removed (e.g. legacy smells).  These are
        excluded from the expected set so their absence is not a failure.

    Returns
    -------
    dict with keys: status, missing, unexpected, original_symbols,
    generated_symbols, removed, skipped.
    """
    removed = removed or []
    base: dict = {
        "status": "pass",
        "missing": [],
        "unexpected": [],
        "original_symbols": [],
        "generated_symbols": [],
        "removed": removed,
        "skipped": False,
    }

    orig = Path(original_path)
    gen = Path(generated_path)

    # Non-Python files are not auditable.
    if orig.suffix != ".py" or gen.suffix != ".py":
        print(
            f"symbol-audit: skipping non-Python file(s) ({orig.suffix}, {gen.suffix})",
            file=sys.stderr,
        )
        base["skipped"] = True
        return base

    try:
        orig_source = orig.read_text(encoding="utf-8")
        gen_source = gen.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"symbol-audit: cannot read input: {exc}", file=sys.stderr)
        return {**base, "status": "error", "hint": str(exc)}

    try:
        orig_symbols = _extract_public_symbols(orig_source)
    except SyntaxError as exc:
        print(f"symbol-audit: cannot parse original: {exc}", file=sys.stderr)
        return {**base, "status": "error", "hint": f"original: {exc}"}

    try:
        gen_symbols = _extract_public_symbols(gen_source)
    except SyntaxError as exc:
        print(f"symbol-audit: cannot parse generated: {exc}", file=sys.stderr)
        return {**base, "status": "error", "hint": f"generated: {exc}"}

    expected = orig_symbols - set(removed)
    missing = sorted(expected - gen_symbols)
    unexpected = sorted(gen_symbols - expected)

    status = "fail" if missing else "pass"
    return {
        "status": status,
        "missing": missing,
        "unexpected": unexpected,
        "original_symbols": sorted(orig_symbols),
        "generated_symbols": sorted(gen_symbols),
        "removed": removed,
        "skipped": False,
    }


def main() -> None:
    """CLI entry point for symbol audit."""
    if len(sys.argv) < 3:
        print(
            "Usage: symbol_audit.py <original> <generated> [--removed s1,s2]",
            file=sys.stderr,
        )
        sys.exit(1)

    original = sys.argv[1]
    generated = sys.argv[2]
    removed: list[str] = []
    if "--removed" in sys.argv:
        idx = sys.argv.index("--removed")
        if idx + 1 >= len(sys.argv):
            print("symbol-audit: --removed requires a comma-separated value", file=sys.stderr)
            sys.exit(1)
        removed = [s for s in sys.argv[idx + 1].split(",") if s]

    result = audit_symbols(original, generated, removed=removed)
    print(json.dumps(result, indent=2))
    if result["status"] == "error":
        sys.exit(2)
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
