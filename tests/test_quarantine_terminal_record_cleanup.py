from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry
from app.service import FileCenterService


@pytest.fixture
def maintenance_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200

    return {"service": service, "data": data, "trash": trash, "admin": client}


def _seed(service, data: Path, trash: Path, *, state: str, name: str) -> int:
    with service.SessionLocal() as session:
        row = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(trash / (name + ".q")),
            state=state,
            size=0,
            mtime_ns=0,
            device=0,
            inode=0,
        )
        session.add(row)
        session.commit()
        return int(row.id)


def test_terminal_record_cleanup_accepts_abandoned_and_conflict(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    ids = [
        _seed(service, data, trash, state="abandoned", name="abandoned"),
        _seed(service, data, trash, state="conflict", name="conflict"),
    ]
    for entry_id in ids:
        response = admin.delete(
            f"/api/quarantine/{entry_id}/record?confirmation=DELETE_RECORD"
        )
        assert response.status_code == 200

    with service.SessionLocal() as session:
        for entry_id in ids:
            assert session.get(QuarantineEntry, entry_id) is None


def test_conflict_record_cleanup_blocks_when_tx_artifact_exists(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    entry_id = _seed(service, data, trash, state="conflict", name="conflict-artifact")
    tx_dir = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
    tx_dir.mkdir(parents=True)
    (tx_dir / "anchor").write_text("evidence", encoding="utf-8")

    response = admin.delete(
        f"/api/quarantine/{entry_id}/record?confirmation=DELETE_RECORD"
    )
    assert response.status_code == 409

    with service.SessionLocal() as session:
        assert session.get(QuarantineEntry, entry_id) is not None


def test_bulk_terminal_record_cleanup_accepts_mixed_states(maintenance_env):
    env = maintenance_env
    admin = env["admin"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    ids = [
        _seed(service, data, trash, state="purged", name="purged"),
        _seed(service, data, trash, state="abandoned", name="abandoned-bulk"),
        _seed(service, data, trash, state="conflict", name="conflict-bulk"),
    ]
    response = admin.post(
        "/api/quarantine/records/bulk-delete",
        json={"entry_ids": ids, "confirmation": "DELETE_RECORDS"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["deleted_ids"] == ids

    with service.SessionLocal() as session:
        assert list(
            session.scalars(select(QuarantineEntry).where(QuarantineEntry.id.in_(ids)))
        ) == []
