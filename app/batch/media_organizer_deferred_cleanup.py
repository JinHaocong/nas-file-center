"""Fail-closed manual cleanup handoff for semantic media organization.

An execution may publish media into approved final targets, but this module
never unlinks staged custody, deletes a directory, or removes recovery markers.
All old classification folders and the original staged file links are kept
until separately reviewed cleanup is performed outside this API.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Callable

from app.batch.file_rename import _open_directory_nofollow
from app.config_sharing import shared_config_gid, require_shared_directory
from app.batch.media_organizer_custody import (
    assert_exclusive_custody, NamespaceCustodyUnavailable,
)
from app.batch.media_organizer_manifest import (
    FrozenPreviewError, _checksum, load_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import _check_scope
from app.batch.media_organizer_publish import (
    PublishingConflict, _check_unit, _group_receipts, _validate_shape,
)
from app.batch.media_organizer_retire import _verify_public
from app.batch.media_organizer_stage import (
    StagingConflict, _authority, _inspect_stage, _check_identity,
)


class DeferredCleanupConflict(ValueError):
    """Safe publication cannot yet be handed off for manual cleanup."""


def validate_deferred_publication(
    manifest: dict, *, namespace_custody=None,
) -> None:
    """Refuse overlapping old groups and any grouped plan without real custody."""
    if not isinstance(manifest, dict) or manifest.get("cleanup_policy") != "deferred":
        raise DeferredCleanupConflict("deferred cleanup policy is mandatory")
    unit = Path(manifest.get("unit", ""))
    if not unit.is_absolute():
        raise DeferredCleanupConflict("organizing unit must be absolute")
    rows, _ = _validate_shape(manifest, unit)
    old_directories = manifest.get("wrapper_identities")
    groups = manifest.get("groups")
    if not isinstance(old_directories, dict) or not isinstance(groups, list):
        raise DeferredCleanupConflict("invalid frozen wrapper/group evidence")
    occupied = sorted(
        set(old_directories) &
        {str(unit / row["name"]) for row in groups}
    )
    if occupied:
        # With cleanup disabled, a same-named historical group must not be
        # replaced. Block BEFORE staging source files or creating any job
        # directories; the user can resolve this in a separate safe plan.
        raise DeferredCleanupConflict(
            "public group would require deleting an old classification wrapper"
        )
    # Production's namespace-custody issuer has no grants until the actual
    # NAS ACL, mount and concurrent-writer assumptions are independently
    # validated. A boolean ACK/Worker lease cannot bypass this requirement.
    # A synthetic test issuer can exercise the exact Worker path in tmp_path.
    if groups:
        parents = {unit}
        parents.update(Path(row["source"]).parent for row in rows)
        parents.update(Path(row["target"]).parent for row in rows)
        parents.update(Path(row["final"]).parent for row in rows)
        try:
            assert_exclusive_custody(namespace_custody, sorted(parents))
        except NamespaceCustodyUnavailable as exc:
            raise DeferredCleanupConflict(str(exc)) from exc
    # Do this before staging as well. A retained original source may
    # otherwise occupy a flat target that the prior rename-first engine freed.
    retained = {str(row["source"]).casefold() for row in rows}
    if any(str(row["final"]).casefold() in retained for row in rows):
        raise DeferredCleanupConflict(
            "retained original source would occupy a final target"
        )



def read_deferred_cleanup_review(
    manifest: dict, *, frozen_manifest_path: Path,
    page: int = 1, page_size: int = 25,
) -> dict:
    """Bounded immutable cleanup-evidence read; no mutation or cleanup grant.

    The journal is private 0600 Worker evidence today. A different API UID
    must fail closed if it cannot read the report; any group-sharing change
    needs separate explicit #403 permission review and regression tests.
    """
    if not isinstance(manifest, dict) or manifest.get("cleanup_policy") != "deferred":
        raise DeferredCleanupConflict("deferred cleanup evidence required")
    if not (isinstance(page, int) and page >= 1 and
            isinstance(page_size, int) and 1 <= page_size <= 100):
        raise DeferredCleanupConflict("invalid cleanup review page")
    path = _report_path(frozen_manifest_path)
    folder_fd = _open_directory_nofollow(path.parent)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        report_fd = os.open(path.name, flags, dir_fd=folder_fd)
        with os.fdopen(report_fd, "rb") as report_file:
            info = os.fstat(report_file.fileno())
            shared_gid = shared_config_gid()
            mode = 0o640 if shared_gid is not None else 0o600
            if (not stat.S_ISREG(info.st_mode)
                    or not 1 <= info.st_size <= 1024 * 1024
                    or stat.S_IMODE(info.st_mode) != mode
                    or (shared_gid is None and info.st_uid != os.geteuid())
                    or (shared_gid is not None and info.st_gid != shared_gid)):
                raise DeferredCleanupConflict("private cleanup report permissions changed")
            raw = report_file.read(1024 * 1024 + 1)
    except (OSError, ValueError) as exc:
        raise DeferredCleanupConflict("private cleanup evidence is unavailable or unsafe") from exc
    finally:
        os.close(folder_fd)
    try:
        saved = json.loads(raw)
        rows = manifest["moves"]
        wrapper_ids = manifest["wrapper_identities"]
        stage = Path(manifest["unit"]) / manifest["stage_directory"]
        expected = {
            "schema_version": 1,
            "cleanup_policy": "deferred",
            "manual_cleanup_required": True,
            "automatic_cleanup_authorized": False,
            "job_id": manifest["job_id"],
            "unit": manifest["unit"],
            "manifest_checksum": _checksum(manifest),
            "stage_directory": str(stage),
            "staged_links_retained": len(rows),
            "original_sources_retained": len(rows),
            "files_published": len(rows),
            "old_wrapper_identities": wrapper_ids,
            "published_targets": [row["final"] for row in rows],
            "disposition": "retain_all_until_independent_manual_review",
        }
        if not isinstance(saved, dict) or any(
            saved.get(key) != val for key, val in expected.items()
        ):
            raise DeferredCleanupConflict("private cleanup journal differs from frozen authority")
        # Group records (if any) must be the exact frozen group-inode receipts.
        bindings = _group_receipts(manifest, frozen_manifest_path)
        expected_groups = {
            str(Path(manifest["unit"]) / name): list(identity)
            for name, identity in bindings.items()
        }
        if saved.get("public_group_identities") != expected_groups:
            raise DeferredCleanupConflict("cleanup group receipts changed")
        stage_info = os.lstat(stage)
        if (not stat.S_ISDIR(stage_info.st_mode)
                or saved.get("stage_identity") != [
                    int(stage_info.st_dev), int(stage_info.st_ino)
                ]):
            raise DeferredCleanupConflict("private stage identity changed")

        # Verify reviewed page's three file locations by no-follow parent FDs.
        # These metadata checks are NOT an authorization to unlink a basename.
        def assert_frozen_file(literal: str, identity: list, role: str) -> None:
            item = Path(literal)
            if not item.is_relative_to(Path(manifest["unit"])):
                raise DeferredCleanupConflict("frozen file escaped organizing unit")
            parent_fd = _open_directory_nofollow(item.parent)
            try:
                stat_item = os.stat(item.name, dir_fd=parent_fd, follow_symlinks=False)
                _check_identity(stat_item, identity, item)
            except (StagingConflict, OSError) as exc:
                raise DeferredCleanupConflict(
                    f"{role} identity changed; no cleanup authorized"
                ) from exc
            finally:
                os.close(parent_fd)

        start = (page - 1) * page_size
        selected = rows[start:start + page_size]
        items = []
        total_bytes = 0
        for original in rows:
            identity = original["identity"]
            if not isinstance(identity, list) or len(identity) != 4:
                raise DeferredCleanupConflict("frozen source identity incomplete")
            total_bytes += int(identity[2])
        for row in selected:
            identity = row["identity"]
            assert_frozen_file(row["source"], identity, "original source")
            assert_frozen_file(row["target"], identity, "private staged file")
            assert_frozen_file(row["final"], identity, "public final file")
            items.append({
                "source": row["source"],
                "stage": row["target"],
                "target": row["final"],
                "bytes": int(identity[2]),
                "source_present": True,
                "stage_present": True,
                "target_present": True,
                "identity_matches": True,
            })
        for literal, identity in wrapper_ids.items():
            wrapper_fd = _open_directory_nofollow(Path(literal))
            try:
                current = os.fstat(wrapper_fd)
                if [int(current.st_dev), int(current.st_ino)] != identity:
                    raise DeferredCleanupConflict("old wrapper identity changed")
            finally:
                os.close(wrapper_fd)
        return {
            "job_id": int(manifest["job_id"]),
            "unit": str(manifest["unit"]),
            "files_total": len(rows),
            "total_bytes": total_bytes,
            "page": page,
            "page_size": page_size,
            "items": items,
            "groups": manifest["groups"],
            "old_wrapper_count": len(wrapper_ids),
            "old_wrappers": sorted(wrapper_ids),
            "original_sources_retained": len(rows),
            "staged_links_retained": len(rows),
            "manual_cleanup_required": True,
            "finalized": False,
            "cleanup_authorized": False,
            "review_scope": "immutable_journal_and_page_identity_only",
            "whole_unit_live_verified": False,
        }
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        if isinstance(exc, DeferredCleanupConflict):
            raise
        raise DeferredCleanupConflict("cleanup evidence cannot be reviewed safely") from exc

def _report_path(frozen_manifest_path: Path) -> Path:
    path = Path(frozen_manifest_path)
    return path.with_name(path.name + ".manual-cleanup.json")


def _read_verified_report(path: Path, expected: dict) -> None:
    fd = _open_directory_nofollow(path.parent)
    try:
        item_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(item_fd, "rb") as source:
            info = os.fstat(source.fileno())
            shared_gid = shared_config_gid()
            mode = 0o640 if shared_gid is not None else 0o600
            if (not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 1024 * 1024
                    or stat.S_IMODE(info.st_mode) != mode
                    or (shared_gid is None and info.st_uid != os.geteuid())
                    or (shared_gid is not None and info.st_gid != shared_gid)):
                raise DeferredCleanupConflict("manual cleanup journal has unsafe attributes")
            raw = source.read(1024 * 1024 + 1)
    finally:
        os.close(fd)
    try:
        saved = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise DeferredCleanupConflict("manual cleanup journal is invalid") from exc
    if saved != expected:
        raise DeferredCleanupConflict("manual cleanup journal contents changed")


def _write_report(path: Path, report: dict) -> None:
    serialized = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(serialized) > 1024 * 1024:
        raise DeferredCleanupConflict("manual cleanup evidence exceeds bound")
    shared_gid = shared_config_gid()
    if shared_gid is not None:
        require_shared_directory(path.parent, shared_gid)
    fd = _open_directory_nofollow(path.parent)
    try:
        try:
            mode = 0o640 if shared_gid is not None else 0o600
            file_fd = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode, dir_fd=fd,
            )
        except FileExistsError:
            _read_verified_report(path, report)
            return
        with os.fdopen(file_fd, "wb") as output:
            if shared_gid is not None:
                stat_new = os.fstat(output.fileno())
                if (not stat.S_ISREG(stat_new.st_mode)
                        or stat_new.st_uid != os.geteuid()
                        or stat_new.st_gid != shared_gid):
                    raise DeferredCleanupConflict("new cleanup journal group identity unsafe")
            os.fchmod(output.fileno(), mode)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(fd)
    finally:
        os.close(fd)


def record_deferred_cleanup_evidence(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    lease_fence: Callable[[], None], quarantine_root: Path | None = None,
    namespace_custody=None,
) -> dict:
    """Verify frozen staged/published files and persist a PRIVATE review record.

    No source-dir rename, file unlink, stage rmdir or witness deletion occurs.
    A second invocation is idempotent only when the exact report is intact.
    """
    if not callable(lease_fence):
        raise DeferredCleanupConflict("Worker lease fence is required")
    try:
        validate_deferred_publication(manifest, namespace_custody=namespace_custody)
        unit = Path(manifest["unit"])
        frozen_path = Path(frozen_manifest_path)
        approved = load_frozen_preview_manifest(
            frozen_path, job_id=manifest["job_id"], unit=unit,
        )
        if approved != manifest:
            raise DeferredCleanupConflict("frozen manual cleanup authority changed")
        _check_scope(unit, [Path(p) for p in allowed_roots], quarantine_root)
        _check_unit(unit, manifest, lease_fence)
        rows, groups = _validate_shape(manifest, unit)
        stage = unit / manifest["stage_directory"]
        stage_fd = _open_directory_nofollow(stage)
        try:
            stat_stage = os.fstat(stage_fd)
            if int(stat_stage.st_dev) != manifest["unit_dev"]:
                raise DeferredCleanupConflict("staged workspace changed filesystem")
            if not _inspect_stage(
                stage_fd, stage, rows, _authority(manifest),
                groups=manifest["groups"],
            ):
                raise DeferredCleanupConflict("stage completion witness missing")
        finally:
            os.close(stage_fd)
        group_bindings = _group_receipts(manifest, frozen_path)
        _verify_public(
            unit, manifest, rows, groups, _authority(manifest),
            require_witness=True, group_bindings=group_bindings,
        )
        # Current V1.6 custody retains ALL original source names: verify each
        # still resolves to the same frozen inode before recording the handoff.
        for row in rows:
            original = Path(row["source"])
            parent_fd = _open_directory_nofollow(original.parent)
            try:
                source_info = os.stat(
                    original.name, dir_fd=parent_fd, follow_symlinks=False,
                )
                _check_identity(source_info, row["identity"], original)
            finally:
                os.close(parent_fd)
        # Every old wrapper must retain exactly its original frozen children,
        # including nested original wrappers. Never demand it be empty.
        for literal, identity in manifest["wrapper_identities"].items():
            directory = Path(literal)
            expected_names = set()
            for row in rows:
                original = Path(row["source"])
                if original.is_relative_to(directory):
                    expected_names.add(original.relative_to(directory).parts[0])
            for nested_literal in manifest["wrapper_identities"]:
                nested = Path(nested_literal)
                if nested != directory and nested.is_relative_to(directory):
                    expected_names.add(nested.relative_to(directory).parts[0])
            fd = _open_directory_nofollow(directory)
            try:
                st = os.fstat(fd)
                if [int(st.st_dev), int(st.st_ino)] != identity:
                    raise DeferredCleanupConflict("old wrapper identity changed")
                with os.scandir(fd) as scan:
                    observed = {entry.name for entry in scan}
                if observed != expected_names:
                    raise DeferredCleanupConflict("old wrapper differs from retained original layout")
            finally:
                os.close(fd)
        _check_unit(unit, manifest, lease_fence)
        report = {
            "schema_version": 1,
            "cleanup_policy": "deferred",
            "manual_cleanup_required": True,
            "automatic_cleanup_authorized": False,
            "job_id": manifest["job_id"],
            "unit": str(unit),
            "manifest_checksum": _checksum(manifest),
            "stage_directory": str(stage),
            "stage_identity": [int(stat_stage.st_dev), int(stat_stage.st_ino)],
            "staged_links_retained": len(rows),
            "original_sources_retained": len(rows),
            "files_published": len(rows),
            "old_wrapper_identities": manifest["wrapper_identities"],
            "public_group_identities": {
                str(unit / name): list(identity)
                for name, identity in group_bindings.items()
            },
            "published_targets": [row["final"] for row in rows],
            "disposition": "retain_all_until_independent_manual_review",
        }
        _write_report(_report_path(frozen_path), report)
        return {
            "manual_cleanup_required": True,
            "files_published": len(rows),
            "old_wrapper_count": len(manifest["wrapper_identities"]),
            "staged_links_retained": len(rows),
            "original_sources_retained": len(rows),
            "manual_cleanup_record": str(_report_path(frozen_path)),
        }
    except (OSError, KeyError, TypeError, ValueError, FrozenPreviewError,
            StagingConflict, PublishingConflict) as exc:
        if isinstance(exc, DeferredCleanupConflict):
            raise
        raise DeferredCleanupConflict(f"manual cleanup evidence invalid: {exc}") from exc
