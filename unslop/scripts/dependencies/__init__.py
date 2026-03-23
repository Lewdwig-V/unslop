"""Dependency resolution: abstract spec graph, concrete inheritance, unified DAG."""

from __future__ import annotations

from dependencies.concrete_graph import (
    MAX_EXTENDS_DEPTH,
    STRICT_CHILD_ONLY,
    build_concrete_order,
    check_concrete_staleness,
    flatten_inheritance_chain,
    get_all_strategy_providers,
    resolve_extends_chain,
    resolve_inherited_sections,
)
from dependencies.graph import build_order_from_dir, resolve_deps, topo_sort
from dependencies.unified_dag import (
    _build_unified_dag,
    _compute_parallel_batches,
    _unified_topo_sort,
)

__all__ = [
    "MAX_EXTENDS_DEPTH",
    "STRICT_CHILD_ONLY",
    "_build_unified_dag",
    "_compute_parallel_batches",
    "_unified_topo_sort",
    "build_concrete_order",
    "build_order_from_dir",
    "check_concrete_staleness",
    "flatten_inheritance_chain",
    "get_all_strategy_providers",
    "resolve_deps",
    "resolve_extends_chain",
    "resolve_inherited_sections",
    "topo_sort",
]
