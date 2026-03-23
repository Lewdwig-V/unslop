"""Deep sync planning: compute ordered plan for a file and its blast radius."""

from __future__ import annotations

from pathlib import Path

from ..core.hashing import parse_header
from ..dependencies.unified_dag import _unified_topo_sort
from ..freshness.checker import check_freshness
from .ripple import ripple_check


def compute_deep_sync_plan(
    file_path: str,
    project_root: str,
    force: bool = False,
) -> dict:
    """Compute an ordered plan for deep-syncing a file and its blast radius.

    Starting from a single managed file (or spec), identifies all downstream
    files that need regeneration and returns them in topological order.

    Args:
        file_path: Path to the managed file or spec to start from.
        project_root: Project root directory.
        force: If True, include modified/conflict files without flagging them.

    Returns:
        dict with:
          - trigger: The input file/spec that initiated the deep sync.
          - plan: Ordered list of dicts, each with:
              managed, spec, state, cause, concrete (optional)
          - skipped: Files that need user confirmation (modified/conflict).
          - stats: Summary counts.
    """
    root = Path(project_root).resolve()

    # Normalize: if given a managed file, derive the spec; if given a spec, use it
    fp = Path(file_path)
    if fp.suffix == ".md" and ".spec." in fp.name:
        trigger_spec = file_path
    else:
        # Managed file -> try reading spec path from @unslop-managed header
        trigger_spec = None
        managed_full = root / file_path
        if managed_full.exists():
            try:
                managed_content = managed_full.read_text(encoding="utf-8")
                header = parse_header(managed_content)
                if header and header.get("spec_path"):
                    trigger_spec = header["spec_path"]
            except (OSError, UnicodeDecodeError):
                pass

        # Fall back to basename convention if header lookup failed
        if not trigger_spec:
            trigger_spec = file_path + ".spec.md"

    trigger_spec_full = root / trigger_spec
    if not trigger_spec_full.exists():
        return {"error": f"No spec found at {trigger_spec}"}

    # Get freshness data for all files
    try:
        freshness = check_freshness(str(root))
    except (ValueError, OSError) as e:
        return {"error": f"Freshness check failed: {e}"}

    state_map = {f["managed"]: f for f in freshness.get("files", [])}

    # Use ripple_check to compute full blast radius from this spec
    ripple = ripple_check([trigger_spec], str(root))

    # Merge the code-layer results: both direct regenerations and ghost-stale
    all_affected: list[dict] = []
    seen_managed: set[str] = set()

    for entry in ripple["layers"]["code"]["regenerate"]:
        managed = entry["managed"]
        if managed in seen_managed:
            continue
        seen_managed.add(managed)

        # Get actual freshness state from check_freshness
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

    # Split into actionable plan vs skipped (needs confirmation)
    plan = []
    skipped = []

    for entry in all_affected:
        state = entry["state"]
        if state == "fresh":
            continue  # Already up to date -- skip entirely
        if state in ("modified", "conflict") and not force:
            skipped.append(entry)
        else:
            plan.append(entry)

    # Order the plan using unified abstract+concrete DAG
    plan_specs = {e["spec"] for e in plan}
    sorted_specs, _, _ = _unified_topo_sort(root, filter_specs=plan_specs)
    spec_order = {s: i for i, s in enumerate(sorted_specs)}

    plan.sort(key=lambda e: spec_order.get(e["spec"], 999999))
    build_order = sorted_specs

    return {
        "trigger": trigger_spec,
        "plan": plan,
        "skipped": skipped,
        "stats": {
            "total_affected": len(all_affected),
            "to_regenerate": len(plan),
            "skipped_need_confirm": len(skipped),
            "fresh_skipped": len(all_affected) - len(plan) - len(skipped),
        },
        "build_order": build_order,
    }
