"""Freshness checking: file classification, staleness detection, manifest computation."""

from __future__ import annotations

from freshness.checker import (
    check_freshness,
    classify_file,
    diagnose_ghost_staleness,
    format_ghost_diagnostic,
)
from freshness.manifest import (
    compute_concrete_deps_hash,
    compute_concrete_manifest,
    format_manifest_header,
)

__all__ = [
    "check_freshness",
    "classify_file",
    "compute_concrete_deps_hash",
    "compute_concrete_manifest",
    "diagnose_ghost_staleness",
    "format_manifest_header",
    "format_ghost_diagnostic",
]
