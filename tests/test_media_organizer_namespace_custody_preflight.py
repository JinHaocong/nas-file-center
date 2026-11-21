"""Read-only ACL/mount custody preflight parser and scope contracts."""
from __future__ import annotations

from contextlib import redirect_stdout
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v16_nas_namespace_custody_preflight.py"
SPEC = importlib.util.spec_from_file_location("v16_nas_custody_preflight_test", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def _acl(*entries):
    raw = bytearray(struct.pack("<I", 2))
    for tag, perm, ident in entries:
        raw.extend(struct.pack("<HHI", tag, perm, ident))
    return bytes(raw)


def _safe_acl():
    return _acl(
        (0x01, 0x7, 0xFFFFFFFF),  # owner
        (0x04, 0x0, 0xFFFFFFFF),  # owning group
        (0x10, 0x7, 0xFFFFFFFF),  # mask
        (0x20, 0x0, 0xFFFFFFFF),  # other
    )


def test_named_worker_acl_uses_acl_permission_bits_not_file_mode_bits():
    acl = PREFLIGHT._decode_acl(_acl(
        (0x01, 0x0, 0xFFFFFFFF),
        (0x02, 0x3, 10002),       # named Worker: write + execute
        (0x04, 0x0, 0xFFFFFFFF),
        (0x10, 0x3, 0xFFFFFFFF),
        (0x20, 0x0, 0xFFFFFFFF),
    ))
    info = SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFDIR | 0o700)
    assert PREFLIGHT._worker_can_write(info, acl, 10002) is True


def test_worker_acl_owner_precedes_named_user():
    acl = PREFLIGHT._decode_acl(_acl(
        (0x01, 0x5, 0xFFFFFFFF),
        (0x02, 0x3, 10002),
        (0x04, 0x3, 0xFFFFFFFF),
        (0x10, 0x7, 0xFFFFFFFF),
        (0x20, 0x3, 0xFFFFFFFF),
    ))
    info = SimpleNamespace(st_uid=10002, st_gid=10000, st_mode=stat.S_IFDIR | 0o573)
    assert PREFLIGHT._worker_can_write(info, acl, 10002) is False


def test_worker_acl_matching_groups_need_write_and_search_in_one_entry():
    for owning_perm, named_perm, mask, expected in (
        (0x3, 0x0, 0x7, True),
        (0x0, 0x3, 0x7, True),
        (0x2, 0x1, 0x7, False),
        (0x3, 0x3, 0x5, False),
    ):
        acl = PREFLIGHT._decode_acl(_acl(
            (0x01, 0x7, 0xFFFFFFFF),
            (0x04, owning_perm, 0xFFFFFFFF),
            (0x08, named_perm, 10000),
            (0x10, mask, 0xFFFFFFFF),
            (0x20, 0x3, 0xFFFFFFFF),
        ))
        info = SimpleNamespace(
            st_uid=10001, st_gid=10000, st_mode=stat.S_IFDIR | (0o703 | mask << 3),
        )
        assert PREFLIGHT._worker_can_write(info, acl, 10002) is expected


def test_worker_acl_other_applies_only_without_a_matching_user_or_group():
    for named_uid, expected in ((10003, True), (10002, False)):
        acl = PREFLIGHT._decode_acl(_acl(
            (0x01, 0x7, 0xFFFFFFFF),
            (0x02, 0x3, named_uid),
            (0x04, 0x7, 0xFFFFFFFF),
            (0x08, 0x7, 10001),
            (0x10, 0x5, 0xFFFFFFFF),
            (0x20, 0x3, 0xFFFFFFFF),
        ))
        info = SimpleNamespace(st_uid=10001, st_gid=10001, st_mode=stat.S_IFDIR | 0o753)
        assert PREFLIGHT._worker_can_write(info, acl, 10002) is expected


def test_worker_mode_permissions_use_owner_then_group_then_other():
    acl = {"status": "ABSENT", "entries": []}
    for uid, gid, mode, expected in (
        (10001, 10001, 0o703, True),
        (10002, 10000, 0o533, False),
        (10001, 10000, 0o753, False),
    ):
        info = SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=stat.S_IFDIR | mode)
        assert PREFLIGHT._worker_can_write(info, acl, 10002) is expected


