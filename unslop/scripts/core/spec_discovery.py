"""File discovery and spec parsing utilities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


EXCLUDED_DIRS = {
    "__pycache__",
    "node_modules",
    "target",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    "vendor",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
}

TEST_FILE_PATTERNS = [
    re.compile(r"^test_"),
    re.compile(r"_test\."),
    re.compile(r"\.test\."),
    re.compile(r"\.spec\.(ts|js)$"),
]

TEST_DIR_NAMES = {"__tests__", "tests", "spec"}


def discover_files(
    directory: str,
    extensions: list[str] | None = None,
    extra_excludes: list[str] | None = None,
) -> list[str]:
    """Discover source files in a directory, excluding tests and build artifacts.

    Returns sorted list of file paths relative to the scanned directory.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")
    excluded = EXCLUDED_DIRS | set(extra_excludes or [])
    results = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in excluded or p.endswith(".egg-info") for p in parts[:-1]):
            continue

        if any(p in TEST_DIR_NAMES for p in parts[:-1]):
            continue

        if extensions and path.suffix not in extensions:
            continue

        if any(pat.search(path.name) for pat in TEST_FILE_PATTERNS):
            continue

        results.append(str(rel))

    return results


def parse_unit_spec_files(content: str) -> list[str]:
    """Extract the file list from a unit spec's ``## Files`` section.

    Returns a list of relative filenames (e.g. ``["calc.py", "utils.py"]``).
    These are relative to the spec file's parent directory.
    """
    result: list[str] = []
    in_files = False
    for line in content.split("\n"):
        if re.match(r"^## Files", line):
            in_files = True
            continue
        if in_files:
            if re.match(r"^## ", line):
                break
            m = re.match(r"^\s*-\s+`([^`]+)`", line)
            if m:
                result.append(m.group(1))
    return result


def get_registry_key_for_spec(source_spec: str) -> str:
    """Map an impl.md's source-spec to the managed-file registry key.

    Unit specs (*.unit.spec.md) use the parent directory as the registry key,
    matching how check_freshness() registers them.  Per-file specs strip
    .spec.md to get the managed filename.
    """
    if source_spec.endswith(".unit.spec.md"):
        parent = str(Path(source_spec).parent)
        # Top-level unit spec: parent is ".", registry key is "."
        return parent
    return re.sub(r"\.spec\.md$", "", source_spec)


def file_tree(directory: str) -> list[str]:
    """List git-tracked files in directory.

    Returns sorted list of tracked filenames relative to the directory.
    Used by the Architect stage to see file names without file contents.

    An empty repo (no tracked files) returns [].
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise ValueError("git executable not found on PATH. Install git and ensure it is available.")
    except subprocess.CalledProcessError as exc:
        stderr_detail = exc.stderr.strip() if exc.stderr else ""
        detail = f" ({stderr_detail})" if stderr_detail else ""
        raise ValueError(f"Not a git repository: {directory}{detail}") from exc

    files = [f for f in result.stdout.strip().split("\n") if f]
    return sorted(files)
