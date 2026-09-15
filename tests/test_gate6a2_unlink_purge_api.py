from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import IndexRoot, IndexedPath, QuarantineEntry, utcnow
from app.service import FileCenterService


def _setup_api(tmp_path: Path):
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
    service = FileCenterService(settings)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200
    return service, client, data, trash


def _seed_transactional_entry_with_indexed_survivor(
    service: FileCenterService,
    data: Path,
    trash: Path,
):
    payload = b"gate6a2-single-clear"
    indexed = data / "indexed"
    indexed.mkdir(parents=True)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "selected.bin"),
            quarantine_path=str(trash / "pending.bin"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()
        entry_id = entry.id

        attempt = trash / ".tx" / f"entry-{entry_id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"selected.q-{entry_id}.bin"
        survivor = indexed / "external-hardlink.bin"

        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        os.link(anchor, survivor)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns

        root_key = str(indexed)
        session.add(IndexRoot(root=root_key, last_indexed_at=utcnow()))
        session.add(
            IndexedPath(
                root_key=root_key,
                absolute_path=str(survivor),
                relative_path=survivor.name,
                basename=survivor.name,
                stem=survivor.stem,
                suffix=survivor.suffix,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation="gate6a2-single",
            )
        )
        session.commit()

    return entry_id, anchor, captured, public_view, survivor, payload


def test_single_clear_uses_unlink_v1_and_reports_indexed_hardlink_survivor(tmp_path: Path) -> None:
    service, client, data, trash = _setup_api(tmp_path)
    entry_id, anchor, captured, public_view, survivor, payload = (
        _seed_transactional_entry_with_indexed_survivor(service, data, trash)
    )

    survivor_before = survivor.stat(follow_symlinks=False)

    response = client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["entry_id"] == entry_id
    assert result["purged"] is True
    assert result["state"] == "purged"
    assert result["purge_semantics"] == "unlink_v1"
    assert result["removed_count"] == 3
    assert result["removed_roles"] == [
        "authoritative_anchor",
        "captured_source",
        "public_view",
    ]

    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()

    survivor_after = survivor.stat(follow_symlinks=False)
    assert survivor.read_bytes() == payload
    assert (survivor_after.st_dev, survivor_after.st_ino) == (
        survivor_before.st_dev,
        survivor_before.st_ino,
    )

    assert result["survivor_scope"] == "indexed_roots_only"
    assert result["survivor_status"] == "found"
    assert result["hardlink_survivor_count"] == 1
    assert result["hardlink_survivor_paths"] == [str(survivor)]
    assert result["independent_copy_count"] == 0
    assert result["independent_copy_paths"] == []

    rendered = str(result).lower()
    assert "secure erase" not in rendered
    assert "physical bytes definitely destroyed" not in rendered