def test_named_nonworker_user_and_group_write_are_reported():
    acl = PREFLIGHT._decode_acl(_acl(
        (0x01, 0x7, 0xFFFFFFFF),
        (0x02, 0x2, 10003),
        (0x08, 0x2, 20000),
        (0x04, 0x0, 0xFFFFFFFF),
        (0x10, 0x7, 0xFFFFFFFF),
        (0x20, 0x0, 0xFFFFFFFF),
    ))
    writers = PREFLIGHT._acl_writers(acl, 10002)
    assert "named-user:10003" in writers
    assert "named-group:20000" in writers


def test_group_writable_unit_is_blocked_even_without_extended_acl():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        root = Path(raw)
        data = root / "data"
        unit = data / "unit"
        data.mkdir(mode=0o700)
        unit.mkdir(mode=0o770)
        unit.chmod(0o770)  # mkdir mode is filtered by the process umask
        worker = os.geteuid()
        api = worker + 1 if worker != 10001 else worker + 2
        with patch.object(PREFLIGHT, "_read_acl",
                          return_value={"status": "ABSENT", "entries": []}):
            status, report = PREFLIGHT.run([
                "--data-root", str(data), "--unit", str(unit),
                "--worker-uid", str(worker), "--api-uid", str(api),
                "--shared-gid", str(os.getegid() or 10000),
            ])
        assert status == 2
        assert report["posix_namespace_permissions"] == "BLOCKED"
        assert report["namespace_exclusive_custody_proven"] is False
        assert "unit-mode-allows-group-or-world-write" in report["blocking_conditions"]


def test_api_owned_shared_group_mode_reports_worker_write_and_custody_blockers():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        data = Path(raw) / "data"
        unit = data / "unit"
        data.mkdir()
        unit.mkdir()
        modeled_directories = {(info.st_dev, info.st_ino) for info in (data.stat(), unit.stat())}
        fstat = os.fstat

        def shared_group_metadata(fd):
            info = fstat(fd)
            if (info.st_dev, info.st_ino) not in modeled_directories:
                return info
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o2770, st_uid=10001, st_gid=10000,
                st_dev=info.st_dev, st_ino=info.st_ino,
            )

        with patch.object(PREFLIGHT.os, "fstat", side_effect=shared_group_metadata), patch.object(
            PREFLIGHT, "_read_acl", return_value={"status": "ABSENT", "entries": []},
        ):
            argv = ["--data-root", str(data), "--unit", str(unit), "--shared-gid"]
            status, report = PREFLIGHT.run([*argv, "10000"])
            _, different_gid = PREFLIGHT.run([*argv, "20000"])

    assert [rec["worker_can_create_entries"] for rec in report["directories"][-2:]] == [True, True]
    assert [rec["worker_can_create_entries"] for rec in different_gid["directories"][-2:]] == [False, False]
    assert report["worker_permission_model"]["primary_gid"] == 10000
    assert different_gid["worker_permission_model"]["primary_gid"] == 20000
    assert report["worker_permission_model"]["supplementary_gids_assumed"] == []
    assert status == 2
    assert report["posix_namespace_permissions"] == "BLOCKED"
    assert "worker-cannot-create-in-unit" not in report["blocking_conditions"]
    assert "worker-cannot-create-in-unit" in different_gid["blocking_conditions"]
    assert "unit-mode-allows-group-or-world-write" in report["blocking_conditions"]
    assert "untrusted-unit-owner" in report["blocking_conditions"]
    assert report["namespace_exclusive_custody_proven"] is False
    assert report["release_ready"] is False


def test_unavailable_access_acl_is_unknown_and_requires_review():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        data = Path(raw) / "data"
        unit = data / "unit"
        data.mkdir(mode=0o700)
        unit.mkdir(mode=0o700)
        worker = os.geteuid()
        api = worker + 1 if worker != 10001 else worker + 2
        for acl_status in ("UNSUPPORTED", "ERROR", "MALFORMED"):
            with patch.object(
                PREFLIGHT, "_read_acl", return_value={"status": acl_status, "entries": []},
            ):
                status, report = PREFLIGHT.run([
                    "--data-root", str(data), "--unit", str(unit),
                    "--worker-uid", str(worker), "--api-uid", str(api),
                ])

            assert report["directories"][-1]["worker_can_create_entries"] is None
            assert status == 2
            assert report["posix_namespace_permissions"] == "REVIEW"
            assert "worker-cannot-create-in-unit" not in report["blocking_conditions"]
            assert f"acl-metadata-unavailable-depth-{report['scope']['unit_depth']}" in report["review_conditions"]
            assert report["namespace_exclusive_custody_proven"] is False
            assert report["release_ready"] is False


