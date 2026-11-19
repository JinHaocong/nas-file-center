"""Read-only ACL/mount custody preflight parser and scope contracts."""
from __future__ import annotations

import importlib.util
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
    info = SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o700)
    assert PREFLIGHT._worker_can_write(info, acl, 10002) is True


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
