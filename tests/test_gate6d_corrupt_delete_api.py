import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlanItem,
    IndexedPath,
    MediaAsset,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    User,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.worker import process_work_job


def _env(tmp_path: Path, *, allow_delete: bool = True):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(trash),
        ALLOW_MUTATION=True,
        ALLOW_DELETE=allow_delete,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="AdminPassword123!",
    )
    service = FileCenterService(settings)
    client = TestClient(create_app(settings))
    client.headers["Origin"] = "http://testserver"
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login.status_code == 200
    return client, service, settings, data, trash


def _seed_media(service: FileCenterService, path: Path, *, status: str = "corrupt") -> int:
    payload = path.read_bytes()
    st = os.lstat(path)
    digest = hashlib.sha256(payload).hexdigest() if status == "corrupt" else None
    now = utcnow()
    with service.SessionLocal() as session:
        indexed = IndexedPath(
            root_key=str(path.parent),
            absolute_path=str(path),
            relative_path=path.name,
            basename=path.name,
            stem=path.stem,
            suffix=path.suffix.lower(),
            size=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            device=int(st.st_dev),
            inode=int(st.st_ino),
            is_dir=False,
            first_seen_at=now,
            last_seen_at=now,
            scan_generation="scan-g6d",
        )
        session.add(indexed)
        session.flush()
        asset = MediaAsset(
            indexed_path_id=int(indexed.id),
            media_kind="image",
            integrity_status=status,
            integrity_reason_code=(
                "IMAGE_DECODE_FAILED" if status == "corrupt" else None
            ),
            observed_device=int(st.st_dev),
            observed_inode=int(st.st_ino),
            observed_size=int(st.st_size),
            observed_mtime_ns=int(st.st_mtime_ns),
            corrupt_sha256=digest,
            source_scan_generation="scan-g6d",
            probe_generation="probe-g6d",
            probed_at=now,
            updated_at=now,
        )
        session.add(asset)
        session.commit()
        return int(asset.id)


def _run_worker(service: FileCenterService, settings: Settings, job_id: int) -> bool:
    worker_id = "gate6d-delete-worker"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(
                id=1,
                locked=True,
                owner=worker_id,
                acquired_at=utcnow(),
            )
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()
    return process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=worker_id,
    )


def test_corrupt_media_direct_delete_end_to_end_bypasses_quarantine(tmp_path: Path):
    client, service, settings, data, _trash = _env(tmp_path)
    source = data / "broken.jpg"
    source.write_bytes(b"not-a-real-jpeg-but-frozen-corrupt-evidence")
    asset_id = _seed_media(service, source, status="corrupt")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    )
    assert preview.status_code == 200
    pbody = preview.json()
    assert pbody["eligible_count"] == 1
    assert pbody["blocked_count"] == 0
    assert pbody["items"][0]["eligible"] is True

    created = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": pbody["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    assert created.status_code == 200
    plan_id = int(created.json()["id"])

    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    validated = client.post(f"/api/plans/{plan_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["status"] == "ready"

    queued = client.post(f"/api/plans/{plan_id}/execute")
    assert queued.status_code == 200
    job_id = int(queued.json()["work_job_id"])
    assert _run_worker(service, settings, job_id) is True

    assert not source.exists()

    detail = client.get(f"/api/plans/{plan_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["items"][0]["operation"] == "media_corrupt_unlink_delete"
    assert detail.json()["items"][0]["state"] == "completed"

    with service.SessionLocal() as session:
        assert session.get(MediaAsset, asset_id) is None
        assert session.scalar(select(func.count(QuarantineEntry.id))) == 0
        journals = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.operation == "media_corrupt_unlink_delete")
                .order_by(OperationJournal.id)
            )
        )
        assert len(journals) == 2
        assert '"phase":"intent"' in journals[0].before_json
        assert '"phase":"terminal"' in journals[1].before_json


def test_healthy_media_cannot_enter_direct_delete_plan(tmp_path: Path):
    client, service, _settings, data, _trash = _env(tmp_path)
    source = data / "healthy.jpg"
    source.write_bytes(b"healthy-placeholder")
    asset_id = _seed_media(service, source, status="healthy")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["eligible_count"] == 0
    assert "MEDIA_NOT_CORRUPT" in body["items"][0]["blockers"]


def test_direct_delete_plan_requires_allow_delete(tmp_path: Path):
    client, service, _settings, data, _trash = _env(tmp_path, allow_delete=False)
    source = data / "broken.jpg"
    source.write_bytes(b"corrupt")
    asset_id = _seed_media(service, source, status="corrupt")
    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    ).json()

    response = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    assert response.status_code == 409
    assert source.exists()


def test_generic_plan_api_cannot_forge_media_corrupt_delete_operation(tmp_path: Path):
    client, _service, _settings, data, _trash = _env(tmp_path)
    source = data / "x.jpg"
    source.write_bytes(b"x")

    response = client.post(
        "/api/plans",
        json={
            "name": "forged media delete",
            "kind": "media-corrupt-delete",
            "items": [
                {
                    "operation": "media_corrupt_unlink_delete",
                    "source": str(source),
                    "expected_size": 1,
                }
            ],
        },
    )
    assert response.status_code in {400, 409, 422}
    assert source.exists()


