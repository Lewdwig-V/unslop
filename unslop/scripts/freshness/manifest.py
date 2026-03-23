"""Concrete dependency manifest computation for ghost-staleness detection."""

from __future__ import annotations

from pathlib import Path

from ..core.frontmatter import parse_concrete_frontmatter
from ..core.hashing import MISSING_SENTINEL, UNREADABLE_SENTINEL, compute_hash
from ..dependencies.concrete_graph import get_all_strategy_providers


def _gather_recursive_providers(
    root: Path,
    meta: dict,
    seen: set | None = None,
) -> list[str]:
    """Recursively gather all strategy provider content from the full DAG.

    Walks concrete-dependencies and extends transitively, returning a
    sorted list of ``path:hash`` entries for every node in the tree.
    The ``seen`` set prevents infinite loops on circular references.
    """
    if seen is None:
        seen = set()

    entries = []
    providers = get_all_strategy_providers(meta)

    for dep_path in sorted(providers):
        if dep_path in seen:
            continue
        seen.add(dep_path)

        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                entries.append(f"{dep_path}:{compute_hash(dep_content)}")
                # Recurse into this provider's own upstream
                dep_meta = parse_concrete_frontmatter(dep_content)
                entries.extend(_gather_recursive_providers(root, dep_meta, seen))
            except (OSError, UnicodeDecodeError):
                entries.append(f"{dep_path}:unreadable")
        else:
            entries.append(f"{dep_path}:missing")

    return entries


def compute_concrete_deps_hash(impl_path: str, project_root: str) -> str | None:
    """Compute a deep hash of all transitive strategy providers.

    Recursively walks concrete-dependencies and extends chains so that
    a change to a grandparent spec correctly invalidates all descendants.
    Returns a 12-char hex hash, or None if no strategy providers exist.
    Raises ValueError if the impl file exists but cannot be read.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"Cannot read concrete spec: {impl} ({e})")

    meta = parse_concrete_frontmatter(content)
    providers = get_all_strategy_providers(meta)
    if not providers:
        return None

    root = Path(project_root).resolve()
    combined = _gather_recursive_providers(root, meta)
    return compute_hash("\n".join(combined))


def compute_concrete_manifest(impl_path: str, project_root: str) -> dict[str, str] | None:
    """Compute a per-dependency manifest for surgical ghost-staleness detection.

    Returns a dict of {dep_path: 12-char-hex-hash} for all **transitive**
    strategy providers (concrete-dependencies + extends parent, recursively).
    Returns None if no strategy providers exist.

    Unlike compute_concrete_deps_hash (which produces a single opaque hash),
    the manifest stores each dependency individually so check_freshness() can
    pinpoint exactly which dep changed -- including deep transitive changes.
    """
    impl = Path(impl_path)
    if not impl.exists():
        return None

    try:
        content = impl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"Cannot read concrete spec: {impl} ({e})")

    meta = parse_concrete_frontmatter(content)
    direct_providers = get_all_strategy_providers(meta)
    if not direct_providers:
        return None

    root = Path(project_root).resolve()
    manifest = {}

    # BFS through the full transitive provider tree
    queue = list(direct_providers)
    visited: set[str] = set()

    while queue:
        dep_path = queue.pop(0)
        if dep_path in visited:
            continue
        visited.add(dep_path)

        dep_full = root / dep_path
        if dep_full.exists():
            try:
                dep_content = dep_full.read_text(encoding="utf-8")
                manifest[dep_path] = compute_hash(dep_content)
                # Walk this dep's own providers (transitive)
                dep_meta = parse_concrete_frontmatter(dep_content)
                for upstream in get_all_strategy_providers(dep_meta):
                    if upstream not in visited:
                        queue.append(upstream)
            except (OSError, UnicodeDecodeError):
                manifest[dep_path] = UNREADABLE_SENTINEL
        else:
            manifest[dep_path] = MISSING_SENTINEL

    return manifest if manifest else None


def format_manifest_header(manifest: dict[str, str]) -> str:
    """Format a concrete manifest dict as a header-safe string.

    Output: dep1.impl.md:a3f8c2e9b7d1,dep2.impl.md:7f2e1b8a9c04
    """
    return ",".join(f"{path}:{h}" for path, h in sorted(manifest.items()))
