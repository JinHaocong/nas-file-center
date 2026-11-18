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


def validate_deferred_publication(manifest: dict) -> None:
    """Refuse a plan that would require deleting an old P/V bucket to publish."""
    if not isinstance(manifest, dict) or manifest.get("cleanup_policy") != "deferred":
        raise DeferredCleanupConflict("deferred cleanup policy is mandatory")
    unit = Path(manifest.get("unit", ""))
    if not unit.is_absolute():
        raise DeferredCleanupConflict("organizing unit must be absolute")
    rows, _ = _validate_shape(manifest, unit)
    # Retained original source names may occupy flat final targets. Under
    # deferred no-delete semantics, publishing into such names is forbidden.
    retained = {str(row["source"]).casefold() for row in rows}
    if any(str(row["final"]).casefold() in retained for row in rows):
        raise DeferredCleanupConflict(
            "retained original source would occupy a final target"
        )
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


def _report_path(frozen_manifest_path: Path) -> Path:
    path = Path(frozen_manifest_path)
    return path.with_name(path.name + ".manual-cleanup.json")


def _read_verified_report(path: Path, expected: dict) -> None:
    fd = _open_directory_nofollow(path.parent)
    try:
        item_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(item_fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size < 1
                    or info.st_size > 1024 * 1024 or info.st_mode & 0o077):
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
    fd = _open_directory_nofollow(path.parent)
    try:
        try:
            file_fd = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=fd,
            )
        except FileExistsError:
            _read_verified_report(path, report)
            return
        with os.fdopen(file_fd, "wb") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(fd)
    finally:
        os.close(fd)


def record_deferred_cleanup_evidence(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    lease_fence: Callable[[], None], quarantine_root: Path | None = None,
) -> dict:
    """Verify frozen staged/published files and persist a PRIVATE review record.

    No source-dir rename, file unlink, stage rmdir or witness deletion occurs.
    A second invocation is idempotent only when the exact report is intact.
    """
    if not callable(lease_fence):
        raise DeferredCleanupConflict("Worker lease fence is required")
    try:
        validate_deferred_publication(manifest)
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
