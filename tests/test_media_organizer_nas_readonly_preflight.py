"""#403 read-only NAS host metadata audit. All fixtures are disposable."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

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
        config_mount = _PREFLIGHT._mount_record_from_lines(
            Path("/tmp/zfsv3/nvme13/config"), mountinfo
        )
        data_mount = _PREFLIGHT._mount_record_from_lines(
            Path("/tmp/zfsv3/sata11/data"), mountinfo
        )

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


if __name__ == "__main__":
    unittest.main()
