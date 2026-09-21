from __future__ import annotations

import hashlib
import os
import shutil
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


def test_unlink_manifest_blocks_unknown_payload_in_selected_private_namespace(
    tmp_path: Path,
) -> None:
    from app.quarantine.unlink_purge import build_unlink_manifest

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "selected.q-1.bin"
    original = data / "selected.bin"
    unexpected = attempt / "unexpected-hardlink"

    anchor.write_bytes(b"gate6a2-unknown-selected-private-payload")
    os.link(anchor, captured)
    os.link(anchor, public_view)
    os.link(anchor, unexpected)
    entry = _entry(1, original, public_view, anchor)

    manifest = build_unlink_manifest(entry, trash)

    assert "UNRECOGNIZED_PRIVATE_PATH" in manifest["blockers"]
    assert str(unexpected) not in {item["path"] for item in manifest["owned_paths"]}


def test_revalidate_unlink_manifest_blocks_aba_public_view_replacement(
    tmp_path: Path,
) -> None:
    from app.quarantine.unlink_purge import (
        build_unlink_manifest,
        revalidate_unlink_manifest,
    )

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "selected.q-1.bin"
    original = data / "selected.bin"
    payload = b"gate6a2-aba-replacement"

    anchor.write_bytes(payload)
    os.link(anchor, captured)
    os.link(anchor, public_view)
    entry = _entry(1, original, public_view, anchor)

    manifest = build_unlink_manifest(entry, trash)
    assert manifest["blockers"] == []

    os.unlink(public_view)
    public_view.write_bytes(payload)
    os.utime(
        public_view,
        ns=(entry.mtime_ns, entry.mtime_ns),
        follow_symlinks=False,
    )
    replacement_stat = public_view.stat(follow_symlinks=False)

    assert replacement_stat.st_dev == entry.device
    assert replacement_stat.st_size == entry.size
    assert replacement_stat.st_mtime_ns == entry.mtime_ns
    assert replacement_stat.st_ino != entry.inode

    result = revalidate_unlink_manifest(entry, trash, manifest)

    assert "IDENTITY_MISMATCH:public_view" in result["blockers"]
    assert public_view.read_bytes() == payload
    assert anchor.read_bytes() == payload
    assert captured.read_bytes() == payload


def test_exact_owned_paths_are_unlinked_without_inode_payload_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.quarantine.unlink_purge as unlink_purge

    try:
        unlink_owned_paths = unlink_purge._unlink_frozen_owned_paths
    except AttributeError as exc:
        pytest.fail(f"Gate6-A2 unlink mutation primitive is not implemented yet: {exc}")

    data = tmp_path / "data"
    indexed = data / "indexed"
    indexed.mkdir(parents=True)
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "selected.q-1.bin"
    original = data / "selected.bin"
    external_survivor = indexed / "external-hardlink.bin"
    unrelated = indexed / "unrelated.bin"
    payload = b"gate6a2-exact-owned-path-unlink"

    anchor.write_bytes(payload)
    os.link(anchor, captured)
    os.link(anchor, public_view)
    os.link(anchor, external_survivor)
    unrelated.write_bytes(b"unrelated-must-survive")

    entry = _entry(1, original, public_view, anchor)
    manifest = unlink_purge.build_unlink_manifest(entry, trash)
    assert manifest["blockers"] == []

    authorized_paths = {item["path"] for item in manifest["owned_paths"]}
    assert authorized_paths == {str(anchor), str(captured), str(public_view)}

    survivor_before = external_survivor.stat(follow_symlinks=False)
    survivor_bytes_before = external_survivor.read_bytes()
    unrelated_bytes_before = unrelated.read_bytes()
    real_unlink = os.unlink
    unlink_calls: list[str] = []

    def tracked_unlink(path, *args, **kwargs):
        path_obj = Path(os.fspath(path))
        dir_fd = kwargs.get("dir_fd")
        if dir_fd is not None and not path_obj.is_absolute():
            parent = Path(os.readlink(f"/proc/self/fd/{dir_fd}"))
            path_obj = parent / path_obj
        unlink_calls.append(str(path_obj))
        return real_unlink(path, *args, **kwargs)

    def forbidden_ftruncate(*args, **kwargs):
        pytest.fail("Gate6-A2 unlink purge must never call os.ftruncate")

    def forbidden_rmtree(*args, **kwargs):
        pytest.fail("Gate6-A2 unlink purge must never recursively delete")

    with monkeypatch.context() as patch:
        patch.setattr(unlink_purge.os, "unlink", tracked_unlink)
        patch.setattr(unlink_purge.os, "ftruncate", forbidden_ftruncate)
        patch.setattr(shutil, "rmtree", forbidden_rmtree)
        result = unlink_owned_paths(entry, trash, manifest)

    assert len(unlink_calls) == 3
    assert set(unlink_calls) == authorized_paths
    assert result["removed_count"] == 3
    assert set(result["removed_roles"]) == {
        "authoritative_anchor",
        "captured_source",
        "public_view",
    }

    assert not anchor.exists()
    assert not captured.exists()
    assert not public_view.exists()

    survivor_after = external_survivor.stat(follow_symlinks=False)
    assert external_survivor.read_bytes() == survivor_bytes_before == payload
    assert (survivor_after.st_dev, survivor_after.st_ino) == (
        survivor_before.st_dev,
        survivor_before.st_ino,
    )
    assert unrelated.exists()
    assert unrelated.read_bytes() == unrelated_bytes_before


