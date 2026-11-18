"""Immutable *review-only* cleanup-plan journal for V1.6 (#400).

This module does not unlink, rename, remove or chmod any existing media file.
Only a new, exclusive 0600/0640 evidence file under the private /config
execution report directory may be created. It never authorizes cleanup and
cannot establish concurrent NAS namespace custody.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_manifest import _checksum
from app.config_sharing import shared_config_gid, require_shared_directory

_MAX_BYTES = 16 * 1024 * 1024


class CleanupPlanConflict(ValueError):
    """Cleanup plan is absent, changed, untrusted or not yet ready."""


def cleanup_plan_path(frozen_manifest_path: Path) -> Path:
    path = Path(frozen_manifest_path)
    return path.with_name(path.name + ".cleanup-plan.json")


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def build_cleanup_plan(manifest: dict) -> dict:
    """Build an exact deterministic review plan from a VERIFIED frozen manifest.

    Caller must run full frozen-inventory audit before saving or returning.
    This function alone is not proof that paths or inodes are still present.
    """
    if not isinstance(manifest, dict) or manifest.get("cleanup_policy") != "deferred":
        raise CleanupPlanConflict("only deferred frozen manifests can be planned")
    unit = Path(manifest["unit"])
    rows = manifest["moves"]
    if not unit.is_absolute() or not isinstance(rows, list) or not rows:
        raise CleanupPlanConflict("invalid frozen cleanup source")
    stage = unit / manifest["stage_directory"]
    original_links = []
    staged_links = []
    for row in rows:
        identity = row["identity"]
        if not isinstance(identity, list) or len(identity) != 4:
            raise CleanupPlanConflict("incomplete frozen source identity")
        for field in ("source", "target", "final"):
            file = Path(row[field])
            if not file.is_absolute() or not file.is_relative_to(unit) or file == unit:
                raise CleanupPlanConflict("frozen cleanup path outside organizing unit")
        original_links.append({
            "path": row["source"],
            "identity": list(identity),
            "published_path": row["final"],
        })
        staged_links.append({
            "path": row["target"],
            "identity": list(identity),
            "published_path": row["final"],
        })
    wrappers = manifest.get("wrapper_identities", {})
    if not isinstance(wrappers, dict):
        raise CleanupPlanConflict("invalid old classification inventory")
    wrapper_directories = [
        {"path": literal, "identity": list(identity)}
        for literal, identity in sorted(
            wrappers.items(), key=lambda pair: (-len(Path(pair[0]).parts), pair[0])
        )
    ]
    # This stat is observation ONLY. After the full audit it can still become
    # stale if another writer can modify the NAS namespace; that is why
    # cleanup_authorized is ALWAYS false.
    stage_info = os.lstat(stage)
    if not stat.S_ISDIR(stage_info.st_mode):
        raise CleanupPlanConflict("staging directory is not a real directory")
    payload = {
        "schema_version": 1,
        "plan_kind": "review_only",
        "job_id": manifest["job_id"],
        "unit": str(unit),
        "manifest_checksum": _checksum(manifest),
        "stage": {
            "path": str(stage),
            "identity": [int(stage_info.st_dev), int(stage_info.st_ino)],
        },
        "original_links": original_links,
        "staged_links": staged_links,
        "wrapper_directories": wrapper_directories,
        "cleanup_authorized": False,
        "finalized": False,
        "zero_change_rescan_verified": False,
        "namespace_exclusive_custody_proven": False,
    }
    payload["plan_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def _read_existing(path: Path) -> dict:
    gid = shared_config_gid()
    if gid is not None:
        require_shared_directory(path.parent, gid)
    parent_fd = _open_directory_nofollow(path.parent)
    try:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        try:
            info = os.fstat(fd)
            mode = 0o640 if gid is not None else 0o600
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not 1 <= info.st_size <= _MAX_BYTES
                    or stat.S_IMODE(info.st_mode) != mode
                    or (gid is None and info.st_uid != os.geteuid())
                    or (gid is not None and info.st_gid != gid)):
                raise CleanupPlanConflict("cleanup plan file has untrusted permissions")
            with os.fdopen(fd, "rb") as file:
                fd = -1
                raw = file.read(_MAX_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError as exc:
        raise CleanupPlanConflict("immutable cleanup plan missing or unavailable") from exc
    finally:
        os.close(parent_fd)
    try:
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise CleanupPlanConflict("cleanup plan is not a JSON object")
        digest = record.get("plan_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise CleanupPlanConflict("cleanup plan checksum missing")
        actual = hashlib.sha256(_canonical({
            k: v for k, v in record.items() if k != "plan_sha256"
        })).hexdigest()
        if actual != digest:
            raise CleanupPlanConflict("immutable cleanup plan checksum mismatch")
        return record
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, CleanupPlanConflict):
            raise
        raise CleanupPlanConflict("immutable cleanup plan malformed") from exc


def read_cleanup_plan(path: Path, manifest: dict) -> dict:
    """Require byte-exact correspondence to the checksum-frozen plan."""
    expected = build_cleanup_plan(manifest)
    existing = _read_existing(path)
    if existing != expected:
        raise CleanupPlanConflict("cleanup plan differs from frozen manifest")
    return existing


def save_cleanup_plan(path: Path, manifest: dict) -> dict:
    """Commit a new file with O_EXCL; exact replay is idempotent.

    An existing foreign, wrong-group or corrupted plan is preserved verbatim.
    No current host path is chmod/chowned.
    """
    expected = build_cleanup_plan(manifest)
    body = _canonical(expected)
    if len(body) > _MAX_BYTES:
        raise CleanupPlanConflict("cleanup plan exceeds bounded evidence size")
    gid = shared_config_gid()
    if gid is not None:
        require_shared_directory(path.parent, gid)
    parent_fd = _open_directory_nofollow(path.parent)
    try:
        mode = 0o640 if gid is not None else 0o600
        try:
            file_fd = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode, dir_fd=parent_fd,
            )
        except FileExistsError:
            return read_cleanup_plan(path, manifest)
        with os.fdopen(file_fd, "wb") as file:
            info = os.fstat(file.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                    or (gid is not None and info.st_gid != gid)):
                raise CleanupPlanConflict("new cleanup plan owner/group unexpected")
            os.fchmod(file.fileno(), mode)  # Only our newly created inode.
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        os.fsync(parent_fd)
    except OSError as exc:
        raise CleanupPlanConflict("cannot write private immutable cleanup plan") from exc
    finally:
        os.close(parent_fd)
    return expected
