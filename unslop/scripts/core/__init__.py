"""Core utilities: hashing, header parsing, frontmatter, file discovery."""

from __future__ import annotations

from core.frontmatter import parse_concrete_frontmatter, parse_frontmatter
from core.hashing import (
    MISSING_SENTINEL,
    UNREADABLE_SENTINEL,
    compute_hash,
    get_body_below_header,
    parse_header,
)
from core.spec_discovery import (
    EXCLUDED_DIRS,
    TEST_DIR_NAMES,
    TEST_FILE_PATTERNS,
    discover_files,
    file_tree,
    get_registry_key_for_spec,
    parse_unit_spec_files,
)

__all__ = [
    "EXCLUDED_DIRS",
    "MISSING_SENTINEL",
    "TEST_DIR_NAMES",
    "TEST_FILE_PATTERNS",
    "UNREADABLE_SENTINEL",
    "compute_hash",
    "discover_files",
    "file_tree",
    "get_body_below_header",
    "get_registry_key_for_spec",
    "parse_concrete_frontmatter",
    "parse_frontmatter",
    "parse_header",
    "parse_unit_spec_files",
]
