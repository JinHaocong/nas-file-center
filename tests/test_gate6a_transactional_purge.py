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


def test_purge_topology_classifier_accepts_normal_active_transactional_entry(tmp_path: Path) -> None:
    from app.quarantine.purge import build_purge_topology_manifest

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "normal.q-1.bin"
    original = data / "normal.bin"
    anchor.write_bytes(b"gate6a-purge-normal-payload")
    os.link(anchor, captured)
    os.link(anchor, public_view)

    entry = _entry(1, original, public_view, anchor)

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

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "symlink.q-1.bin"
    original = data / "symlink.bin"
    anchor.write_bytes(b"gate6a-purge-symlink-payload")
    os.link(anchor, captured)
    os.link(anchor, public_view)
    (attempt / "unexpected-link").symlink_to(anchor)

    entry = _entry(1, original, public_view, anchor)

    manifest = build_purge_topology_manifest(entry, trash, owner_lookup=lambda _: None)

    assert "SYMLINK_IN_PAYLOAD_ALIAS_SET" in manifest["blockers"]