def test_source_hash_drift_blocks_execution_before_unlink(tmp_path: Path):
    client, service, settings, data, _trash = _env(tmp_path)
    source = data / "broken.jpg"
    source.write_bytes(b"corrupt-v1")
    asset_id = _seed_media(service, source, status="corrupt")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    ).json()
    created = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    plan_id = int(created.json()["id"])
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    assert client.post(f"/api/plans/{plan_id}/validate").json()["status"] == "ready"

    # Same pathname is no longer the frozen object.
    previous = source.with_suffix(".old")
    source.rename(previous)
    source.write_bytes(b"replacement")

    execute = client.post(f"/api/plans/{plan_id}/execute")
    assert execute.status_code == 409
    assert source.read_bytes() == b"replacement"

    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)
        )
        assert item is not None
        assert item.state == "stale"


def test_non_admin_cannot_manage_corrupt_delete_plan_lifecycle(tmp_path: Path):
    client, service, _settings, data, _trash = _env(tmp_path)
    source = data / "admin-only-broken.jpg"
    source.write_bytes(b"corrupt-admin-only")
    asset_id = _seed_media(service, source, status="corrupt")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    ).json()
    created = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    assert created.status_code == 200
    plan_id = int(created.json()["id"])

    with service.SessionLocal() as session:
        resume_job = WorkJob(
            kind="batch-plan-execute",
            status="paused",
            state_json=json.dumps({"plan_id": plan_id}),
            checkpoint_json=json.dumps({"schema_version": 1}),
        )
        retry_job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan_id}),
        )
        session.add_all([resume_job, retry_job])
        session.flush()
        resume_job_id = int(resume_job.id)
        retry_job_id = int(retry_job.id)

        admin = session.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.role = "user"
        session.commit()

    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 403
    assert client.post(f"/api/plans/{plan_id}/validate").status_code == 403
    assert client.post(f"/api/plans/{plan_id}/execute").status_code == 403
    assert client.post(f"/api/tasks/{resume_job_id}/resume").status_code == 403
    assert client.post(f"/api/tasks/{retry_job_id}/retry").status_code == 403
    assert source.exists()



def test_hash_drift_after_enqueue_cannot_create_durable_intent(monkeypatch, tmp_path: Path):
    client, service, settings, data, _trash = _env(tmp_path)
    source = data / "post-enqueue-drift.jpg"
    source.write_bytes(b"AAAA1111")
    asset_id = _seed_media(service, source, status="corrupt")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    ).json()
    created = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    plan_id = int(created.json()["id"])
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    assert client.post(f"/api/plans/{plan_id}/validate").json()["status"] == "ready"

    queued = client.post(f"/api/plans/{plan_id}/execute")
    assert queued.status_code == 200
    job_id = int(queued.json()["work_job_id"])

    # Change content after enqueue while preserving the frozen pathname,
    # inode, size and mtime. Only the authoritative SHA256 can detect this.
    frozen = os.stat(source, follow_symlinks=False)
    source.write_bytes(b"BBBB2222")
    os.utime(
        source,
        ns=(int(frozen.st_atime_ns), int(frozen.st_mtime_ns)),
        follow_symlinks=False,
    )

    # Bypass the generic BatchPlan freshness guard in this regression so the
    # test exercises the dedicated Gate6-D boundary itself. The direct-delete
    # executor must still hash the exact opened file before it commits durable
    # unlink intent.
    monkeypatch.setattr(
        "app.tasks.handlers_base._verify_plan_item_and_keep_freshness",
        lambda *_args, **_kwargs: (True, None),
    )

    assert _run_worker(service, settings, job_id) is True
    assert source.read_bytes() == b"BBBB2222"

    with service.SessionLocal() as session:
        journals = list(
            session.scalars(
                select(OperationJournal).where(
                    OperationJournal.operation == "media_corrupt_unlink_delete"
                )
            )
        )
        assert journals == []
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)
        )
        assert item is not None
        assert item.state == "failed"
        assert item.reason is not None
        assert "SOURCE_HASH_CHANGED" in item.reason



def test_parent_symlink_rebind_after_enqueue_is_fail_closed(tmp_path: Path):
    client, service, settings, data, _trash = _env(tmp_path)
    folder = data / "album"
    folder.mkdir()
    source = folder / "broken.jpg"
    source.write_bytes(b"corrupt-parent-rebind")
    asset_id = _seed_media(service, source, status="corrupt")

    preview = client.post(
        "/api/media/corrupt-delete/preview",
        json={"media_asset_ids": [asset_id]},
    ).json()
    created = client.post(
        "/api/media/corrupt-delete/plan",
        json={
            "media_asset_ids": [asset_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE_CORRUPT_FILES",
        },
    )
    plan_id = int(created.json()["id"])
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    assert client.post(f"/api/plans/{plan_id}/validate").json()["status"] == "ready"

    queued = client.post(f"/api/plans/{plan_id}/execute")
    assert queued.status_code == 200
    job_id = int(queued.json()["work_job_id"])

    # Rebind a frozen ancestor through a symlink while keeping the exact same
    # leaf inode/content reachable. Resolving the path before the no-follow
    # walk would hide this namespace ABA and wrongly authorize an unlink.
    moved = data / "album-moved"
    folder.rename(moved)
    folder.symlink_to(moved, target_is_directory=True)
    rebound_source = moved / "broken.jpg"
    assert source.exists()
    assert rebound_source.exists()

    _run_worker(service, settings, job_id)

    assert rebound_source.exists()
    assert rebound_source.read_bytes() == b"corrupt-parent-rebind"
    with service.SessionLocal() as session:
        journals = list(
            session.scalars(
                select(OperationJournal).where(
                    OperationJournal.operation == "media_corrupt_unlink_delete"
                )
            )
        )
        assert journals == []
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)
        )
        assert item is not None
        assert item.state == "failed"
        assert item.reason is not None
        assert "UNSAFE_ANCESTOR" in item.reason
