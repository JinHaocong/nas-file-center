import gzip
import json
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db import create_engine_and_session
from app.models import Base, OperationJournal, QuarantineEntry, User
from app.quarantine import unlink_purge as purge
from test_gate6a2_unlink_purge_recovery import _setup_recovery_entry


def test_archive_only_expired_detached_whitelist_and_keep_rowid_watermark(tmp_path):
    from app.maintenance.journal import archive_operation_journal, preview_operation_journal_archive

    engine, factory = create_engine_and_session(tmp_path / "db")
    Base.metadata.create_all(engine)
    cutoff = datetime(2025, 1, 2)
    archive = tmp_path / "history"
    with factory.begin() as session:
        for operation in ("move", "rename", "touch", "quarantine", "rmdir_empty",
                          "unknown", "media_corrupt_unlink_delete"):
            session.add(OperationJournal(operation=operation, created_at=cutoff - timedelta(days=1)))
        session.add(OperationJournal(operation="move", created_at=cutoff))
        session.add(OperationJournal(operation="touch", created_at=cutoff - timedelta(days=1)))
    with factory.begin() as session:
        user = User(id=9007199254740993, username="archiver", password_hash="test", role="admin")
        session.add(user)
        session.flush()
        session.get(OperationJournal, 1).user_id = user.id
    assert preview_operation_journal_archive(factory, cutoff) == {"rows": 5}
    assert not archive.exists()
    with pytest.raises(RuntimeError, match="lease"):
        archive_operation_journal(factory, archive, cutoff, fence=lambda _: (_ for _ in ()).throw(RuntimeError("lease")))
    assert not archive.exists()
    result = archive_operation_journal(factory, archive, cutoff)
    assert result["rows"] == 5
    with gzip.open(result["files"][0], "rt") as gz:
        records = json.load(gz)["rows"]
    assert [row["id"] for row in records] == ["1", "2", "3", "4", "5"]
    assert records[0]["user_id"] == "9007199254740993"
    assert records[0]["plan_item_id"] is None
    assert isinstance(records[0]["sequence"], int)
    assert set(records[0]) == set(OperationJournal.__table__.columns.keys())
    assert archive_operation_journal(factory, archive, cutoff) == {"rows": 0, "files": []}
    with factory.begin() as session:
        row = OperationJournal(operation="move")
        session.add(row)
        session.flush()
        assert row.id == 10
    assert preview_operation_journal_archive(factory, cutoff) == {"rows": 1}


def test_completed_unlink_epoch_survives_archive_and_entry_id_reuse(tmp_path):
    from app.maintenance.journal import archive_operation_journal, preview_operation_journal_archive

    factory, trash, anchor, captured, public, survivor, original_content = _setup_recovery_entry(tmp_path)
    with factory() as session:
        manifest = purge.build_unlink_manifest(session.get(QuarantineEntry, 1), trash)
    purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=manifest)
    cutoff = datetime.now() + timedelta(days=2)
    with factory.begin() as session:
        # A legacy intent without explicit generation inherits its authority's generation.
        intent = session.get(OperationJournal, 2)
        payload = json.loads(intent.before_json)
        del payload["active_attempt_generation"]
        intent.before_json = json.dumps(payload)
        session.add(OperationJournal(operation="unknown"))
        session.execute(text("DROP TABLE IF EXISTS quarantine_unlink_evidence"))
    def snapshot():
        with factory() as session:
            return [(row.id, row.before_json, row.after_json) for row, _ in
                    purge._journal_records_for_entry(session, 1, attempt_generation=1)]
    original = snapshot()
    assert len(original) == 5
    assert preview_operation_journal_archive(factory, cutoff) == {"rows": 5}
    archive = tmp_path / "archive"
    archive.write_text("unwritable directory")
    with pytest.raises(OSError):
        archive_operation_journal(factory, archive, cutoff)
    assert snapshot() == original
    archive.unlink()
    assert archive_operation_journal(factory, archive, cutoff)["rows"] == 5
    assert snapshot() == original
    with factory.begin() as session:
        assert list(session.scalars(select(OperationJournal.id))) == [6]
        session.delete(session.get(QuarantineEntry, 1))

    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"new payload for reused entry")
    os.link(anchor, public)
    os.link(anchor, captured)
    stat = anchor.stat()
    with factory.begin() as session:
        entry = QuarantineEntry(
            original_path=str(trash.parent / "new.bin"), quarantine_path=str(public),
            state="active", tx_phase="active", authoritative_anchor_path=str(anchor),
            active_attempt_generation=1, device=stat.st_dev, inode=stat.st_ino,
            mtime_ns=stat.st_mtime_ns, size=stat.st_size,
        )
        session.add(entry)
        session.flush()
        assert entry.id == 1
        new_manifest = purge.build_unlink_manifest(entry, trash)
    result = purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=new_manifest)
    assert result["removed_count"] == 3
    assert survivor.read_bytes() == original_content
    assert [r[0] for r in snapshot()] == [7, 8, 9, 10, 11]
    assert preview_operation_journal_archive(factory, cutoff) == {"rows": 0}


