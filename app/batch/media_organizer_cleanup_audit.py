"""Full, READ-ONLY verification of a retained semantic-organizer frozen inventory.

This is a prerequisite for a *future* separately authorized cleanup, NOT an
unlink permission, a real-NAS namespace custody proof or a zero-change rescan.
Each frozen source, private staged hardlink and final published hardlink is
verified by a no-follow parent FD. Old classification wrappers and the private
stage are scanned for unexpected entries. Media contents are never read.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_deferred_cleanup import (
    DeferredCleanupConflict, read_deferred_cleanup_review,
)
from app.batch.media_organizer_manifest import load_frozen_preview_manifest
from app.batch.media_organizer_planner import _check_scope
from app.batch.media_organizer_path_roles import classify_path_roles, uses_path_roles
from app.batch.media_organizer_publish import (
    _group_receipts, _validate_shape, _check_unit,
)
from app.batch.media_organizer_retire import _verify_public
from app.batch.media_organizer_stage import (
    _authority, _assert_private_stage_fd, _check_identity, _inspect_stage,
)


def audit_deferred_cleanup_inventory(
    manifest: dict, *, frozen_manifest_path: Path, allowed_roots: list[Path],
    quarantine_root: Path | None = None,
) -> dict:
    """Verify *all frozen entries* in one nonmutating pass.

    Its positive result does not certify that the surrounding NAS namespace
    is idle or exclusively owned. It cannot authorize original unlink/rmdir.
    """
    try:
        if not isinstance(manifest, dict) or manifest.get("cleanup_policy") != "deferred":
            raise DeferredCleanupConflict("only deferred publications can be audited")
        unit = Path(manifest["unit"])
        frozen = Path(frozen_manifest_path)
        if (not unit.is_absolute() or not frozen.is_absolute()
                or frozen.is_relative_to(unit)):
            raise DeferredCleanupConflict("unsafe frozen cleanup inventory paths")
        _check_scope(
            unit, [Path(path) for path in allowed_roots], quarantine_root,
        )
        verified_manifest = load_frozen_preview_manifest(
            frozen, job_id=manifest["job_id"], unit=unit,
        )
        if verified_manifest != manifest:
            raise DeferredCleanupConflict("frozen inventory differs from checksum evidence")

        # Verify the immutable journal, exact group receipt and stage identity
        # before doing any full-file audit. This is already a read-only reader.
        review = read_deferred_cleanup_review(
            manifest, frozen_manifest_path=frozen, page=1, page_size=1,
        )
        if review["cleanup_authorized"] or review["finalized"]:
            raise DeferredCleanupConflict("unsafe cleanup authorization in review evidence")

        rows, groups = _validate_shape(manifest, unit)
        role_mode = uses_path_roles(manifest)
        deferred = ({row["final"] for row in classify_path_roles(manifest)["deferred_rows"]}
                    if role_mode else set())
        stage = unit / manifest["stage_directory"]
        stage_fd = _open_directory_nofollow(stage)
        try:
            info = _assert_private_stage_fd(stage_fd)
            if (int(info.st_dev) != manifest["unit_dev"]
                    or not _inspect_stage(
                        stage_fd, stage, rows, _authority(manifest),
                        groups=manifest["groups"],
                    )):
                raise DeferredCleanupConflict("private stage inventory changed")
        finally:
            os.close(stage_fd)

        # Verify ALL public destinations and their exact group receipts.
        # Even with an empty group list this checks every final file inode.
        bindings = _group_receipts(manifest, frozen)
        if role_mode:
            from app.batch.media_organizer_publish import verify_prepared_publication
            verify_prepared_publication(manifest, frozen_manifest_path=frozen)
        else:
            _verify_public(
                unit, manifest, rows, groups, _authority(manifest),
                require_witness=True, group_bindings=bindings,
            )

        def require_frozen_link(path: str, identity: list[int], role: str) -> None:
            target = Path(path)
            if not target.is_relative_to(unit) or target == unit:
                raise DeferredCleanupConflict("frozen source escaped unit")
            parent_fd = _open_directory_nofollow(target.parent)
            try:
                current = os.stat(
                    target.name, dir_fd=parent_fd, follow_symlinks=False,
                )
                _check_identity(current, identity, target)
                if not stat.S_ISREG(current.st_mode):
                    raise DeferredCleanupConflict(f"{role} is not a regular file")
            finally:
                os.close(parent_fd)

        total_bytes = 0
        for row in rows:
            identity = row["identity"]
            for field, role in (
                ("source", "original"),
                ("target", "staged"),
                ("final", "published"),
            ):
                if field == "final" and row["final"] in deferred:
                    continue
                require_frozen_link(row[field], identity, role)
            total_bytes += identity[2]

        # In addition to inode identity, OLD classification wrappers must
        # contain exactly their expected retained files / nested wrappers.
        # Unknown directories/files are preserved and cause a safe stop.
        wrappers = manifest["wrapper_identities"]
        for name, identity in ({} if role_mode else wrappers).items():
            directory = Path(name)
            if not directory.is_relative_to(unit) or directory == unit:
                raise DeferredCleanupConflict("old wrapper outside frozen unit")
            expected = set()
            for row in rows:
                source = Path(row["source"])
                if source.is_relative_to(directory):
                    expected.add(source.relative_to(directory).parts[0])
            for child_name in wrappers:
                child = Path(child_name)
                if child != directory and child.is_relative_to(directory):
                    expected.add(child.relative_to(directory).parts[0])
            fd = _open_directory_nofollow(directory)
            try:
                found = os.fstat(fd)
                if (not stat.S_ISDIR(found.st_mode)
                        or [int(found.st_dev), int(found.st_ino)] != identity):
                    raise DeferredCleanupConflict("old classification directory changed")
                with os.scandir(fd) as entries:
                    actual = {entry.name for entry in entries}
                if actual != expected:
                    raise DeferredCleanupConflict(
                        "unrecognized or missing retained classification entry"
                    )
            finally:
                os.close(fd)
        return {
            "job_id": int(manifest["job_id"]),
            "unit": str(unit),
            "frozen_file_count": len(rows),
            "frozen_total_bytes": total_bytes,
            "verified_source_links": len(rows),
            "verified_stage_links": len(rows),
            "verified_final_links": len(rows) - len(deferred),
            "publication_complete": not deferred,
            "deferred_publication_count": len(deferred),
            "verified_wrapper_count": len(wrappers),
            "frozen_inventory_matches": True,
            "read_only": True,
            "cleanup_authorized": False,
            "finalized": False,
            "zero_change_rescan_verified": False,
            "namespace_exclusive_custody_proven": False,
            "whole_unit_namespace_exhaustiveness_proven": False,
            "file_content_hashes_verified": False,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DeferredCleanupConflict):
            raise
        raise DeferredCleanupConflict(
            "full frozen cleanup inventory invalid; no cleanup is authorized"
        ) from exc
