"""Shared-GID review of a completed Worker's immutable cleanup snapshot.

Only shared 0640 artifacts are read here. Private group receipts, progress
journals, stage directories and live media remain exclusively Worker checks.
The snapshot grants no filesystem authority and is never a custody proof.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_cleanup_plan import _read_existing, cleanup_plan_path
from app.batch.media_organizer_deferred_cleanup import _publication_evidence, _report_path
from app.batch.media_organizer_manifest import _checksum, load_frozen_preview_manifest
from app.batch.media_organizer_path_roles import classify_path_roles, uses_path_roles
from app.batch.media_organizer_publish import _validate_shape
from app.config_sharing import require_shared_directory, shared_config_gid

_MAX_REPORT_BYTES = 1024 * 1024
SNAPSHOT_SCOPE = {
    "verification_scope": "worker_handoff_snapshot",
    "live_inventory_verified": False,
    "read_only": True,
}


class SharedHandoffConflict(ValueError):
    """Shared artifacts do not match the completed Worker's frozen checkpoint."""


def _read_shared_report(path: Path, gid: int) -> tuple[dict, str]:
    require_shared_directory(path.parent, gid)
    parent_fd = _open_directory_nofollow(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                     getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o640 or before.st_gid != gid
                    or not 1 <= before.st_size <= _MAX_REPORT_BYTES):
                raise SharedHandoffConflict("shared cleanup report permissions or size changed")
            raw = stream.read(_MAX_REPORT_BYTES + 1)
            after = os.fstat(stream.fileno())
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if ((named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                    or len(raw) != before.st_size
                    or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns)):
                raise SharedHandoffConflict("shared cleanup report changed while being read")
    finally:
        os.close(parent_fd)
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise SharedHandoffConflict("shared cleanup report must be an object")
    return report, hashlib.sha256(raw).hexdigest()


def _directory_identity(identity, device: int) -> None:
    if (not isinstance(identity, list) or len(identity) != 2
            or any(type(value) is not int for value in identity)
            or identity[0] != device or identity[1] <= 0):
        raise SharedHandoffConflict("shared snapshot directory identity is invalid")


def _artifacts(manifest: dict, frozen_manifest_path: Path) -> dict:
    gid = shared_config_gid()
    if gid is None:
        raise SharedHandoffConflict("explicit shared config GID required for snapshot review")
    frozen = Path(frozen_manifest_path)
    require_shared_directory(frozen.parent, gid)
    unit = Path(manifest["unit"])
    if (manifest.get("cleanup_policy") != "deferred"
            or load_frozen_preview_manifest(frozen, job_id=manifest["job_id"], unit=unit) != manifest):
        raise SharedHandoffConflict("shared frozen manifest differs from Worker snapshot")
    rows, groups = _validate_shape(manifest, unit)
    report, report_sha = _read_shared_report(_report_path(frozen), gid)
    plan = _read_existing(cleanup_plan_path(frozen))
    # This validator consumes only frozen dictionaries; it does not stat the
    # stage as read_cleanup_plan/build_cleanup_plan would do.
    from app.batch.media_organizer_finalize import _operations
    _operations(manifest, plan)
    expected_version = 2 if uses_path_roles(manifest) else 1
    if (type(plan.get("schema_version")) is not int
            or plan["schema_version"] != expected_version
            or any(plan.get(key) is not False for key in (
                "cleanup_authorized", "finalized", "zero_change_rescan_verified",
                "namespace_exclusive_custody_proven"))):
        raise SharedHandoffConflict("shared cleanup plan is not a review-only snapshot")
    stage_identity = plan.get("stage", {}).get("identity")
    _directory_identity(stage_identity, manifest["unit_dev"])
    group_ids = report.get("public_group_identities")
    if not isinstance(group_ids, dict) or set(group_ids) != {str(unit / name) for name in groups}:
        raise SharedHandoffConflict("shared snapshot public-group inventory changed")
    for literal, identity in group_ids.items():
        _directory_identity(identity, manifest["unit_dev"])
        original = manifest["wrapper_identities"].get(literal)
        if original is not None and uses_path_roles(manifest) and identity != original:
            raise SharedHandoffConflict("shared retained-group identity differs from frozen input")
    expected = {
        "schema_version": 1, "cleanup_policy": "deferred",
        "manual_cleanup_required": True, "automatic_cleanup_authorized": False,
        "job_id": manifest["job_id"], "unit": str(unit),
        "manifest_checksum": _checksum(manifest),
        "stage_directory": str(unit / manifest["stage_directory"]),
        "stage_identity": stage_identity,
        "staged_links_retained": len(rows), "original_sources_retained": len(rows),
        "old_wrapper_identities": manifest["wrapper_identities"],
        "public_group_identities": group_ids,
        **_publication_evidence(manifest),
    }
    if report != expected:
        raise SharedHandoffConflict("shared cleanup report differs from frozen review plan")
    return {
        "plan": plan, "report": report,
        "binding": {
            "manifest_checksum": _checksum(manifest),
            "cleanup_plan_sha256": plan["plan_sha256"],
            "cleanup_report_sha256": report_sha,
        },
    }


