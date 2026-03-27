"""Frontmatter parsers for spec and concrete spec files."""

from __future__ import annotations

import json
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


def parse_managed_file(content: str) -> str | None:
    """Extract managed-file field from abstract spec frontmatter.

    Returns the managed-file path if present, or None.
    Used to override the default filename-stripping heuristic for
    directory modules (e.g., dispatch.spec.md -> dispatch/mod.rs).
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    for i in range(1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "---":
            break
        if stripped.startswith("managed-file:"):
            return stripped.split(":", 1)[1].strip()

    return None


def parse_intent(content: str) -> dict | None:
    """Extract intent fields from abstract spec frontmatter.

    Returns dict with intent, intent_approved, intent_hash if intent is present.
    Returns None if no intent field found.

    Handles both single-line and multi-line (YAML folded scalar >) intent values.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return None

    intent = None
    intent_approved = None
    intent_hash = None
    in_intent = False
    intent_lines = []

    for line in lines[1:end]:
        stripped = line.strip()

        if in_intent:
            # Multi-line intent: continuation lines are indented, blank lines are valid
            if stripped == "":
                # Blank line in folded/literal scalar -- preserve as paragraph break
                intent_lines.append("")
                continue
            if line.startswith("  ") and not stripped.startswith(("intent-approved:", "intent-hash:")):
                intent_lines.append(stripped)
                continue
            else:
                in_intent = False
                intent = " ".join(part for part in intent_lines if part)

        if stripped.startswith("intent:"):
            val = stripped.split(":", 1)[1].strip()
            if val.startswith(">") or val.startswith("|"):
                # YAML folded/literal scalar (>, >-, >+, |, |-, |+) -- collect continuation lines
                in_intent = True
                intent_lines = []
            elif val:
                intent = val
        elif stripped.startswith("intent-approved:"):
            intent_approved = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("intent-hash:"):
            intent_hash = stripped.split(":", 1)[1].strip()

    # Flush multi-line intent if still collecting at end of frontmatter
    if in_intent and intent_lines:
        intent = " ".join(part for part in intent_lines if part)

    if intent is None:
        return None

    return {
        "intent": intent,
        "intent_approved": intent_approved,
        "intent_hash": intent_hash,
    }