@pytest.mark.parametrize("problem", ["purging", "unconfirmed", "truncated", "wrong-generation", "duplicate-terminal", "numeric-alias-terminal", "oversized-id", "unknown-empty-manifest"])
def test_uncertain_unlink_evidence_remains_hot(tmp_path, problem):
    from app.maintenance.journal import archive_operation_journal, preview_operation_journal_archive

    factory, trash, *_ = _setup_recovery_entry(tmp_path)
    with factory() as session:
        manifest = purge.build_unlink_manifest(session.get(QuarantineEntry, 1), trash)
    purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=manifest)
    with factory.begin() as session:
        if problem == "purging":
            session.get(QuarantineEntry, 1).tx_phase = "purging"
        elif problem == "unconfirmed":
            session.get(OperationJournal, 2).after_json = "{}"
        elif problem == "truncated":
            session.delete(session.get(OperationJournal, 1))
        elif problem == "oversized-id":
            for row in session.scalars(select(OperationJournal)):
                for field in ("before_json", "after_json"):
                    doc = json.loads(getattr(row, field))
                    if "entry_id" in doc:
                        doc["entry_id"] = 1 << 64
                    if "manifest" in doc:
                        doc["manifest"]["selected_entry_id"] = 1 << 64
                    setattr(row, field, json.dumps(doc))
        elif problem == "numeric-alias-terminal":
            row = session.get(OperationJournal, 5)
            doc = json.loads(row.before_json)
            doc["entry_id"] = True
            session.add(OperationJournal(operation=purge.OPERATION_ID, before_json=json.dumps(doc), after_json=row.after_json))
        elif problem == "duplicate-terminal":
            row = session.get(OperationJournal, 5)
            session.add(OperationJournal(operation=purge.OPERATION_ID, before_json=row.before_json, after_json=row.after_json))
        elif problem == "wrong-generation":
            row = session.get(OperationJournal, 5)
            row.after_json = row.after_json.replace('"active_attempt_generation":1', '"active_attempt_generation":2')
        else:
            row = session.get(OperationJournal, 1)
            payload = json.loads(row.before_json)
            payload["manifest"]["owned_paths"] = []
            row.before_json = json.dumps(payload)
            session.execute(text("DELETE FROM operation_journal WHERE id IN (2,3,4)"))
        session.add(OperationJournal(operation="unknown"))
    cutoff = datetime.now() + timedelta(days=2)
    archive = tmp_path / "archives"
    assert preview_operation_journal_archive(factory, cutoff) == {"rows": 0}
    assert archive_operation_journal(factory, archive, cutoff) == {"rows": 0, "files": []}
    assert not archive.exists()


def test_archive_is_bounded_preserves_each_live_reference_and_reuses_file_on_rollback(tmp_path):
    from app.maintenance.journal import archive_operation_journal, preview_operation_journal_archive
    from app.models import BatchPlan, BatchPlanItem, WorkJob
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    engine, factory = create_engine_and_session(tmp_path / "db")
    Base.metadata.create_all(engine)
    cutoff = datetime.now() + timedelta(days=2)
    archive = tmp_path / "archives"
    with factory.begin() as session:
        plan = BatchPlan(name="test", kind="organize", status="completed")
        job = WorkJob(kind="batch-plan-execute", status="completed")
        session.add_all([plan, job])
        session.flush()
        item = BatchPlanItem(plan_id=plan.id, sequence=1, operation="rename", source_path="/a", state="completed")
        session.add(item)
        session.flush()
        session.add_all([OperationJournal(operation="move", plan_id=plan.id),
                         OperationJournal(operation="move", plan_item_id=item.id),
                         OperationJournal(operation="move", task_id=job.id)])
        session.flush()
        session.execute(insert(OperationJournal), [{"operation": "rename"}] * 2001)
        session.add(OperationJournal(operation="unknown"))
        session.execute(text("CREATE TRIGGER stop BEFORE DELETE ON operation_journal BEGIN SELECT RAISE(ABORT,'stop'); END"))
    assert preview_operation_journal_archive(factory, cutoff)["rows"] == 2001
    with pytest.raises(IntegrityError, match="stop"):
        archive_operation_journal(factory, archive, cutoff)
    assert preview_operation_journal_archive(factory, cutoff)["rows"] == 2001
    published, = archive.glob("*.gz")
    with factory.begin() as session:
        session.execute(text("DROP TRIGGER stop"))
    first = archive_operation_journal(factory, archive, cutoff)
    assert first["files"] == [str(published)]
    assert 1000 <= first["rows"] <= 2000
    assert archive_operation_journal(factory, archive, cutoff)["rows"] == 2001 - first["rows"]
    with factory() as session:
        assert set(session.scalars(select(OperationJournal.id))) == {1, 2, 3, 2005}


