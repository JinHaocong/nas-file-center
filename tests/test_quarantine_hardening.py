from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.indexing.indexer import iter_root
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DataLifecyclePolicy,
    QuarantineEntry,
    utcnow,
)
from app.organizers.engine import collect_tree_stats_bottom_up
from app.quarantine.paths import (
    build_quarantine_target_path,
    get_containing_root_slot,
    safe_quarantine_hash,
)
from app.scanners.fclones import build_group_command
from app.service import FileCenterService


def _setup_service(tmp_path: Path) -> tuple[FileCenterService, Path, Path]:
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
    return service, data, trash


def test_purge_symlink_does_not_delete_referent(tmp_path: Path):
    """Purge must refuse when quarantine_path is a symlink, and must never delete the referent."""
    service, data, trash = _setup_service(tmp_path)
    victim = trash / "victim.txt"
    victim.write_text("DO NOT DELETE", encoding="utf-8")

    symlink_entry = trash / "link-entry.txt"
    symlink_entry.symlink_to(victim)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "original.txt"),
            quarantine_path=str(symlink_entry),
            state="active",
            size=len(b"DO NOT DELETE"),
            content_hash="somehash",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Attempting to purge a symlink entry must be rejected
    with pytest.raises((ValueError, Exception)):
        service.purge_quarantine_entry(entry_id, confirmation="DELETE", is_admin=True)

    # Assert referent and link still exist
    assert victim.exists(), "victim.txt must still exist!"
    assert victim.read_text(encoding="utf-8") == "DO NOT DELETE"
    assert symlink_entry.is_symlink() or symlink_entry.exists()

    with service.SessionLocal() as session:
        refreshed = session.get(QuarantineEntry, entry_id)
        assert refreshed.state != "purged"
        assert refreshed.purged_at is None


def test_purge_missing_target_fails_closed(tmp_path: Path):
    """Purge on non-existent quarantine target must fail closed and never report fake purged."""
    service, data, trash = _setup_service(tmp_path)
    missing_file = trash / "does-not-exist.txt"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "missing.txt"),
            quarantine_path=str(missing_file),
            state="active",
            size=10,
            content_hash="abc",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    with pytest.raises(Exception) as exc_info:
        service.purge_quarantine_entry(entry_id, confirmation="DELETE", is_admin=True)

    with service.SessionLocal() as session:
        refreshed = session.get(QuarantineEntry, entry_id)
        assert refreshed.state != "purged", "Missing target must never transition to purged"
        assert refreshed.purged_at is None


def test_directory_quarantine(tmp_path: Path):
    """Directories can be quarantined without safe_quarantine_hash failing on IsADirectoryError."""
    service, data, trash = _setup_service(tmp_path)
    folder = data / "test_folder"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.txt").write_text("file A", encoding="utf-8")
    child = folder / "child"
    child.mkdir(parents=True, exist_ok=True)
    (child / "b.txt").write_text("file B", encoding="utf-8")

    plan = service.create_plan(
        name="Quarantine Directory Plan",
        kind="organize",
        items=[
            {
                "source": str(folder),
                "operation": "quarantine",
            }
        ],
    )
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        p.status = "ready"
        session.commit()

    result = service.execute_plan(plan.id)
    assert result["status"] == "completed"
    assert not folder.exists()

    with service.SessionLocal() as session:
        entries = list(session.scalars(select(QuarantineEntry)).all())
        assert len(entries) == 1
        q_entry = entries[0]
        assert q_entry.state == "active"
        assert q_entry.content_hash is None
        tgt = Path(q_entry.quarantine_path)
        assert tgt.is_dir()
        assert (tgt / "a.txt").read_text(encoding="utf-8") == "file A"
        assert (tgt / "child" / "b.txt").read_text(encoding="utf-8") == "file B"


def test_directory_reconciliation(tmp_path: Path):
    """Crash state where source dir is missing and quarantine dir exists reconciles to active with content_hash=None."""
    service, data, trash = _setup_service(tmp_path)
    target_dir = trash / "plan-1" / "root-0" / "somedir.q-999"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "sub.txt").write_text("sub content", encoding="utf-8")

    source_dir = data / "somedir"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=999,
            original_path=str(source_dir),
            quarantine_path=str(target_dir),
            state="preparing",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    reconciled = service.reconcile_quarantine_entry(999)
    assert reconciled["state"] == "active"
    assert reconciled["content_hash"] is None


