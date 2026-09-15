from __future__ import annotations

import hashlib
import os
import re
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
    app = create_app(settings)
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def _seed_active_transactional_entry(client: TestClient, name: str = "active.txt") -> tuple[int, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / name
    payload = b"gate6a-active-payload"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
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
        return entry.id, original


def test_bulk_preview_rejects_empty_selection(tmp_path: Path) -> None:
    """Gate6-A bulk preview requires at least one explicit quarantine entry ID."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_duplicate_entry_ids(tmp_path: Path) -> None:
    """Duplicate selection is invalid; Gate6-A must never silently deduplicate it."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [7, 7],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_unsupported_action(tmp_path: Path) -> None:
    """Only the frozen restore and purge actions are valid Gate6-A bulk operations."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "archive",
            "entry_ids": [7],
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_unsupported_restore_conflict_policy(tmp_path: Path) -> None:
    """Bulk restore conflict handling is frozen to skip or deterministic rename only."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [7],
            "conflict_policy": "overwrite",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_conflict_policy_for_purge(tmp_path: Path) -> None:
    """Purge has no restore conflict policy; sending one is invalid instead of ignored."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "purge",
            "entry_ids": [7],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_custom_target_for_purge(tmp_path: Path) -> None:
    """Bulk purge must reject restore-only custom target input instead of ignoring it."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "purge",
            "entry_ids": [7],
            "custom_target": str(tmp_path / "forbidden-target.txt"),
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_marks_missing_entry_blocked(tmp_path: Path) -> None:
    """Preview remains read-only and reports a missing selected member as blocked."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [999],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "restore"
    assert body["entry_ids"] == [999]
    assert body["eligible_count"] == 0
    assert body["blocked_count"] == 1
    assert body["items"] == [
        {
            "entry_id": 999,
            "eligible": False,
            "reason": "MISSING_ENTRY",
        }
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", body["preview_digest"])


def test_bulk_preview_marks_non_active_entry_blocked(tmp_path: Path) -> None:
    """A selected quarantine row that is no longer active remains visible but blocked."""
    client = _setup_admin_client(tmp_path)
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "already-restored.txt"),
            quarantine_path=str(trash / "already-restored.q-1.txt"),
            state="restored",
            tx_phase="restored",
            active_attempt_generation=3,
            size=12,
            content_hash="a" * 64,
            mtime_ns=123456,
            device=10,
            inode=20,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_count"] == 0
    assert body["blocked_count"] == 1
    assert body["items"][0]["entry_id"] == entry_id
    assert body["items"][0]["eligible"] is False
    assert body["items"][0]["reason"] == "NON_ACTIVE_ENTRY"
    assert body["items"][0]["state"] == "restored"
    assert body["items"][0]["tx_phase"] == "restored"


def test_bulk_restore_preview_defaults_to_skip_and_freezes_original_target(tmp_path: Path) -> None:
    """An active restore Preview defaults to skip and freezes the exact original target."""
    client = _setup_admin_client(tmp_path)
    entry_id, original = _seed_active_transactional_entry(client)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_count"] == 1
    assert body["blocked_count"] == 0
    assert body["items"][0]["entry_id"] == entry_id
    assert body["items"][0]["eligible"] is True
    assert body["items"][0]["conflict_policy"] == "skip"
    assert body["items"][0]["target_path"] == str(original)
    assert re.fullmatch(r"[0-9a-f]{64}", body["preview_digest"])
