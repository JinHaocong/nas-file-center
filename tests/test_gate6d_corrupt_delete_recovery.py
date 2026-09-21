import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.media.corrupt_delete import (
    OPERATION_ID,
    _load_frozen_row,
    build_corrupt_delete_preview,
    create_corrupt_delete_plan,
    reconcile_corrupt_media_delete,
)
from app.models import IndexedPath, MediaAsset, OperationJournal, utcnow
from app.service import FileCenterService


def _setup(tmp_path: Path):
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
        ALLOW_DELETE=True,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="AdminPassword123!",
    )
    service = FileCenterService(settings)
    client = TestClient(create_app(settings))
    client.headers["Origin"] = "http://testserver"
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    ).status_code == 200
    return client, service, settings, data


def _seed_corrupt(service: FileCenterService, source: Path) -> int:
    import hashlib

    st = os.lstat(source)
    now = utcnow()
    with service.SessionLocal() as session:
        indexed = IndexedPath(
            root_key=str(source.parent),
            absolute_path=str(source),
            relative_path=source.name,
            basename=source.name,
            stem=source.stem,
            suffix=source.suffix,
            size=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            device=int(st.st_dev),
            inode=int(st.st_ino),
            is_dir=False,
            first_seen_at=now,
            last_seen_at=now,
            scan_generation="scan-recovery",
        )
        session.add(indexed)
        session.flush()
        asset = MediaAsset(
            indexed_path_id=int(indexed.id),
            media_kind="image",
            integrity_status="corrupt",
            integrity_reason_code="IMAGE_DECODE_FAILED",
            observed_device=int(st.st_dev),
            observed_inode=int(st.st_ino),
            observed_size=int(st.st_size),
            observed_mtime_ns=int(st.st_mtime_ns),
            corrupt_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            source_scan_generation="scan-recovery",
            probe_generation="probe-recovery",
            probed_at=now,
            updated_at=now,
        )
        session.add(asset)
        session.commit()
        return int(asset.id)


def _create_plan(service: FileCenterService, settings: Settings, asset_id: int) -> tuple[int, int, dict]:
    preview = build_corrupt_delete_preview(service.SessionLocal, settings, [asset_id])
    created = create_corrupt_delete_plan(
        service.SessionLocal,
        settings,
        asset_ids=[asset_id],
        expected_preview_digest=preview["preview_digest"],
        confirmation="DELETE_CORRUPT_FILES",
        requested_by_user_id=None,
    )
    plan_id = int(created["id"])
    service.freeze_plan(plan_id)

    with service.SessionLocal() as session:
        item = session.scalar(
            select(__import__("app.models", fromlist=["BatchPlanItem"]).BatchPlanItem)
            .where(__import__("app.models", fromlist=["BatchPlanItem"]).BatchPlanItem.plan_id == plan_id)
        )
        assert item is not None
        _plan, _row, _plan_meta, _item_meta, manifest = _load_frozen_row(
            session,
            plan_id=plan_id,
            item_id=int(item.id),
        )
        return plan_id, int(item.id), manifest


def _set_executing(service: FileCenterService, item_id: int) -> None:
    from app.models import BatchPlanItem

    with service.SessionLocal() as session:
        row = session.get(BatchPlanItem, item_id)
        assert row is not None
        row.state = "executing"
        session.commit()


def _add_intent(service: FileCenterService, plan_id: int, item_id: int, manifest: dict) -> None:
    from app.models import BatchPlanItem

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        session.add(
            OperationJournal(
                operation=OPERATION_ID,
                sequence=int(item.sequence),
                plan_id=plan_id,
                plan_item_id=item_id,
                task_id=None,
                user_id=None,
                before_json=json.dumps(
                    {"phase": "intent", "manifest": manifest},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                after_json="{}",
                metadata_before_json=json.dumps(manifest["identity"], ensure_ascii=False),
                metadata_after_json="{}",
                created_at=utcnow(),
            )
        )
        session.commit()


def _reconcile(service: FileCenterService, settings: Settings, plan_id: int, item_id: int) -> tuple[str, str | None]:
    from app.models import BatchPlanItem

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        assert reconcile_corrupt_media_delete(
            session,
            item,
            plan_id,
            None,
            None,
            settings,
            utcnow(),
        ) is True
        state = item.state
        reason = item.reason
        session.commit()
        return state, reason


def test_recovery_without_durable_intent_has_no_unlink_authority(tmp_path: Path):
    _client, service, settings, data = _setup(tmp_path)
    source = data / "before-intent.jpg"
    source.write_bytes(b"corrupt-before-intent")
    asset_id = _seed_corrupt(service, source)
    plan_id, item_id, _manifest = _create_plan(service, settings, asset_id)
    _set_executing(service, item_id)

    state, reason = _reconcile(service, settings, plan_id, item_id)

    assert state == "planned"
    assert reason is None
    assert source.exists()
    with service.SessionLocal() as session:
        assert list(
            session.scalars(
                select(OperationJournal).where(
                    OperationJournal.operation == OPERATION_ID,
                    OperationJournal.plan_item_id == item_id,
                )
            )
        ) == []


def test_recovery_after_intent_with_exact_source_only_requeues_exact_delete(tmp_path: Path):
    _client, service, settings, data = _setup(tmp_path)
    source = data / "after-intent-present.jpg"
    source.write_bytes(b"corrupt-after-intent")
    asset_id = _seed_corrupt(service, source)
    plan_id, item_id, manifest = _create_plan(service, settings, asset_id)
    _set_executing(service, item_id)
    _add_intent(service, plan_id, item_id, manifest)

    state, reason = _reconcile(service, settings, plan_id, item_id)

    assert state == "planned"
    assert reason is None
    assert source.exists()


def test_recovery_after_intent_and_unlink_converges_terminal_without_quarantine(tmp_path: Path):
    _client, service, settings, data = _setup(tmp_path)
    source = data / "after-unlink.jpg"
    source.write_bytes(b"corrupt-after-unlink")
    asset_id = _seed_corrupt(service, source)
    plan_id, item_id, manifest = _create_plan(service, settings, asset_id)
    _set_executing(service, item_id)
    _add_intent(service, plan_id, item_id, manifest)

    source.unlink()
    state, reason = _reconcile(service, settings, plan_id, item_id)

    assert state == "completed"
    assert reason == "source absent after durable corrupt-media delete intent"
    with service.SessionLocal() as session:
        assert session.get(MediaAsset, asset_id) is None
        terminal = list(
            session.scalars(
                select(OperationJournal)
                .where(
                    OperationJournal.operation == OPERATION_ID,
                    OperationJournal.plan_item_id == item_id,
                )
                .order_by(OperationJournal.id)
            )
        )
        assert len(terminal) == 2
        assert '"phase":"terminal"' in terminal[-1].before_json


def test_recovery_after_intent_rejects_same_path_replacement(tmp_path: Path):
    _client, service, settings, data = _setup(tmp_path)
    source = data / "replacement.jpg"
    source.write_bytes(b"corrupt-original")
    asset_id = _seed_corrupt(service, source)
    plan_id, item_id, manifest = _create_plan(service, settings, asset_id)
    _set_executing(service, item_id)
    _add_intent(service, plan_id, item_id, manifest)

    old = data / "replacement.old"
    source.rename(old)
    source.write_bytes(b"foreign-replacement")

    state, reason = _reconcile(service, settings, plan_id, item_id)

    assert state == "failed"
    assert reason is not None
    assert "SOURCE_IDENTITY_CHANGED" in reason
    assert source.read_bytes() == b"foreign-replacement"
