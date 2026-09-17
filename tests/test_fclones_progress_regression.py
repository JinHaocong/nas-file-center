from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.service import FileCenterService
from app.worker import process_work_job


def test_fclones_import_more_than_one_batch_completes_with_unknown_total(tmp_path: Path):
    """Regression: >100 duplicate groups must not fail on an unknown import total."""
    fake = tmp_path / "fake-fclones.py"
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    root_a = data / "A"
    root_b = data / "B"
    root_a.mkdir()
    root_b.mkdir()

    groups = []
    for idx in range(101):
        payload = f"payload-{idx:03d}".encode()
        path_a = root_a / f"file-{idx:03d}.bin"
        path_b = root_b / f"file-{idx:03d}.bin"
        path_a.write_bytes(payload)
        path_b.write_bytes(payload)
        groups.append(
            {
                "file_len": len(payload),
                "file_hash": f"hash-{idx:03d}",
                "files": [str(path_a), str(path_b)],
            }
        )

    report = {"groups": groups}
    fake.write_text(
        "#!/usr/bin/env python3\nimport json\nprint("
        + repr(json.dumps(report, ensure_ascii=False))
        + ")\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=True,
        ALLOW_DELETE=False,
        FCLONES_BINARY=str(fake),
    )
    service = FileCenterService(settings)
    queued = service.enqueue_scan(
        name="101-group progress regression",
        roots=[str(root_a), str(root_b)],
        isolate=True,
    )

    success = process_work_job(settings, queued["work_job_id"])

    assert success is True
    scan = service.scan_detail(queued["scan_job_id"])
    assert scan["status"] == "completed"
    assert scan["total_groups"] == 101
    assert scan["total_files_in_groups"] == 202
