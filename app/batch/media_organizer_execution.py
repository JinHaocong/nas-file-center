"""Fail-closed preflight for a frozen semantic media organizer manifest.

No filesystem mutations occur in this module. A future Worker must repeat
identity, no-follow and no-replace checks at each mutation syscall.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_manifest import MANIFEST_VERSION
from app.batch.media_organizer_planner import _check_scope, preview_semantic_unit, _normalized_excluded_dir_names
from app.batch.media_organizer_path_roles import classify_path_roles, uses_path_roles


class ExecutionPreflightError(ValueError):
    """Frozen authority cannot safely start a new execution."""


def _absolute_literal(path: object, unit: Path, *, is_source: bool) -> Path:
    if not isinstance(path, str) or not path:
        raise ExecutionPreflightError("invalid frozen path")
    value = Path(path)
    if (not value.is_absolute() or ".." in value.parts or "." in value.parts
            or os.path.normpath(path) != path or not value.is_relative_to(unit)
            or value == unit):
        raise ExecutionPreflightError("frozen path escaped unit")
    if is_source and len(value.parts) <= len(unit.parts):
        raise ExecutionPreflightError("invalid source path")
    return value


def validate_execution_preflight(manifest: dict, *, allowed_roots: list[Path],
                                 quarantine_root: Path | None = None) -> dict:
    """Verify exact frozen mappings before any new source-file operation.

    This is an initial preflight, not a recovery procedure. A pre-existing
    staging directory is never adopted on the strength of a basename.
    """
    try:
        if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_VERSION:
            raise ExecutionPreflightError("unsupported frozen manifest")
        job_id = manifest.get("job_id")
        unit_text = manifest.get("unit")
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
            raise ExecutionPreflightError("invalid job identity")
        if not isinstance(unit_text, str) or not unit_text or not Path(unit_text).is_absolute():
            raise ExecutionPreflightError("invalid unit path")
        unit = Path(unit_text)
        if os.path.normpath(unit_text) != unit_text or ".." in unit.parts:
            raise ExecutionPreflightError("noncanonical unit path")
        _check_scope(unit, [Path(x) for x in allowed_roots],
                     Path(quarantine_root) if quarantine_root is not None else None)
        expected_stage = f".nfc-media-organizer-stage-{job_id}"
        if manifest.get("stage_directory") != expected_stage:
            raise ExecutionPreflightError("untrusted staging directory label")
        stage = unit / expected_stage
        if os.path.lexists(stage):
            raise ExecutionPreflightError("staging workspace already exists")
        fd = _open_directory_nofollow(unit)
        try:
            current = os.fstat(fd)
            if (not stat.S_ISDIR(current.st_mode)
                    or [int(current.st_dev), int(current.st_ino)]
                    != [manifest.get("unit_dev"), manifest.get("unit_ino")]):
                raise ExecutionPreflightError("unit directory identity changed")
        finally:
            os.close(fd)

        frozen_moves = manifest.get("moves")
        if not isinstance(frozen_moves, list) or not frozen_moves:
            raise ExecutionPreflightError("frozen move list missing")
        needed = manifest.get("needed_moves")
        if type(needed) is not int or needed < 0:
            raise ExecutionPreflightError("invalid frozen change count")
        if needed == 0:
            # Empty historical classification wrappers are real cleanup work.
            # Only the explicitly versioned retained-final workflow may stage
            # these files, and the fresh exact comparison below must confirm it.
            if (not uses_path_roles(manifest) or not manifest.get("wrapper_cleanup")
                    or any(not isinstance(row, dict) or row.get("source") != row.get("final")
                           for row in frozen_moves)
                    or not classify_path_roles(manifest)["removed_wrappers"]):
                raise ExecutionPreflightError("no changes to execute")
        sources: set[str] = set()
        targets: set[str] = set()
        for index, move in enumerate(frozen_moves, 1):
            if not isinstance(move, dict):
                raise ExecutionPreflightError("invalid frozen mapping")
            src = _absolute_literal(move.get("source"), unit, is_source=True)
            final = _absolute_literal(move.get("final"), unit, is_source=False)
            temporary = _absolute_literal(move.get("target"), unit, is_source=False)
            if (temporary != stage / f"{index:06d}{src.suffix}"
                    or not isinstance(move.get("target_name"), str)
                    or final.name != move.get("target_name")
                    or final.suffix != src.suffix
                    or move.get("group") not in ("P", "V", "Other")):
                raise ExecutionPreflightError("invalid staging or final target mapping")
            identity = move.get("identity")
            if (not isinstance(identity, list) or len(identity) != 4
                    or not all(isinstance(v, int) and not isinstance(v, bool) for v in identity)
                    or identity[0] != int(current.st_dev)):
                raise ExecutionPreflightError("frozen file identity invalid")
            if str(src) in sources or str(final).casefold() in targets:
                raise ExecutionPreflightError("duplicate frozen source or target")
            sources.add(str(src))
            targets.add(str(final).casefold())
        names = sorted(_normalized_excluded_dir_names(
            manifest.get("excluded_dir_names", []),
        ))
        fresh = preview_semantic_unit(
            unit, allowed_roots=[Path(x) for x in allowed_roots],
            quarantine_root=quarantine_root, exclude_dir_names=names,
        )
        if fresh.get("status") != "ready":
            raise ExecutionPreflightError("organizing unit changed since freeze")
        same_fields = (
            "input_fingerprint", "operation", "groups", "needed_moves",
            "renamed_count", "wrapper_cleanup",
        )
        if any(fresh.get(k) != manifest.get(k) for k in same_fields):
            raise ExecutionPreflightError("organizing unit changed since freeze")
        current_rows = fresh.get("items", [])
        if len(current_rows) != len(frozen_moves):
            raise ExecutionPreflightError("file count changed since freeze")
        for row, expected in zip(current_rows, frozen_moves):
            if (row["source"] != expected["source"]
                    or row["target"] != expected["final"]
                    or row["kind"] != expected["group"]
                    or row["target_name"] != expected["target_name"]
                    or row["identity"] != expected["identity"]):
                raise ExecutionPreflightError("source identity or target changed since freeze")
        return {
            "ready": True,
            "unit": str(unit),
            "file_count": len(current_rows),
            "group_count": len(fresh["groups"]),
            "bytes": sum(row["bytes"] for row in current_rows),
            "input_fingerprint": fresh["input_fingerprint"],
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ExecutionPreflightError):
            raise
        raise ExecutionPreflightError(f"execution preflight changed or unsafe: {exc}") from exc