def test_directory_restore(tmp_path: Path):
    """Restoring a quarantined directory renames the entire tree back to original path."""
    service, data, trash = _setup_service(tmp_path)
    orig_dir = data / "my_docs"
    q_dir = trash / "plan-1" / "root-0" / "my_docs.q-101"
    q_dir.mkdir(parents=True, exist_ok=True)
    (q_dir / "doc1.txt").write_text("hello 1", encoding="utf-8")
    sub = q_dir / "sub"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "doc2.txt").write_text("hello 2", encoding="utf-8")

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=101,
            original_path=str(orig_dir),
            quarantine_path=str(q_dir),
            state="active",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    res = service.restore_quarantine_entry(101, conflict_strategy="skip")
    assert res["status"] == "restored"
    assert orig_dir.is_dir()
    assert (orig_dir / "doc1.txt").read_text(encoding="utf-8") == "hello 1"
    assert (orig_dir / "sub" / "doc2.txt").read_text(encoding="utf-8") == "hello 2"
    assert not q_dir.exists()


def test_directory_purge(tmp_path: Path):
    """Purging a quarantined directory removes the entire tree safely without unlink(directory) or unchecked rmtree."""
    service, data, trash = _setup_service(tmp_path)
    q_dir = trash / "plan-1" / "root-0" / "to_purge.q-102"
    q_dir.mkdir(parents=True, exist_ok=True)
    (q_dir / "subfile.txt").write_text("subfile", encoding="utf-8")
    (q_dir / "subdir").mkdir()
    (q_dir / "subdir" / "deep.txt").write_text("deep", encoding="utf-8")

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=102,
            original_path=str(data / "to_purge"),
            quarantine_path=str(q_dir),
            state="active",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    res = service.purge_quarantine_entry(102, confirmation="DELETE", is_admin=True)
    assert res["status"] == "purged"
    assert not q_dir.exists()


def test_directory_purge_does_not_follow_child_symlink(tmp_path: Path):
    """Purging a directory containing a symlink unlinks the symlink, but leaves the external victim untouched."""
    service, data, trash = _setup_service(tmp_path)
    victim = data / "innocent_victim.txt"
    victim.write_text("DO NOT TOUCH", encoding="utf-8")

    q_dir = trash / "plan-1" / "root-0" / "dir_with_link.q-103"
    q_dir.mkdir(parents=True, exist_ok=True)
    link = q_dir / "symlink_to_victim"
    link.symlink_to(victim)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=103,
            original_path=str(data / "dir_with_link"),
            quarantine_path=str(q_dir),
            state="active",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    res = service.purge_quarantine_entry(103, confirmation="DELETE", is_admin=True)
    assert res["status"] == "purged"
    assert not q_dir.exists()
    assert victim.exists(), "Victim referenced by child symlink must NOT be deleted!"
    assert victim.read_text(encoding="utf-8") == "DO NOT TOUCH"


def test_startup_reconciles_preparing(tmp_path: Path):
    """Service startup automatically reconciles preparing quarantine entries."""
    service, data, trash = _setup_service(tmp_path)
    target = trash / "plan-1" / "root-0" / "crashed.q-201.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content", encoding="utf-8")
    source = data / "crashed.txt"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=201,
            original_path=str(source),
            quarantine_path=str(target),
            state="preparing",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    # Restart service
    service2 = FileCenterService(service.settings)
    with service2.SessionLocal() as session:
        refreshed = session.get(QuarantineEntry, 201)
        assert refreshed.state == "active"


