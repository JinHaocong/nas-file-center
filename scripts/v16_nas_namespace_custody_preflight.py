#!/usr/bin/env python3
"""Read-only POSIX namespace/ACL evidence collector for V1.6 custody review.

This tool never creates, deletes, renames, chmods, chowns, or opens file
contents. It observes one organizing unit and its directory ancestors only.
A PASS is limited to visible POSIX metadata; SMB/NFS, same-UID and privileged
writers remain unproven, so this tool NEVER grants execution custody.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import re
import stat
import struct

_ACL_TAGS = {
    0x01: "USER_OBJ",
    0x02: "USER",
    0x04: "GROUP_OBJ",
    0x08: "GROUP",
    0x10: "MASK",
    0x20: "OTHER",
}
_ACL_ACCESS = "system.posix_acl_access"
_ACL_DEFAULT = "system.posix_acl_default"
_TRUSTED_UIDS = {0}


def _args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only V1.6 NAS namespace/ACL preflight; never grants custody"
    )
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Existing host SATA data mount root")
    parser.add_argument("--unit", type=Path, required=True,
                        help="One existing organizing unit inside data-root")
    parser.add_argument("--worker-uid", type=int, default=10002)
    parser.add_argument("--api-uid", type=int, default=10001)
    parser.add_argument("--shared-gid", type=int, default=10000)
    args = parser.parse_args(argv)
    if min(args.worker_uid, args.api_uid, args.shared_gid) < 1:
        parser.error("UID/GID values must be positive")
    if args.worker_uid == args.api_uid:
        parser.error("API and Worker UIDs must differ")
    for label in ("data_root", "unit"):
        path = getattr(args, label)
        if (not path.is_absolute() or str(path) != os.path.normpath(str(path))
                or ".." in path.parts):
            parser.error(f"{label} must be an absolute normalized path without traversal")
    try:
        if os.path.commonpath((str(args.data_root), str(args.unit))) != str(args.data_root):
            parser.error("unit must be inside data-root")
    except ValueError:
        parser.error("data-root and unit must share a path root")
    if args.unit == args.data_root:
        parser.error("unit must be below data-root")
    return args


def _open_directory_chain(path: Path) -> list[int]:
    """Open each component with O_NOFOLLOW and retain FDs for metadata only."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fds = [os.open("/", flags)]
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fds[-1])
            fds.append(next_fd)
        return fds
    except BaseException:
        for fd in reversed(fds):
            os.close(fd)
        raise


def _decode_acl(raw: bytes) -> dict:
    if len(raw) < 4 or (len(raw) - 4) % 8:
        raise ValueError("malformed POSIX ACL xattr length")
    version = struct.unpack_from("<I", raw, 0)[0]
    if version != 2:
        raise ValueError("unsupported POSIX ACL xattr version")
    entries = []
    mandatory = {"USER_OBJ", "GROUP_OBJ", "OTHER"}
    seen_mandatory = set()
    seen_named = set()
    seen_singletons = set()
    for offset in range(4, len(raw), 8):
        tag, perm, ident = struct.unpack_from("<HHI", raw, offset)
        if tag not in _ACL_TAGS or perm & ~0x7:
            raise ValueError("malformed POSIX ACL entry")
        label = _ACL_TAGS[tag]
        if label in mandatory | {"MASK"}:
            if ident != 0xFFFFFFFF or label in seen_singletons:
                raise ValueError("duplicate or malformed singleton POSIX ACL entry")
            seen_singletons.add(label)
            if label in mandatory:
                seen_mandatory.add(label)
        elif label in ("USER", "GROUP"):
            if ident == 0xFFFFFFFF or (label, ident) in seen_named:
                raise ValueError("duplicate or malformed named POSIX ACL entry")
            seen_named.add((label, ident))
        entries.append({
            "tag": label,
            "id": ident if label in ("USER", "GROUP") else None,
            "perm": perm,
        })
    if not entries or seen_mandatory != mandatory:
        raise ValueError("POSIX ACL is missing mandatory entries")
    if seen_named and "MASK" not in seen_singletons:
        raise ValueError("named POSIX ACL entries require a mask")
    mask = next((e["perm"] for e in entries if e["tag"] == "MASK"), 0x7)
    for entry in entries:
        entry["effective_perm"] = (
            entry["perm"] & mask
            if entry["tag"] in ("USER", "GROUP", "GROUP_OBJ")
            else entry["perm"]
        )
    return {"status": "PRESENT", "entries": entries}


def _read_acl(fd: int, name: str) -> dict:
    try:
        return _decode_acl(os.getxattr(fd, name))
    except OSError as exc:
        if exc.errno in (getattr(errno, "ENODATA", 61), getattr(errno, "ENOATTR", 93)):
            return {"status": "ABSENT", "entries": []}
        if exc.errno in (errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)):
            return {"status": "UNSUPPORTED", "entries": []}
        return {"status": "ERROR", "errno": errno.errorcode.get(exc.errno or 0, "UNKNOWN"),
                "entries": []}
    except (TypeError, ValueError, struct.error):
        return {"status": "MALFORMED", "entries": []}


