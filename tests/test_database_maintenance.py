from __future__ import annotations

from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3

import pytest

from app.db import create_engine_and_session


def _database_with_free_pages(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE work_jobs (status TEXT)")
        db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, payload BLOB)")
        db.executemany("INSERT INTO sample (payload) VALUES (zeroblob(?))", [(8192,)] * 40)
        db.execute("DELETE FROM sample WHERE id != 1")
        db.commit()


def test_application_connections_limit_retained_wal(tmp_path):
    engine, _ = create_engine_and_session(tmp_path / "app.db")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_size_limit").scalar_one() == 64 * 1024 * 1024


def test_new_application_database_enables_incremental_vacuum(tmp_path):
    engine, _ = create_engine_and_session(tmp_path / "app.db")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        assert connection.exec_driver_sql("PRAGMA auto_vacuum").scalar_one() == 2
    engine.dispose()


def test_offline_compaction_verifies_backup_and_preserves_records(tmp_path):
    from app.maintenance.database import compact_database, inspect_database

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    before = inspect_database(db_path)
    assert before["reusable_bytes"] >= 39 * 8192
    result = compact_database(db_path, tmp_path / "backups")

    assert result["after"]["database_bytes"] < before["database_bytes"]
    assert result["after"]["wal_bytes"] == 0
    assert result["temporary_backup_removed"] is True
    assert not list((tmp_path / "backups").iterdir())
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("SELECT id, length(payload) FROM sample").fetchall() == [(1, 8192)]
        assert db.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]


def test_failed_integrity_verification_keeps_the_verified_backup(tmp_path, monkeypatch):
    from app.maintenance import database

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)

    def fail_validation(_db):
        raise database.MaintenanceConflict("test validation failure")

    monkeypatch.setattr(database, "_verify_integrity", fail_validation, raising=False)
    with pytest.raises(database.MaintenanceConflict, match="备份"):
        database.compact_database(db_path, tmp_path / "backups")
    backup, = (tmp_path / "backups").glob("*.db")
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("SELECT id, length(payload) FROM sample").fetchall() == [(1, 8192)]


def test_verified_temporary_backup_removal_can_be_retried(tmp_path, monkeypatch):
    from app.maintenance.database import compact_database, remove_verified_maintenance_backups

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    existing = backups / "existing-backup.db"
    existing.write_bytes(b"keep this copy")
    original_unlink = Path.unlink

    def deny_verified_copy(path, *args, **kwargs):
        if path.name.startswith(".nfc-verified-"):
            raise PermissionError("temporary cleanup error")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", deny_verified_copy)
        result = compact_database(db_path, backups)
    assert result["temporary_backup_removed"] is False
    assert Path(result["temporary_backup_path"]).is_file()
    remove_verified_maintenance_backups(backups)
    assert list(backups.iterdir()) == [existing]


def test_idle_maintenance_upgrades_a_legacy_database_then_reclaims_in_bounded_batches(tmp_path):
    from app.maintenance.database import reclaim_idle_database_space

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    with closing(sqlite3.connect(db_path)) as reader:
        reader.execute("BEGIN")
        assert reader.execute("SELECT id FROM sample").fetchall() == [(1,)]
        assert reclaim_idle_database_space(db_path, min_bytes=1)
        assert reader.execute("SELECT id FROM sample").fetchall() == [(1,)]
    assert not (tmp_path / "backups").exists()

    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        db.executemany("INSERT INTO sample (payload) VALUES (zeroblob(?))", [(8192,)] * 20)
        db.execute("DELETE FROM sample WHERE id > 1")
        db.commit()
        free_before = db.execute("PRAGMA freelist_count").fetchone()[0]
        db_size_before = db.execute("PRAGMA page_count").fetchone()[0]
        assert free_before > 3
        assert reclaim_idle_database_space(db_path, min_bytes=1, max_pages=3)
        assert db.execute("PRAGMA freelist_count").fetchone() == (free_before - 3,)
        assert db.execute("PRAGMA page_count").fetchone()[0] < db_size_before
        assert db.execute("SELECT id, length(payload) FROM sample").fetchall() == [(1, 8192)]


def test_idle_maintenance_skips_when_a_job_is_queued(tmp_path):
    from app.maintenance.database import reclaim_idle_database_space

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("INSERT INTO work_jobs VALUES ('queued')")
        db.commit()
    assert not reclaim_idle_database_space(db_path, min_bytes=1)
    assert not (tmp_path / "backups").exists()


def test_compaction_refuses_while_a_database_client_is_connected(tmp_path):
    from app.maintenance.database import MaintenanceConflict, compact_database

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    with closing(sqlite3.connect(db_path)) as reader:
        reader.execute("SELECT COUNT(*) FROM sample").fetchone()
        with pytest.raises(MaintenanceConflict):
            compact_database(db_path, tmp_path / "backups", timeout=0.01)
    assert not (tmp_path / "backups").exists()


