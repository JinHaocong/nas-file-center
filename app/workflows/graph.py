from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from app.path_safety import UnsafePathError, validate_mutation_destination
from app.workflows.errors import (
    VirtualGraphCollisionError,
    VirtualGraphCycleError,
    WorkflowBoundaryError,
)
from app.workflows.schema import MoveStep, QuarantineStep, RenameStep, TouchStep


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
    operations: list[dict[str, Any]] = field(default_factory=list)


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

    def apply_rename(self, step: RenameStep) -> None:
        pattern = step.pattern
        replacement = step.replacement
        is_regex = step.is_regex

        compiled_re = re.compile(pattern) if is_regex else None

        # Track targets generated in this step to detect collisions
        step_targets: dict[str, int] = {}
        all_current_paths = {c.current_path: c.id for c in self.candidates.values()}

        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue

            curr_p = Path(cand.current_path)
            curr_name = curr_p.name

            if is_regex:
                new_name = compiled_re.sub(replacement, curr_name)
            else:
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

            # Collision check 1: within same step
            if target_str in step_targets:
                other_id = step_targets[target_str]
                raise VirtualGraphCollisionError(
                    f"Path collision: multiple files renamed to same target '{target_str}'",
                    details={"step_id": step.id, "target": target_str, "file_ids": [other_id, cid]},
                )

            # Collision check 2: target is an existing candidate that isn't moving away or physical file
            step_targets[target_str] = cid

            op = {
                "operation": "rename",
                "source": cand.current_path,
                "target": target_str,
                "step_id": step.id,
            }
            cand.operations.append(op)
            cand.current_path = target_str

        # After step, check if any target collides with static physical files
        self._check_physical_collisions(step_targets)

    def apply_move(
        self,
        step: MoveStep,
        destination_root_path: str,
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

            op = {
                "operation": "move",
                "source": cand.current_path,
                "target": target_str,
                "step_id": step.id,
            }
            cand.operations.append(op)
            cand.current_path = target_str
            cand.current_root_id = step.destination_root_id

        self._check_physical_collisions(step_targets)

    def apply_touch(self, step: TouchStep) -> None:
        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue
            op = {
                "operation": "touch",
                "source": cand.current_path,
                "target": None,
                "step_id": step.id,
                "mtime_ns": step.mtime_ns,
            }
            cand.operations.append(op)

    def apply_quarantine(self, step: QuarantineStep) -> None:
        for cid, cand in sorted(self.candidates.items(), key=lambda x: x[0]):
            if cand.is_quarantined:
                continue
            op = {
                "operation": "quarantine",
                "source": cand.current_path,
                "target": None,
                "step_id": step.id,
                "reason": step.reason,
            }
            cand.operations.append(op)
            cand.is_quarantined = True

    def _check_physical_collisions(self, step_targets: dict[str, int]) -> None:
        # All original candidate paths
        all_original_paths = {c.original_path for c in self.candidates.values()}
        for target_str, cid in step_targets.items():
            tp = Path(target_str)
            if tp.exists():
                # If target physically exists, it must be one of our candidates moving away
                if target_str not in all_original_paths:
                    raise VirtualGraphCollisionError(
                        f"Target path already exists on filesystem: '{target_str}'",
                        details={"target": target_str, "candidate_id": cid},
                    )

    def resolve_ordered_operations(self) -> list[dict[str, Any]]:
        """
        Collect all operations across candidates, detect cycles,
        and topologically sort path modifications before touch/quarantine.
        """
        path_ops: list[dict[str, Any]] = []
        terminal_ops: list[dict[str, Any]] = []

        for cand in sorted(self.candidates.values(), key=lambda c: (c.original_path, c.id)):
            for op in cand.operations:
                if op["operation"] in {"rename", "move"}:
                    path_ops.append(op)
                else:
                    terminal_ops.append(op)

        # Detect cycles in path_ops
        sorted_path_ops = self._topological_sort_path_ops(path_ops)

        # Combine
        combined = sorted_path_ops + terminal_ops
        # Assign sequence numbers deterministically
        for idx, op in enumerate(combined, 1):
            op["sequence"] = idx

        return combined

    def _topological_sort_path_ops(self, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(ops) <= 1:
            return list(ops)

        n = len(ops)
        source_to_idx = {op["source"]: i for i, op in enumerate(ops)}

        adj = defaultdict(list)
        in_degree = [0] * n

        for i, op in enumerate(ops):
            target = op["target"]
            if target in source_to_idx and source_to_idx[target] != i:
                j = source_to_idx[target]
                # j must execute before i so target is vacated
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
            cycle_sources = [ops[i]["source"] for i in range(n) if in_degree[i] > 0]
            raise VirtualGraphCycleError(
                f"Detected dependency cycle in planned path mutations: {cycle_sources}",
                details={"cycle_sources": sorted(cycle_sources)},
            )

        return [ops[i] for i in ordered_indices]
