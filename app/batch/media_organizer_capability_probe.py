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
                 created_inodes: set[tuple[int, int]]) -> tuple[bool, str | None]:
    """Remove only empty directories created within this exact scratch inode."""
    try:
        if not stat.S_ISDIR(os.lstat(scratch).st_mode):
            return False, "scratch directory replaced"
        current = os.lstat(scratch)
        if (int(current.st_dev), int(current.st_ino)) != original:
            return False, "scratch directory identity changed"
        for child in list(scratch.iterdir()):
            info = os.lstat(child)
            identity = (int(info.st_dev), int(info.st_ino))
            if not stat.S_ISDIR(info.st_mode) or identity not in created_inodes:
                return False, "unrecognized scratch entry preserved for manual review"
            # rmdir never removes a nonempty directory: fail closed rather
            # than removing any file or symlink written by another process.
            child.rmdir()
        scratch.rmdir()
        return True, None
    except (OSError, ValueError) as exc:
        return False, f"owned scratch cleanup requires manual review: {exc}"


def probe_semantic_organizer_mount(parent: Path) -> dict:
    """Run bounded scratch-only tests; never trust a directory rename fallback."""
    parent = _check_parent(parent)
    report = {
        "directory_noreplace": False,
        "collision_preserved": False,
        "directory_fsync": False,
        "cleanup_complete": False,
        "compatible": False,
        "errors": [],
        "synthetic_only": True,
    }
    scratch = Path(tempfile.mkdtemp(dir=parent, prefix=".nfc-semantic-probe-"))
    base = os.lstat(scratch)
    original = (int(base.st_dev), int(base.st_ino))
    owned: set[tuple[int, int]] = set()
    try:
        fd = _open_directory_nofollow(scratch)
        try:
            os.fsync(fd)
            report["directory_fsync"] = True
            for name in ("source", "occupied"):
                os.mkdir(name, mode=0o700, dir_fd=fd)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                owned.add((int(info.st_dev), int(info.st_ino)))
            os.fsync(fd)
            original_target = os.stat("occupied", dir_fd=fd, follow_symlinks=False)
            expected_target = (int(original_target.st_dev), int(original_target.st_ino))
            try:
                # Target is deliberately EMPTY. An unsafe plain os.rename()
                # could silently replace it, so ENOTEMPTY is not enough.
                rename_noreplace_at(fd, "source", fd, "occupied")
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                    report["directory_noreplace"] = True
                else:
                    report["errors"].append(f"directory no-replace capability: {exc}")
            else:
                report["errors"].append("empty occupied directory was silently replaced")
            target = os.stat("occupied", dir_fd=fd, follow_symlinks=False)
            report["collision_preserved"] = (
                (int(target.st_dev), int(target.st_ino)) == expected_target
            )
            if not report["collision_preserved"]:
                report["errors"].append("foreign empty target was replaced by rename")
            if report["directory_noreplace"] and report["collision_preserved"]:
                try:
                    rename_noreplace_at(fd, "source", fd, "published")
                    proof = os.stat("published", dir_fd=fd, follow_symlinks=False)
                    if (int(proof.st_dev), int(proof.st_ino)) not in owned:
                        report["directory_noreplace"] = False
                        report["errors"].append("published directory identity differs")
                    os.fsync(fd)
                except OSError as exc:
                    report["directory_noreplace"] = False
                    report["errors"].append(f"directory publish capability: {exc}")
        except OSError as exc:
            report["errors"].append(f"disposable directory/metadata test: {exc}")
        finally:
            os.close(fd)
    finally:
        cleaned, problem = _clear_owned(scratch, original, owned)
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
            "directory_noreplace", "collision_preserved", "directory_fsync",
            "hardlink_noreplace", "cross_directory_hardlink",
            "original_probe_compatible", "cleanup_complete",
        )
    )
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