def test_compaction_refuses_when_work_has_not_reached_a_terminal_state(tmp_path):
    from app.maintenance.database import MaintenanceConflict, compact_database

    db_path = tmp_path / "app.db"
    _database_with_free_pages(db_path)
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("INSERT INTO work_jobs VALUES ('cancel_requested')")
        db.commit()
    with pytest.raises(MaintenanceConflict):
        compact_database(db_path, tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_history_file_is_reusable_and_refuses_a_corrupted_existing_copy(tmp_path):
    from app.maintenance.archive_files import write_history_archive

    rows = [{"id": "9007199254740993", "value": "历史"}]
    path = write_history_archive(tmp_path / "history", "test-records", rows)
    assert write_history_archive(tmp_path / "history", "test-records", rows) == path
    assert json.loads(gzip.decompress(path.read_bytes()))["rows"] == rows
    assert path.stat().st_mode & 0o777 == 0o640
    assert path.parent.stat().st_mode & 0o777 == 0o770

    path.write_bytes(b"invalid gzip")
    with pytest.raises(OSError):
        write_history_archive(tmp_path / "history", "test-records", rows)
    assert path.read_bytes() == b"invalid gzip"


def test_database_maintenance_is_an_admin_preview(tmp_path):
    from fastapi.testclient import TestClient

    from app.auth.password import hash_password
    from app.config import Settings
    from app.main import create_app
    from app.models import User

    settings = Settings(
        config_dir=tmp_path / "config",
        data_mount=tmp_path / "data",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)
    with app.state.service.SessionLocal.begin() as session:
        session.add(User(username="viewer", password_hash=hash_password("ViewerPassword123!"), role="user"))

    endpoint = "/api/database-maintenance"
    origin = {"Origin": "http://testserver"}
    with TestClient(app) as client:
        assert client.get(endpoint).status_code == 401
        assert client.post(
            "/api/auth/login", json={"username": "viewer", "password": "ViewerPassword123!"}, headers=origin,
        ).status_code == 200
        assert client.get(endpoint).status_code == 403
        assert client.post(endpoint + "/archive", json={"kind": "operation_journal"}, headers=origin).status_code == 403
    with TestClient(app) as admin:
        assert admin.post(
            "/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"}, headers=origin,
        ).status_code == 200
        preview = admin.get(endpoint)
        assert preview.status_code == 200, preview.text
        assert preview.json()["database"]["database_bytes"] > 0
        assert preview.json()["task_events"] == {"jobs": 0, "rows": 0}
        assert preview.json()["operation_journal"] == {"rows": 0}
        assert admin.post(endpoint + "/archive", json={"kind": "task_events"}).status_code == 403
        apply = admin.post(endpoint + "/archive", json={"kind": "task_events"}, headers=origin)
        assert apply.status_code == 200, apply.text
        assert apply.json() == {"rows": 0, "files": []}
    assert not (settings.config_dir / "history-archives").exists()


def test_opt_in_worker_archives_only_expired_history(tmp_path):
    from datetime import timedelta
    from threading import Event, Thread
    import time

    from sqlalchemy import select

    from app.config import Settings
    from app.models import OperationJournal, utcnow
    from app.service import FileCenterService
    from app.worker import worker_loop

    data = tmp_path / "data"
    data.mkdir()
    settings = Settings(
        config_dir=tmp_path / "config", data_mount=data, allowed_roots_raw=str(data),
        quarantine_root=data / ".trash", history_archive_auto_enabled=True, operation_journal_retention_days=5,
    )
    service = FileCenterService(settings)
    with service.SessionLocal.begin() as session:
        session.add_all([
            OperationJournal(operation="move", created_at=utcnow() - timedelta(days=6)),
            OperationJournal(operation="rename", created_at=utcnow() - timedelta(days=4)),
        ])

    stop = Event()
    worker = Thread(target=worker_loop, args=(settings,), kwargs={"stop_event": stop, "poll_seconds": 0.02})
    worker.start()
    deadline = time.monotonic() + 5
    try:
        while True:
            with service.SessionLocal() as session:
                operations = list(session.scalars(select(OperationJournal.operation)))
            if operations == ["rename"] or time.monotonic() >= deadline:
                break
            stop.wait(0.02)
    finally:
        stop.set()
        worker.join(5)
    assert not worker.is_alive()
    assert operations == ["rename"]
    assert len(list(settings.history_archives_dir.glob("operation-journal-*.json.gz"))) == 1


def test_worker_reclaims_free_pages_without_enabling_optional_archives(tmp_path):
    from threading import Event, Thread
    import time

    from app.config import Settings
    from app.models import utcnow
    from app.service import FileCenterService
    from app.worker import worker_loop
    from tests.test_organizer_log_purge import _pair

    data = tmp_path / "data"
    data.mkdir()
    settings = Settings(config_dir=tmp_path / "config", data_mount=data, allowed_roots_raw=str(data))
    service = FileCenterService(settings)
    _, batch_id = _pair(service.SessionLocal, utcnow())
    service.engine.dispose()
    with closing(sqlite3.connect(settings.database_path)) as db:
        db.execute("CREATE TABLE disposable (id INTEGER PRIMARY KEY, payload BLOB)")
        db.executemany("INSERT INTO disposable(payload) VALUES(zeroblob(262144))", [()] * 48)
        db.execute("DELETE FROM disposable WHERE id > 1")
        db.commit()
        free_before = db.execute("PRAGMA freelist_count").fetchone()[0]
    assert free_before > 2048

    stop = Event()
    worker = Thread(target=worker_loop, args=(settings,), kwargs={"stop_event": stop, "poll_seconds": 0.02})
    worker.start()
    deadline = time.monotonic() + 5
    try:
        with closing(sqlite3.connect(settings.database_path)) as db:
            while True:
                remaining = db.execute("PRAGMA freelist_count").fetchone()[0]
                log_count = db.execute(
                    "SELECT count(*) FROM task_events WHERE job_id = ?", (batch_id,),
                ).fetchone()[0]
                if (free_before - remaining >= 2048 and log_count == 0) or time.monotonic() >= deadline:
                    break
                stop.wait(0.02)
            assert db.execute("SELECT id, length(payload) FROM disposable").fetchall() == [(1, 262144)]
    finally:
        stop.set()
        worker.join(5)
    assert not worker.is_alive()
    assert free_before - remaining >= 2048
    assert log_count == 0
    assert not settings.history_archives_dir.exists()
