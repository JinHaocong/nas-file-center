from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry, utcnow


def _setup_admin_client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

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


def _seed_selected_active(client: TestClient) -> tuple[int, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-history-payload"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "selected.txt"),
            quarantine_path=str(trash / "pending-selected.txt"),
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
        attempt.mkdir(parents=True, exist_ok=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"selected.q-{entry.id}.txt"
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
        return entry.id, anchor


def _seed_historical_conflict_candidate(client: TestClient, source_anchor: Path) -> tuple[int, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    st = source_anchor.stat(follow_symlinks=False)
    payload_hash = hashlib.sha256(source_anchor.read_bytes()).hexdigest()

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "historical.txt"),
            quarantine_path=str(trash / "pending-historical.txt"),
            state="conflict",
            tx_phase="conflict",
            active_attempt_generation=1,
            authoritative_anchor_path=None,
            size=st.st_size,
            content_hash=payload_hash,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()

        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True, exist_ok=True)
        candidate = attempt / "anchor"
        os.link(source_anchor, candidate)
        session.commit()
        return entry.id, candidate


def test_bulk_purge_preview_accepts_requalified_historical_conflict_candidate(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    selected_id, selected_anchor = _seed_selected_active(client)
    historical_id, candidate = _seed_historical_conflict_candidate(client, selected_anchor)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [selected_id]},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_count"] == 1
    assert body["blocked_count"] == 0
    item = body["items"][0]
    assert item["eligible"] is True
    assert item["reason"] is None

    manifest = item["purge_topology_manifest"]
    assert manifest["blockers"] == []
    assert manifest["blocking_owner_entry_ids"] == []
    assert manifest["historical_conflict_entry_ids"] == [historical_id]
    assert {
        "role": "historical_conflict_candidate",
        "owner_entry_id": historical_id,
        "path": str(candidate),
    } in manifest["aliases"]
