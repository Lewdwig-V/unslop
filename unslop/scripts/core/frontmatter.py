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


def _parse_nested_list_field(
    content: str,
    field_name: str,
    first_key: str,
    required_fields: set[str],
) -> list[dict]:
    """Shared state machine for parsing nested YAML-like list fields from frontmatter.

    Parses fields of the form::

        ---
        <field_name>:
          - <first_key>: value1
            other_key: value2
        ---

    Entries are delimited by ``- <first_key>:``. Each entry is a dict of
    key-value pairs. Entries missing any ``required_fields`` are skipped
    with a stderr warning.

    Fields present but with empty values (e.g., ``hash:`` with no value)
    emit a distinct "present but empty" warning rather than a generic
    "missing field" warning.

    Returns list of validated dicts, or empty list if absent or no frontmatter.
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
    in_section = False
    current_entry: dict | None = None
    entry_delimiter = re.compile(rf"^  - {re.escape(first_key)}:")
    seen_keys: set[str] = set()

    for line in frontmatter_lines:
        stripped = line.strip()

        if in_section:
            if entry_delimiter.match(line):
                if current_entry is not None:
                    entries.append((current_entry, seen_keys))
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                current_entry = {first_key: val} if val else {}
                seen_keys = {first_key}
                continue
            elif current_entry is not None and re.match(r"^    \w", line):
                key, _, val = stripped.partition(":")
                k = key.strip()
                if k:
                    seen_keys.add(k)
                    v = val.strip().strip('"').strip("'")
                    if v:
                        current_entry[k] = v
                continue
            elif re.match(r"^\s+- ", line) or (current_entry is not None and re.match(r"^\s+\w", line)):
                print(
                    json.dumps({"warning": f"possible malformed {field_name} entry (wrong indentation): {line!r}"}),
                    file=sys.stderr,
                )
                if current_entry is not None:
                    entries.append((current_entry, seen_keys))
                    current_entry = None
                    seen_keys = set()
                in_section = False
                continue
            else:
                if current_entry is not None:
                    entries.append((current_entry, seen_keys))
                    current_entry = None
                    seen_keys = set()
                in_section = False
                continue

        if stripped == f"{field_name}:":
            in_section = True

    if current_entry is not None:
        entries.append((current_entry, seen_keys))

    validated = []
    for entry, keys_seen in entries:
        missing = required_fields - set(entry.keys())
        if missing:
            # Distinguish "field present but empty" from "field absent"
            empty_fields = missing & keys_seen
            absent_fields = missing - keys_seen
            parts = []
            if absent_fields:
                parts.append(f"missing field(s) {sorted(absent_fields)}")
            if empty_fields:
                parts.append(f"empty value for field(s) {sorted(empty_fields)}")
            msg = f"{field_name} entry {', '.join(parts)}, skipping: {entry}"
            print(json.dumps({"warning": msg}), file=sys.stderr)
        else:
            validated.append(entry)

    return validated


def parse_uncertain(content: str) -> list[dict]:
    """Parse uncertain list from abstract spec frontmatter.

    Each entry has three required fields: title, observation, question.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "uncertain", "title", {"title", "observation", "question"})


def parse_distilled_from(content: str) -> list[dict]:
    """Parse distilled-from list from abstract spec frontmatter.

    Each entry has two required fields: path and hash.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "distilled-from", "path", {"path", "hash"})


def parse_absorbed_from(content: str) -> list[dict]:
    """Parse absorbed-from provenance list from spec frontmatter.

    Each entry has two required fields: path and hash.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "absorbed-from", "path", {"path", "hash"})


def parse_exuded_from(content: str) -> list[dict]:
    """Parse exuded-from provenance list from spec frontmatter.

    Symmetric with absorbed-from. Each entry has two required fields: path and hash.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "exuded-from", "path", {"path", "hash"})


def parse_provenance_history(content: str) -> list[dict]:
    """Parse provenance-history append-only audit log from spec frontmatter.

    Each entry has four required fields: type, path, hash, timestamp.
    Returns ordered list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "provenance-history", "type", {"type", "path", "hash", "timestamp"})


def parse_spec_changelog(content: str) -> list[dict]:
    """Parse spec-changelog entries from spec frontmatter.

    Append-only structured envelope for spec mutation history.
    Each entry has four required fields: hash, timestamp, operation, prior-hash.
    Returns ordered list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "spec-changelog", "hash", {"hash", "timestamp", "operation", "prior-hash"})


def parse_discovered(content: str) -> list[dict]:
    """Parse discovered constraint entries from abstract spec frontmatter.

    Written by the Archaeologist during Generate Stage 0.
    Each entry has three required fields: title, observation, question.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "discovered", "title", {"title", "observation", "question"})


def parse_rejected(content: str) -> list[dict]:
    """Parse rejected alternatives from spec frontmatter.

    Each entry has two required fields: title and rationale.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "rejected", "title", {"title", "rationale"})


def parse_constitutional_overrides(content: str) -> list[dict]:
    """Parse constitutional-overrides from spec frontmatter.

    Records explicit overrides of project principles with mandatory rationale.
    Each entry has three required fields: principle, rationale, timestamp.
    Returns list of dicts, or empty list if absent or no frontmatter.
    """
    return _parse_nested_list_field(content, "constitutional-overrides", "principle", {"principle", "rationale", "timestamp"})


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
