from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, IndexedPath, IndexRoot
from app.quarantine.unlink_purge import build_unlink_manifest


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


def test_indexed_scope_advisory_requires_live_lstat_for_hardlink_survivor(
    tmp_path: Path,
) -> None:
    try:
        from app.quarantine.purge_advisory import discover_unlink_purge_advisory
    except ImportError as exc:
        pytest.fail(f"Gate6-A2 purge advisory is not implemented yet: {exc}")

    data = tmp_path / "data"
    indexed_root = data / "indexed"
    indexed_root.mkdir(parents=True)
    trash = data / ".nas-file-center-trash"
    attempt = trash / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    anchor = attempt / "anchor"
    captured = attempt / "captured_source"
    public_view = trash / "selected.q-1.bin"
    original = data / "selected.bin"
    survivor = indexed_root / "survivor.bin"
    stale = indexed_root / "stale.bin"

    anchor.write_bytes(b"gate6a2-indexed-hardlink-survivor")
    os.link(anchor, captured)
    os.link(anchor, public_view)
    os.link(anchor, survivor)
    entry = _entry(1, original, public_view, anchor)
    manifest = build_unlink_manifest(entry, trash)
    assert manifest["blockers"] == []

    engine = create_engine(f"sqlite:///{tmp_path / 'advisory.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    survivor_stat = survivor.stat(follow_symlinks=False)
    with SessionLocal() as session:
        session.add(IndexRoot(root=str(indexed_root)))
        session.add_all(
            [
                IndexedPath(
                    root_key="indexed-root",
                    absolute_path=str(survivor),
                    relative_path="survivor.bin",
                    basename="survivor.bin",
                    stem="survivor",
                    suffix=".bin",
                    size=survivor_stat.st_size,
                    mtime_ns=survivor_stat.st_mtime_ns,
                    device=entry.device,
                    inode=entry.inode,
                    is_dir=False,
                    scan_generation="gate6a2-test",
                ),
                IndexedPath(
                    root_key="indexed-root",
                    absolute_path=str(stale),
                    relative_path="stale.bin",
                    basename="stale.bin",
                    stem="stale",
                    suffix=".bin",
                    size=entry.size,
                    mtime_ns=entry.mtime_ns,
                    device=entry.device,
                    inode=entry.inode,
                    is_dir=False,
                    scan_generation="gate6a2-test",
                ),
            ]
        )
        session.commit()

        advisory = discover_unlink_purge_advisory(session, entry, manifest)

    assert advisory["scope"] == "indexed_roots_only"
    assert advisory["status"] == "verified_found"
    assert advisory["hardlink_survivors"] == [str(survivor)]
    assert str(stale) in advisory["stale_candidates"]
    assert {
        item["path"] for item in manifest["owned_paths"]
    }.isdisjoint(advisory["hardlink_survivors"])
