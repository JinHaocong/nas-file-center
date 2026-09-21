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


def _seed_transactional_entry(
    service: FileCenterService,
    data: Path,
    trash: Path,
    *,
    label: str,
    add_unknown_private_path: bool = False,
) -> int:
    payload = f"gate6a2-{label}".encode()
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / f"{label}.bin"),
            quarantine_path=str(trash / f"pending-{label}.bin"),
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
        public_view = trash / f"{label}.q-{entry_id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        if add_unknown_private_path:
            os.link(anchor, attempt / "unexpected-hardlink")
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns
        session.commit()
    return entry_id


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


def test_bulk_purge_preview_uses_per_entry_unlink_eligibility_and_keeps_survivors_informational(
    tmp_path: Path,
) -> None:
    service, client, data, trash = _setup_api(tmp_path)
    eligible_id, _, _, _, survivor, _ = _seed_transactional_entry_with_indexed_survivor(
        service, data, trash
    )
    blocked_id = _seed_transactional_entry(
        service,
        data,
        trash,
        label="blocked",
        add_unknown_private_path=True,
    )
    unselected_id = _seed_transactional_entry(
        service,
        data,
        trash,
        label="unselected",
    )

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "purge",
            "entry_ids": [blocked_id, eligible_id],
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result["entry_ids"]) == {eligible_id, blocked_id}
    assert unselected_id not in result["entry_ids"]
    assert result["eligible_count"] == 1
    assert result["blocked_count"] == 1

    items = {int(item["entry_id"]): item for item in result["items"]}
    assert set(items) == {eligible_id, blocked_id}

    eligible = items[eligible_id]
    assert eligible["eligible"] is True
    assert eligible["purge_semantics"] == "unlink_v1"
    assert eligible["mutation_blockers"] == []
    assert eligible["survivor_scope"] == "indexed_roots_only"
    assert eligible["survivor_status"] == "found"
    assert eligible["hardlink_survivor_paths"] == [str(survivor)]

    blocked = items[blocked_id]
    assert blocked["eligible"] is False
    assert blocked["reason"] == "UNLINK_MANIFEST_BLOCKED"
    assert "UNRECOGNIZED_PRIVATE_PATH" in blocked["mutation_blockers"]


def test_bulk_purge_preview_digest_excludes_advisory_drift_but_binds_owned_authority(
    tmp_path: Path,
) -> None:
    service, client, data, trash = _setup_api(tmp_path)
    entry_id, _, _, public_view, survivor, payload = (
        _seed_transactional_entry_with_indexed_survivor(service, data, trash)
    )

    def preview() -> dict:
        response = client.post(
            "/api/quarantine/bulk-preview",
            json={"action": "purge", "entry_ids": [entry_id]},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = preview()
    first_item = first["items"][0]
    assert first_item["eligible"] is True
    assert first_item["survivor_status"] == "found"
    assert first_item["hardlink_survivor_paths"] == [str(survivor)]
    first_digest = first["preview_digest"]

    survivor.unlink()
    second = preview()
    second_item = second["items"][0]
    assert second_item["eligible"] is True
    assert second_item["survivor_status"] == "incomplete"
    assert second_item["hardlink_survivor_paths"] == []
    assert second["preview_digest"] == first_digest

    public_view.unlink()
    public_view.write_bytes(payload)
    third = preview()
    third_item = third["items"][0]
    assert third_item["eligible"] is False
    assert "IDENTITY_MISMATCH:public_view" in third_item["mutation_blockers"]
    assert third["preview_digest"] != first_digest


def _seed_cross_storage_missing_payload_entry(
    service: FileCenterService,
    data: Path,
    trash: Path,
) -> int:
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "legacy-missing-source.bin"),
            quarantine_path=str(trash / "legacy-missing-public.q.bin"),
            state="active",
            tx_phase="active",
            transaction_mode="cross_storage_transactional",
            active_attempt_generation=2,
            size=8192,
            content_hash=hashlib.sha256(b"legacy-missing-payload").hexdigest(),
            mtime_ns=1003,
            device=1001,
            inode=1002,
            quarantine_device=2001,
            quarantine_inode=2002,
            quarantine_mtime_ns=2003,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        return int(entry.id)


def test_bulk_purge_preview_and_draft_accept_legacy_cross_storage_missing_payload(
    tmp_path: Path,
) -> None:
    service, client, data, trash = _setup_api(tmp_path)
    entry_id = _seed_cross_storage_missing_payload_entry(service, data, trash)

    preview_response = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["eligible_count"] == 1
    assert preview["blocked_count"] == 0
    item = preview["items"][0]
    assert item["entry_id"] == entry_id
    assert item["eligible"] is True
    assert item["mutation_blockers"] == []

    plan_response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "expected_preview_digest": preview["preview_digest"],
            "confirmation": "DELETE",
        },
        headers={"Origin": "http://testserver"},
    )
    assert plan_response.status_code == 200, plan_response.text
    assert plan_response.json()["kind"] == "quarantine-bulk-purge"


def test_journaled_purge_terminalizes_legacy_cross_storage_missing_payload_without_unlink(
    tmp_path: Path,
) -> None:
    from app.quarantine.unlink_purge import (
        build_unlink_manifest,
        execute_journaled_unlink_purge,
    )

    service, _client, data, trash = _setup_api(tmp_path)
    entry_id = _seed_cross_storage_missing_payload_entry(service, data, trash)

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        manifest = build_unlink_manifest(entry, trash)
        assert manifest["metadata_only_orphan"] is True
        assert manifest["owned_paths"] == []

    result = execute_journaled_unlink_purge(
        service.SessionLocal,
        entry_id=entry_id,
        quarantine_root=trash,
        frozen_manifest=manifest,
        worker_id=None,
    )

    assert result["removed_count"] == 0
    assert result["removed_roles"] == []
    assert not Path(data / "legacy-missing-source.bin").exists()
    assert not Path(trash / "legacy-missing-public.q.bin").exists()
    assert not (trash / ".tx" / f"entry-{entry_id}").exists()

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "purged"
        assert entry.tx_phase == "purged"
