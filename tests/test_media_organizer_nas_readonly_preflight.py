"""#403 read-only NAS host metadata audit. All fixtures are disposable."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v16_nas_readonly_preflight.py"

_SPEC = importlib.util.spec_from_file_location("v16_nas_readonly_preflight_test_target", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_PREFLIGHT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PREFLIGHT)


class TestNasReadOnlyPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nfc-preflight-test-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config"
        self.data = root / "data"
        self.config.mkdir(mode=0o700)
        self.data.mkdir(mode=0o755)
        self.gid = os.getegid() or 10000
        if os.getegid() == 0:
            os.chown(self.config, -1, self.gid)
        self.config.chmod(0o2770)

    def cmd(self, *, config=None, data=None, gid=None):
        p = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--config-dir", str(config or self.config),
             "--data-dir", str(data or self.data),
             "--api-uid", "10001", "--worker-uid", "10002",
             "--shared-gid", str(gid if gid is not None else self.gid)],
            text=True, capture_output=True, check=False,
        )
        return p, json.loads(p.stdout) if p.stdout.startswith("{") else {}

    def _provision(self):
        for name in ("reports", "backups", "logs", "home", "archive-recovery-reports"):
            d = self.config / name
            d.mkdir(mode=0o770)
            d.chmod(0o2770)
        for name in ("app.db", ".db-init.lock", "app.db-wal", "app.db-shm"):
            f = self.config / name
            f.write_bytes(b"synthetic-only")
            f.chmod(0o660)
        report = self.config / "archive-recovery-reports" / "2.json"
        report.write_text("{}", encoding="utf-8")
        report.chmod(0o640)

    def test_stacked_mountpoint_selects_topmost_filesystem_not_underlay(self):
        mountinfo = [
            "509 33 0:42 / /tmp/zfsv3 rw,relatime - tmpfs tmpfs rw,size=4k,inode64",
            "620 509 0:43 / /tmp/zfsv3 rw,nosuid,nodev,relatime - "
            "zfuse.zfsv3 zfsv3 rw,user_id=0,group_id=0,default_permissions,allow_other",
        ]
        config_mount = _PREFLIGHT._mount_record_from_lines("620", mountinfo)
        data_mount = _PREFLIGHT._mount_record_from_lines("620", mountinfo)

        self.assertEqual(config_mount["mount_id"], "620")
        self.assertEqual(config_mount["fs_type"], "zfuse.zfsv3")
        self.assertFalse(config_mount["host_view_read_only"])
        self.assertEqual(data_mount["mount_id"], "620")
        self.assertEqual(data_mount["fs_type"], "zfuse.zfsv3")

    def test_provisioned_metadata_reports_check_only_not_release_approval(self):
        self._provision()
        p, out = self.cmd()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out["config_metadata"], "CHECKS_PASS")
        self.assertFalse(out["release_ready"])
        self.assertEqual(out["media_exclusive_namespace"], "NOT_PROVEN")
        self.assertEqual(out["mode"], "READ_ONLY")
        self.assertTrue(any(x["key"] == "config.app_db" and x["status"] == "PASS" for x in out["checks"]))
        # Never disclose the two host paths in evidence JSON.
        self.assertNotIn(str(self.config), p.stdout)
        self.assertNotIn(str(self.data), p.stdout)

    def test_private_existing_archive_report_is_flagged_without_reading_it(self):
        self._provision()
        report = self.config / "archive-recovery-reports" / "2.json"
        report.chmod(0o600)
        p, out = self.cmd()
        self.assertEqual(p.returncode, 2)
        self.assertIn("config.archive_report_files", out["blocking_checks"])
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
        self.assertNotIn("2.json", p.stdout)

    def test_many_archive_reports_require_manual_review_instead_of_false_pass(self):
        self._provision()
        report_dir = self.config / "archive-recovery-reports"
        for idx in range(1001):
            (report_dir / f"{idx:04d}.json").touch(mode=0o640)
        p, out = self.cmd()
        self.assertEqual(p.returncode, 2)
        self.assertIn("config.archive_report_files", out["blocking_checks"])
        self.assertFalse(out["release_ready"])

    def test_private_config_blocks_without_chmod_or_creating_new_files(self):
        self.config.chmod(0o700)
        before = stat.S_IMODE(self.config.stat().st_mode)
        p, out = self.cmd()
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(out["config_metadata"], "BLOCKED")
        self.assertFalse(out["release_ready"])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), before)
        self.assertEqual(list(self.config.iterdir()), [])

    def test_preexisting_private_database_fails_closed_untouched(self):
        self._provision()
        f = self.config / "app.db"
        f.chmod(0o600)
        original = f.read_bytes()
        p, out = self.cmd()
        self.assertEqual(p.returncode, 2)
        self.assertIn("config.app_db", [x["key"] for x in out["checks"] if x["status"] == "FAIL"])
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(f.read_bytes(), original)

    def test_symlinked_child_blocks_without_touching_foreign_directory(self):
        foreign = Path(self.temp.name) / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("unchanged", encoding="utf-8")
        (self.config / "reports").symlink_to(foreign, target_is_directory=True)
        p, out = self.cmd()
        self.assertEqual(p.returncode, 2)
        self.assertEqual(out["config_metadata"], "BLOCKED")
        self.assertEqual((foreign / "keep.txt").read_text(encoding="utf-8"), "unchanged")
        self.assertTrue((self.config / "reports").is_symlink())

    def test_symlinked_media_root_is_rejected_without_descending(self):
        outside = Path(self.temp.name) / "foreign-media"
        outside.mkdir()
        payload = outside / "photo.bin"
        payload.write_bytes(b"untouched")
        fake = Path(self.temp.name) / "linked-data"
        fake.symlink_to(outside, target_is_directory=True)
        p, out = self.cmd(data=fake)
        self.assertEqual(p.returncode, 2)
        self.assertTrue(any(x["key"] == "media.root" and x["status"] == "FAIL" for x in out["checks"]))
        self.assertEqual(payload.read_bytes(), b"untouched")

    def test_never_enumerates_media_files_and_changes_no_media_bytes(self):
        self._provision()
        photo = self.data / "sensitive.bin"
        photo.write_bytes(b"do-not-open")
        # Cannot enumerate this directory as an unprivileged user. Auditing
        # must inspect the directory inode, not traverse children.
        self.data.chmod(0o111)
        p, out = self.cmd()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(out["release_ready"])
        self.data.chmod(0o755)
        self.assertEqual(photo.read_bytes(), b"do-not-open")


class TestBoundMountIdentity(unittest.TestCase):
    """Synthetic proc metadata, real directory descriptors, no mount privileges."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nfc-mount-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "data"
        self.target.mkdir()
        self.unknown = {"mount_id": None, "fs_type": None, "host_view_read_only": None}
        self.underlay = f"509 33 0:42 / {self.root} rw,relatime - tmpfs tmpfs rw,size=4k"
        self.visible = f"620 509 0:43 / {self.root} rw,nosuid,nodev - fuse.example example rw"

    def observe(self, records, fdinfo="pos:\t0\nflags:\t012000000\nmnt_id:\t620\nino:\t12\n"):
        real_open = open

        def proc_open(path, *args, **kwargs):
            if str(path) == "/proc/self/mountinfo":
                return io.StringIO("\n".join(records) + "\n")
            if str(path).startswith("/proc/self/fdinfo/"):
                if isinstance(fdinfo, Exception):
                    raise fdinfo
                return io.StringIO(fdinfo)
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=proc_open):
            return _PREFLIGHT._mount_record(self.target)

    def test_bound_mount_identity_is_independent_of_stacked_record_order(self):
        for records in ([self.underlay, self.visible], [self.visible, self.underlay]):
            with self.subTest(records=records):
                self.assertEqual(self.observe(records), {
                    "mount_id": "620", "fs_type": "fuse.example", "host_view_read_only": False,
                })

    def test_hidden_longer_mountpoint_does_not_override_bound_identity(self):
        hidden = f"700 509 0:44 / {self.target} ro - ext4 /dev/example ro"
        self.assertEqual(self.observe([self.underlay, self.visible, hidden]), {
            "mount_id": "620", "fs_type": "fuse.example", "host_view_read_only": False,
        })

    def test_unavailable_or_malformed_fd_identity_never_falls_back_to_path(self):
        for fdinfo in (
            PermissionError(13, "proc metadata denied"), "pos:\t0\n", "mnt_id:\t0\n",
            "mnt_id:\t-1\n", "mnt_id:\tbad\n", "mnt_id:\t620 extra\n",
            "mnt_id:\t620\nmnt_id:\t620\n", "mnt_id:\t620\nmnt_id:\t509\n",
        ):
            with self.subTest(fdinfo=fdinfo):
                self.assertEqual(self.observe([self.underlay, self.visible], fdinfo), self.unknown)

    def test_missing_or_duplicate_matching_mount_record_is_unknown(self):
        for records in ([self.underlay], [self.visible, self.visible], [self.visible, self.visible.replace("rw,nosuid", "ro,nosuid")]):
            with self.subTest(records=records):
                self.assertEqual(self.observe(records), self.unknown)

    def test_malformed_matching_mount_record_is_unknown(self):
        for record in (
            "620 509 0:43 /", f"620 509 0:43 / {self.root} rw - fuse.example",
            f"620 509 invalid / {self.root} rw - fuse.example example rw",
            f"620 509 0:43 / {self.root} relatime - fuse.example example rw",
            f"620 509 0:43 / {self.root} rw - fuse.example example relatime",
        ):
            with self.subTest(record=record):
                self.assertEqual(self.observe([self.underlay, record]), self.unknown)

    def test_superblock_readonly_is_reported_even_when_mount_options_are_rw(self):
        record = self.visible.rsplit(" rw", 1)[0] + " ro"
        self.assertEqual(self.observe([record]), {
            "mount_id": "620", "fs_type": "fuse.example", "host_view_read_only": True,
        })

    def test_missing_target_cannot_borrow_an_ancestor_mount(self):
        self.target.rmdir()
        self.assertEqual(self.observe([self.underlay, self.visible]), self.unknown)

    def test_symlink_target_is_not_opened_as_its_destination(self):
        self.target.rmdir()
        self.target.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.observe([self.underlay, self.visible]), self.unknown)

    def test_real_directory_descriptor_matches_kernel_mount_id(self):
        fd = os.open(self.target, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            with open(f"/proc/self/fdinfo/{fd}", encoding="utf-8") as info:
                expected = [line.split()[1] for line in info if line.startswith("mnt_id:")]
        finally:
            os.close(fd)
        self.assertEqual(len(expected), 1)
        self.assertEqual(_PREFLIGHT._mount_record(self.target)["mount_id"], expected[0])

    def test_directory_handle_is_metadata_only_and_closed_after_proc_failure(self):
        handles = []
        real_open = os.open

        def capture_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            handles.append((fd, flags))
            return fd

        with patch.object(_PREFLIGHT.os, "open", side_effect=capture_open):
            self.assertEqual(self.observe([self.visible], PermissionError(13, "denied")), self.unknown)
        self.assertTrue(handles)
        for fd, flags in handles:
            self.assertEqual(flags & (os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC),
                             os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.assertEqual(flags & (os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR), 0)
            with self.assertRaises(OSError):
                os.fstat(fd)


if __name__ == "__main__":
    unittest.main()
