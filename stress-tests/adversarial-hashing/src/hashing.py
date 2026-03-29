# @unslop-managed -- Edit hashing.py.spec.md instead
# spec-hash:8e43c7b51522 output-hash:0086857549bd generated:2026-03-28T00:00:00Z
from __future__ import annotations

import hashlib
import re
import sys

MISSING_SENTINEL: str = "missing00000"
UNREADABLE_SENTINEL: str = "unreadabl000"
_SENTINEL_HASHES: set = {MISSING_SENTINEL, UNREADABLE_SENTINEL}

_COMMENT_PREFIXES = ["<!--", "/*", "//", "--", "#"]
_COMMENT_SUFFIXES = ["-->", "*/"]


def compute_hash(content: str) -> str:
    """Return 12-char lowercase hex SHA-256 of stripped content."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:12]


def _strip_comment(line: str) -> str:
    """Strip the first matching comment prefix and any matching suffix."""
    stripped = line.strip()
    for prefix in _COMMENT_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    for suffix in _COMMENT_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return stripped.strip()


def _is_header_line(line: str) -> bool:
    """Check if a line looks like a header marker line."""
    stripped = _strip_comment(line)
    if not stripped:
        return False
    markers = [
        "@unslop-managed",
        "spec-hash:",
        "output-hash:",
        "principles-hash:",
        "concrete-deps-hash:",
        "generated:",
        "managed-end-line:",
        "concrete-manifest:",
        "Generated from spec at",
    ]
    return any(marker in stripped for marker in markers)


def parse_header(content: str) -> dict | None:
    """Parse the unslop header from the first 5 lines of content.

    Returns a dict with 9 keys if @unslop-managed marker found, else None.
    """
    if not content:
        return None

    lines = content.split("\n")[:5]

    spec_path = None
    spec_hash = None
    output_hash = None
    principles_hash = None
    concrete_deps_hash = None
    concrete_manifest = None
    managed_end_line = None
    generated = None
    old_format = False

    found_marker = False

    for line in lines:
        stripped = _strip_comment(line)

        # Check for @unslop-managed marker
        m = re.search(r"@unslop-managed\s+--\s+Edit\s+(\S+)\s+instead", stripped)
        if m:
            spec_path = m.group(1)
            found_marker = True

        # Check for spec-hash
        m = re.search(r"spec-hash:([0-9a-f]{12})", stripped)
        if m:
            spec_hash = m.group(1)

        # Check for output-hash
        m = re.search(r"output-hash:([0-9a-f]{12})", stripped)
        if m:
            output_hash = m.group(1)

        # Check for principles-hash
        m = re.search(r"principles-hash:([0-9a-f]{12})", stripped)
        if m:
            principles_hash = m.group(1)

        # Check for concrete-deps-hash
        m = re.search(r"concrete-deps-hash:([0-9a-f]{12})", stripped)
        if m:
            concrete_deps_hash = m.group(1)

        # Check for generated timestamp
        m = re.search(r"generated:(\S+)", stripped)
        if m:
            generated = m.group(1)

        # Check for managed-end-line
        m = re.search(r"managed-end-line:(\d+)", stripped)
        if m:
            managed_end_line = int(m.group(1))

        # Check for concrete-manifest
        m = re.search(r"concrete-manifest:(.+)", stripped)
        if m:
            manifest_str = m.group(1).strip()
            concrete_manifest = {}
            entries = manifest_str.split(",")
            for entry in entries:
                entry = entry.strip()
                if not entry:
                    continue
                # Use rfind to split path from hash (paths may contain colons)
                colon_pos = entry.rfind(":")
                if colon_pos < 0:
                    continue
                path = entry[:colon_pos]
                hash_val = entry[colon_pos + 1 :]
                # Only include entries with valid 12-char hex or sentinel values
                if not path:
                    continue
                if hash_val in _SENTINEL_HASHES:
                    concrete_manifest[path] = hash_val
                elif re.match(r"^[0-9a-f]{12}$", hash_val):
                    concrete_manifest[path] = hash_val
                # else: silently drop malformed entries

        # Check for old format
        m = re.search(r"Generated from spec at\s+(\S+)", stripped)
        if m:
            generated = m.group(1)
            old_format = True

    if not found_marker:
        return None

    # Determine old_format based on spec_hash being None when old format marker seen
    if spec_hash is None and old_format:
        old_format = True
    elif not old_format:
        old_format = False

    return {
        "spec_path": spec_path,
        "spec_hash": spec_hash,
        "output_hash": output_hash,
        "principles_hash": principles_hash,
        "concrete_deps_hash": concrete_deps_hash,
        "concrete_manifest": concrete_manifest if concrete_manifest else None,
        "managed_end_line": managed_end_line,
        "generated": generated,
        "old_format": old_format,
    }


def get_body_below_header(content: str, end_line: int | None = None) -> str:
    """Extract body content below the header.

    Scans first 5 lines for header markers and blank lines. Stops at
    first non-header, non-blank line. Returns everything after.

    When end_line is provided and valid, truncates body at end_line - 1
    (1-indexed, exclusive). Invalid end_line triggers stderr warning.
    """
    if not content:
        return ""

    lines = content.split("\n")
    body_start = 0

    # Scan first 5 lines for header
    for i, line in enumerate(lines[:5]):
        if _is_header_line(line) or line.strip() == "":
            body_start = i + 1
        else:
            break

    body_lines = lines[body_start:]

    if end_line is not None:
        # Validate end_line: must be >= 1 and after header
        if end_line < 1 or end_line <= body_start + 1:
            print(
                f"Warning: invalid end_line={end_line} (body starts at line {body_start + 1})",
                file=sys.stderr,
            )
            return "\n".join(body_lines)

        # end_line is 1-indexed, exclusive -- truncate body
        # body_lines starts at body_start (0-indexed)
        # We want lines from body_start to end_line - 2 (inclusive, 0-indexed)
        truncated_end = end_line - 1 - body_start
        if truncated_end < len(body_lines):
            body_lines = body_lines[:truncated_end]

    return "\n".join(body_lines)