def test_getxattr_protocol_error_keeps_access_acl_unknown():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        data = Path(raw) / "data"
        unit = data / "unit"
        data.mkdir(mode=0o700)
        unit.mkdir(mode=0o700)
        worker = os.geteuid()
        api = worker + 1 if worker != 10001 else worker + 2

        def getxattr(_fd, name):
            error = errno.EPROTONOSUPPORT if name == "system.posix_acl_access" else errno.ENODATA
            raise OSError(error, "unavailable xattr")

        with patch.object(PREFLIGHT.os, "getxattr", side_effect=getxattr):
            status, report = PREFLIGHT.run([
                "--data-root", str(data), "--unit", str(unit),
                "--worker-uid", str(worker), "--api-uid", str(api),
            ])

    target = report["directories"][-1]
    assert target["worker_can_create_entries"] is None
    assert target["access_acl"]["status"] == "ERROR"
    assert target["access_acl"]["errno"] == "EPROTONOSUPPORT"
    assert target["default_acl"]["status"] == "ABSENT"
    assert status == 2
    assert report["posix_namespace_permissions"] == "REVIEW"
    assert f"acl-metadata-unavailable-depth-{target['depth']}" in report["review_conditions"]


def test_private_worker_owned_unit_reports_only_posix_scope_not_release_authority():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        root = Path(raw)
        data = root / "data"
        unit = data / "unit"
        data.mkdir(mode=0o700)
        unit.mkdir(mode=0o700)
        worker = os.geteuid()
        api = worker + 1 if worker != 10001 else worker + 2
        with patch.object(PREFLIGHT, "_read_acl",
                          return_value=PREFLIGHT._decode_acl(_safe_acl())):
            status, report = PREFLIGHT.run([
                "--data-root", str(data), "--unit", str(unit),
                "--worker-uid", str(worker), "--api-uid", str(api),
                "--shared-gid", str(os.getegid() or 10000),
            ])
        assert status == 0
        assert report["posix_namespace_permissions"] == "POSIX_SCOPE_RESTRICTED"
        assert report["smb_nfs_write_exclusion"] == "NOT_PROVEN"
        assert report["same_uid_process_exclusion"] == "NOT_PROVEN"
        assert report["root_admin_exclusion"] == "NOT_PROVEN"
        assert report["namespace_exclusive_custody_proven"] is False
        assert report["release_ready"] is False
        assert str(root) not in str(report)


def test_symlink_component_is_rejected_without_following_target():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        root = Path(raw)
        data = root / "data"
        outside = root / "outside"
        data.mkdir(mode=0o700)
        outside.mkdir(mode=0o700)
        link = data / "unit"
        link.symlink_to(outside, target_is_directory=True)
        try:
            PREFLIGHT._open_directory_chain(link)
        except OSError:
            pass
        else:
            raise AssertionError("symlinked unit path must fail closed")
        assert list(outside.iterdir()) == []