def test_startup_recovers_restoring_safely(tmp_path: Path):
    """Startup recovery for 'restoring': if target still exists -> back to active; if not -> inconsistent."""
    service, data, trash = _setup_service(tmp_path)
    tgt1 = trash / "plan-1" / "root-0" / "r1.q-202.txt"
    tgt1.parent.mkdir(parents=True, exist_ok=True)
    tgt1.write_text("c1", encoding="utf-8")

    tgt2 = trash / "plan-1" / "root-0" / "r2.q-203.txt"
    # tgt2 does not exist

    with service.SessionLocal() as session:
        e1 = QuarantineEntry(
            id=202,
            original_path=str(data / "r1.txt"),
            quarantine_path=str(tgt1),
            state="restoring",
            quarantined_at=utcnow(),
        )
        e2 = QuarantineEntry(
            id=203,
            original_path=str(data / "r2.txt"),
            quarantine_path=str(tgt2),
            state="restoring",
            quarantined_at=utcnow(),
        )
        session.add_all([e1, e2])
        session.commit()

    service2 = FileCenterService(service.settings)
    with service2.SessionLocal() as session:
        r1 = session.get(QuarantineEntry, 202)
        r2 = session.get(QuarantineEntry, 203)
        assert r1.state == "active"
        assert r2.state == "inconsistent"


def test_startup_recovers_purging_safely(tmp_path: Path):
    """Startup recovery for 'purging': if target still exists -> back to active; if target gone -> purged."""
    service, data, trash = _setup_service(tmp_path)
    tgt1 = trash / "plan-1" / "root-0" / "p1.q-204.txt"
    tgt1.parent.mkdir(parents=True, exist_ok=True)
    tgt1.write_text("p1", encoding="utf-8")

    tgt2 = trash / "plan-1" / "root-0" / "p2.q-205.txt"
    # tgt2 does not exist (was unlinked before crash)

    with service.SessionLocal() as session:
        e1 = QuarantineEntry(
            id=204,
            original_path=str(data / "p1.txt"),
            quarantine_path=str(tgt1),
            state="purging",
            quarantined_at=utcnow(),
        )
        e2 = QuarantineEntry(
            id=205,
            original_path=str(data / "p2.txt"),
            quarantine_path=str(tgt2),
            state="purging",
            quarantined_at=utcnow(),
        )
        session.add_all([e1, e2])
        session.commit()

    service2 = FileCenterService(service.settings)
    with service2.SessionLocal() as session:
        r1 = session.get(QuarantineEntry, 204)
        r2 = session.get(QuarantineEntry, 205)
        assert r1.state == "active"
        assert r2.state == "purged"
        assert r2.purged_at is not None


def test_parent_index_excludes_quarantine(tmp_path: Path):
    """Parent-root index traversal must prune the quarantine root subtree."""
    service, data, trash = _setup_service(tmp_path)
    (data / "normal.txt").write_text("normal", encoding="utf-8")
    sub_trash = trash / "plan-1" / "root-0"
    sub_trash.mkdir(parents=True, exist_ok=True)
    (sub_trash / "q.txt").write_text("trash", encoding="utf-8")

    indexed = list(iter_root(data, [data], excluded_roots=[trash]))
    indexed_paths = [e.absolute_path.as_posix() for e in indexed]

    assert (data / "normal.txt").as_posix() in indexed_paths
    for p in indexed_paths:
        assert not p.startswith(trash.as_posix()), f"Quarantine path leaked into index: {p}"


def test_parent_scan_excludes_quarantine(tmp_path: Path):
    """fclones group command must explicitly include exclude pattern for quarantine root."""
    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)

    cmd = build_group_command(
        binary="fclones",
        roots=[data],
        allowed_roots=[data],
        exclude_patterns=[f"{trash}/**"],
    )
    assert "--exclude" in cmd
    idx = cmd.index("--exclude")
    assert cmd[idx + 1] == f"{trash}/**"


def test_organizer_parent_excludes_quarantine(tmp_path: Path):
    """Organizer bottom-up tree stats must prune quarantine root subtree."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    (trash / "secret.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

    good_dir = data / "photos"
    good_dir.mkdir(parents=True, exist_ok=True)
    (good_dir / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

    stats, total_bytes, candidates = collect_tree_stats_bottom_up(
        data,
        image_extensions={".jpg"},
        video_extensions={".mp4"},
        excluded_roots=[trash],
    )
    candidate_paths = [p.as_posix() for p in candidates]
    for p in candidate_paths:
        assert not p.startswith(trash.as_posix()), f"Quarantine root entered organizer candidates: {p}"


def test_quarantine_root_symlink_rejected(tmp_path: Path):
    """build_quarantine_target_path with check_symlink=True must reject symlinked quarantine root."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    real_trash = data / "real-trash"
    real_trash.mkdir(parents=True, exist_ok=True)

    symlink_trash = data / ".nas-file-center-trash"
    symlink_trash.symlink_to(real_trash)

    src = data / "file.txt"
    src.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="symlink"):
        build_quarantine_target_path(
            source=src,
            allowed_roots=[data],
            quarantine_root=symlink_trash,
            plan_id=1,
            entry_id=1,
            check_symlink=True,
        )


