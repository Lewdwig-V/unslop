"""Bulk sync planning: batch all stale files respecting topological order."""

from __future__ import annotations

from pathlib import Path

from dependencies.unified_dag import _compute_parallel_batches, _unified_topo_sort
from freshness.checker import check_freshness
from planning.ripple import ripple_check


def compute_bulk_sync_plan(
    project_root: str,
    force: bool = False,
    max_batch_size: int = 8,
) -> dict:
    """Compute a batched plan for syncing ALL stale files in the project.

    Instead of processing each stale file individually (each spawning its own
    Agent+worktree), this groups stale files into worktree batches that respect
    topological order.  Files within a batch share no dependency edges, so they
    can be regenerated in parallel inside a single worktree.

    Args:
        project_root: Project root directory.
        force: If True, include modified/conflict files without flagging.
        max_batch_size: Maximum files per worktree batch (caps parallelism).

    Returns:
        dict with:
          - batches: Ordered list of batches, each containing files to regenerate.
          - skipped: Files that need user confirmation (modified/conflict).
          - stats: Summary counts.
          - build_order: Topological spec order used for sequencing.
    """
    root = Path(project_root).resolve()

    # 1. Get freshness data for all files
    try:
        freshness = check_freshness(str(root))
    except (ValueError, OSError) as e:
        return {"error": f"Freshness check failed: {e}"}

    state_map = {f["managed"]: f for f in freshness.get("files", [])}

    # 2. Collect all non-fresh files
    stale_files = []
    for entry in freshness.get("files", []):
        state = entry["state"]
        if state == "fresh":
            continue
        stale_files.append(entry)

    if not stale_files:
        return {
            "batches": [],
            "skipped": [],
            "stats": {
                "total_stale": 0,
                "total_batches": 0,
                "to_regenerate": 0,
                "skipped_need_confirm": 0,
            },
            "build_order": [],
        }

    # 3. Collect all unique specs from stale files for a combined ripple check
    stale_specs = set()
    for entry in stale_files:
        spec = entry.get("spec")
        if spec:
            stale_specs.add(spec)

    if not stale_specs:
        return {
            "batches": [],
            "skipped": [],
            "stats": {
                "total_stale": len(stale_files),
                "total_batches": 0,
                "to_regenerate": 0,
                "skipped_need_confirm": 0,
            },
            "build_order": [],
        }

    # 4. Combined ripple check for all stale specs at once
    try:
        ripple = ripple_check(sorted(stale_specs), str(root))
    except (ValueError, OSError) as e:
        return {"error": f"Ripple check failed: {e}"}

    # 5. Merge all affected files (direct + ghost-stale), deduped
    all_affected: list[dict] = []
    seen_managed: set[str] = set()

    for entry in ripple["layers"]["code"]["regenerate"]:
        managed = entry["managed"]
        if managed in seen_managed:
            continue
        seen_managed.add(managed)
        fresh_entry = state_map.get(managed)
        state = fresh_entry["state"] if fresh_entry else entry.get("current_state", "new")
        all_affected.append(
            {
                "managed": managed,
                "spec": entry["spec"],
                "state": state,
                "cause": entry["cause"],
                "concrete": entry.get("concrete"),
            }
        )

    for entry in ripple["layers"]["code"]["ghost_stale"]:
        managed = entry["managed"]
        if managed in seen_managed:
            continue
        seen_managed.add(managed)
        fresh_entry = state_map.get(managed)
        state = fresh_entry["state"] if fresh_entry else "ghost-stale"
        all_affected.append(
            {
                "managed": managed,
                "spec": entry["spec"],
                "state": state,
                "cause": entry["cause"],
                "concrete": entry.get("concrete"),
            }
        )

    # 6. Split into actionable vs skipped
    plan_entries = []
    skipped = []

    for entry in all_affected:
        state = entry["state"]
        if state == "fresh":
            continue
        if state in ("modified", "conflict") and not force:
            skipped.append(entry)
        else:
            plan_entries.append(entry)

    # 7. Unified topo sort via single DAG (abstract + concrete edges)
    plan_specs = {e["spec"] for e in plan_entries}
    sorted_specs, graph, _ = _unified_topo_sort(root, filter_specs=plan_specs)
    spec_order = {s: i for i, s in enumerate(sorted_specs)}
    plan_entries.sort(key=lambda e: spec_order.get(e["spec"], 999999))
    build_order = sorted_specs

    # 8. Parallel-safe batching via Kahn's depth grouping.
    #    Nodes at the same topological depth share no dependency edges,
    #    so they can safely run in parallel within a single worktree.
    batches = _compute_parallel_batches(plan_entries, graph, max_batch_size=max_batch_size)

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
        "stats": {
            "total_stale": len(stale_files),
            "total_batches": len(batches),
            "to_regenerate": len(plan_entries),
            "skipped_need_confirm": len(skipped),
            "fresh_skipped": len(all_affected) - len(plan_entries) - len(skipped),
        },
        "build_order": build_order,
    }