def _cross_storage_orphan(entry_id: int, data: Path, trash: Path):
    return SimpleNamespace(
        id=entry_id,
        state="active",
        tx_phase="active",
        transaction_mode="cross_storage_transactional",
        original_path=str(data / f"missing-original-{entry_id}.bin"),
        quarantine_path=str(trash / f"missing-public-{entry_id}.q.bin"),
        authoritative_anchor_path=None,
        active_attempt_generation=2,
        device=101,
        inode=202,
        size=4096,
        mtime_ns=303,
        content_hash=hashlib.sha256(b"legacy-orphan").hexdigest(),
        quarantine_device=404,
        quarantine_inode=505,
        quarantine_mtime_ns=606,
    )


def test_cross_storage_missing_payload_builds_metadata_only_orphan_manifest(
    tmp_path: Path,
) -> None:
    from app.quarantine.unlink_purge import (
        build_unlink_manifest,
        revalidate_unlink_manifest,
    )

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True)
    entry = _cross_storage_orphan(41, data, trash)

    manifest = build_unlink_manifest(entry, trash)

    assert manifest["blockers"] == []
    assert manifest["metadata_only_orphan"] is True
    assert manifest["owned_paths"] == []
    assert manifest["orphan_absence"] == {
        "mode": "cross_storage_missing_payload_v1",
        "original_path": entry.original_path,
        "public_view": entry.quarantine_path,
        "tx_entry_root": str(trash / ".tx" / "entry-41"),
    }

    validation = revalidate_unlink_manifest(entry, trash, manifest)
    assert validation["valid"] is True
    assert validation["blockers"] == []


@pytest.mark.parametrize("reappearing_role", ["original_path", "public_view", "tx_entry_root"])
def test_metadata_only_orphan_revalidation_blocks_reappearing_path(
    tmp_path: Path,
    reappearing_role: str,
) -> None:
    from app.quarantine.unlink_purge import (
        build_unlink_manifest,
        revalidate_unlink_manifest,
    )

    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True)
    entry = _cross_storage_orphan(42, data, trash)
    manifest = build_unlink_manifest(entry, trash)
    assert manifest["metadata_only_orphan"] is True

    if reappearing_role == "original_path":
        path = Path(entry.original_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"replacement")
    elif reappearing_role == "public_view":
        path = Path(entry.quarantine_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"replacement")
    else:
        path = trash / ".tx" / f"entry-{entry.id}"
        path.mkdir(parents=True)

    validation = revalidate_unlink_manifest(entry, trash, manifest)
    assert validation["valid"] is False
    assert any(
        blocker.startswith(f"ORPHAN_PATH_PRESENT:{reappearing_role}")
        for blocker in validation["blockers"]
    )