def test_worker_lease_loss_after_export_preserves_originals_and_reuses_archive(tmp_path):
    from app.maintenance.journal import archive_operation_journal

    engine, factory = create_engine_and_session(tmp_path / "db")
    Base.metadata.create_all(engine)
    with factory.begin() as session:
        session.add_all([OperationJournal(operation="move"), OperationJournal(operation="unknown")])
    cutoff = datetime.now() + timedelta(days=2)
    archive = tmp_path / "archives"

    def expired_after_export(_session):
        if archive.exists():
            raise RuntimeError("worker lease expired")

    with pytest.raises(RuntimeError, match="worker lease expired"):
        archive_operation_journal(factory, archive, cutoff, fence=expired_after_export)
    with factory() as session:
        assert session.get(OperationJournal, 1).operation == "move"
    original_file, = archive.glob("*.gz")
    assert archive_operation_journal(factory, archive, cutoff) == {"rows": 1, "files": [str(original_file)]}


def test_legacy_reader_keeps_snapshot_when_first_archive_creates_evidence_table(tmp_path):
    from sqlalchemy import event
    from app.maintenance.journal import archive_operation_journal

    factory, trash, *_ = _setup_recovery_entry(tmp_path)
    with factory() as session:
        manifest = purge.build_unlink_manifest(session.get(QuarantineEntry, 1), trash)
    purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=manifest)
    with factory.begin() as session:
        session.execute(text("DROP TABLE quarantine_unlink_evidence"))
        session.add(OperationJournal(operation="unknown"))
    with factory() as reader:
        def first_archive_during_read(_conn, _cursor, statement, _parameters, _context, _many):
            if "FROM operation_journal" in statement:
                result = archive_operation_journal(factory, tmp_path / "archive", datetime.now() + timedelta(days=1))
                assert result["rows"] == 5
        event.listen(reader.connection(), "before_cursor_execute", first_archive_during_read)
        rows = purge._journal_records_for_entry(reader, 1, attempt_generation=1)
        assert [row.id for row, _ in rows] == [1, 2, 3, 4, 5]

def test_empty_archive_avoids_write_lock(tmp_path):
    from sqlalchemy import event
    from app.maintenance.journal import archive_operation_journal

    engine, factory = create_engine_and_session(tmp_path / "db")
    Base.metadata.create_all(engine)
    with factory.begin() as session:
        session.add_all([OperationJournal(operation=purge.OPERATION_ID, before_json="truncated"),
                         OperationJournal(operation="unknown")])
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _c, _s, sql, *_args: statements.append(sql))
    result = archive_operation_journal(factory, tmp_path / "archives", datetime.now() + timedelta(days=2))
    assert result == {"rows": 0, "files": []}
    assert "BEGIN IMMEDIATE" not in statements


def test_unrelated_hot_payloads_are_scanned_only_in_read_snapshot(tmp_path, monkeypatch):
    from app.maintenance import journal

    factory, trash, *_ = _setup_recovery_entry(tmp_path)
    with factory() as session:
        manifest = purge.build_unlink_manifest(session.get(QuarantineEntry, 1), trash)
    purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=manifest)
    unrelated = '{"entry_id":200,"phase":"future-format"}'
    with factory.begin() as session:
        session.add(OperationJournal(operation=purge.OPERATION_ID, before_json=unrelated))
        session.add(OperationJournal(operation="unknown"))
    write_started = False
    parse = journal._object

    def check_lock(raw):
        assert not (write_started and raw == unrelated), "full recovery scan holds the write lock"
        return parse(raw)

    def mark_write_start(_session):
        nonlocal write_started
        write_started = True

    monkeypatch.setattr(journal, "_object", check_lock)
    result = journal.archive_operation_journal(factory, tmp_path / "archives", datetime.now() + timedelta(days=2),
                                                fence=mark_write_start)
    assert result["rows"] == 5


def test_concurrent_change_between_selection_and_write_invalidates_epoch(tmp_path):
    from sqlalchemy import event
    from app.maintenance.journal import archive_operation_journal

    factory, trash, *_ = _setup_recovery_entry(tmp_path)
    with factory() as session:
        manifest = purge.build_unlink_manifest(session.get(QuarantineEntry, 1), trash)
    purge.execute_journaled_unlink_purge(factory, entry_id=1, quarantine_root=trash, frozen_manifest=manifest)
    with factory.begin() as session:
        session.add(OperationJournal(operation="unknown"))
    injected = False

    def duplicate_terminal(_conn, _cursor, sql, _parameters, _context, _many):
        nonlocal injected
        if sql == "BEGIN IMMEDIATE" and not injected:
            injected = True
            with factory.begin() as session:
                row = session.get(OperationJournal, 5)
                payload = json.loads(row.before_json)
                payload["entry_id"] = True
                session.add(OperationJournal(operation=purge.OPERATION_ID, before_json=json.dumps(payload), after_json=row.after_json))

    with factory() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", duplicate_terminal)
    result = archive_operation_journal(factory, tmp_path / "archives", datetime.now() + timedelta(days=2))
    assert injected
    assert result == {"rows": 0, "files": []}