def test_denied_ancestor_error_reports_depth_without_paths_or_open_descriptors():
    with tempfile.TemporaryDirectory(prefix="nfc-custody-preflight-") as raw:
        root = Path(raw)
        data = root / "private-data-component"
        parent = data / "private-unit-ancestor"
        unit = parent / "private-unit-component"
        unit.mkdir(parents=True)
        sentinel = unit / "private-sentinel-name"
        sentinel.write_text("sentinel", encoding="utf-8")
        paths = (data, parent, unit, sentinel)
        before = [path.stat() for path in paths]
        open_dir = os.open

        for denied_path, path_role in ((data, "data_root"), (parent, "unit")):
            opened = set()

            def deny_component(path, flags, *, dir_fd=None):
                if path == denied_path.name:
                    raise PermissionError(errno.EACCES, "private exception text", str(denied_path))
                fd = open_dir(path, flags, dir_fd=dir_fd)
                opened.add(fd)
                return fd

            output = io.StringIO()
            with patch.object(PREFLIGHT.os, "open", side_effect=deny_component), redirect_stdout(output):
                status = PREFLIGHT.main(["--data-root", str(data), "--unit", str(unit)])

            assert status == 2
            report = json.loads(output.getvalue())
            assert report.get("collection_error") == {
                "type": "PermissionError",
                "errno": errno.EACCES,
                "errno_name": "EACCES",
                "operation": "open_directory",
                "path_role": path_role,
                "directory_depth": len(denied_path.parts) - 1,
                "invoking_uid": os.getuid(),
            }
            assert report["posix_namespace_permissions"] == "BLOCKED"
            assert report["namespace_exclusive_custody_proven"] is False
            assert report["release_ready"] is False
            for private in (str(root), "private exception text", *(path.name for path in paths)):
                assert private not in output.getvalue()
            for fd in opened:
                try:
                    os.fstat(fd)
                except OSError as exc:
                    assert exc.errno == errno.EBADF
                else:
                    raise AssertionError(f"directory descriptor {fd} leaked")

        assert [path.stat() for path in paths] == before
        assert sentinel.read_text(encoding="utf-8") == "sentinel"


def test_malformed_acl_xattr_is_not_treated_as_absent():
    with patch.object(PREFLIGHT.os, "getxattr", return_value=b"\x00\x00\x00\x00"):
        result = PREFLIGHT._read_acl(123, "system.posix_acl_access")
    assert result == {"status": "MALFORMED", "entries": []}


def test_acl_missing_mandatory_entries_is_malformed():
    raw = _acl((0x01, 0x7, 0xFFFFFFFF), (0x20, 0x0, 0xFFFFFFFF))
    try:
        PREFLIGHT._decode_acl(raw)
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete ACL must be rejected")


def test_fuse_mount_options_are_readonly_indicators_not_exclusive_custody():
    observed = PREFLIGHT._fuse_option_indicators(
        "zfuse.zfsv3", {"rw", "relatime"}, {"rw", "default_permissions", "allow_other"},
    )
    assert observed == {
        "is_fuse": True,
        "default_permissions_option_observed": True,
        "allow_other_option_observed": True,
        "assurance": "MOUNT_OPTION_OBSERVATION_ONLY",
    }
    missing = PREFLIGHT._fuse_option_indicators("zfuse.zfsv3", {"rw"}, {"rw"})
    assert missing["default_permissions_option_observed"] is False
    assert missing["assurance"] == "MOUNT_OPTION_OBSERVATION_ONLY"
    local = PREFLIGHT._fuse_option_indicators("ext4", {"rw"}, {"rw"})
    assert local["default_permissions_option_observed"] is None
    assert local["assurance"] == "NOT_FUSE"


def test_fuse_without_visible_default_permissions_is_review_not_execution_grant():
    with tempfile.TemporaryDirectory(prefix="nfc-fuse-options-only-") as raw:
        data = Path(raw) / "data"
        unit = data / "unit"
        data.mkdir(mode=0o700)
        unit.mkdir(mode=0o700)
        data.chmod(0o700)
        unit.chmod(0o700)
        mount = {
            "mount_id": "620", "fs_type": "zfuse.zfsv3", "read_only": False,
            "fuse_option_indicators": PREFLIGHT._fuse_option_indicators(
                "zfuse.zfsv3", {"rw"}, {"rw"},
            ),
        }
        with patch.object(PREFLIGHT, "_read_acl",
                          return_value={"status": "ABSENT", "entries": []}), patch.object(
            PREFLIGHT, "_mount_record", return_value=mount,
        ):
            status, report = PREFLIGHT.run([
                "--data-root", str(data), "--unit", str(unit),
                "--worker-uid", "10002", "--api-uid", "10001",
            ])
    assert status == 2
    assert "fuse-default-permissions-option-unobserved" in report["review_conditions"]
    assert report["scope"]["unit_mount"]["fuse_option_indicators"]["assurance"] == (
        "MOUNT_OPTION_OBSERVATION_ONLY"
    )
    assert report["fuse_permission_enforcement"] == "NOT_PROVEN_BY_MOUNT_OPTIONS"
    assert report["alternate_mount_alias_exclusion"] == "NOT_PROVEN"
    assert report["namespace_exclusive_custody_proven"] is False
    assert report["release_ready"] is False
