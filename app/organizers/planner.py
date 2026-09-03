from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.organizers.engine import OrganizerProposal


def compute_final_paths(proposals: list[OrganizerProposal]) -> dict[str, str]:
    """
    Compute final paths of all directories taking into account ancestor and self renames.
    Sorts by source depth (shallowest first). Each directory's parent final path
    is looked up from already computed final paths, correctly handling arbitrary depth (e.g. >= 4 levels).
    Returns mapping: {original_source_str: final_path_str}
    """
    sorted_proposals = sorted(
        proposals,
        key=lambda p: len(Path(p.source).parts),
    )

    final_paths: dict[Path, Path] = {}

    for prop in sorted_proposals:
        src = Path(prop.source)
        parent_src = src.parent

        if parent_src in final_paths:
            final_parent = final_paths[parent_src]
        else:
            final_parent = parent_src

        if prop.changed:
            final_name = Path(prop.target).name
        else:
            final_name = src.name

        final_paths[src] = final_parent / final_name

    return {str(k): str(v) for k, v in final_paths.items()}


def detect_rename_cycles_and_sort(rename_items: list[dict]) -> tuple[list[dict], set[str]]:
    """
    Topologically sort rename items to resolve dependency chains (e.g. 001->002, 002->003).
    Returns (sorted_items, cycle_sources). If cycle_sources is non-empty, a cycle was detected.
    """
    if len(rename_items) <= 1:
        return rename_items, set()

    # If target of item A is source of item B, item B must execute before item A
    # Nodes: indices in rename_items
    n = len(rename_items)
    source_to_idx = {item["source"]: i for i, item in enumerate(rename_items)}

    adj = defaultdict(list)
    in_degree = [0] * n

    for i, item in enumerate(rename_items):
        target = item["target"]
        if target in source_to_idx and source_to_idx[target] != i:
            j = source_to_idx[target]
            # j must execute before i (j moves away so i can move in)
            adj[j].append(i)
            in_degree[i] += 1

    queue = deque([i for i in range(n) if in_degree[i] == 0])
    ordered_indices = []

    while queue:
        u = queue.popleft()
        ordered_indices.append(u)
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if len(ordered_indices) < n:
        # Cycle detected among nodes with in_degree > 0
        cycle_sources = {rename_items[i]["source"] for i in range(n) if in_degree[i] > 0}
        return rename_items, cycle_sources

    return [rename_items[i] for i in ordered_indices], set()


def plan_organizer_operations(
    proposals: list[OrganizerProposal],
    *,
    include_touch: bool = True,
    mtime_mode: str = "none",
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Plan rename and touch operations:
    1. Sort renames bottom-up (deepest directories first) so child renames happen before parent renames.
    2. At each depth, resolve dependency chains (e.g. 001->002, 002->003) via topological sort.
    3. Detect cycles (e.g. A->B, B->A).
    4. Sequence touch operations on final computed paths after all renames.
    """
    final_path_map = compute_final_paths(proposals)

    # Filter proposals that require rename
    changed_proposals = [p for p in proposals if p.changed and not p.conflict]

    # Group renames by path depth
    depth_groups: dict[int, list[dict]] = defaultdict(list)
    for p in changed_proposals:
        src = Path(p.source)
        tgt = Path(p.target)
        depth = len(src.parts)
        depth_groups[depth].append({
            "operation": "rename",
            "source": str(src),
            "target": str(tgt),
            "depth": depth,
        })

    all_renames: list[dict] = []
    all_cycle_sources: set[str] = set()

    # Process from deepest to shallowest (bottom-up)
    for depth in sorted(depth_groups.keys(), reverse=True):
        items_at_depth = depth_groups[depth]
        sorted_at_depth, cycle_sources = detect_rename_cycles_and_sort(items_at_depth)
        if cycle_sources:
            all_cycle_sources.update(cycle_sources)
        all_renames.extend(sorted_at_depth)

    # If any cycles were found, return early with cycle sources flagged
    if all_cycle_sources:
        return all_renames, all_cycle_sources

    plan_items: list[dict[str, Any]] = []
    seq = 1

    for r in all_renames:
        plan_items.append({
            "sequence": seq,
            "operation": "rename",
            "source": r["source"],
            "target": r["target"],
        })
        seq += 1

    # If ordered touch is requested, append touch operations on final paths
    if include_touch and mtime_mode == "ordered":
        # Sort directories by their expected mtime order or target name
        touch_proposals = sorted(
            proposals,
            key=lambda p: (
                p.expected_mtime_order if p.expected_mtime_order is not None else 999999,
                p.target,
            ),
        )
        for p in touch_proposals:
            final_path = final_path_map.get(p.source, p.target)
            plan_items.append({
                "sequence": seq,
                "operation": "touch",
                "source": final_path,
                "target": None,
            })
            seq += 1

    return plan_items, set()
