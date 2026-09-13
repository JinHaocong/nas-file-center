from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.exceptions import StateConflictError
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, utcnow


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=trash,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
            allow_mutation=True,
            allow_delete=True,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def _active_entry(client: TestClient, name: str = "purge-lifecycle.txt") -> tuple[int, dict[str, Path]]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-purge-lifecycle"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(trash / f"pending-{name}"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=0,
            content_hash=None,
            mtime_ns=0,
            device=0,
            inode=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)
        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return entry.id, {"anchor": anchor, "captured_source": captured, "public_view": public_view}


def _purge_draft(client: TestClient, entry_id: int) -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    assert preview.json()["eligible_count"] == 1
    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def _add_shared_active_owner(client: TestClient, source_anchor: Path) -> tuple[int, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    st = source_anchor.stat(follow_symlinks=False)
    payload_hash = hashlib.sha256(source_anchor.read_bytes()).hexdigest()
    with service.SessionLocal() as session:
        owner = QuarantineEntry(
            original_path=str(data / "late-owner.txt"),
            quarantine_path=str(trash / "pending-late-owner.txt"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=st.st_size,
            content_hash=payload_hash,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(owner)
        session.flush()
        attempt = trash / ".tx" / f"entry-{owner.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"late-owner.q-{owner.id}.txt"
        os.link(source_anchor, anchor)
        os.link(source_anchor, captured)
        os.link(source_anchor, public_view)
        owner.quarantine_path = str(public_view)
        owner.authoritative_anchor_path = str(anchor)
        session.commit()
        return owner.id, anchor


def test_bulk_purge_freeze_rejects_new_shared_active_owner_after_draft(tmp_path: Path) -> None:
    client = _client(tmp_path)
    selected_id, paths = _active_entry(client)
    plan_id = _purge_draft(client, selected_id)
    owner_id, owner_anchor = _add_shared_active_owner(client, paths["anchor"])
    service = client.app.state.service

    with pytest.raises(StateConflictError, match="SHARED_ACTIVE_PAYLOAD"):
        service.freeze_plan(plan_id)

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "planned"
        owner = session.get(QuarantineEntry, owner_id)
        assert owner is not None
        assert owner.state == "active"

    assert paths["anchor"].exists()
    assert paths["captured_source"].exists()
    assert paths["public_view"].exists()
    assert owner_anchor.exists()


def test_bulk_purge_validate_rejects_new_shared_active_owner_after_freeze(tmp_path: Path) -> None:
    client = _client(tmp_path)
    selected_id, paths = _active_entry(client)
    plan_id = _purge_draft(client, selected_id)
    service = client.app.state.service

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    owner_id, owner_anchor = _add_shared_active_owner(client, paths["anchor"])
    detail = service.validate_plan(plan_id)

    assert detail["status"] == "stale"
    assert detail["items"][0]["state"] == "stale"
    assert detail["items"][0]["reason"] == "SHARED_ACTIVE_PAYLOAD"

    with service.SessionLocal() as session:
        selected = session.get(QuarantineEntry, selected_id)
        owner = session.get(QuarantineEntry, owner_id)
        assert selected is not None and selected.state == "active"
        assert owner is not None and owner.state == "active"

    assert paths["anchor"].exists()
    assert paths["captured_source"].exists()
    assert paths["public_view"].exists()
    assert owner_anchor.exists()


def test_bulk_purge_validate_rejects_unrecognized_private_alias_after_freeze(tmp_path: Path) -> None:
    client = _client(tmp_path)
    selected_id, paths = _active_entry(client)
    plan_id = _purge_draft(client, selected_id)
    service = client.app.state.service

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    rogue_alias = paths["anchor"].parent / "unexpected-private-alias"
    os.link(paths["anchor"], rogue_alias)
    detail = service.validate_plan(plan_id)

    assert detail["status"] == "stale"
    assert detail["items"][0]["state"] == "stale"
    assert detail["items"][0]["reason"] == "UNRECOGNIZED_PRIVATE_PATH"
    assert rogue_alias.exists()
    assert paths["anchor"].exists()
    assert paths["captured_source"].exists()
    assert paths["public_view"].exists()


def test_bulk_purge_validate_rejects_same_size_same_mtime_hash_drift_after_freeze(tmp_path: Path) -> None:
    client = _client(tmp_path)
    selected_id, paths = _active_entry(client)
    plan_id = _purge_draft(client, selected_id)
    service = client.app.state.service

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    anchor = paths["anchor"]
    before = anchor.stat(follow_symlinks=False)
    original = anchor.read_bytes()
    replacement = bytes((byte ^ 0x01) for byte in original)
    assert len(replacement) == len(original)
    anchor.write_bytes(replacement)
    os.utime(anchor, ns=(before.st_atime_ns, before.st_mtime_ns), follow_symlinks=False)

    detail = service.validate_plan(plan_id)

    assert detail["status"] == "stale"
    assert detail["items"][0]["state"] == "stale"
    assert detail["items"][0]["reason"] == "purge_source_identity_changed"
    assert anchor.exists()
    assert paths["captured_source"].exists()
    assert paths["public_view"].exists()
