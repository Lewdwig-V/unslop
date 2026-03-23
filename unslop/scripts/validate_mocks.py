"""unslop validate-mocks — AST-based Mock Budget Linter.

Enforces the Boundary Manifest: tests may only mock modules listed in
.unslop/boundaries.json.  Any mock/patch of an internal module is
Hard Rejected to prevent implementation-coupled "test scum."

Exit codes:
  0  — all mocks target allowed boundaries
  1  — violations found (details in JSON output)
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Boundary manifest loading
# ---------------------------------------------------------------------------


def load_boundaries(project_root: Path) -> list[str]:
    """Load allowed mock targets from .unslop/boundaries.json.

    The file should contain a JSON array of module name prefixes that
    represent external boundaries (e.g. ["requests", "boto3", "psycopg2"]).
    """
    boundaries_path = project_root / ".unslop" / "boundaries.json"
    if not boundaries_path.exists():
        return []
    content = boundaries_path.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"boundaries.json contains invalid JSON: {e}")
    if not isinstance(data, list):
        raise ValueError(f"boundaries.json must be a JSON array, got {type(data).__name__}")
    return [str(entry) for entry in data]


# ---------------------------------------------------------------------------
# AST visitor — extracts all mock/patch targets
# ---------------------------------------------------------------------------

_PATCH_NAMES = {"patch", "patch.object", "patch.dict", "patch.multiple"}


class MockTargetExtractor(ast.NodeVisitor):
    """Walk an AST and collect every string target passed to mock.patch().

    Detects:
      - @patch("some.module.thing")
      - @patch.object(SomeClass, "method")
      - with patch("some.module.thing"):
      - unittest.mock.patch("some.module.thing")
      - from unittest.mock import patch; patch("thing")
      - mocker.patch("thing")  (pytest-mock)
    """

    def __init__(self) -> None:
        self.targets: list[dict] = []  # {"target": str, "line": int, "col": int, "kind": str}
        self._seen_nodes: set[int] = set()  # Track node ids to avoid double-counting decorators

    # Receiver names known to be mock frameworks
    _MOCK_RECEIVERS = {"mock", "mocker", "unittest"}

    def _is_patch_call(self, node: ast.expr) -> str | None:
        """Return the patch variant name if node looks like a patch call, else None.

        Only matches known mock module patterns to avoid false positives
        on unrelated .patch() calls (e.g., requests.patch, client.patch).
        """
        if isinstance(node, ast.Attribute):
            if node.attr == "patch":
                # unittest.mock.patch(...)
                if isinstance(node.value, ast.Attribute) and node.value.attr == "mock":
                    return "patch"
                # mock.patch(...) or mocker.patch(...)
                if isinstance(node.value, ast.Name) and node.value.id in self._MOCK_RECEIVERS:
                    return "patch"
                return None
            # patch.object, patch.dict, patch.multiple
            if isinstance(node.value, ast.Attribute) and node.value.attr == "patch":
                return f"patch.{node.attr}"
            if isinstance(node.value, ast.Name) and node.value.id == "patch":
                return f"patch.{node.attr}"
        if isinstance(node, ast.Name) and node.id == "patch":
            return "patch"
        return None

    def _extract_target_from_call(self, node: ast.Call) -> None:
        node_id = id(node)
        if node_id in self._seen_nodes:
            return
        self._seen_nodes.add(node_id)

        kind = self._is_patch_call(node.func)
        if kind is None:
            return

        # For patch.object(SomeClass, "method") — the target is an object, not a string.
        # Count it as a mock and flag as internal (implementation-coupled by definition).
        if kind == "patch.object":
            attr_name = ""
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                attr_name = node.args[1].value
            obj_name = ""
            if node.args and isinstance(node.args[0], ast.Name):
                obj_name = node.args[0].id
            target_label = f"{obj_name}.{attr_name}" if obj_name and attr_name else f"<patch.object at line {node.lineno}>"
            self.targets.append(
                {
                    "target": target_label,
                    "line": node.lineno,
                    "col": node.col_offset,
                    "kind": kind,
                    "internal": True,
                }
            )
            return

        # For patch("target_string") — first positional arg is the target
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            self.targets.append(
                {
                    "target": node.args[0].value,
                    "line": node.args[0].lineno,
                    "col": node.args[0].col_offset,
                    "kind": kind,
                }
            )
            return

        # For patch(target="target_string") — keyword arg
        for kw in node.keywords:
            if kw.arg == "target" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                self.targets.append(
                    {
                        "target": kw.value.value,
                        "line": kw.value.lineno,
                        "col": kw.value.col_offset,
                        "kind": kind,
                    }
                )
                return

    def visit_Call(self, node: ast.Call) -> None:
        self._extract_target_from_call(node)
        self.generic_visit(node)

    # Decorators are visited as part of FunctionDef / AsyncFunctionDef
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                self._extract_target_from_call(decorator)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                self._extract_target_from_call(decorator)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------


def _module_root(target: str) -> str:
    """Extract the top-level module from a dotted path.

    Example: "src.retry.time.sleep" → "src"
    """
    return target.split(".")[0]


def _is_stdlib_or_boundary(target: str, boundaries: list[str]) -> bool:
    """Check if a mock target is an allowed boundary.

    A target is allowed if:
      1. Its root module matches an entry in boundaries.json, OR
      2. It targets a well-known stdlib module (time, os, sys, etc.)

    The stdlib allowlist covers modules commonly mocked in tests —
    these are external boundaries by definition.
    """
    STDLIB_ALLOWLIST = {
        "time",
        "os",
        "sys",
        "io",
        "tempfile",
        "subprocess",
        "socket",
        "http",
        "urllib",
        "ssl",
        "email",
        "smtplib",
        "logging",
        "random",
        "datetime",
        "json",
        "pathlib",
        "builtins",
        "signal",
        "threading",
        "multiprocessing",
        "asyncio",
        "unittest",
    }

    parts = target.split(".")

    # Check stdlib: any prefix component matches
    if parts[0] in STDLIB_ALLOWLIST:
        return True

    # Check boundaries: target starts with a boundary prefix
    for boundary in boundaries:
        if target == boundary or target.startswith(boundary + "."):
            return True

    return False


def _is_internal_mock(target: str, boundaries: list[str]) -> bool:
    """Return True if the mock target is an internal module (violation)."""
    return not _is_stdlib_or_boundary(target, boundaries)


def validate_test_file(source: str, file_path: str, boundaries: list[str]) -> dict:
    """Validate a single test file for mock budget violations.

    Returns a dict with:
      - status: "pass" | "fail"
      - file_path: the test file path
      - violations: list of violation dicts (empty if passing)
      - mock_count: total mocks found
      - boundary_mocks: count of allowed boundary mocks
      - internal_mocks: count of disallowed internal mocks
    """
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return {
            "status": "fail",
            "file_path": file_path,
            "violations": [{"check": "syntax_error", "message": str(e), "line": e.lineno or 0}],
            "mock_count": 0,
            "boundary_mocks": 0,
            "internal_mocks": 0,
        }

    extractor = MockTargetExtractor()
    extractor.visit(tree)

    violations = []
    boundary_count = 0
    internal_count = 0

    for mock_info in extractor.targets:
        target = mock_info["target"]
        if mock_info.get("internal") or _is_internal_mock(target, boundaries):
            internal_count += 1
            violations.append(
                {
                    "check": "internal_mock",
                    "target": target,
                    "line": mock_info["line"],
                    "col": mock_info["col"],
                    "kind": mock_info["kind"],
                    "message": (
                        f"Mock targets internal module '{target}'. "
                        f"Only external boundaries may be mocked. "
                        f"Add '{_module_root(target)}' to .unslop/boundaries.json if this is an external dependency."
                    ),
                }
            )
        else:
            boundary_count += 1

    return {
        "status": "fail" if violations else "pass",
        "file_path": file_path,
        "violations": violations,
        "mock_count": len(extractor.targets),
        "boundary_mocks": boundary_count,
        "internal_mocks": internal_count,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: validate_mocks.py <test-file-or-dir> [--project-root <path>]", file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])
    project_root = Path(".")

    if "--project-root" in sys.argv:
        idx = sys.argv.index("--project-root")
        if idx + 1 >= len(sys.argv):
            print("--project-root requires a value", file=sys.stderr)
            sys.exit(1)
        project_root = Path(sys.argv[idx + 1])

    boundaries = load_boundaries(project_root)
    boundaries_missing = not (project_root / ".unslop" / "boundaries.json").exists()

    test_files: list[Path] = []
    if target.is_dir():
        test_files = sorted(target.rglob("test_*.py"))
    elif target.is_file():
        test_files = [target]
    else:
        print(json.dumps({"status": "fail", "message": f"Path not found: {target}"}))
        sys.exit(1)

    results = []
    any_fail = False
    for tf in test_files:
        try:
            source = tf.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            results.append(
                {
                    "status": "fail",
                    "file_path": str(tf),
                    "violations": [{"check": "read_error", "message": str(e), "line": 0}],
                    "mock_count": 0,
                    "boundary_mocks": 0,
                    "internal_mocks": 0,
                }
            )
            any_fail = True
            continue
        result = validate_test_file(source, str(tf), boundaries)
        results.append(result)
        if result["status"] == "fail":
            any_fail = True

    output = {
        "status": "fail" if any_fail else "pass",
        "boundaries": boundaries,
        "files_checked": len(results),
        "results": results,
    }
    if boundaries_missing:
        output["warning"] = (
            "No .unslop/boundaries.json found -- only stdlib mocks are allowed. "
            "Create boundaries.json to declare external dependency boundaries."
        )
    print(json.dumps(output, indent=2))
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
