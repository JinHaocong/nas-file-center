from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import heapq
from pathlib import Path
from typing import Any, Iterable

from app.path_safety import UnsafePathError, validate_mutation_destination
from app.workflows.errors import (
    VirtualGraphCollisionError,
    VirtualGraphCycleError,
    WorkflowBoundaryError,
)
from app.workflows.schema import MoveStep, QuarantineStep, RenameStep, TouchStep


@dataclass
class VirtualOperation:
    candidate_id: int
    workflow_step_index: int
    candidate_operation_index: int
    operation: str
    source: str
    target: str | None
    mtime_ns: int | None = None
    reason: str | None = None
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "workflow_step_index": self.workflow_step_index,
            "candidate_operation_index": self.candidate_operation_index,
            "operation": self.operation,
            "source": self.source,
            "target": self.target,
            "sequence": self.sequence,
        }
        if self.mtime_ns is not None:
            d["mtime_ns"] = self.mtime_ns
        if self.reason is not None:
            d["reason"] = self.reason
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class VirtualCandidate:
    id: int
    original_path: str
    original_root_id: int
    current_path: str
    current_root_id: int
    size: int
    mtime_ns: int
    is_quarantined: bool = False
    operations: list[VirtualOperation] = field(default_factory=list)


class VirtualPathGraph:
    """
    In-memory multi-step virtual simulation graph.
    Tracks state of candidate files, verifies path safety boundaries,
    detects collisions and cycles, and determines execution ordering.
    """

    def __init__(
        self,
        allowed_roots: Iterable[Path | str],
        quarantine_root: Path | str | None = None,
    ):
        self.allowed_roots = list(allowed_roots)
        self.quarantine_root = quarantine_root
        self.candidates: dict[int, VirtualCandidate] = {}

    def add_candidate(self, cand: VirtualCandidate) -> None:
        self.candidates[cand.id] = cand

    def apply_rename(self, step: RenameStep, step_index: int = 0) -> None:
        pattern = step.pattern
        replacement = step.replacement

        step_targets: dict[str, int] = {}

        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue

            curr_p = Path(cand.current_path)
            curr_name = curr_p.name

            # Literal substring replacement only (regex strictly forbidden in V1)
            new_name = curr_name.replace(pattern, replacement)

            if new_name == curr_name:
                continue

            target_path_obj = curr_p.parent / new_name
            target_str = str(target_path_obj)

            # Validate boundary
            try:
                valid_target = validate_mutation_destination(
                    target_str,
                    self.allowed_roots,
                    quarantine_root=self.quarantine_root,
                )
                target_str = str(valid_target)
            except (UnsafePathError, ValueError) as exc:
                raise WorkflowBoundaryError(
                    f"Rename target '{target_str}' is outside allowed roots: {exc}",
                    details={"step_id": step.id, "target": target_str, "error": str(exc)},
                ) from exc

            # Collision check within same step
            if target_str in step_targets:
                other_id = step_targets[target_str]
                raise VirtualGraphCollisionError(
                    f"Path collision: multiple files renamed to same target '{target_str}'",
                    details={"step_id": step.id, "target": target_str, "file_ids": [other_id, cid]},
                )

            step_targets[target_str] = cid

            op_index = len(cand.operations)
            op = VirtualOperation(
                candidate_id=cid,
                workflow_step_index=step_index,
                candidate_operation_index=op_index,
                operation="rename",
                source=cand.current_path,
                target=target_str,
                metadata={"step_id": step.id},
            )
            cand.operations.append(op)
            cand.current_path = target_str

    def apply_move(
        self,
        step: MoveStep,
        destination_root_path: str,
        step_index: int = 0,
    ) -> None:
        dest_root_p = Path(destination_root_path)
        if step.destination_subpath:
            dest_dir = dest_root_p / step.destination_subpath.strip().lstrip("/\\")
        else:
            dest_dir = dest_root_p

        step_targets: dict[str, int] = {}

        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue

            curr_p = Path(cand.current_path)
            target_path_obj = dest_dir / curr_p.name
            target_str = str(target_path_obj)

            if target_str == cand.current_path:
                continue

            # Validate boundary
            try:
                valid_target = validate_mutation_destination(
                    target_str,
                    self.allowed_roots,
                    quarantine_root=self.quarantine_root,
                )
                target_str = str(valid_target)
            except (UnsafePathError, ValueError) as exc:
                raise WorkflowBoundaryError(
                    f"Move target '{target_str}' violates path boundary: {exc}",
                    details={"step_id": step.id, "target": target_str, "error": str(exc)},
                ) from exc

            # Collision check within same step
            if target_str in step_targets:
                other_id = step_targets[target_str]
                raise VirtualGraphCollisionError(
                    f"Path collision: multiple files moved to same target '{target_str}'",
                    details={"step_id": step.id, "target": target_str, "file_ids": [other_id, cid]},
                )

            step_targets[target_str] = cid

            op_index = len(cand.operations)
            op = VirtualOperation(
                candidate_id=cid,
                workflow_step_index=step_index,
                candidate_operation_index=op_index,
                operation="move",
                source=cand.current_path,
                target=target_str,
                metadata={"step_id": step.id},
            )
            cand.operations.append(op)
            cand.current_path = target_str
            cand.current_root_id = step.destination_root_id

    def apply_touch(self, step: TouchStep, step_index: int = 0) -> None:
        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue
            op_index = len(cand.operations)
            op = VirtualOperation(
                candidate_id=cid,
                workflow_step_index=step_index,
                candidate_operation_index=op_index,
                operation="touch",
                source=cand.current_path,
                target=None,
                mtime_ns=step.mtime_ns,
                metadata={"step_id": step.id},
            )
            cand.operations.append(op)

    def apply_quarantine(self, step: QuarantineStep, step_index: int = 0) -> None:
        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue
            op_index = len(cand.operations)
            op = VirtualOperation(
                candidate_id=cid,
                workflow_step_index=step_index,
                candidate_operation_index=op_index,
                operation="quarantine",
                source=cand.current_path,
                target=None,
                reason=step.reason,
                metadata={"step_id": step.id},
            )
            cand.operations.append(op)
            cand.is_quarantined = True

    def resolve_ordered_operations(self) -> list[dict[str, Any]]:
        """
        Collect all operations across candidates, enforce collision reservation rules,
        distinguish same-entity from cross-entity dependencies, detect cycles,
        and topologically sort operations deterministically.
        """
        # Map original paths to candidates
        original_path_to_cand: dict[str, VirtualCandidate] = {
            c.original_path: c for c in self.candidates.values()
        }

        # Gather all operations (convert dict to VirtualOperation if needed)
        all_ops: list[VirtualOperation] = []
        for cand in sorted(self.candidates.values(), key=lambda c: (c.original_path, c.id)):
            converted_ops: list[VirtualOperation] = []
            for idx, op in enumerate(cand.operations):
                if isinstance(op, dict):
                    op_obj = VirtualOperation(
                        candidate_id=cand.id,
                        workflow_step_index=op.get("workflow_step_index", 0),
                        candidate_operation_index=op.get("candidate_operation_index", idx),
                        operation=op["operation"],
                        source=op["source"],
                        target=op.get("target"),
                        mtime_ns=op.get("mtime_ns"),
                        reason=op.get("reason"),
                        sequence=op.get("sequence", 0),
                        metadata=op.get("metadata", {}),
                    )
                    converted_ops.append(op_obj)
                else:
                    converted_ops.append(op)
            cand.operations = converted_ops
            all_ops.extend(converted_ops)

        if not all_ops:
            return []

        # Check target collision across all operations: multiple candidates cannot end up at the same target
        target_to_ops: dict[str, list[VirtualOperation]] = defaultdict(list)
        for op in all_ops:
            if op.target is not None and op.target != op.source:
                target_to_ops[op.target].append(op)

        for target_path, ops in target_to_ops.items():
            candidate_ids = {op.candidate_id for op in ops}
            if len(candidate_ids) > 1:
                final_candidates = [
                    cid for cid in candidate_ids
                    if self.candidates[cid].current_path == target_path
                ]
                if len(final_candidates) > 1:
                    raise VirtualGraphCollisionError(
                        f"Path collision: multiple candidates target the same path '{target_path}'",
                        details={"target": target_path, "candidate_ids": sorted(final_candidates)},
                    )

        # Check collision reservation rules for operations targeting existing paths
        # Map path -> list of operations that VACATE that path (i.e. op.source == path and op.target != path)
        vacating_ops_by_path: dict[str, list[VirtualOperation]] = defaultdict(list)
        for op in all_ops:
            if op.target is not None and op.target != op.source:
                vacating_ops_by_path[op.source].append(op)

        # Validate each mutation target
        for op in all_ops:
            if op.target is not None and op.target != op.source:
                target_p = Path(op.target)
                if target_p.exists():
                    # Target exists on physical filesystem!
                    # Check if target is a known candidate
                    occupant = original_path_to_cand.get(op.target)
                    if occupant is None:
                        # Physical file that is not in workflow candidates -> cannot move into it!
                        raise VirtualGraphCollisionError(
                            f"Target path already exists on filesystem: '{op.target}'",
                            details={"target": op.target, "candidate_id": op.candidate_id},
                        )
                    # Occupant is in candidates. But does occupant VACATE this target?
                    vacating = vacating_ops_by_path.get(op.target, [])
                    if not vacating:
                        # Occupant candidate has NO vacating operation!
                        raise VirtualGraphCollisionError(
                            f"Target path '{op.target}' is occupied by candidate {occupant.id} which does not vacate it",
                            details={"target": op.target, "candidate_id": op.candidate_id, "occupant_id": occupant.id},
                        )

        # Build dependency graph
        # Nodes: 0..len(all_ops)-1
        n = len(all_ops)
        adj: dict[int, list[int]] = defaultdict(list)
        in_degree = [0] * n
        op_index_by_id = {id(op): idx for idx, op in enumerate(all_ops)}

        def add_edge(u: int, v: int) -> None:
            adj[u].append(v)
            in_degree[v] += 1

        # 1. Same-Entity Dependencies:
        # For the same candidate, operations must execute strictly in chronological order (op_k BEFORE op_k+1)
        for cand in self.candidates.values():
            if len(cand.operations) > 1:
                for k in range(len(cand.operations) - 1):
                    op_before = cand.operations[k]
                    op_after = cand.operations[k + 1]
                    idx_before = op_index_by_id[id(op_before)]
                    idx_after = op_index_by_id[id(op_after)]
                    add_edge(idx_before, idx_after)

        # 2. Cross-Entity Dependencies:
        # If candidate X targets path P, and candidate Y (Y != X) vacates path P via operation op_Y,
        # then op_Y must execute BEFORE op_X so that P is vacated first!
        for i, op_X in enumerate(all_ops):
            if op_X.target is not None and op_X.target != op_X.source:
                target_path = op_X.target
                for op_Y in vacating_ops_by_path.get(target_path, []):
                    if op_Y.candidate_id != op_X.candidate_id:
                        j = op_index_by_id[id(op_Y)]
                        add_edge(j, i)

        # 3. Deterministic Topological sort using Kahn's algorithm with min-heap
        def make_heap_item(idx: int):
            op = all_ops[idx]
            return (
                op.workflow_step_index,
                op.candidate_operation_index,
                op.candidate_id,
                op.source,
                idx,
            )

        heap = [make_heap_item(i) for i in range(n) if in_degree[i] == 0]
        heapq.heapify(heap)

        ordered_indices: list[int] = []

        while heap:
            item = heapq.heappop(heap)
            u = item[-1]
            ordered_indices.append(u)
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    heapq.heappush(heap, make_heap_item(v))

        if len(ordered_indices) < n:
            cycle_sources = [all_ops[i].source for i in range(n) if in_degree[i] > 0]
            raise VirtualGraphCycleError(
                f"Detected dependency cycle in planned path mutations: {sorted(set(cycle_sources))}",
                details={"cycle_sources": sorted(set(cycle_sources))},
            )

        # Assign deterministic sequence numbers (1-indexed)
        result: list[dict[str, Any]] = []
        for seq, idx in enumerate(ordered_indices, 1):
            op = all_ops[idx]
            op.sequence = seq
            result.append(op.to_dict())

        return result
