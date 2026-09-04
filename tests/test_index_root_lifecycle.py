from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    DuplicateFile,
    DuplicateGroup,
    IndexRoot,
    IndexedPath,
    ScanJob,
    TaskEvent,
    WorkJob,
)
from app.service import FileCenterService


def make_service(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    return FileCenterService(settings), data, settings


def make_authed_client(tmp_path: Path):
    service, data, settings = make_service(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    return client, service, data, settings


# ==============================================================================
# Core Acceptance Tests
# ==============================================================================


def test_empty_root_persists_in_registry_and_list_view(tmp_path: Path):
    """1. 空目录完成索引后持久存在，且 files=0, folders=0, last_indexed_at 非空"""
    service, data, _ = make_service(tmp_path)
    empty_dir = data / "EmptyFolder"
    empty_dir.mkdir()

    res = service.reindex_root(str(empty_dir))
    assert res["files"] == 0
    assert res["folders"] == 0

    roots = service.list_index_roots()
    assert roots["total"] == 1
    item = roots["items"][0]
    assert item["root"] == str(empty_dir.resolve())
    assert item["files"] == 0
    assert item["folders"] == 0
    assert item["last_indexed_at"] is not None
    assert item["last_seen_at"] == item["last_indexed_at"]
    assert item["path_state"] == "available"
    assert item["exists"] is True
    assert item["can_remove"] is True


def test_enqueue_index_creates_registry_immediately(tmp_path: Path):
    """2. enqueue_index 立即建立 Registry 记录，未开始索引前 last_indexed_at=null"""
    service, data, _ = make_service(tmp_path)
    target_dir = data / "PendingFolder"
    target_dir.mkdir()

    enq_res = service.enqueue_index(str(target_dir))
    assert "index_root_id" in enq_res
    assert enq_res["status"] == "queued"
    assert enq_res["created"] is True

    roots = service.list_index_roots()
    assert roots["total"] == 1
    item = roots["items"][0]
    assert item["root"] == str(target_dir.resolve())
    assert item["files"] == 0
    assert item["folders"] == 0
    assert item["last_indexed_at"] is None
    assert item["has_active_job"] is True
    assert item["active_job_id"] == enq_res["work_job_id"]
    assert item["active_job_status"] == "queued"
    assert item["can_remove"] is False


def test_same_root_enqueue_does_not_duplicate_registry(tmp_path: Path):
    """3. 同一 Root 重复 enqueue 不创建重复 Registry，created 标记为 False"""
    service, data, _ = make_service(tmp_path)
    folder = data / "DuplicateTarget"
    folder.mkdir()

    first = service.enqueue_index(str(folder))
    assert first["created"] is True

    second = service.enqueue_index(str(folder))
    assert second["created"] is False
    assert second["index_root_id"] == first["index_root_id"]
    assert second["work_job_id"] != first["work_job_id"]

    roots = service.list_index_roots()
    assert roots["total"] == 1


def test_successful_reindex_sets_last_indexed_at_and_counts(tmp_path: Path):
    """4 & 6. 重新索引更新 files/folders 统计与 last_indexed_at 时间戳"""
    service, data, _ = make_service(tmp_path)
    folder = data / "FilesDir"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    sub = folder / "Sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")

    service.enqueue_index(str(folder))
    before_index = service.list_index_roots()["items"][0]
    assert before_index["last_indexed_at"] is None

    service.reindex_root(str(folder))

    after_index = service.list_index_roots()["items"][0]
    assert after_index["files"] == 2
    assert after_index["folders"] == 1
    assert after_index["last_indexed_at"] is not None


def test_external_directory_removed_path_state_missing(tmp_path: Path):
    """8. NAS 外部删除目录后，Registry 依然保留，快照计数保留，path_state 变为 missing"""
    service, data, _ = make_service(tmp_path)
    folder = data / "ToExternalDelete"
    folder.mkdir()
    (folder / "file.txt").write_text("data")

    service.enqueue_index(str(folder))
    service.reindex_root(str(folder))

    # NAS 外部删除文件与目录
    (folder / "file.txt").unlink()
    folder.rmdir()

    roots = service.list_index_roots()
    assert roots["total"] == 1
    item = roots["items"][0]
    assert item["exists"] is False
    assert item["path_state"] == "missing"
    # 保存的元数据计数依然完好呈现，不自动清空
    assert item["files"] == 1
    assert item["folders"] == 0


def test_blocked_root_semantics(tmp_path: Path):
    """9. 当 ALLOWED_ROOTS 变更导致已登记 Root 逃逸时，path_state 变为 blocked"""
    service, data, settings = make_service(tmp_path)
    folder = data / "Restricted"
    folder.mkdir()
    enq = service.enqueue_index(str(folder))

    # 标记任务为已完成，解除活动任务阻塞
    with service.SessionLocal() as session:
        j = session.get(WorkJob, enq["work_job_id"])
        j.status = "completed"
        session.commit()

    # 模拟 ALLOWED_ROOTS 变更，仅允许 data / "AllowedOnly"
    new_allowed = data / "AllowedOnly"
    new_allowed.mkdir()
    settings.allowed_roots_raw = str(new_allowed)

    roots = service.list_index_roots()
    assert roots["total"] == 1
    item = roots["items"][0]
    assert item["exists"] is False
    assert item["path_state"] == "blocked"
    assert item["can_remove"] is True


def test_missing_and_blocked_root_can_be_metadata_removed(tmp_path: Path):
    """10 & 11. 即使目录已 missing 或 blocked，只要无活跃任务仍允许删除其元数据"""
    service, data, settings = make_service(tmp_path)
    folder = data / "MissingThenRemove"
    folder.mkdir()
    enq = service.enqueue_index(str(folder))
    idx_id = enq["index_root_id"]
    job_id = enq["work_job_id"]

    # 终态任务
    with service.SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.status = "completed"
        session.commit()

    folder.rmdir()
    del_res = service.delete_index_root(idx_id)
    assert del_res["deleted"] is True
    assert service.list_index_roots()["total"] == 0


def test_delete_root_exact_root_key_isolation(tmp_path: Path):
    """12 & 13. 删除根目录仅删除该 exact root_key 的 IndexedPath，绝不误删子目录或前缀相同目录"""
    service, data, _ = make_service(tmp_path)
    # 构造三组目录：/data/A, /data/A/sub, /data/AB
    dir_a = data / "A"
    dir_a_sub = dir_a / "sub"
    dir_ab = data / "AB"
    dir_a.mkdir()
    dir_a_sub.mkdir()
    dir_ab.mkdir()

    (dir_a / "a1.txt").write_text("a1")
    (dir_a_sub / "sub1.txt").write_text("sub1")
    (dir_ab / "ab1.txt").write_text("ab1")

    # 分别登记并索引
    enq_a = service.enqueue_index(str(dir_a))
    enq_sub = service.enqueue_index(str(dir_a_sub))
    enq_ab = service.enqueue_index(str(dir_ab))

    service.reindex_root(str(dir_a))
    service.reindex_root(str(dir_a_sub))
    service.reindex_root(str(dir_ab))

    # 标记全部任务为终态
    with service.SessionLocal() as session:
        for jid in [enq_a["work_job_id"], enq_sub["work_job_id"], enq_ab["work_job_id"]]:
            job = session.get(WorkJob, jid)
            job.status = "completed"
        session.commit()

    # 删除 A
    del_res = service.delete_index_root(enq_a["index_root_id"])
    assert del_res["deleted"] is True
    assert del_res["root"] == str(dir_a.resolve())

    with service.SessionLocal() as session:
        # A 的 IndexedPath 被清理
        rows_a = list(session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(dir_a.resolve()))))
        assert len(rows_a) == 0

        # A/sub 与 AB 绝不受影响
        rows_sub = list(session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(dir_a_sub.resolve()))))
        assert len(rows_sub) > 0

        rows_ab = list(session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(dir_ab.resolve()))))
        assert len(rows_ab) > 0


