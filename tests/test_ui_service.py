import json


def make_service(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    config = tmp_path / "config"; config.mkdir()
    from app.config import Settings
    from app.service import FileCenterService
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
    )
    return FileCenterService(settings), data


def test_dashboard_summary_and_list_views_are_bounded(tmp_path):
    service, data = make_service(tmp_path)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    (a / "x.txt").write_text("x")
    service.reindex_root(str(a))
    service.enqueue_scan(name="A-B", roots=[str(a), str(b)], isolate=True)

    summary = service.dashboard_summary()
    assert summary["indexed_files"] == 1
    assert summary["scan_count"] == 1
    assert summary["queued_or_running_jobs"] == 1

    scans = service.list_scans(limit=10)
    assert scans[0]["name"] == "A-B"
    jobs = service.list_work_jobs(limit=10)
    assert jobs[0]["kind"] == "fclones-scan"
    roots = service.list_index_roots(limit=10)
    assert roots[0]["root"] == str(a.resolve())
    assert roots[0]["files"] == 1


def test_scan_groups_and_audit_list_renderable_shape(tmp_path):
    service, data = make_service(tmp_path)
    from app.models import AuditEvent, DuplicateFile, DuplicateGroup, ScanJob

    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    pa = a / "same.bin"; pb = b / "same.bin"
    pa.write_bytes(b"same"); pb.write_bytes(b"same")
    with service.SessionLocal() as session:
        scan = ScanJob(name="done", mode="isolate", roots_json=json.dumps([str(a), str(b)]), status="completed", fclones_args_json="{}", total_groups=1, total_files_in_groups=2, reclaimable_bytes=4)
        session.add(scan); session.flush()
        group = DuplicateGroup(scan_job_id=scan.id, content_hash="hash", file_size=4, member_count=2)
        session.add(group); session.flush()
        for root_id, path in enumerate((pa, pb)):
            stat = path.stat()
            session.add(DuplicateFile(group_id=group.id, root_id=root_id, absolute_path=str(path), relative_path=path.name, top_level_dir=str(path.parent), size=4, mtime_ns=stat.st_mtime_ns, device=stat.st_dev, inode=stat.st_ino))
        session.add(AuditEvent(operation="scan", path=str(a), result="ok", details_json='{"x":1}'))
        session.commit()
        scan_id = scan.id

    groups = service.scan_groups(scan_id, limit=10)
    assert groups[0]["file_size"] == 4
    assert len(groups[0]["members"]) == 2
    assert groups[0]["members"][0]["path"]

    audit = service.list_audit_events(limit=10)
    assert audit[0]["operation"] == "scan"
    assert audit[0]["details"] == {"x": 1}