def compute_intent_hash(intent_text: str) -> str:
    """Compute a 12-char hex hash of the intent text.

    Uses the same algorithm as compute_hash (SHA-256, truncated).
    Normalizes whitespace before hashing for resilience against reformatting.
    """
    import hashlib

    normalized = " ".join(intent_text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def validate_intent_hash(intent_text: str, stored_hash: str) -> bool:
    """Validate that the intent text matches its stored hash.

    Returns True if the hash matches, False if tampered or edited.
    """
    return compute_intent_hash(intent_text) == stored_hash


def parse_non_goals(content: str) -> list[str]:
    """Parse non_goals list from abstract spec frontmatter.

    Accepts both ``non_goals:`` and ``non-goals:`` as the field name.
    Returns list of strings, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    items = []
    in_non_goals = False
    for line in frontmatter_lines:
        stripped = line.strip()
        if stripped in ("non_goals:", "non-goals:"):
            in_non_goals = True
            continue
        if in_non_goals:
            match = re.match(r"^  - (.+)$", line)
            if match:
                items.append(match.group(1).strip())
            elif re.match(r"^\s+- ", line):
                print(
                    f"Warning: possible malformed non_goals entry (wrong indentation): {line!r}",
                    file=sys.stderr,
                )
                in_non_goals = False
            else:
                in_non_goals = False

    return items


def parse_needs_review(content: str) -> str | None:
    """Extract needs-review field from spec frontmatter.

    Returns the intent-hash string if present, or None.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    for i in range(1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "---":
            break
        if stripped.startswith("needs-review:"):
            return stripped.split(":", 1)[1].strip() or None

    return None


def parse_review_acknowledged(content: str) -> str | None:
    """Extract review-acknowledged field from spec frontmatter.

    Returns the intent-hash string if present, or None.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    for i in range(1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "---":
            break
        if stripped.startswith("review-acknowledged:"):
            return stripped.split(":", 1)[1].strip() or None

    return None


def parse_uncertain(content: str) -> list[dict]:
    """Parse uncertain list from abstract spec frontmatter.

    Each entry has three required fields: title, observation, question.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        uncertain:
          - title: "Unbounded retry loop"
            observation: "Code retries indefinitely with no cap."
            question: "Is the missing cap intentional?"
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_uncertain = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_uncertain:
            if re.match(r"^  - title:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"title": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed uncertain entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_uncertain = False
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_uncertain = False

        if stripped == "uncertain:":
            in_uncertain = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"title", "observation", "question"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            print(
                json.dumps({"warning": f"uncertain entry missing required field(s) {sorted(missing)}, skipping: {entry}"}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_distilled_from(content: str) -> list[dict]:
    """Parse distilled-from list from abstract spec frontmatter.

    Each entry has two required fields: path and hash.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        distilled-from:
          - path: src/retry.py
            hash: a3f8c2e9b7d1
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_distilled = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_distilled:
            if re.match(r"^  - path:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"path": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed distilled-from entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_distilled = False
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_distilled = False

        if stripped == "distilled-from:":
            in_distilled = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"path", "hash"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            msg = f"distilled-from entry missing required field(s) {sorted(missing)}, skipping: {entry}"
            print(
                json.dumps({"warning": msg}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_absorbed_from(content: str) -> list[dict]:
    """Parse absorbed-from list from abstract spec frontmatter.

    Each entry has two required fields: path and hash.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        absorbed-from:
          - path: src/retry.py.spec.md
            hash: a3f8c2e9b7d1
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_absorbed = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_absorbed:
            if re.match(r"^  - path:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"path": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed absorbed-from entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_absorbed = False
                continue
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_absorbed = False
                continue

        if stripped == "absorbed-from:":
            in_absorbed = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"path", "hash"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            msg = f"absorbed-from entry missing required field(s) {sorted(missing)}, skipping: {entry}"
            print(
                json.dumps({"warning": msg}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_exuded_from(content: str) -> list[dict]:
    """Parse exuded-from list from abstract spec frontmatter.

    Symmetric with absorbed-from: a spec may be exuded multiple times.
    Each entry has two required fields: path and hash.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        exuded-from:
          - path: src/network.unit.spec.md
            hash: a3f8c2e9b7d1
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_exuded = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_exuded:
            if re.match(r"^  - path:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"path": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed exuded-from entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_exuded = False
                continue
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_exuded = False
                continue

        if stripped == "exuded-from:":
            in_exuded = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"path", "hash"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            msg = f"exuded-from entry missing required field(s) {sorted(missing)}, skipping: {entry}"
            print(
                json.dumps({"warning": msg}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_provenance_history(content: str) -> list[dict]:
    """Parse provenance-history append-only audit log from spec frontmatter.

    Each entry has four required fields: type, path, hash, timestamp.
    Entries are delimited by ``- type:`` and preserve input order.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        provenance-history:
          - type: absorbed-from
            path: src/retry.py
            hash: a3f8c2e9b7d1
            timestamp: 2026-03-15T14:30:00Z
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_provenance = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_provenance:
            if re.match(r"^  - type:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"type": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed provenance-history entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_provenance = False
                continue
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_provenance = False
                continue

        if stripped == "provenance-history:":
            in_provenance = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"type", "path", "hash", "timestamp"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            msg = f"provenance-history entry missing required field(s) {sorted(missing)}, skipping: {entry}"
            print(
                json.dumps({"warning": msg}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_discovered(content: str) -> list[dict]:
    """Parse discovered constraint entries from abstract spec frontmatter.

    Written by the Archaeologist during Generate Stage 0.
    Entries missing required fields are skipped with a stderr warning.

    Supported format (strict string matching, not YAML):
        ---
        discovered:
          - title: "Implicit ordering constraint"
            observation: "Retry depends on token refresh before each attempt."
            question: "Should the spec require token refresh before retry?"
        ---

    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return []

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return []

    frontmatter_lines = lines[1:end]

    entries = []
    in_discovered = False
    current_entry: dict | None = None

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_discovered:
            if re.match(r"^  - title:", line):
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {"title": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_entry[key.strip()] = val.strip().strip('"').strip("'")
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed discovered entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_discovered = False
            else:
                if current_entry is not None:
                    entries.append(current_entry)
                    current_entry = None
                in_discovered = False

        if stripped == "discovered:":
            in_discovered = True

    # Flush final entry
    if current_entry is not None:
        entries.append(current_entry)

    _required_fields = {"title", "observation", "question"}
    validated = []
    for entry in entries:
        missing = _required_fields - set(entry.keys())
        if missing:
            print(
                json.dumps({"warning": f"discovered entry missing required field(s) {sorted(missing)}, skipping: {entry}"}),
                file=sys.stderr,
            )
        else:
            validated.append(entry)

    return validated


def parse_concrete_frontmatter(content: str) -> dict:
    """Parse frontmatter from a concrete spec (.impl.md) file.

    Returns dict with: source_spec, target_language, ephemeral, complexity,
    concrete_dependencies (list of paths), targets (list of dicts),
    blocked_by (list of dicts with symbol, reason, resolution, affects),
    protected_regions (list of dicts with marker, position, semantics, starts_at).
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
    blocked_by = []
    in_blocked_by = False
    current_blocker = None
    protected_regions = []
    in_protected_regions = False
    current_region = None

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

        if in_blocked_by:
            if re.match(r"^  - symbol:", line):
                if current_blocker:
                    blocked_by.append(current_blocker)
                current_blocker = {"symbol": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_blocker and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    current_blocker[key.strip()] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_blocker:
                    blocked_by.append(current_blocker)
                    current_blocker = None
                in_blocked_by = False

        if in_protected_regions:
            if re.match(r"^  - marker:", line):
                if current_region:
                    protected_regions.append(current_region)
                current_region = {"marker": line.split(":", 1)[1].strip().strip('"').strip("'")}
                continue
            elif current_region and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                if key.strip() and val.strip():
                    parsed_key = key.strip().replace("-", "_")
                    current_region[parsed_key] = val.strip().strip('"').strip("'")
                continue
            else:
                if current_region:
                    protected_regions.append(current_region)
                    current_region = None
                in_protected_regions = False

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
        elif stripped == "blocked-by:":
            in_blocked_by = True
        elif stripped == "protected-regions:":
            in_protected_regions = True

    # Flush final target
    if current_target:
        targets.append(current_target)

    if current_blocker:
        blocked_by.append(current_blocker)

    if current_region:
        protected_regions.append(current_region)

    if concrete_deps:
        result["concrete_dependencies"] = concrete_deps
    if targets:
        result["targets"] = targets

    _required_blocker_fields = {"symbol", "reason", "resolution", "affects"}
    validated_blockers = []
    for entry in blocked_by:
        missing = _required_blocker_fields - set(entry.keys())
        if missing:
            print(
                json.dumps({"warning": f"blocked-by entry missing required field(s) {sorted(missing)}, skipping: {entry}"}),
                file=sys.stderr,
            )
        else:
            validated_blockers.append(entry)
    if validated_blockers:
        result["blocked_by"] = validated_blockers
        if result.get("ephemeral", True):
            print(
                json.dumps({"warning": "blocked-by on ephemeral concrete spec has no effect -- promote to permanent first"}),
                file=sys.stderr,
            )

    _required_region_fields = {"marker", "position", "semantics", "starts_at"}
    _valid_semantics = {"test-suite", "entry-point", "examples", "benchmarks"}
    validated_regions = []
    for entry in protected_regions:
        missing = _required_region_fields - set(entry.keys())
        if missing:
            print(
                json.dumps(
                    {"warning": f"protected-regions entry missing required field(s) {sorted(missing)}, skipping: {entry}"}
                ),
                file=sys.stderr,
            )
        else:
            if entry["semantics"] not in _valid_semantics:
                print(
                    json.dumps(
                        {"warning": f"protected-regions entry has unknown semantics {entry['semantics']!r} -- keeping entry"}
                    ),
                    file=sys.stderr,
                )
            validated_regions.append(entry)
    if validated_regions:
        result["protected_regions"] = validated_regions

    return result
