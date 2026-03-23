"""Resume sync planning: compute minimal plan to finish a partial bulk sync."""

from __future__ import annotations

from pathlib import Path

from core.hashing import parse_header
from dependencies.unified_dag import (
    _build_unified_dag,
    _compute_parallel_batches,
    _unified_topo_sort,
)
from freshness.checker import check_freshness


def compute_resume_plan(
    project_root: str,
    failed_files: list[str],
    succeeded_files: list[str],
    force: bool = False,
    max_batch_size: int = 8,
) -> dict:
    """Compute a plan to resume a partial bulk sync after a batch failure.

    When a Builder fails on some files in a batch, the sibling files in
    that batch may have succeeded (they're independent).  This function
    computes the minimal plan to finish the job:

    1. Exclude succeeded_files -- they're already fresh.
    2. Include failed_files -- they need retry after the user fixes the spec.
    3. Include all transitive downstream dependents of failed_files that
       are still stale -- they were blocked by the failure.
    4. Re-check freshness to exclude anything that became fresh since
       the original plan was computed.

    Args:
        project_root: Project root directory.
        failed_files: Managed file paths that failed during the previous run.
        succeeded_files: Managed file paths that succeeded (skip these).
        force: If True, include modified/conflict files.
        max_batch_size: Maximum files per worktree batch.

    Returns:
        dict with batches, skipped, stats, build_order (same shape as
        compute_bulk_sync_plan), plus:
          - resumed_from: The failed files that triggered the resume.
          - already_done: Count of succeeded files excluded from the plan.
    """
    root = Path(project_root).resolve()

    # 1. Get current freshness
    try:
        freshness = check_freshness(str(root))
    except (ValueError, OSError) as e:
        return {"error": f"Freshness check failed: {e}"}

    state_map = {f["managed"]: f for f in freshness.get("files", [])}
    succeeded_set = set(succeeded_files)

    # 2. Identify the specs of failed files
    failed_specs: set[str] = set()
    for managed in failed_files:
        entry = state_map.get(managed)
        if entry and entry.get("spec"):
            failed_specs.add(entry["spec"])
        else:
            # Try header-based resolution
            managed_full = root / managed
            if managed_full.exists():
                try:
                    content = managed_full.read_text(encoding="utf-8")
                    header = parse_header(content)
                    if header and header.get("spec_path"):
                        failed_specs.add(header["spec_path"])
                except (OSError, UnicodeDecodeError):
                    pass
            # Fall back to basename
            if managed + ".spec.md" not in failed_specs:
                candidate = managed + ".spec.md"
                if (root / candidate).exists():
                    failed_specs.add(candidate)

    if not failed_specs:
        return {
            "batches": [],
            "skipped": [],
            "resumed_from": failed_files,
            "already_done": len(succeeded_files),
            "stats": {
                "total_stale": 0,
                "total_batches": 0,
                "to_regenerate": 0,
                "skipped_need_confirm": 0,
            },
            "build_order": [],
        }

    # 3. Build unified DAG and find downstream closure of failed specs
    graph, impl_to_spec = _build_unified_dag(root)

    # Build reverse graph (spec -> set of specs that depend on it)
    reverse: dict[str, set[str]] = {s: set() for s in graph}
    for spec, deps in graph.items():
        for dep in deps:
            reverse.setdefault(dep, set()).add(spec)

    # BFS from failed specs to find all downstream dependents
    downstream: set[str] = set(failed_specs)
    queue = list(failed_specs)
    while queue:
        current = queue.pop(0)
        for dependent in reverse.get(current, set()):
            if dependent not in downstream:
                downstream.add(dependent)
                queue.append(dependent)

    # 4. Collect all stale files whose spec is in the downstream set
    plan_entries: list[dict] = []
    skipped: list[dict] = []

    for entry in freshness.get("files", []):
        managed = entry["managed"]
        spec = entry.get("spec")
        state = entry["state"]

        # Skip fresh files
        if state == "fresh":
            continue
        # Skip succeeded files
        if managed in succeeded_set:
            continue
        # Only include files whose spec is in the downstream closure
        if spec not in downstream:
            continue

        plan_entry = {
            "managed": managed,
            "spec": spec,
            "state": state,
            "cause": "retry" if spec in failed_specs else "downstream",
        }

        if state in ("modified", "conflict") and not force:
            skipped.append(plan_entry)
        else:
            plan_entries.append(plan_entry)

    if not plan_entries:
        return {
            "batches": [],
            "skipped": skipped,
            "resumed_from": failed_files,
            "already_done": len(succeeded_files),
            "stats": {
                "total_stale": 0,
                "total_batches": 0,
                "to_regenerate": 0,
                "skipped_need_confirm": len(skipped),
            },
            "build_order": [],
        }

    # 5. Sort and batch using unified DAG
    plan_specs = {e["spec"] for e in plan_entries}
    sorted_specs, sub_graph, _ = _unified_topo_sort(root, filter_specs=plan_specs)
    spec_order = {s: i for i, s in enumerate(sorted_specs)}
    plan_entries.sort(key=lambda e: spec_order.get(e["spec"], 999999))

    batches = _compute_parallel_batches(plan_entries, sub_graph, max_batch_size=max_batch_size)

    return {
        "batches": [
            {
                "batch_index": i,
                "files": batch,
                "size": len(batch),
            }
            for i, batch in enumerate(batches)
        ],
        "skipped": skipped,
        "resumed_from": failed_files,
        "already_done": len(succeeded_files),
        "stats": {
            "total_stale": len(plan_entries) + len(skipped),
            "total_batches": len(batches),
            "to_regenerate": len(plan_entries),
            "skipped_need_confirm": len(skipped),
        },
        "build_order": sorted_specs,
    }