def _mount_record(fd: int) -> dict:
    try:
        with open(f"/proc/self/fdinfo/{fd}", "r", encoding="utf-8") as src:
            ids = [line.partition(":")[2].strip() for line in src if line.startswith("mnt_id:")]
        if len(ids) != 1 or not re.fullmatch(r"[1-9][0-9]*", ids[0]):
            return {"mount_id": None, "fs_type": None, "read_only": None}
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as src:
            found = []
            for line in src:
                halves = line.rstrip("\n").split(" - ", 1)
                before = halves[0].split()
                if not before or before[0] != ids[0]:
                    continue
                if len(halves) != 2 or len(before) < 6:
                    return {"mount_id": None, "fs_type": None, "read_only": None}
                after = halves[1].split()
                if len(after) != 3:
                    return {"mount_id": None, "fs_type": None, "read_only": None}
                mount_access = set(before[5].split(","))
                super_access = set(after[2].split(","))
                if (len({"ro", "rw"} & mount_access) != 1
                        or len({"ro", "rw"} & super_access) != 1):
                    return {"mount_id": None, "fs_type": None, "read_only": None}
                found.append({
                    "mount_id": ids[0],
                    "fs_type": after[0],
                    "read_only": "ro" in mount_access or "ro" in super_access,
                })
        return found[0] if len(found) == 1 else {
            "mount_id": None, "fs_type": None, "read_only": None,
        }
    except (OSError, UnicodeError):
        return {"mount_id": None, "fs_type": None, "read_only": None}


def _acl_writers(acl: dict, worker_uid: int) -> list[str]:
    if acl.get("status") != "PRESENT":
        return []
    writers = []
    for entry in acl["entries"]:
        if not entry.get("effective_perm", 0) & 0x2:
            continue
        tag, ident = entry["tag"], entry.get("id")
        if tag == "USER" and ident not in (0, worker_uid):
            writers.append(f"named-user:{ident}")
        elif tag == "GROUP":
            writers.append(f"named-group:{ident}")
        elif tag == "GROUP_OBJ":
            writers.append("owning-group")
        elif tag == "OTHER":
            writers.append("other")
    return writers


def _worker_can_write(info, access_acl: dict, worker_uid: int) -> bool:
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid == worker_uid and (mode & 0o300) == 0o300:
        return True
    if access_acl.get("status") == "PRESENT":
        return any(
            entry["tag"] == "USER"
            and entry.get("id") == worker_uid
            and (entry.get("effective_perm", 0) & 0x3) == 0x3
            for entry in access_acl["entries"]
        )
    return False


def _directory_record(fd: int, index: int, worker_uid: int) -> dict:
    info = os.fstat(fd)
    access = _read_acl(fd, _ACL_ACCESS)
    default = _read_acl(fd, _ACL_DEFAULT)
    mode = stat.S_IMODE(info.st_mode)
    return {
        "depth": index,
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "mode": f"{mode:04o}",
        "sticky": bool(info.st_mode & stat.S_ISVTX),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "mount": _mount_record(fd),
        "access_acl": access,
        "default_acl": default,
        "worker_can_create_entries": _worker_can_write(info, access, worker_uid),
        "untrusted_access_writers": _acl_writers(access, worker_uid),
        "untrusted_default_writers": _acl_writers(default, worker_uid),
    }


def _read_id_map(path: str) -> list[list[int]] | None:
    try:
        rows = []
        with open(path, "r", encoding="ascii") as src:
            for line in src:
                fields = line.split()
                if len(fields) != 3:
                    return None
                rows.append([int(x) for x in fields])
        return rows
    except (OSError, ValueError, UnicodeError):
        return None