def test_task_id_foreign_key(tmp_path: Path):
    """QuarantineEntry.task_id must have a foreign key referencing work_jobs.id."""
    service, data, trash = _setup_service(tmp_path)
    conn = sqlite3.connect(str(service.settings.database_path))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_list(quarantine_entries);")
    fks = cur.fetchall()
    conn.close()

    # Format of PRAGMA foreign_key_list: (id, seq, table, from, to, on_update, on_delete, match)
    fk_map = {row[3]: (row[2], row[4]) for row in fks}
    assert "task_id" in fk_map, f"task_id must have foreign key, found {fk_map}"
    assert fk_map["task_id"] == ("work_jobs", "id")
    assert "plan_item_id" in fk_map
    assert fk_map["plan_item_id"] == ("batch_plan_items", "id")


def test_restore_atomic_noreplace(tmp_path: Path):
    """Restore must never overwrite an existing destination even if created concurrently."""
    service, data, trash = _setup_service(tmp_path)
    orig_file = data / "victim_dst.txt"
    orig_file.write_text("DESTINATION CONTENT MUST SURVIVE", encoding="utf-8")

    q_file = trash / "plan-1" / "root-0" / "somefile.q-301.txt"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_file.write_text("SOURCE CONTENT TO RESTORE", encoding="utf-8")

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            id=301,
            original_path=str(orig_file),
            quarantine_path=str(q_file),
            state="active",
            quarantined_at=utcnow(),
        )
        session.add(entry)
        session.commit()

    # Even with conflict_strategy="skip", if someone creates orig_file, it must NOT overwrite
    res = service.restore_quarantine_entry(301, conflict_strategy="skip")
    assert res["status"] == "skipped"
    assert orig_file.read_text(encoding="utf-8") == "DESTINATION CONTENT MUST SURVIVE"
    assert q_file.exists()


def test_quarantine_atomic_noreplace(tmp_path: Path):
    """Quarantine must never overwrite existing quarantine target if created concurrently."""
    from app.fs_ops import rename_noreplace

    src = tmp_path / "src.txt"
    src.write_text("SRC", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    dst.write_text("EXISTING TARGET", encoding="utf-8")

    # rename_noreplace must raise FileExistsError and NOT overwrite dst
    with pytest.raises(FileExistsError):
        rename_noreplace(src, dst)

    assert dst.read_text(encoding="utf-8") == "EXISTING TARGET"
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "SRC"


def test_rename_noreplace_concurrency_race(tmp_path: Path):
    """Two concurrent threads race to rename their distinct source files to the same target."""
    import concurrent.futures
    from app.fs_ops import rename_noreplace

    src1 = tmp_path / "src1.txt"
    src1.write_text("CONTENT_1", encoding="utf-8")
    src2 = tmp_path / "src2.txt"
    src2.write_text("CONTENT_2", encoding="utf-8")
    target = tmp_path / "common_target.txt"

    def try_rename(src: Path):
        try:
            rename_noreplace(src, target)
            return True, None
        except Exception as e:
            return False, e

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_rename, src1)
        f2 = executor.submit(try_rename, src2)
        r1 = f1.result()
        r2 = f2.result()

    successes = [r for r in (r1, r2) if r[0]]
    failures = [r for r in (r1, r2) if not r[0]]

    assert len(successes) == 1, "Exactly one rename must succeed"
    assert len(failures) == 1, "Exactly one rename must fail"
    assert isinstance(failures[0][1], FileExistsError)

    # Winner's content is in target, loser's source file still exists!
    target_content = target.read_text(encoding="utf-8")
    if target_content == "CONTENT_1":
        assert not src1.exists()
        assert src2.exists()
        assert src2.read_text(encoding="utf-8") == "CONTENT_2"
    else:
        assert target_content == "CONTENT_2"
        assert not src2.exists()
        assert src1.exists()
        assert src1.read_text(encoding="utf-8") == "CONTENT_1"


