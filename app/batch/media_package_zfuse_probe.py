"""Opt-in, isolated ZOS/FUSE capability check using sibling stage/final directories.

Only a randomly created private scratch directory below the explicit parent
is changed. Never reads, renames, or removes existing NAS media files.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path


def probe(parent: Path) -> dict:
    parent = Path(parent)
    if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
        raise ValueError("Probe parent must be an existing literal absolute directory")
    result = {
        "exclusive_mkdir": False,
        "file_link": False,
        "no_clobber_link": False,
        "directory_fsync": False,
        "file_fsync": False,
        "source_retirement": False,
        "cleanup_complete": False,
        "errors": [],
    }
    scratch = Path(tempfile.mkdtemp(dir=parent, prefix=".nfc-media-fs-probe-"))
    owned: dict[str, tuple[str, int, int]] = {}

    def remember(relative: str, st, kind: str) -> None:
        owned[relative] = (kind, int(st.st_dev), int(st.st_ino))

    def create_test_file(dirfd: int, relative: str, name: str, content: bytes) -> None:
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=dirfd,
        )
        try:
            remember(relative, os.fstat(fd), "file")
            if os.write(fd, content) != len(content):
                raise OSError("Short write in disposable test file")
            os.fsync(fd)
            if relative == "final/marker":
                result["file_fsync"] = True
        finally:
            os.close(fd)

    try:
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        scratch_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.fsync(parent_fd)
                os.fsync(scratch_fd)
                result["directory_fsync"] = True
            except OSError as exc:
                result["errors"].append(f"directory fsync: {exc}")

            # Exactly match the real path layout: stage and final are two
            # new sibling directories underneath one original package.
            for dirname in ("stage", "final"):
                try:
                    os.mkdir(dirname, mode=0o700, dir_fd=scratch_fd)
                    remember(dirname, os.stat(dirname, dir_fd=scratch_fd,
                                              follow_symlinks=False), "dir")
                except OSError as exc:
                    result["errors"].append(f"mkdir {dirname}: {exc}")
            if "final" in owned:
                try:
                    os.mkdir("final", mode=0o700, dir_fd=scratch_fd)
                except FileExistsError:
                    result["exclusive_mkdir"] = True
                except OSError as exc:
                    result["errors"].append(f"mkdir collision: {exc}")
                else:
                    result["errors"].append("Exclusive mkdir unexpectedly succeeded")

            if "stage" in owned and "final" in owned:
                stage_fd = os.open("stage", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=scratch_fd)
                final_fd = os.open("final", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=scratch_fd)
                try:
                    try:
                        create_test_file(stage_fd, "stage/source.bin",
                                         "source.bin", b"source-test")
                        create_test_file(final_fd, "final/occupied.bin",
                                         "occupied.bin", b"foreign-sentinel")
                        create_test_file(final_fd, "final/marker",
                                         "marker", b"job-owned")
                    except OSError as exc:
                        result["errors"].append(f"disposable file create/fsync: {exc}")

                    if "stage/source.bin" in owned:
                        try:
                            os.link("source.bin", "published.bin",
                                    src_dir_fd=stage_fd, dst_dir_fd=final_fd,
                                    follow_symlinks=False)
                            st = os.stat("published.bin", dir_fd=final_fd,
                                         follow_symlinks=False)
                            remember("final/published.bin", st, "file")
                            result["file_link"] = (
                                owned["final/published.bin"][1:] ==
                                owned["stage/source.bin"][1:]
                            )
                        except OSError as exc:
                            result["errors"].append(f"cross-directory hardlink: {exc}")

                        try:
                            os.link("source.bin", "occupied.bin",
                                    src_dir_fd=stage_fd, dst_dir_fd=final_fd,
                                    follow_symlinks=False)
                        except FileExistsError:
                            result["no_clobber_link"] = True
                        except OSError as exc:
                            result["errors"].append(f"hardlink collision: {exc}")
                        else:
                            result["errors"].append("Hardlink unexpectedly replaced a target")
                        try:
                            if (scratch / "final" / "occupied.bin").read_bytes() != b"foreign-sentinel":
                                result["no_clobber_link"] = False
                                result["errors"].append("Foreign sentinel changed")
                        except OSError:
                            result["no_clobber_link"] = False

                        if result["file_link"] and result["no_clobber_link"]:
                            try:
                                os.unlink("source.bin", dir_fd=stage_fd)
                                result["source_retirement"] = (
                                    (scratch / "final" / "published.bin").read_bytes()
                                    == b"source-test"
                                )
                                if not result["source_retirement"]:
                                    result["errors"].append("Content lost during source retirement")
                            except OSError as exc:
                                result["errors"].append(f"source link retirement: {exc}")
                    try:
                        os.fsync(stage_fd)
                        os.fsync(final_fd)
                    except OSError as exc:
                        result["directory_fsync"] = False
                        result["errors"].append(f"directory fsync after link: {exc}")
                finally:
                    os.close(final_fd)
                    os.close(stage_fd)
        finally:
            os.close(scratch_fd)
            os.close(parent_fd)
    finally:
        # Remove only recorded names under the unique scratch root. Reject
        # unexpected children, symbolic links, special files, changed regular
        # file identities or a different device. Directory inode drift may be
        # normal on FUSE; rmdir still refuses nonempty/foreign contents.
        try:
            paths = sorted(
                scratch.rglob("*"), key=lambda p: (-len(p.relative_to(scratch).parts), str(p)),
            )
            unexpected = [str(p.relative_to(scratch)) for p in paths
                          if p.relative_to(scratch).as_posix() not in owned]
            if unexpected:
                raise ValueError(f"Unexpected scratch entries: {unexpected}")
            for path in paths:
                relative = path.relative_to(scratch).as_posix()
                kind, dev, ino = owned[relative]
                st = path.lstat()
                if int(st.st_dev) != dev:
                    raise ValueError(f"Probe entry changed device: {relative}")
                if kind == "file":
                    if not stat.S_ISREG(st.st_mode) or int(st.st_ino) != ino:
                        raise ValueError(f"Probe file identity changed: {relative}")
                    path.unlink()
                elif kind == "dir":
                    if not stat.S_ISDIR(st.st_mode):
                        raise ValueError(f"Probe directory type changed: {relative}")
                    path.rmdir()
                else:
                    raise ValueError(f"Unrecognized owned probe item: {relative}")
            scratch.rmdir()
            result["cleanup_complete"] = True
        except (OSError, ValueError) as exc:
            result["errors"].append(f"SCRATCH NOT CLEANED; manual review: {scratch}: {exc}")

    result["compatible"] = all(
        result[key] for key in (
            "exclusive_mkdir", "file_link", "no_clobber_link",
            "directory_fsync", "file_fsync", "source_retirement", "cleanup_complete",
        )
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated ZOS/FUSE namespace capability probe")
    parser.add_argument("--parent", type=Path, required=True,
                        help="Existing container-visible directory on the target NAS mount")
    parser.add_argument("--ack-scratch-write", action="store_true",
                        help="Required consent for a random disposable scratch directory")
    args = parser.parse_args()
    if not args.ack_scratch_write:
        parser.error("Explicit --ack-scratch-write is required")
    report = probe(args.parent)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["compatible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