def shared_handoff_checkpoint(manifest: dict, frozen_manifest_path: Path) -> dict:
    """Worker records these digests only after its separate full live audit."""
    return _artifacts(manifest, frozen_manifest_path)["binding"]


def read_shared_cleanup_handoff(manifest: dict, frozen_manifest_path: Path,
                                checkpoint: dict) -> dict:
    """Read only shared artifacts already bound to a completed execution row."""
    try:
        if (not isinstance(checkpoint, dict)
                or checkpoint.get("phase") != "manual_cleanup_required"
                or checkpoint.get("frozen_job_id") != manifest["job_id"]
                or checkpoint.get("unit") != manifest["unit"]):
            raise SharedHandoffConflict("shared snapshot checkpoint belongs to another frozen unit")
        result = _artifacts(manifest, frozen_manifest_path)
        if any(checkpoint.get(key) != value for key, value in result["binding"].items()):
            raise SharedHandoffConflict("shared cleanup artifacts differ from completed Worker checkpoint")
        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, SharedHandoffConflict):
            raise
        raise SharedHandoffConflict(f"shared Worker snapshot is unavailable or invalid: {exc}") from exc


def shared_review_page(manifest: dict, *, page: int, page_size: int) -> dict:
    rows = manifest["moves"]
    deferred = ({row["final"] for row in classify_path_roles(manifest)["deferred_rows"]}
                if uses_path_roles(manifest) else set())
    start = (page - 1) * page_size
    return {
        **SNAPSHOT_SCOPE, "job_id": manifest["job_id"], "unit": manifest["unit"],
        "files_total": len(rows), "total_bytes": sum(row["identity"][2] for row in rows),
        "page": page, "page_size": page_size,
        "items": [{
            "source": row["source"], "stage": row["target"], "target": row["final"],
            "bytes": row["identity"][2], "snapshot_source_present": True,
            "snapshot_stage_present": True, "snapshot_target_present": row["final"] not in deferred,
            "snapshot_identity_matches": True, "target_deferred": row["final"] in deferred,
        } for row in rows[start:start + page_size]],
        "groups": manifest["groups"], "old_wrapper_count": len(manifest["wrapper_identities"]),
        "old_wrappers": sorted(manifest["wrapper_identities"]),
        "snapshot_original_sources_retained": len(rows), "snapshot_staged_links_retained": len(rows),
        "publication_complete": not deferred, "deferred_publication_count": len(deferred),
        "manual_cleanup_required": True, "finalized": False, "cleanup_authorized": False,
        "review_scope": "worker_handoff_snapshot", "whole_unit_live_verified": False,
    }


def shared_audit_summary(manifest: dict) -> dict:
    rows = manifest["moves"]
    pending = len(classify_path_roles(manifest)["deferred_rows"]) if uses_path_roles(manifest) else 0
    return {
        **SNAPSHOT_SCOPE, "job_id": manifest["job_id"], "unit": manifest["unit"],
        "frozen_file_count": len(rows), "frozen_total_bytes": sum(row["identity"][2] for row in rows),
        "snapshot_verified_source_links": len(rows), "snapshot_verified_stage_links": len(rows),
        "snapshot_verified_final_links": len(rows) - pending,
        "snapshot_verified_wrapper_count": len(manifest["wrapper_identities"]),
        "snapshot_frozen_inventory_matches": True, "publication_complete": pending == 0,
        "deferred_publication_count": pending, "cleanup_authorized": False, "finalized": False,
        "zero_change_rescan_verified": False, "namespace_exclusive_custody_proven": False,
        "whole_unit_namespace_exhaustiveness_proven": False, "file_content_hashes_verified": False,
    }
