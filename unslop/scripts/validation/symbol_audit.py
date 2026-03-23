"""AST-level public symbol audit for testless takeover.

Verifies that public symbols (functions, classes, UPPER_CASE constants) in an
original Python file also exist in a generated replacement file.  Used during
Milestone N to ensure the Builder does not accidentally drop public API members.

CLI usage:
    python -m unslop.scripts.validation.symbol_audit <original> <generated> [--removed s1,s2]
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _extract_public_symbols(source: str) -> set[str]:
    """Return the set of public top-level symbol names from *source*.

    Public symbols are:
    - ``FunctionDef`` / ``AsyncFunctionDef`` whose name does not start with ``_``
    - ``ClassDef`` whose name does not start with ``_``
    - ``Assign`` targets that are ``UPPER_CASE`` (all caps + underscores)
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

    # Non-Python files are not auditable -- skip silently.
    if orig.suffix != ".py" or gen.suffix != ".py":
        base["skipped"] = True
        return base

    try:
        orig_source = orig.read_text(encoding="utf-8")
        gen_source = gen.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {**base, "status": "error", "hint": str(exc)}

    try:
        orig_symbols = _extract_public_symbols(orig_source)
    except SyntaxError as exc:
        return {**base, "status": "error", "hint": f"original: {exc}"}

    try:
        gen_symbols = _extract_public_symbols(gen_source)
    except SyntaxError as exc:
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
        if idx + 1 < len(sys.argv):
            removed = [s for s in sys.argv[idx + 1].split(",") if s]

    result = audit_symbols(original, generated, removed=removed)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
