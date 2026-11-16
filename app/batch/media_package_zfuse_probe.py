"""Opt-in, isolated ZOS/FUSE namespace capability probe.

Only creates a random private scratch directory beneath an explicitly selected
existing directory. Never scans, renames, or removes pre-existing media.
Run inside the existing worker container (same /data mount) only after reviewing
--parent and explicitly acknowledging scratch mutations.
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
        raise ValueError("Probe parent must be a literal existing absolute directory")
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
    owned: dict[str, tuple[int, int]] = {}
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
            try:
                os.mkdir("owned", mode=0o700, dir_fd=scratch_fd)
                st = os.stat("owned", dir_fd=scratch_fd, follow_symlinks=False)
                owned["owned"] = (int(st.st_dev), int(st.st_ino))
                try:
                    os.mkdir("owned", mode=0o700, dir_fd=scratch_fd)
                except FileExistsError:
                    result["exclusive_mkdir"] = True
                else:
                    result["errors"].append("Second exclusive mkdir unexpectedly succeeded")
            except OSError as exc:
                result["errors"].append(f"exclusive mkdir: {exc}")

            for name, payload in (
                ("source.bin", b"source-test"),
                ("occupied.bin", b"foreign-sentinel"),
                ("marker", b"job-owned"),
            ):
                try:
                    fd = os.open(
                        name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600, dir_fd=scratch_fd,
                    )
                    st = os.fstat(fd)
                    owned[name] = (int(st.st_dev), int(st.st_ino))
                    try:
                        os.write(fd, payload)
                        os.fsync(fd)
                        if name == "marker":
                            result["file_fsync"] = True
                    finally:
                        os.close(fd)
                except OSError as exc:
                    result["errors"].append(f"file create/fsync {name}: {exc}")

            if "source.bin" in owned:
                try:
                    os.link("source.bin", "published.bin",
                            src_dir_fd=scratch_fd, dst_dir_fd=scratch_fd,
                            follow_symlinks=False)
                    st = os.stat("published.bin", dir_fd=scratch_fd, follow_symlinks=False)
                    owned["published.bin"] = (int(st.st_dev), int(st.st_ino))
                    result["file_link"] = owned["published.bin"] == owned["source.bin"]
                except OSError as exc:
                    result["errors"].append(f"hardlink: {exc}")
                try:
                    os.link("source.bin", "occupied.bin",
                            src_dir_fd=scratch_fd, dst_dir_fd=scratch_fd,
                            follow_symlinks=False)
                except FileExistsError:
                    result["no_clobber_link"] = True
                except OSError as exc:
                    result["errors"].append(f"hardlink collision: {exc}")
                else:
                    result["errors"].append("Hardlink replaced an existing target")
                existing = (scratch / "occupied.bin").read_bytes()
                if existing != b"foreign-sentinel":
                    result["no_clobber_link"] = False
                    result["errors"].append("Sentinel payload changed unexpectedly")
                if result["file_link"] and result["no_clobber_link"]:
                    try:
                        os.unlink("source.bin", dir_fd=scratch_fd)
                        if (scratch / "published.bin").read_bytes() == b"source-test":
                            result["source_retirement"] = True
                        else:
                            result["errors"].append("Hardlink content changed after source retirement")
                    except OSError as exc:
                        result["errors"].append(f"source retirement: {exc}")
            try:
                os.fsync(scratch_fd)
            except OSError as exc:
                result["directory_fsync"] = False
                result["errors"].append(f"directory fsync after mutation: {exc}")
        finally:
            os.close(scratch_fd)
            os.close(parent_fd)
    finally:
        # Never delete unexpected entries or changed identities, even in the
        # unique probe namespace. Leave residue for manual investigation.
        try:
            names = {p.name for p in scratch.iterdir()}
            if not names.issubset(set(owned)):
                raise ValueError(f"Unexpected probe scratch entries: {sorted(names - set(owned))}")
            for name in sorted(names):
                path = scratch / name
                st = path.lstat()
                identity = (int(st.st_dev), int(st.st_ino))
                if identity != owned[name]:
                    raise ValueError(f"Probe entry changed identity: {name}")
                if stat.S_ISDIR(st.st_mode):
                    path.rmdir()
                elif stat.S_ISREG(st.st_mode):
                    path.unlink()
                else:
                    raise ValueError(f"Unexpected probe entry type: {name}")
            scratch.rmdir()
            result["cleanup_complete"] = True
        except (OSError, ValueError) as exc:
            result["errors"].append(f"SCRATCH NOT CLEANED; manual review required: {scratch}: {exc}")
    result["compatible"] = all(
        result[key] for key in (
            "exclusive_mkdir", "file_link", "no_clobber_link",
            "directory_fsync", "file_fsync", "source_retirement",
            "cleanup_complete",
        )
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated ZOS/FUSE namespace capability probe")
    parser.add_argument("--parent", type=Path, required=True,
                        help="Existing container-visible directory on the target NAS mount")
    parser.add_argument("--ack-scratch-write", action="store_true",
                        help="Required confirmation to create only a random disposable scratch directory")
    args = parser.parse_args()
    if not args.ack_scratch_write:
        parser.error("Explicit --ack-scratch-write is required")
    report = probe(args.parent)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["compatible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
