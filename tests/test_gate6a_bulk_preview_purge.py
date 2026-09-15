from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason='Gate6-A v0.3.6 COMPAT permanent purge release path is deferred after B10; dormant purge-core safety is covered by direct transactional/recovery tests')

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


def _seed_active_entry(client: TestClient, name: str = "purge.txt") -> tuple[int, dict[str, Path]]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-purge-preview"

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
        attempt.mkdir(parents=True, exist_ok=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat()

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return entry.id, {
            "anchor": anchor,
            "captured_source": captured,
            "public_view": public_view,
        }


def _seed_shared_active_owner(client: TestClient, source_anchor: Path, name: str = "shared.txt") -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    st = source_anchor.stat(follow_symlinks=False)
    payload_hash = hashlib.sha256(source_anchor.read_bytes()).hexdigest()

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(trash / f"pending-{name}"),
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
        session.add(entry)
        session.flush()

        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True, exist_ok=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
        os.link(source_anchor, anchor)
        os.link(source_anchor, captured)
        os.link(source_anchor, public_view)
        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        session.commit()
        return entry.id


def test_bulk_purge_preview_builds_read_only_owned_topology_manifest(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    entry_id, paths = _seed_active_entry(client)
    before = {role: path.stat(follow_symlinks=False) for role, path in paths.items()}

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "purge"
    assert body["entry_ids"] == [entry_id]
    assert body["eligible_count"] == 1
    assert body["blocked_count"] == 0

    item = body["items"][0]
    assert item["entry_id"] == entry_id
    assert item["eligible"] is True
    assert item["reason"] is None
    manifest = item["purge_topology_manifest"]
    assert manifest["selected_entry_id"] == entry_id
    assert manifest["blockers"] == []
    assert manifest["historical_conflict_entry_ids"] == []
    assert manifest["aliases"] == [
        {"role": "authoritative_anchor", "owner_entry_id": entry_id, "path": str(paths["anchor"])},
        {"role": "captured_source", "owner_entry_id": entry_id, "path": str(paths["captured_source"])},
        {"role": "public_view", "owner_entry_id": entry_id, "path": str(paths["public_view"])},
    ]

    for role, path in paths.items():
        assert path.exists(), role
        after = path.stat(follow_symlinks=False)
        assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
            before[role].st_dev,
            before[role].st_ino,
            before[role].st_size,
            before[role].st_mtime_ns,
        )


def test_bulk_purge_preview_blocks_same_payload_owned_by_another_active_entry(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    selected_id, selected_paths = _seed_active_entry(client, "selected.txt")
    other_id = _seed_shared_active_owner(client, selected_paths["anchor"], "other-active.txt")

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [selected_id]},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_count"] == 0
    assert body["blocked_count"] == 1
    item = body["items"][0]
    assert item["eligible"] is False
    assert item["reason"] == "SHARED_ACTIVE_PAYLOAD"
    manifest = item["purge_topology_manifest"]
    assert manifest["blocking_owner_entry_ids"] == [other_id]
    assert manifest["historical_conflict_entry_ids"] == []
