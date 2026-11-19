#!/usr/bin/env python3
"""V1.6 #403: READ-ONLY NAS filesystem metadata preflight.

This script has no mutation, file-content-reading or media-directory-walking
operations. It checks known /config paths and the two mount locations, but
cannot establish container UID mapping, NAS ACLs, exclusive namespace custody,
or the safety of a media organizer release. Never use a green result as
permission to enable execution flags or change production file permissions.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import re
import stat

_CONFIG_DIRECTORIES = ("reports", "backups", "logs", "home", "archive-recovery-reports")
_CONFIG_FILES = {
    "app.db": "app_db",
    "app.db-wal": "app_db_wal",
    "app.db-shm": "app_db_shm",
    ".db-init.lock": "db_init_lock",
}


def _numeric_id(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("UID and GID must be positive integers")
    return value


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only NAS V1.6 permissions metadata inspection")
    parser.add_argument("--config-dir", type=Path, required=True, help="Host's EXISTING /config bind source")
    parser.add_argument("--data-dir", type=Path, required=True, help="Host's existing /data bind source; never traversed")
    parser.add_argument("--api-uid", type=_numeric_id, default=10001)
    parser.add_argument("--worker-uid", type=_numeric_id, default=10002)
    parser.add_argument("--shared-gid", type=_numeric_id, default=10000)
    args = parser.parse_args(argv)
    if args.api_uid == args.worker_uid:
        parser.error("API and Worker UID must differ")
    for label in ("config_dir", "data_dir"):
        path = getattr(args, label)
        if not path.is_absolute() or any(part in (".", "..") for part in path.parts):
            parser.error(f"{label} must be an absolute path without traversal")
    config = os.path.normpath(str(args.config_dir))
    data = os.path.normpath(str(args.data_dir))
    if config == data or data.startswith(config.rstrip("/") + "/") or config.startswith(data.rstrip("/") + "/"):
        parser.error("config and media mounts must be disjoint")
    return args


def _entry(key: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "status": status, "detail": detail}


class MetadataUnavailable(Exception):
    """Unreadable metadata must be a blocking error, never 'not present'."""


def _st(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return None
        raise MetadataUnavailable(errno.errorcode.get(exc.errno or 0, "UNKNOWN")) from None


def _guard(key: str, check) -> dict[str, str]:
    try:
        return check()
    except MetadataUnavailable as exc:
        return _entry(key, "FAIL", f"metadata unavailable ({exc}); no changes made")


def _ancestor_symlink(path: Path) -> bool:
    """Reject symlink aliases including intermediate path components."""
    current = Path("/")
    for part in path.parts[1:]:
        current = current / part
        info = _st(current)
        if info is None:
            return False  # The missing path is diagnosed by the relevant check.
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _metadata(info: os.stat_result) -> str:
    return f"mode={stat.S_IMODE(info.st_mode):04o},uid={info.st_uid},gid={info.st_gid}"


def _config_dir_check(key: str, path: Path, gid: int, *, must_exist: bool) -> dict[str, str]:
    info = _st(path)
    if info is None:
        return _entry(key, "FAIL" if must_exist else "NEW_ON_STARTUP", "not present; no directory created")
    if _ancestor_symlink(path) or not stat.S_ISDIR(info.st_mode):
        return _entry(key, "FAIL", "not a real directory; symlink or incompatible type")
    mode = stat.S_IMODE(info.st_mode)
    permitted = (
        info.st_gid == gid
        and (mode & 0o070) == 0o070
        and (mode & stat.S_ISGID) != 0
        and (mode & 0o007) == 0
    )
    return _entry(key, "PASS" if permitted else "FAIL", _metadata(info))


def _config_file_check(key: str, path: Path, gid: int, expected_mode: int) -> dict[str, str]:
    info = _st(path)
    if info is None:
        return _entry(key, "NOT_PRESENT", "not present; no file created")
    if _ancestor_symlink(path) or not stat.S_ISREG(info.st_mode):
        return _entry(key, "FAIL", "not a regular file; symlink or incompatible type")
    permitted = info.st_gid == gid and stat.S_IMODE(info.st_mode) == expected_mode
    return _entry(key, "PASS" if permitted else "FAIL", _metadata(info))


def _report_children(directory: Path, gid: int) -> dict[str, str]:
    """Inspect known config reports, never media; emit no original filenames."""
    status = _st(directory)
    if status is None:
        return _entry("config.archive_report_files", "NOT_PRESENT", "report directory absent")
    if _ancestor_symlink(directory) or not stat.S_ISDIR(status.st_mode):
        return _entry("config.archive_report_files", "FAIL", "report directory is not real")
    checked = 0
    invalid = 0
    try:
        with os.scandir(directory) as it:
            for child in it:
                checked += 1
                if checked > 1000:
                    return _entry("config.archive_report_files", "REVIEW", "more than 1000 items; bounded audit")
                info = child.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o640:
                    invalid += 1
    except OSError as exc:
        name = errno.errorcode.get(exc.errno or 0, "UNKNOWN")
        return _entry("config.archive_report_files", "FAIL", f"metadata access failed ({name})")
    return _entry("config.archive_report_files", "FAIL" if invalid else "PASS", f"checked={checked}, incompatible={invalid}; names omitted")


def _unescape_mount(path: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def _mount_record_from_lines(target: Path, lines) -> dict[str, object]:
    """Select the visible mount: longest target, then last stacked mount.

    mountinfo can contain multiple records for the same mountpoint when a
    filesystem is mounted over an existing mount. The later matching record
    is the visible top layer; keeping the first record misreported the
    underlying tmpfs instead of the ZFS FUSE mount on the NAS.
    """
    best: dict[str, object] | None = None
    best_key = (-1, -1)
    location = str(target)
    for index, line in enumerate(lines):
        halves = line.rstrip("\\n").split(" - ", 1)
        if len(halves) != 2:
            continue
        before = halves[0].split()
        after = halves[1].split()
        if len(before) < 6 or not after:
            continue
        mount_point = _unescape_mount(before[4])
        root = mount_point.rstrip("/") or "/"
        if location != root and not location.startswith(root.rstrip("/") + "/"):
            continue
        candidate_key = (len(root), index)
        if candidate_key > best_key:
            best = {
                "mount_id": before[0],
                "fs_type": after[0],
                "host_view_read_only": "ro" in before[5].split(","),
            }
            best_key = candidate_key
    return best or {"mount_id": None, "fs_type": None, "host_view_read_only": None}


def _mount_record(target: Path) -> dict[str, object]:
    """Read mountinfo and omit host source from the report."""
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as src:
            return _mount_record_from_lines(target, src)
    except OSError:
        return {"mount_id": None, "fs_type": None, "host_view_read_only": None}


def run(argv: list[str] | None = None) -> tuple[int, dict[str, object]]:
    args = _args(argv)
    checks: list[dict[str, str]] = []
    cfg = args.config_dir
    data = args.data_dir
    gid = args.shared_gid

    checks.append(_guard("config.root", lambda: _config_dir_check("config.root", cfg, gid, must_exist=True)))
    for name in _CONFIG_DIRECTORIES:
        key = f"config.{name.replace('-', '_')}"
        checks.append(_guard(key, lambda name=name, key=key: _config_dir_check(key, cfg / name, gid, must_exist=False)))
    for name, key_part in _CONFIG_FILES.items():
        key = "config." + key_part
        checks.append(_guard(key, lambda name=name, key=key: _config_file_check(key, cfg / name, gid, 0o660)))
    checks.append(_guard("config.archive_report_files", lambda: _report_children(cfg / "archive-recovery-reports", gid)))

    def check_media():
        media = _st(data)
        if media is None:
            return _entry("media.root", "FAIL", "host media mount path not present")
        if _ancestor_symlink(data) or not stat.S_ISDIR(media.st_mode):
            return _entry("media.root", "FAIL", "host media mount is not a real directory")
        return _entry("media.root", "OBSERVED", "directory metadata only; media contents not inspected; Worker ACL NOT PROVEN")

    checks.append(_guard("media.root", check_media))

    cfg_mount = _mount_record(cfg)
    data_mount = _mount_record(data)
    for label, record in (("config", cfg_mount), ("media", data_mount)):
        if record["mount_id"] is None:
            checks.append(_entry("mount." + label, "FAIL", "Linux mountinfo unavailable"))
        elif record["host_view_read_only"] and label == "media":
            checks.append(_entry("mount.media", "FAIL", "host mount is read-only, Worker cannot write"))
        else:
            checks.append(_entry("mount." + label, "OBSERVED", f"mount-id={record['mount_id']},fstype={record['fs_type']}; ACL not inferred"))

    blockers = [item["key"] for item in checks if item["status"] in ("FAIL", "REVIEW")]
    result: dict[str, object] = {
        "tool": "v16-nas-readonly-preflight",
        "mode": "READ_ONLY",
        "candidate_pr": 397,
        "principals": {"api_uid": args.api_uid, "worker_uid": args.worker_uid, "shared_gid": gid},
        "config_metadata": "BLOCKED" if blockers else "CHECKS_PASS",
        "checks": checks,
        "mounts": {"config": cfg_mount, "media": data_mount},
        "blocking_checks": blockers,
        "media_exclusive_namespace": "NOT_PROVEN",
        "nas_acl_and_smb_custody": "NOT_PROVEN",
        "docker_user_namespace_mapping": "NOT_PROVEN",
        "media_execution_verified": False,
        "release_ready": False,
        "note": "No files changed. A passing metadata audit is NOT permission to deploy/enable V1.6; owner-approved disposable same-mount and ACL proof are still required.",
    }
    return (2 if blockers else 0), result


def main(argv: list[str] | None = None) -> int:
    status, report = run(argv)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
