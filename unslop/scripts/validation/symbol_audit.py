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
        elif isinstance(node, ast.ImportFrom):
            # Re-exports: from .core import Foo, Bar (common in __init__.py)
            if node.names:
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    if name != "*" and not name.startswith("_"):
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


def _extract_symbol_sources(source: str) -> dict[str, str]:
    """Extract source text for each public top-level symbol (function/class).

    Returns a mapping of symbol name -> normalized source text.
    Only tracks FunctionDef, AsyncFunctionDef, ClassDef (not starting with ``_``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines(keepends=True)
    nodes = [
        n
        for n in ast.iter_child_nodes(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_")
    ]
    result: dict[str, str] = {}
    for i, node in enumerate(nodes):
        start = node.lineno - 1  # 0-indexed
        if i + 1 < len(nodes):
            end = nodes[i + 1].lineno - 1
        else:
            end = len(lines)
        raw = "".join(lines[start:end])
        result[node.name] = _normalize_source(raw)
    return result


def _normalize_source(text: str) -> str:
    """Strip trailing whitespace per line and collapse consecutive blank lines."""
    out: list[str] = []
    prev_blank = False
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped:
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        out.append(stripped)
    # Remove trailing blank lines
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _parse_affected_tag(name: str) -> tuple[str, str]:
    """Parse 'name (new)' or 'name (deleted)' -> (name, tag).

    Returns (name, '') for plain names.
    """
    name = name.strip()
    if name.endswith("(new)"):
        return name[: -len("(new)")].strip(), "new"
    if name.endswith("(deleted)"):
        return name[: -len("(deleted)")].strip(), "deleted"
    return name, ""


def check_drift(old_path: str, new_path: str, affected_symbols: list[str]) -> dict:
    """Compare two Python files and warn if symbols outside *affected_symbols* changed.

    Parameters
    ----------
    old_path:
        Path to the original file.
    new_path:
        Path to the new/modified file.
    affected_symbols:
        List of symbol names that are expected to change.  Supports tags:
        ``"name (new)"`` -- new symbol, exempt from unauthorized-new check.
        ``"name (deleted)"`` -- deleted symbol, expected to be absent.

    Returns
    -------
    dict with keys: status ("clean"|"drift"|"error"), drifted, modified, skipped.
    """
    base: dict = {"status": "clean", "drifted": [], "modified": [], "skipped": False}

    old_p = Path(old_path)
    new_p = Path(new_path)

    # Non-Python -> skip
    if old_p.suffix != ".py" or new_p.suffix != ".py":
        return {**base, "skipped": True}

    # Parse affected tags
    modified_names: set[str] = set()
    new_names: set[str] = set()
    deleted_names: set[str] = set()
    for raw in affected_symbols:
        name, tag = _parse_affected_tag(raw)
        if tag == "new":
            new_names.add(name)
        elif tag == "deleted":
            deleted_names.add(name)
        else:
            modified_names.add(name)

    try:
        old_source = old_p.read_text(encoding="utf-8")
        new_source = new_p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"check-drift: cannot read input: {exc}", file=sys.stderr)
        return {**base, "status": "error"}

    try:
        old_symbols = _extract_symbol_sources(old_source)
    except Exception as exc:
        print(f"check-drift: cannot parse old file: {exc}", file=sys.stderr)
        return {**base, "status": "error"}

    try:
        new_symbols = _extract_symbol_sources(new_source)
    except Exception as exc:
        print(f"check-drift: cannot parse new file: {exc}", file=sys.stderr)
        return {**base, "status": "error"}

    all_affected = modified_names | new_names | deleted_names
    drifted: list[str] = []
    modified_out: list[str] = []

    # Check protected symbols (in old, not in affected/new/deleted)
    for sym_name, old_src in old_symbols.items():
        if sym_name in all_affected:
            # Expected to change
            if sym_name in modified_names or sym_name in new_names:
                new_src = new_symbols.get(sym_name)
                if new_src is not None and new_src != old_src:
                    modified_out.append(sym_name)
            continue
        # Protected symbol -- must not change
        new_src = new_symbols.get(sym_name)
        if new_src is None:
            drifted.append(sym_name)
        elif new_src != old_src:
            drifted.append(sym_name)

    # Check deleted symbols: should be absent
    for sym_name in deleted_names:
        if sym_name in new_symbols:
            drifted.append(sym_name)

    # Check unauthorized new symbols
    for sym_name in new_symbols:
        if sym_name not in old_symbols and sym_name not in new_names and sym_name not in all_affected:
            drifted.append(sym_name)

    # Record expected modifications
    for sym_name in modified_names:
        old_src = old_symbols.get(sym_name)
        new_src = new_symbols.get(sym_name)
        if old_src is not None and new_src is not None and old_src != new_src:
            modified_out.append(sym_name)

    drifted = sorted(set(drifted))
    modified_out = sorted(set(modified_out))
    status = "drift" if drifted else "clean"
    return {"status": status, "drifted": drifted, "modified": modified_out, "skipped": False}


def compute_spec_diff(old_spec: str, new_spec: str) -> dict:
    """Section-level markdown diff between two spec versions.

    Parses ``## `` headings into ``{heading: content}`` maps and compares values.

    Parameters
    ----------
    old_spec:
        The old spec markdown text.
    new_spec:
        The new spec markdown text.

    Returns
    -------
    dict with keys: changed_sections, unchanged_sections.
    """
    old_sections = _parse_md_sections(old_spec)
    new_sections = _parse_md_sections(new_spec)

    all_headings = set(old_sections.keys()) | set(new_sections.keys())
    changed: list[str] = []
    unchanged: list[str] = []

    for heading in sorted(all_headings):
        old_content = old_sections.get(heading)
        new_content = new_sections.get(heading)
        if old_content == new_content:
            unchanged.append(heading)
        else:
            changed.append(heading)

    return {"changed_sections": changed, "unchanged_sections": unchanged}


def _parse_md_sections(text: str) -> dict[str, str]:
    """Parse markdown into {heading: content} by ``## `` boundaries."""
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


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
