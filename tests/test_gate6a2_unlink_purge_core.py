from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _entry(
    entry_id: int,
    original: Path,
    public_view: Path,
    anchor: Path,
    *,
    generation: int = 1,
):
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


def test_unlink_manifest_does_not_widen_authority_to_same_inode_other_entry(
    tmp_path: Path,
) -> None:
    try:
        from app.quarantine.unlink_purge import build_unlink_manifest
    except ImportError as exc:
        pytest.fail(f"Gate6-A2 unlink manifest is not implemented yet: {exc}")

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"

    attempt_a = trash / ".tx" / "entry-1" / "attempt-1"
    attempt_a.mkdir(parents=True)
    anchor_a = attempt_a / "anchor"
    captured_a = attempt_a / "captured_source"
    public_a = trash / "a.q-1.bin"
    original_a = data / "a.bin"

    anchor_a.write_bytes(b"gate6a2-cross-entry-same-inode")
    os.link(anchor_a, captured_a)
    os.link(anchor_a, public_a)
    entry_a = _entry(1, original_a, public_a, anchor_a)

    attempt_b = trash / ".tx" / "entry-2" / "attempt-1"
    attempt_b.mkdir(parents=True)
    anchor_b = attempt_b / "anchor"
    captured_b = attempt_b / "captured_source"
    public_b = trash / "b.q-2.bin"
    original_b = data / "b.bin"

    os.link(anchor_a, anchor_b)
    os.link(anchor_a, captured_b)
    os.link(anchor_a, public_b)
    entry_b = _entry(2, original_b, public_b, anchor_b)

    assert (entry_a.device, entry_a.inode) == (entry_b.device, entry_b.inode)

    manifest = build_unlink_manifest(entry_a, trash)

    owned_role_paths = [
        (item["role"], item["path"])
        for item in manifest["owned_paths"]
    ]
    assert owned_role_paths == [
        ("authoritative_anchor", str(anchor_a)),
        ("captured_source", str(captured_a)),
        ("public_view", str(public_a)),
    ]

    forbidden_other_entry_paths = {
        str(anchor_b),
        str(captured_b),
        str(public_b),
    }
    assert forbidden_other_entry_paths.isdisjoint(
        {item["path"] for item in manifest["owned_paths"]}
    )
