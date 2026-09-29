from __future__ import annotations

import json
import os
from pathlib import Path

from app.models import DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.scanners.diagnostics import diagnose_duplicate_pair


def _service_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    from app.config import Settings
    from app.service import FileCenterService

    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(quarantine),
        ALLOW_MUTATION=False,
        ALLOW_DELETE=False,
    )
    service = FileCenterService(settings)
    return service, settings, data


def test_duplicate_diagnostics_distinguishes_exact_copy_hardlink_and_different_content(tmp_path: Path):
    service, settings, data = _service_env(tmp_path)

    first = data / "first.bin"
    second = data / "second.bin"
    hardlink = data / "hardlink.bin"
    different = data / "different.bin"

    first.write_bytes(b"same-payload")
    second.write_bytes(b"same-payload")
    os.link(first, hardlink)
    different.write_bytes(b"diff-payload")

    exact = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(first),
        path_b=str(second),
    )
    assert exact["diagnosis"] == "EXACT_CONTENT_DUPLICATE"
    assert exact["sha256_match"] is True
    assert exact["same_filesystem_entry"] is False
    assert exact["exact_duplicate_copies"] is True

    linked = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(first),
        path_b=str(hardlink),
    )
    assert linked["diagnosis"] == "SAME_FILESYSTEM_ENTRY"
    assert linked["sha256_match"] is True
    assert linked["same_filesystem_entry"] is True
    assert linked["exact_duplicate_copies"] is False

    mismatch = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(first),
        path_b=str(different),
    )
    assert mismatch["diagnosis"] == "DIFFERENT_CONTENT"
    assert mismatch["exact_duplicate_copies"] is False


def test_duplicate_diagnostics_explains_scan_snapshot_membership(tmp_path: Path):
    service, settings, data = _service_env(tmp_path)

    first = data / "first.bin"
    second = data / "second.bin"
    late_copy = data / "late-copy.bin"
    payload = b"identical-current-bytes"
    first.write_bytes(payload)
    second.write_bytes(payload)
    late_copy.write_bytes(payload)

    with service.SessionLocal() as session:
        scan = ScanJob(
            name="diagnostic scan",
            mode="normal",
            roots_json=json.dumps([str(data)]),
            status="completed",
            fclones_args_json=json.dumps(
                {
                    "min_size": None,
                    "name_patterns": None,
                    "exclude_patterns": None,
                }
            ),
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=1,
            total_files_in_groups=2,
            reclaimable_bytes=len(payload),
        )
        session.add(scan)
        session.flush()

        group = DuplicateGroup(
            scan_job_id=scan.id,
            content_hash="discovery-hash",
            file_size=len(payload),
            member_count=2,
        )
        session.add(group)
        session.flush()

        for path in (first, second):
            st = path.stat()
            session.add(
                DuplicateFile(
                    group_id=group.id,
                    root_id=0,
                    absolute_path=str(path.resolve()),
                    relative_path=path.name,
                    top_level_dir=str(data),
                    size=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    device=st.st_dev,
                    inode=st.st_ino,
                )
            )
        session.commit()
        scan_id = scan.id

    present = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(first),
        path_b=str(second),
        scan_job_id=scan_id,
    )
    assert present["diagnosis"] == "EXACT_CONTENT_DUPLICATE"
    assert present["scan"]["same_duplicate_group"] is True
    assert len(present["scan"]["shared_group_ids"]) == 1
    assert all(
        path_info["included_in_duplicate_snapshot"]
        for path_info in present["scan"]["paths"]
    )
    assert present["scan"]["fclones_args"]["match_links"] is False

    missed = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(first),
        path_b=str(late_copy),
        scan_job_id=scan_id,
    )
    assert missed["diagnosis"] == "EXACT_CONTENT_DUPLICATE"
    assert missed["scan"]["same_duplicate_group"] is False
    assert missed["scan"]["paths"][0]["included_in_duplicate_snapshot"] is True
    assert missed["scan"]["paths"][1]["included_in_duplicate_snapshot"] is False
    assert "NOT_IN_SNAPSHOT_AT_SCAN_TIME" in missed["scan"]["paths"][1]["reasons"]


def test_duplicate_diagnostics_fails_closed_for_outside_path(tmp_path: Path):
    service, settings, data = _service_env(tmp_path)
    inside = data / "inside.bin"
    inside.write_bytes(b"x")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")

    result = diagnose_duplicate_pair(
        service.SessionLocal,
        settings,
        path_a=str(inside),
        path_b=str(outside),
    )

    assert result["diagnosis"] == "PATH_OUTSIDE_CONFIGURED_ROOTS"
    assert result["paths"][1]["allowed"] is False
    assert result["paths"][1]["sha256"] is None
