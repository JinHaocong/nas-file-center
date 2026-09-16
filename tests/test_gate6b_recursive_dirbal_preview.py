from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.models import DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.service import FileCenterService


@pytest.fixture
def service_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        quarantine_root=quarantine_dir,
        allowed_roots_raw=str(data_dir),
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    return {
        "service": service,
        "SessionLocal": service.SessionLocal,
        "settings": settings,
        "data_dir": data_dir,
    }


def _recursive_config():
    return {
        "schema_version": 1,
        "selection_mode": "recursive_directory_balanced_by_bytes",
        "factors": {},
    }


def _create_recursive_fixture(env, *, scan_id: int):
    root = env["data_dir"]
    a_dir = root / "A" / "deep"
    b_dir = root / "B" / "deep"
    a_dir.mkdir(parents=True)
    b_dir.mkdir(parents=True)

    left = a_dir / "dup.bin"
    right = b_dir / "dup.bin"
    left.write_bytes(b"same-bytes")
    right.write_bytes(b"same-bytes")
    a_extra = a_dir / "extra.bin"
    b_extra = b_dir / "extra.bin"
    a_extra.write_bytes(b"keep-a-subtree-alive")
    b_extra.write_bytes(b"keep-b-subtree-alive")

    with env["SessionLocal"]() as session:
        session.add(ScanJob(
            id=scan_id,
            name=f"scan-{scan_id}",
            mode="normal",
            roots_json=json.dumps([str(root)]),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=1,
            total_files_in_groups=2,
            reclaimable_bytes=len(b"same-bytes"),
        ))
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"recursive-{scan_id}",
            file_size=len(b"same-bytes"),
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path in (left, right):
            st = os.lstat(path)
            relative = path.relative_to(root)
            session.add(DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(path),
                relative_path=relative.as_posix(),
                top_level_dir=str(root / relative.parts[0]),
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
            ))
        session.commit()
    return left, right, a_extra, b_extra


def _replace_with_same_bytes_new_inode(path: Path) -> tuple[os.stat_result, os.stat_result]:
    before = os.lstat(path)
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement_stat = os.lstat(replacement)
    assert (replacement_stat.st_dev, replacement_stat.st_ino) != (before.st_dev, before.st_ino)
    os.replace(replacement, path)
    after = os.lstat(path)
    assert (after.st_dev, after.st_ino) == (replacement_stat.st_dev, replacement_stat.st_ino)
    assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
    return before, after


def test_recursive_preview_exposes_candidate_bucket_and_decision_explain(service_env):
    scan_id = 901
    left, right, _a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)

    preview = service_env["service"].get_dedupe_preview(scan_id, scorer_config=_recursive_config())

    assert preview["selection_mode"] == "recursive_directory_balanced_by_bytes"
    assert preview["actionable_group_count"] == 1
    rows = preview["rows"]
    assert len(rows) == 2
    by_path = {row["absolute_path"]: row for row in rows}

    keep_rows = [row for row in rows if row["member_decision"] == "KEEP"]
    quarantine_rows = [row for row in rows if row["member_decision"] == "QUARANTINE"]
    assert len(keep_rows) == 1
    assert len(quarantine_rows) == 1

    for row in rows:
        assert row["group_balance_info"]["selection_mode"] == "recursive_directory_balanced_by_bytes"
        assert row["group_balance_info"]["lca"] == str(service_env["data_dir"])
        assert "bucket_released_bytes_before" in row["group_balance_info"]
        assert "bucket_released_bytes_after" in row["group_balance_info"]
        assert "spread_before" in row["group_balance_info"]
        assert "spread_after" in row["group_balance_info"]
        assert isinstance(row["total_score"], int)
        assert row["contributions"]
        assert row["selection_reason"]
        assert row["candidate_balance_bucket"] in {
            str(service_env["data_dir"] / "A"),
            str(service_env["data_dir"] / "B"),
        }

    assert by_path[str(left)]["candidate_balance_bucket"] == str(service_env["data_dir"] / "A")
    assert by_path[str(right)]["candidate_balance_bucket"] == str(service_env["data_dir"] / "B")


def test_recursive_preview_digest_changes_on_live_file_identity_aba(service_env):
    scan_id = 902
    left, _right, _a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]

    before = service.get_dedupe_preview(scan_id, scorer_config=_recursive_config())
    _replace_with_same_bytes_new_inode(left)
    after = service.get_dedupe_preview(scan_id, scorer_config=_recursive_config())

    assert after["source_snapshot_digest"] != before["source_snapshot_digest"]
    assert after["preview_digest"] != before["preview_digest"]


def test_recursive_preview_digest_changes_when_ancestor_regular_file_count_changes(service_env):
    scan_id = 903
    _left, _right, a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]

    before = service.get_dedupe_preview(scan_id, scorer_config=_recursive_config())
    a_extra.unlink()
    after = service.get_dedupe_preview(scan_id, scorer_config=_recursive_config())

    assert after["source_snapshot_digest"] != before["source_snapshot_digest"]
    assert after["preview_digest"] != before["preview_digest"]
    assert after["planned_quarantine_count"] == 1
