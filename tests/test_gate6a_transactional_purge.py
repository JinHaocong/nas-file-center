from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace


def _entry(entry_id: int, original: Path, public_view: Path, anchor: Path, generation: int = 1):
    payload = anchor.read_bytes()
    st = anchor.stat(follow_symlinks=False)
    return SimpleNamespace(
        id=entry_id,
        state="active",
        tx_phase="active",
        original_path=str(original),
        quarantine_path=str(public_view),
        authoritative_anchor_path=str(anchor),
        active_attempt_generation=generation,
        device=st.st_dev,
        inode=st.st_ino,
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        content_hash=hashlib.sha256(payload).hexdigest(),
    )


def _normal_topology(tmp_path: Path, payload: bytes = b"gate6a-purge-normal-payload"):
    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)
    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "normal.q-1.bin"
    original = data / "normal.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured)
    os.link(anchor, public_view)
    entry = _entry(1, original, public_view, anchor)
    return entry, data, trash, attempt, anchor, captured, public_view


def test_purge_topology_classifier_accepts_normal_active_transactional_entry(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, _, trash, _, anchor, captured, public_view = _normal_topology(tmp_path)

    manifest = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert manifest["blockers"] == []
    assert manifest["blocking_owner_entry_ids"] == []
    assert manifest["historical_conflict_entry_ids"] == []
    assert manifest["aliases"] == [
        {"role": "authoritative_anchor", "owner_entry_id": 1, "path": str(anchor)},
        {"role": "captured_source", "owner_entry_id": 1, "path": str(captured)},
        {"role": "public_view", "owner_entry_id": 1, "path": str(public_view)},
    ]


def test_purge_topology_classifier_blocks_symlink_in_selected_private_namespace(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, _, trash, attempt, anchor, _, _ = _normal_topology(
        tmp_path, b"gate6a-purge-symlink-payload"
    )
    (attempt / "unexpected-link").symlink_to(anchor)

    manifest = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert "SYMLINK_IN_PAYLOAD_ALIAS_SET" in manifest["blockers"]


def test_purge_topology_classifier_ignores_st_nlink_as_authority(tmp_path: Path, monkeypatch) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, _, trash, _, _, _, _ = _normal_topology(tmp_path, b"gate6a-nlink-payload")
    baseline = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)
    original_stat = Path.stat

    def fake_stat(path: Path, *args, **kwargs):
        st = original_stat(path, *args, **kwargs)
        return SimpleNamespace(
            st_mode=st.st_mode,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            st_size=st.st_size,
            st_mtime_ns=st.st_mtime_ns,
            st_mtime=st.st_mtime,
            st_nlink=999,
        )

    monkeypatch.setattr(Path, "stat", fake_stat)
    changed_nlink = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert changed_nlink == baseline


def test_purge_topology_classifier_blocks_same_payload_owned_by_active_row(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, data, trash, _, anchor, _, _ = _normal_topology(tmp_path, b"gate6a-shared-active")
    other_attempt = trash / ".tx" / "entry-2" / "attempt-1"
    other_attempt.mkdir(parents=True)
    other_anchor = other_attempt / "anchor"
    os.link(anchor, other_anchor)
    owner = _entry(2, data / "other.bin", trash / "other.q-2.bin", other_anchor)

    manifest = build_purge_topology_manifest(
        entry,
        trash,
        owner_lookup=lambda owner_id: owner if owner_id == 2 else None,
    )

    assert "SHARED_ACTIVE_PAYLOAD" in manifest["blockers"]
    assert manifest["blocking_owner_entry_ids"] == [2]


def test_purge_topology_classifier_blocks_missing_cross_entry_owner(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, _, trash, _, anchor, _, _ = _normal_topology(tmp_path, b"gate6a-missing-owner")
    other_attempt = trash / ".tx" / "entry-2" / "attempt-1"
    other_attempt.mkdir(parents=True)
    os.link(anchor, other_attempt / "anchor")

    manifest = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert "UNKNOWN_PAYLOAD_OWNER" in manifest["blockers"]


def test_purge_topology_classifier_accepts_historical_non_authoritative_conflict_candidate(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, data, trash, _, anchor, _, _ = _normal_topology(tmp_path, b"gate6a-history-candidate")
    other_attempt = trash / ".tx" / "entry-2" / "attempt-1"
    other_attempt.mkdir(parents=True)
    other_anchor = other_attempt / "anchor"
    os.link(anchor, other_anchor)
    owner = _entry(2, data / "old.bin", trash / "old.q-2.bin", other_anchor)
    owner.state = "conflict"
    owner.tx_phase = "conflict"
    owner.authoritative_anchor_path = None

    manifest = build_purge_topology_manifest(
        entry,
        trash,
        owner_lookup=lambda owner_id: owner if owner_id == 2 else None,
    )

    assert manifest["blockers"] == []
    assert manifest["historical_conflict_entry_ids"] == [2]
    assert {
        "role": "historical_conflict_candidate",
        "owner_entry_id": 2,
        "path": str(other_anchor),
    } in manifest["aliases"]


def test_purge_topology_classifier_blocks_unrecognized_same_entry_private_alias(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    entry, _, trash, attempt, anchor, _, _ = _normal_topology(tmp_path, b"gate6a-unrecognized-private")
    os.link(anchor, attempt / "unexpected-hardlink")

    manifest = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert "UNRECOGNIZED_PRIVATE_PATH" in manifest["blockers"]