def test_active_job_matrix_blocks_delete(tmp_path: Path):
    """14~18. queued, running, paused, cancel_requested 及未知非终态任务严格阻止删除"""
    service, data, _ = make_service(tmp_path)
    folder = data / "ActiveJobDir"
    folder.mkdir()
    enq = service.enqueue_index(str(folder))
    idx_id = enq["index_root_id"]
    job_id = enq["work_job_id"]

    for blocked_status in ["queued", "running", "paused", "cancel_requested", "unknown_active"]:
        with service.SessionLocal() as session:
            j = session.get(WorkJob, job_id)
            j.status = blocked_status
            session.commit()

        with pytest.raises(ValueError, match="is active"):
            service.delete_index_root(idx_id)


def test_terminal_jobs_do_not_block_delete(tmp_path: Path):
    """19~21. completed, failed, cancelled 终态任务不阻止删除"""
    service, data, _ = make_service(tmp_path)

    for term_status in ["completed", "failed", "cancelled"]:
        folder = data / f"TermDir_{term_status}"
        folder.mkdir()
        enq = service.enqueue_index(str(folder))
        idx_id = enq["index_root_id"]
        job_id = enq["work_job_id"]

        with service.SessionLocal() as session:
            j = session.get(WorkJob, job_id)
            j.status = term_status
            session.commit()

        del_res = service.delete_index_root(idx_id)
        assert del_res["deleted"] is True


