"""unslop validate-behaviour — schema validation for Behaviour DSL YAML files.

The Behaviour DSL is the machine-enforceable output of the Archaeologist phase.
It replaces prose specs with structured YAML that the Mason can consume without
access to source code.

Exit codes:
  0  — behaviour file is valid
  1  — validation errors found
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# We use a minimal YAML parser to avoid external dependencies.
# The behaviour DSL is intentionally simple enough for line-based parsing.


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = {"behaviour", "interface"}
OPTIONAL_TOP_LEVEL = {"constraints", "invariants", "errors", "properties", "depends_on", "notes"}
ALL_TOP_LEVEL = REQUIRED_TOP_LEVEL | OPTIONAL_TOP_LEVEL

CONSTRAINT_TYPES = {"given", "when", "then", "invariant", "error", "property"}

INTERFACE_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*(:[a-zA-Z_][a-zA-Z0-9_]*)?$"
)


# ---------------------------------------------------------------------------
# Minimal YAML-subset parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_behaviour_yaml(content: str) -> tuple[dict | None, str | None]:
    """Parse a behaviour YAML file into a dict.

    Supports:
      - Top-level scalar fields (key: "value" or key: value)
      - Top-level list fields (key:\\n  - item)
      - Constraint lists with typed items (- given: "condition")

    Returns (parsed_dict, error_message).
    """
    result: dict = {}
    lines = content.split("\n")
    current_key = None
    current_list: list | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Detect indentation
        indent = len(line) - len(line.lstrip())

        if indent == 0 and ":" in stripped:
            # Save previous list
            if current_key and current_list is not None:
                result[current_key] = current_list

            # Top-level key
            colon_idx = stripped.index(":")
            key = stripped[:colon_idx].strip()
            value = stripped[colon_idx + 1:].strip()

            # Normalize key (YAML uses hyphens, Python uses underscores)
            key = key.replace("-", "_")

            if value:
                # Strip quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                result[key] = value
                current_key = None
                current_list = None
            else:
                # Start of a list or nested block
                current_key = key
                current_list = []
        elif indent > 0 and stripped.startswith("- "):
            item_content = stripped[2:].strip()
            if current_list is not None:
                # Check if it's a typed constraint (e.g., "- given: condition")
                if ":" in item_content:
                    c_idx = item_content.index(":")
                    c_type = item_content[:c_idx].strip()
                    c_value = item_content[c_idx + 1:].strip()
                    if (c_value.startswith('"') and c_value.endswith('"')) or \
                       (c_value.startswith("'") and c_value.endswith("'")):
                        c_value = c_value[1:-1]
                    current_list.append({c_type: c_value})
                else:
                    if (item_content.startswith('"') and item_content.endswith('"')) or \
                       (item_content.startswith("'") and item_content.endswith("'")):
                        item_content = item_content[1:-1]
                    current_list.append(item_content)
        i += 1

    # Save final list
    if current_key and current_list is not None:
        result[current_key] = current_list

    if not result:
        return None, "File is empty or contains no parseable YAML"

    return result, None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_behaviour(content: str, file_path: str) -> dict:
    """Validate a behaviour YAML file against the DSL schema.

    Returns a dict with status, issues, and warnings.
    """
    issues = []
    warnings = []

    if not content.strip():
        return {
            "status": "fail",
            "file_path": file_path,
            "issues": [{"check": "empty_file", "message": "Behaviour file is empty"}],
        }

    parsed, parse_error = _parse_behaviour_yaml(content)
    if parse_error:
        return {
            "status": "fail",
            "file_path": file_path,
            "issues": [{"check": "parse_error", "message": parse_error}],
        }

    # Check required fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in parsed:
            issues.append({
                "check": "missing_required_field",
                "field": field,
                "message": f"Required field '{field}' is missing",
            })

    # Check unknown fields
    for field in parsed:
        if field not in ALL_TOP_LEVEL:
            warnings.append({
                "check": "unknown_field",
                "field": field,
                "message": f"Unknown top-level field '{field}' — will be ignored",
            })

    # Validate interface format
    if "interface" in parsed:
        iface = parsed["interface"]
        if isinstance(iface, str) and not INTERFACE_PATTERN.match(iface):
            issues.append({
                "check": "invalid_interface",
                "value": iface,
                "message": (
                    f"Interface '{iface}' does not match expected pattern "
                    f"'module.path:function_name' or 'module.path'"
                ),
            })

    # Validate constraints
    if "constraints" in parsed:
        constraints = parsed["constraints"]
        if not isinstance(constraints, list):
            issues.append({
                "check": "constraints_not_list",
                "message": "constraints must be a list of typed entries",
            })
        else:
            for idx, constraint in enumerate(constraints):
                if isinstance(constraint, dict):
                    for c_type in constraint:
                        if c_type not in CONSTRAINT_TYPES:
                            warnings.append({
                                "check": "unknown_constraint_type",
                                "index": idx,
                                "type": c_type,
                                "message": (
                                    f"Constraint #{idx + 1} has unknown type '{c_type}'. "
                                    f"Expected one of: {', '.join(sorted(CONSTRAINT_TYPES))}"
                                ),
                            })
                        c_val = constraint[c_type]
                        if not c_val or not isinstance(c_val, str):
                            issues.append({
                                "check": "empty_constraint",
                                "index": idx,
                                "type": c_type,
                                "message": f"Constraint #{idx + 1} ({c_type}) has empty value",
                            })
                elif isinstance(constraint, str):
                    # Plain string constraint — warn about missing type
                    warnings.append({
                        "check": "untyped_constraint",
                        "index": idx,
                        "message": (
                            f"Constraint #{idx + 1} is untyped. "
                            f"Use typed form: '- given: \"condition\"' for machine-enforceability."
                        ),
                    })
                else:
                    issues.append({
                        "check": "invalid_constraint",
                        "index": idx,
                        "message": f"Constraint #{idx + 1} has unexpected type {type(constraint).__name__}",
                    })

    # Validate errors list
    if "errors" in parsed:
        errors = parsed["errors"]
        if not isinstance(errors, list):
            issues.append({
                "check": "errors_not_list",
                "message": "errors must be a list",
            })

    # Validate invariants list
    if "invariants" in parsed:
        invariants = parsed["invariants"]
        if not isinstance(invariants, list):
            issues.append({
                "check": "invariants_not_list",
                "message": "invariants must be a list",
            })

    # Must have at least one constraint, invariant, error, or property
    has_behavioural_content = any(
        field in parsed and parsed[field]
        for field in ("constraints", "invariants", "errors", "properties")
    )
    if not has_behavioural_content:
        issues.append({
            "check": "no_behavioural_content",
            "message": (
                "Behaviour spec must define at least one of: "
                "constraints, invariants, errors, or properties"
            ),
        })

    result = {"file_path": file_path}
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: validate_behaviour.py <behaviour-yaml-path>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    path = Path(file_path)

    if not path.exists():
        print(json.dumps({
            "status": "fail", "file_path": file_path,
            "issues": [{"check": "file_not_found", "message": f"File not found: {file_path}"}],
        }))
        sys.exit(1)

    content = path.read_text(encoding="utf-8")
    result = validate_behaviour(content, file_path)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
