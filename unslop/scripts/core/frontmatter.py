"""Frontmatter parsers for spec and concrete spec files."""

from __future__ import annotations

import re
import sys


def parse_frontmatter(content: str) -> list[str]:
    """Parse depends-on list from spec file frontmatter.

    Supported format (strict string matching, not YAML):
        ---
        depends-on:
          - path/to/spec.py.spec.md
        ---

    Returns list of dependency paths, or empty list if no frontmatter/deps.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    # Find closing delimiter
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    deps = []
    in_depends = False
    for line in frontmatter_lines:
        if line.strip() == "depends-on:":
            in_depends = True
            continue
        if in_depends:
            match = re.match(r"^  - (.+)$", line)
            if match:
                deps.append(match.group(1).strip())
            elif re.match(r"^\s+- ", line):
                print(f"Warning: possible malformed dependency (wrong indentation): {line!r}", file=sys.stderr)
                in_depends = False
            else:
                in_depends = False

    return deps


def parse_concrete_frontmatter(content: str) -> dict:
    """Parse frontmatter from a concrete spec (.impl.md) file.

    Returns dict with: source_spec, target_language, ephemeral, complexity,
    concrete_dependencies (list of paths).
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return {}

    result = {}
    concrete_deps = []
    targets = []
    in_concrete_deps = False
    in_targets = False
    current_target = None

    for line in lines[1:end]:
        stripped = line.strip()

        # Handle nested target parsing first
        if in_targets:
            if re.match(r"^  - path:", line):
                if current_target:
                    targets.append(current_target)
                current_target = {"path": line.split(":", 1)[1].strip()}
                continue
            elif current_target and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_target[key.strip()] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_target:
                    targets.append(current_target)
                    current_target = None
                in_targets = False

        if in_concrete_deps:
            match = re.match(r"^  - (.+)$", line)
            if match:
                concrete_deps.append(match.group(1).strip())
                continue
            else:
                in_concrete_deps = False

        if stripped.startswith("source-spec:"):
            result["source_spec"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("target-language:"):
            result["target_language"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("ephemeral:"):
            val = stripped.split(":", 1)[1].strip().lower()
            result["ephemeral"] = val == "true"
        elif stripped.startswith("complexity:"):
            result["complexity"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("extends:"):
            result["extends"] = stripped.split(":", 1)[1].strip()
        elif stripped == "targets:":
            in_targets = True
        elif stripped == "concrete-dependencies:":
            in_concrete_deps = True

    # Flush final target
    if current_target:
        targets.append(current_target)

    if concrete_deps:
        result["concrete_dependencies"] = concrete_deps
    if targets:
        result["targets"] = targets

    return result
