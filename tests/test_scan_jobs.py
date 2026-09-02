import json
from pathlib import Path


def make_settings(tmp_path, fake_binary):
    data = tmp_path / "data"; data.mkdir()
    config = tmp_path / "config"; config.mkdir()
    from app.config import Settings
    return Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=True,
        ALLOW_DELETE=False,
        FCLONES_BINARY=str(fake_binary),
    ), data


def test_durable_scan_import_plan_validate_and_execute(tmp_path):
    fake = tmp_path / "fake-fclones.py"
    settings, data = make_settings(tmp_path, fake)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    pairs = []
    for idx, payload in enumerate((b"alpha", b"beta"), 1):
        pa = a / f"{idx}.bin"; pb = b / f"{idx}.bin"
        pa.write_bytes(payload); pb.write_bytes(payload)
        pairs.append((pa, pb, payload))
    report = {
        "groups": [
            {"file_len": len(payload), "file_hash": f"metro-{idx}", "files": [str(pa), str(pb)]}
            for idx, (pa, pb, payload) in enumerate(pairs, 1)
        ]
    }
    fake.write_text(
        "#!/usr/bin/env python3\nimport json\nprint(" + repr(json.dumps(report, ensure_ascii=False)) + ")\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    from app.service import FileCenterService
    from app.worker import process_work_job
    service = FileCenterService(settings)
    queued = service.enqueue_scan(name="AB", roots=[str(a), str(b)], isolate=True)
    assert queued["status"] == "queued"

    process_work_job(settings, queued["work_job_id"])
    scan = service.scan_detail(queued["scan_job_id"])
    assert scan["status"] == "completed"
    assert scan["total_groups"] == 2
    assert scan["total_files_in_groups"] == 4
    assert scan["reclaimable_bytes"] == len(b"alpha") + len(b"beta")

    plan = service.create_dedupe_plan(queued["scan_job_id"], policy="balanced-roots")
    assert plan["status"] == "draft"
    detail = service.plan_detail(plan["id"])
    deleted_parents = [Path(i["source"]).parent.name for i in detail["items"]]
    assert deleted_parents.count("A") == 1
    assert deleted_parents.count("B") == 1

    service.freeze_plan(plan["id"])
    validated = service.validate_plan(plan["id"])
    assert validated["status"] == "ready"
    assert all(i["state"] == "validated" for i in validated["items"])

    executed = service.execute_plan(plan["id"])
    assert executed["status"] == "completed"
    assert sum(1 for p in a.iterdir() if p.is_file()) == 1
    assert sum(1 for p in b.iterdir() if p.is_file()) == 1
    assert len(list((data / ".trash" / str(plan["id"])).rglob("*.bin"))) == 2
