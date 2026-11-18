"""Opt-in, isolated capability probe for the semantic media organizer.

NEVER touches pre-existing payloads. Requires an explicit parent and CLI
acknowledgment. Creates only a random private scratch namespace and validates
that exclusive directory renames cannot replace an existing EMPTY directory.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import stat
import tempfile
from pathlib import Path

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_zfuse_probe import probe as existing_media_probe
from app.fs_ops import rename_noreplace_at
from app.batch.media_organizer_fd_link import link_pinned_inode_noreplace


def _check_parent(parent: Path) -> Path:
    parent = Path(parent)
    if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
        raise ValueError("probe parent must be an existing literal absolute non-symlink directory")
    fd = _open_directory_nofollow(parent)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ValueError("probe parent is not an ordinary directory")
    finally:
        os.close(fd)
    return parent


def _clear_owned(scratch: Path, original: tuple[int, int],
                 created_inodes: set[tuple[int, int]],
                 owned_files: dict[Path, tuple[int, int]] | None = None) -> tuple[bool, str | None]:
    """Remove only original, empty, locally-created disposable directories."""
    owned_files = owned_files or {}
    try:
        if not stat.S_ISDIR(os.lstat(scratch).st_mode):
            return False, "scratch directory replaced"
        initial = os.lstat(scratch)
        if (int(initial.st_dev), int(initial.st_ino)) != original:
            return False, "scratch directory identity changed"

        def clear_children(parent: Path) -> None:
            for child in list(parent.iterdir()):
                info = os.lstat(child)
                identity = (int(info.st_dev), int(info.st_ino))
                if stat.S_ISREG(info.st_mode):
                    if owned_files.get(child) != identity:
                        raise ValueError("unknown scratch file preserved for manual review")
                    now = os.lstat(child)
                    if (not stat.S_ISREG(now.st_mode) or
                            (int(now.st_dev), int(now.st_ino)) != identity):
                        raise ValueError("scratch file identity changed during cleanup")
                    # Only within our explicitly approved private 0700 scratch.
                    child.unlink()
                    continue
                if not stat.S_ISDIR(info.st_mode) or identity not in created_inodes:
                    raise ValueError("unrecognized scratch entry preserved for manual review")
                clear_children(child)
                current = os.lstat(child)
                if ((int(current.st_dev), int(current.st_ino)) != identity
                        or not stat.S_ISDIR(current.st_mode)):
                    raise ValueError("scratch child directory changed before cleanup")
                # rmdir cannot delete any nonempty directory. Unknown entries
                # are always preserved for a manual inspection, never unlinked.
                child.rmdir()

        clear_children(scratch)
        final = os.lstat(scratch)
        if (int(final.st_dev), int(final.st_ino)) != original:
            return False, "scratch root identity changed before cleanup"
        scratch.rmdir()
        return True, None
    except (OSError, ValueError) as exc:
        return False, f"owned scratch cleanup requires manual review: {exc}"



def probe_semantic_organizer_mount(parent: Path) -> dict:
    """Run bounded scratch-only tests; never trust a directory rename fallback."""
    parent = _check_parent(parent)
    report = {
        "directory_noreplace": False,
        "directory_cross_parent_noreplace": False,
        "collision_preserved": False,
        "directory_fsync": False,
        "private_stage_owner_verified": False,
        "private_stage_mode_verified": False,
        # Necessary POSIX mode checks are NOT proof of isolation against
        # same-UID/root writers, remote NAS mappings or mount ACL behavior.
        "namespace_exclusive_custody_proven": False,
        "grouped_promotion_proven": False,
        "grouped_publication_authorized": False,
        "flat_filesystem_capabilities_compatible": False,
        "source_fd_hardlink_noreplace": False,
        "source_fd_name_swap_safe": False,
        "cleanup_complete": False,
        "compatible": False,
        "errors": [],
        "synthetic_only": True,
    }
    scratch = Path(tempfile.mkdtemp(dir=parent, prefix=".nfc-semantic-probe-"))
    base = os.lstat(scratch)
    original = (int(base.st_dev), int(base.st_ino))
    owned: set[tuple[int, int]] = set()
    owned_files: dict[Path, tuple[int, int]] = {}
    try:
        fd = _open_directory_nofollow(scratch)
        try:
            os.fsync(fd)
            report["directory_fsync"] = True
            for name in ("stage", "occupied"):
                os.mkdir(name, mode=0o700, dir_fd=fd)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                owned.add((int(info.st_dev), int(info.st_ino)))
            os.fsync(fd)
            stage_fd = os.open("stage", os.O_RDONLY | os.O_DIRECTORY |
                               os.O_NOFOLLOW, dir_fd=fd)
            try:
                stage_info = os.fstat(stage_fd)
                report["private_stage_owner_verified"] = (
                    stat.S_ISDIR(stage_info.st_mode)
                    and int(stage_info.st_uid) == os.geteuid()
                )
                report["private_stage_mode_verified"] = (
                    (stat.S_IMODE(stage_info.st_mode) & 0o077) == 0
                )
                if not (report["private_stage_owner_verified"]
                        and report["private_stage_mode_verified"]):
                    # Do not continue performing the probe's stage mutations
                    # under demonstrably unconfined scratch permissions.
                    raise OSError(errno.EACCES, "private stage owner/mode is unsafe")
                # Reproduce real execution: a PRIVATE stage child is atomically
                # promoted into a public sibling of the stage parent.
                os.mkdir("pending", mode=0o700, dir_fd=stage_fd)
                pending_info = os.stat("pending", dir_fd=stage_fd,
                                       follow_symlinks=False)
                pending_id = (int(pending_info.st_dev), int(pending_info.st_ino))
                owned.add(pending_id)
                os.fsync(stage_fd)
                original_target = os.stat("occupied", dir_fd=fd,
                                          follow_symlinks=False)
                expected_target = (int(original_target.st_dev),
                                   int(original_target.st_ino))
                try:
                    # Destination is deliberately an existing EMPTY folder:
                    # ordinary rename may clobber it on some filesystems.
                    rename_noreplace_at(stage_fd, "pending", fd, "occupied")
                except OSError as exc:
                    if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                        report["directory_noreplace"] = True
                    else:
                        report["errors"].append(f"cross-parent directory no-replace: {exc}")
                else:
                    report["errors"].append("existing empty directory was replaced")
                target = os.stat("occupied", dir_fd=fd, follow_symlinks=False)
                report["collision_preserved"] = (
                    (int(target.st_dev), int(target.st_ino)) == expected_target
                )
                if not report["collision_preserved"]:
                    report["errors"].append("foreign empty target was replaced")
                if report["directory_noreplace"] and report["collision_preserved"]:
                    try:
                        rename_noreplace_at(stage_fd, "pending", fd, "published")
                        published = os.stat("published", dir_fd=fd,
                                             follow_symlinks=False)
                        report["directory_cross_parent_noreplace"] = (
                            (int(published.st_dev), int(published.st_ino)) == pending_id
                        )
                        if not report["directory_cross_parent_noreplace"]:
                            report["errors"].append("cross-parent directory identity differs")
                        os.fsync(stage_fd)
                        os.fsync(fd)
                    except OSError as exc:
                        report["errors"].append(f"cross-parent group promotion: {exc}")
            finally:
                os.close(stage_fd)

            # The production file publication is from an OPEN source inode
            # (linkat AT_EMPTY_PATH), NOT os.link(source pathname). Prove that
            # same-mount capability separately from ordinary hardlink tests.
            for name in ("fd-source", "fd-public"):
                os.mkdir(name, mode=0o700, dir_fd=fd)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                owned.add((int(info.st_dev), int(info.st_ino)))
            source_dir_fd = os.open(
                "fd-source", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd,
            )
            try:
                target_dir_fd = os.open(
                    "fd-public", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
                try:
                    original_path = scratch / "fd-source" / "frozen.bin"
                    raw_fd = os.open(
                        "frozen.bin", os.O_CREAT | os.O_EXCL | os.O_RDWR |
                        os.O_NOFOLLOW, 0o600, dir_fd=source_dir_fd,
                    )
                    with os.fdopen(raw_fd, "wb+") as source:
                        saved = os.fstat(source.fileno())
                        original_identity = (int(saved.st_dev), int(saved.st_ino))
                        owned_files[original_path] = original_identity
                        source.write(b"verified-probe-original")
                        source.flush()
                        os.fsync(source.fileno())

                        # Replace the SOURCE BASENAME after its file FD opens.
                        # We must link the previously opened inode, never the
                        # new disposable foreign probe file.
                        os.rename("frozen.bin", "detached.bin",
                                  src_dir_fd=source_dir_fd,
                                  dst_dir_fd=source_dir_fd)
                        del owned_files[original_path]
                        owned_files[scratch / "fd-source" / "detached.bin"] = original_identity
                        impostor_path = scratch / "fd-source" / "frozen.bin"
                        impostor_fd = os.open(
                            "frozen.bin", os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                            os.O_NOFOLLOW, 0o600, dir_fd=source_dir_fd,
                        )
                        with os.fdopen(impostor_fd, "wb") as impostor:
                            impostor_info = os.fstat(impostor.fileno())
                            owned_files[impostor_path] = (
                                int(impostor_info.st_dev), int(impostor_info.st_ino),
                            )
                            impostor.write(b"foreign-probe-source")
                            impostor.flush()
                            os.fsync(impostor.fileno())
                        try:
                            link_pinned_inode_noreplace(
                                source.fileno(), target_dir_fd, "published.bin",
                            )
                            linked = os.stat(
                                "published.bin", dir_fd=target_dir_fd,
                                follow_symlinks=False,
                            )
                            linked_identity = (int(linked.st_dev), int(linked.st_ino))
                            owned_files[scratch / "fd-public" / "published.bin"] = linked_identity
                            impostor_info = os.stat(
                                "frozen.bin", dir_fd=source_dir_fd,
                                follow_symlinks=False,
                            )
                            report["source_fd_name_swap_safe"] = (
                                linked_identity == original_identity and
                                (int(impostor_info.st_dev), int(impostor_info.st_ino))
                                != original_identity
                            )
                            try:
                                link_pinned_inode_noreplace(
                                    source.fileno(), target_dir_fd, "published.bin",
                                )
                            except FileExistsError:
                                report["source_fd_hardlink_noreplace"] = (
                                    linked_identity == original_identity
                                )
                            else:
                                report["errors"].append(
                                    "pinned file link unexpectedly replaced existing output"
                                )
                            os.fsync(source_dir_fd)
                            os.fsync(target_dir_fd)
                        except (OSError, ValueError) as exc:
                            report["errors"].append(f"pinned source hardlink: {exc}")
                finally:
                    os.close(target_dir_fd)
            finally:
                os.close(source_dir_fd)
        except OSError as exc:
            report["errors"].append(f"disposable directory/metadata test: {exc}")
        finally:
            os.close(fd)
    finally:
        cleaned, problem = _clear_owned(scratch, original, owned, owned_files)
        report["cleanup_complete"] = cleaned
        if problem is not None:
            report["errors"].append(problem)
    # Existing isolated probe checks hardlink no-clobber, fsync and retirement
    # in a different newly-created disposable directory on this same mount.
    if report["cleanup_complete"]:
        existing = existing_media_probe(parent)
        report["hardlink_noreplace"] = bool(existing.get("no_clobber_link"))
        report["cross_directory_hardlink"] = bool(existing.get("file_link"))
        report["original_probe_compatible"] = bool(existing.get("compatible"))
        report["cleanup_complete"] = bool(
            report["cleanup_complete"] and existing.get("cleanup_complete")
        )
        report["errors"].extend(existing.get("errors", []))
    report["compatible"] = all(
        report.get(key) is True for key in (
            "directory_noreplace", "directory_cross_parent_noreplace",
            "collision_preserved", "directory_fsync",
            "private_stage_owner_verified", "private_stage_mode_verified",
            "source_fd_hardlink_noreplace", "source_fd_name_swap_safe",
            "hardlink_noreplace", "cross_directory_hardlink",
            "original_probe_compatible", "cleanup_complete",
        )
    )
    # Backward-compatible "compatible" is now explicitly a FLAT-FILE-only
    # capability result. A successful POSIX destination-noreplace test does
    # NOT prove that the pending directory SOURCE basename cannot be swapped.
    report["flat_filesystem_capabilities_compatible"] = report["compatible"]
    # No automated test in this probe can prove absence of uncooperative
    # same-UID/root/NAS clients. Never infer permission to publish groups.
    report["grouped_promotion_proven"] = False
    report["grouped_publication_authorized"] = False
    report["namespace_exclusive_custody_proven"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit-consent disposable media organizer filesystem probe",
    )
    parser.add_argument("--parent", type=Path, required=True,
                        help="Existing absolute directory on target filesystem")
    parser.add_argument("--ack-scratch-write", action="store_true",
                        help="Required consent for private random scratch files")
    args = parser.parse_args()
    if not args.ack_scratch_write:
        parser.error("explicit --ack-scratch-write is required")
    result = probe_semantic_organizer_mount(args.parent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["compatible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