def run(argv=None) -> tuple[int, dict]:
    args = _args(argv)
    data_fds = unit_fds = []
    try:
        data_fds = _open_directory_chain(args.data_root)
        unit_fds = _open_directory_chain(args.unit)
        data_info = os.fstat(data_fds[-1])
        unit_info = os.fstat(unit_fds[-1])
        if not stat.S_ISDIR(data_info.st_mode) or not stat.S_ISDIR(unit_info.st_mode):
            raise ValueError("data-root and unit must be directories")

        # The unit path must resolve to the same opened data-root inode at the
        # corresponding component depth; lexical containment alone is not enough.
        data_depth = len(args.data_root.parts) - 1
        unit_data_binding = os.fstat(unit_fds[data_depth])
        if (data_info.st_dev, data_info.st_ino) != (
                unit_data_binding.st_dev, unit_data_binding.st_ino):
            raise ValueError("unit path does not resolve beneath the opened data-root inode")

        records = [_directory_record(fd, i, args.worker_uid)
                   for i, fd in enumerate(unit_fds)]
        issues = []
        review = []
        for index, record in enumerate(records):
            if (record["access_acl"]["status"] in ("UNSUPPORTED", "ERROR", "MALFORMED")
                    or record["default_acl"]["status"] in ("UNSUPPORTED", "ERROR", "MALFORMED")):
                review.append(f"acl-metadata-unavailable-depth-{index}")
            if record["mount"]["mount_id"] is None:
                review.append(f"mount-identity-unavailable-depth-{index}")
            # For an ancestor, sticky + a trusted child owner prevents a
            # different UID from renaming/unlinking this exact child name.
            # The ancestor's write ACL is therefore not a path-rebinding
            # capability when this exact child is protected by the sticky bit.
            if index < len(records) - 1:
                child_uid = records[index + 1]["uid"]
                protected_child = (
                    record["sticky"] and child_uid in (0, args.worker_uid)
                    and record["uid"] in (0, args.worker_uid)
                )
                if record["uid"] not in (0, args.worker_uid):
                    issues.append(f"untrusted-ancestor-owner-depth-{index}")
                parent_mode = int(record["mode"], 8)
                if (parent_mode & 0o022) and not protected_child:
                    issues.append(f"mutable-ancestor-binding-depth-{index}")
                if record["untrusted_access_writers"] and not protected_child:
                    issues.append(f"untrusted-access-writer-depth-{index}")
            else:
                if record["untrusted_access_writers"]:
                    issues.append(f"untrusted-access-writer-depth-{index}")
                if record["untrusted_default_writers"]:
                    issues.append(f"untrusted-default-writer-depth-{index}")

        target = records[-1]
        target_mode = int(target["mode"], 8)
        if target_mode & 0o022:
            issues.append("unit-mode-allows-group-or-world-write")
        if target["uid"] not in (0, args.worker_uid):
            issues.append("untrusted-unit-owner")
        if not target["worker_can_create_entries"]:
            issues.append("worker-cannot-create-in-unit")
        if target["mount"]["read_only"] is True:
            issues.append("unit-mount-read-only")
        if target["mount"]["read_only"] is not False:
            review.append("unit-mount-writability-unverified")
        if target["access_acl"]["status"] == "ABSENT":
            review.append("unit-has-mode-only-access-control")
        if target["default_acl"]["status"] == "PRESENT" and target["untrusted_default_writers"]:
            issues.append("unit-default-acl-allows-untrusted-writers")

        status = "BLOCKED" if issues else ("REVIEW" if review else "POSIX_SCOPE_RESTRICTED")
        result = {
            "tool": "v16-nas-namespace-custody-preflight",
            "mode": "READ_ONLY_METADATA_ONLY",
            "scope": {
                "directory_count": len(records),
                "unit_depth": len(records) - 1,
                "unit_uid": int(unit_info.st_uid),
                "unit_gid": int(unit_info.st_gid),
                "unit_mode": f"{stat.S_IMODE(unit_info.st_mode):04o}",
                "unit_mount": target["mount"],
            },
            "principals": {
                "worker_uid": args.worker_uid,
                "api_uid": args.api_uid,
                "shared_gid": args.shared_gid,
                "invoking_uid": os.getuid(),
                "invoking_gid": os.getgid(),
                "invoking_process_uid_map": _read_id_map("/proc/self/uid_map"),
                "invoking_process_gid_map": _read_id_map("/proc/self/gid_map"),
            },
            "directories": records,
            "posix_namespace_permissions": status,
            "blocking_conditions": sorted(set(issues)),
            "review_conditions": sorted(set(review)),
            "smb_nfs_write_exclusion": "NOT_PROVEN",
            "same_uid_process_exclusion": "NOT_PROVEN",
            "root_admin_exclusion": "NOT_PROVEN",
            "namespace_exclusive_custody_proven": False,
            "release_ready": False,
            "note": (
                "This is a point-in-time POSIX metadata observation only. "
                "It does not inspect file contents, enumerate media files, "
                "verify container UID mapping, or establish SMB/NFS/root/same-UID exclusion. "
                "A passing result is not an execution authorization."
            ),
        }
        return (2 if status != "POSIX_SCOPE_RESTRICTED" else 0), result
    finally:
        for fd in reversed(unit_fds):
            try:
                os.close(fd)
            except OSError:
                pass
        for fd in reversed(data_fds):
            try:
                os.close(fd)
            except OSError:
                pass


def main(argv=None) -> int:
    try:
        status, report = run(argv)
    except (OSError, ValueError) as exc:
        report = {
            "tool": "v16-nas-namespace-custody-preflight",
            "mode": "READ_ONLY_METADATA_ONLY",
            "posix_namespace_permissions": "BLOCKED",
            "blocking_conditions": [type(exc).__name__],
            "namespace_exclusive_custody_proven": False,
            "release_ready": False,
            "note": "No files changed; path or metadata validation failed.",
        }
        status = 2
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