def test_delete_index_preserves_workjob_audit_scan_plan(tmp_path: Path):
    """22~27. 移除索引仅清理 IndexRoot + IndexedPath，Task/Scan/Plan/Audit 与文件绝对保留"""
    service, data, _ = make_service(tmp_path)
    folder = data / "PreserveDir"
    folder.mkdir()
    test_file = folder / "content.txt"
    test_file.write_text("vital content")

    enq = service.enqueue_index(str(folder))
    idx_id = enq["index_root_id"]
    job_id = enq["work_job_id"]
    service.reindex_root(str(folder))

    with service.SessionLocal() as session:
        # 添加 TaskEvent, ScanJob, BatchPlan, AuditEvent
        j = session.get(WorkJob, job_id)
        j.status = "completed"

        event = TaskEvent(job_id=job_id, level="info", event_type="test", message="index finished")
        session.add(event)

        scan = ScanJob(name="TestScan", roots_json=json.dumps([str(folder)]), status="completed")
        session.add(scan)

        plan = BatchPlan(name="TestPlan", kind="dedupe", status="draft")
        session.add(plan)

        audit = AuditEvent(operation="index_test", path=str(folder), result="success")
        session.add(audit)

        session.commit()
        scan_id = scan.id
        plan_id = plan.id
        audit_id = audit.id

    # 执行删除
    del_res = service.delete_index_root(idx_id)
    assert del_res["deleted"] is True

    # 验证各项记录均完好保留
    with service.SessionLocal() as session:
        assert session.get(WorkJob, job_id) is not None
        assert session.scalar(select(func.count(TaskEvent.id)).where(TaskEvent.job_id == job_id)) == 1
        assert session.get(ScanJob, scan_id) is not None
        assert session.get(BatchPlan, plan_id) is not None
        assert session.get(AuditEvent, audit_id) is not None

    # 磁盘文件毫无变动 (Filesystem Mutation = 0)
    assert test_file.exists()
    assert test_file.read_text() == "vital content"


def test_delete_api_auth_and_csrf_matrix(tmp_path: Path):
    """28~31. DELETE API 认证 (401)、CSRF (403) 及 404 测试"""
    client, service, data, settings = make_authed_client(tmp_path)
    folder = data / "ApiTestDir"
    folder.mkdir()
    enq = service.enqueue_index(str(folder))
    idx_id = enq["index_root_id"]
    job_id = enq["work_job_id"]

    with service.SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.status = "completed"
        session.commit()

    # 1. 未认证访问 -> 401
    unauth_client = TestClient(create_app(settings))
    resp_401 = unauth_client.delete(f"/api/indexes/{idx_id}")
    assert resp_401.status_code == 401

    # 2. 认证但缺失 Origin / Referer -> 403
    resp_403 = client.delete(f"/api/indexes/{idx_id}")
    assert resp_403.status_code == 403

    # 3. 删除不存在的 ID -> 404
    resp_404 = client.delete(
        "/api/indexes/99999",
        headers={"Origin": "http://testserver"},
    )
    assert resp_404.status_code == 404

    # 4. 合法凭据与 Origin -> 200
    resp_200 = client.delete(
        f"/api/indexes/{idx_id}",
        headers={"Origin": "http://testserver"},
    )
    assert resp_200.status_code == 200


def test_create_index_validation_matrix(tmp_path: Path):
    """32~35. 创建索引路径校验：越界、普通文件、不存在、符号链接逃逸返回 400"""
    client, _, data, _ = make_authed_client(tmp_path)

    # 越界
    resp_outside = client.post(
        "/api/indexes",
        json={"root": "/etc/passwd"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_outside.status_code == 400

    # 普通文件
    file_path = data / "regular.txt"
    file_path.write_text("not a dir")
    resp_file = client.post(
        "/api/indexes",
        json={"root": str(file_path)},
        headers={"Origin": "http://testserver"},
    )
    assert resp_file.status_code == 400

    # 不存在
    resp_missing = client.post(
        "/api/indexes",
        json={"root": str(data / "NonExistentDir")},
        headers={"Origin": "http://testserver"},
    )
    assert resp_missing.status_code == 400

    # 符号链接逃逸
    outside_dir = data.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    symlink_path = data / "escape_symlink"
    try:
        symlink_path.symlink_to(outside_dir)
        resp_symlink = client.post(
            "/api/indexes",
            json={"root": str(symlink_path)},
            headers={"Origin": "http://testserver"},
        )
        assert resp_symlink.status_code == 400
    except (OSError, NotImplementedError):
        pass


def test_worker_fencing_aborts_registry_update(tmp_path: Path):
    """36. Worker Fencing: reindex_root 终态短事务中若 lease lost，IndexRoot.last_indexed_at 绝不更新"""
    service, data, _ = make_service(tmp_path)
    folder = data / "FencedDir"
    folder.mkdir()
    (folder / "item.txt").write_text("data")

    # 先做一次正常索引建立 registry
    service.enqueue_index(str(folder))
    service.reindex_root(str(folder))
    orig_time = service.list_index_roots()["items"][0]["last_indexed_at"]
    assert orig_time is not None

    def bad_guard(session):
        raise RuntimeError("Worker fence: lease lost")

    # 再次重索引但模拟租约丢失
    with pytest.raises(RuntimeError, match="lease lost"):
        service.reindex_root(str(folder), transaction_guard=bad_guard)

    # 事务回滚，last_indexed_at 保持不变
    curr_time = service.list_index_roots()["items"][0]["last_indexed_at"]
    assert curr_time == orig_time
