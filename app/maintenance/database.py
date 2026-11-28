from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from uuid import uuid4

from app.maintenance.archive_files import durable_file, sync_directory


WAL_RETAINED_LIMIT_BYTES = 64 * 1024 * 1024
MIN_IDLE_RECLAIM_BYTES = 8 * 1024 * 1024
MAX_IDLE_RECLAIM_PAGES = 2048
_VERIFIED_BACKUP = re.compile(r"\.nfc-verified-nas-file-center-maintenance-\d{8}T\d{6}Z-[a-f0-9]{32}\.db")


class MaintenanceConflict(RuntimeError):
    """The database is in use or unable to complete maintenance safely."""


class MaintenanceRecoveryRequired(MaintenanceConflict):
    """The verified rollback copy remains available after a failed rebuild."""


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _read_usage(db: sqlite3.Connection, database_path: Path) -> dict:
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    page_count = db.execute("PRAGMA page_count").fetchone()[0]
    free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
    active_jobs = db.execute(
        "SELECT count(*) FROM work_jobs WHERE status IN ('running', 'cancel_requested')",
    ).fetchone()[0]
    database_bytes = _size(database_path)
    wal_bytes = _size(database_path.with_name(database_path.name + "-wal"))
    return {
        "database_bytes": database_bytes,
        "wal_bytes": wal_bytes,
        "reusable_bytes": free_pages * page_size,
        "estimated_reclaimable_bytes": max(
            0, database_bytes + wal_bytes - (page_count - free_pages) * page_size,
        ),
        "wal_retained_limit_bytes": WAL_RETAINED_LIMIT_BYTES,
        "active_jobs": active_jobs,
    }


def inspect_database(database_path: Path) -> dict:
    """Sample SQLite's logical page counts and on-disk file sizes without a checkpoint."""
    uri = database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return _read_usage(db, database_path)


def _verified_backup(db: sqlite3.Connection, backups_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backups_dir / f"nas-file-center-maintenance-{timestamp}-{uuid4().hex}.db"
    with durable_file(backups_dir) as staged:
        # Back up logical contents without copying the free pages we are about to reclaim.
        db.execute("VACUUM INTO ?", (str(staged),))
        with closing(sqlite3.connect(staged.resolve().as_uri() + "?mode=ro", uri=True)) as backup:
            if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise MaintenanceConflict("数据库备份校验失败")
        with staged.open("rb") as copied:
            os.fsync(copied.fileno())
        os.link(staged, destination)
        sync_directory(backups_dir)
    return destination


def remove_verified_maintenance_backups(backups_dir: Path) -> None:
    """Retry only temporary copies already marked disposable after integrity verification."""
    if not backups_dir.is_dir():
        return
    removed = False
    for path in backups_dir.iterdir():
        if _VERIFIED_BACKUP.fullmatch(path.name):
            try:
                if stat.S_ISREG(path.lstat().st_mode):
                    path.unlink()
                    removed = True
            except FileNotFoundError:
                continue
    if removed:
        sync_directory(backups_dir)


def _verify_integrity(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise MaintenanceConflict("压缩后的数据库校验失败")


def _ensure_scratch_space(database_path: Path, backups_dir: Path) -> None:
    occupied = _size(database_path) + _size(database_path.with_name(database_path.name + "-wal"))
    database_dir = database_path.parent
    backup_volume = backups_dir if backups_dir.exists() else backups_dir.parent
    same_volume = database_dir.stat().st_dev == backup_volume.stat().st_dev
    if (shutil.disk_usage(database_dir).free < (3 if same_volume else 2) * occupied
            or shutil.disk_usage(backup_volume).free < occupied):
        raise MaintenanceConflict("可用空间不足，无法同时存放备份与压缩临时数据")


def _sqlite_busy(error: sqlite3.OperationalError) -> bool:
    return (error.sqlite_errorcode & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _rebuild_database(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA auto_vacuum=INCREMENTAL")
    db.execute("VACUUM")
    if db.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
        raise MaintenanceConflict("数据库未能进入增量回收模式")
    _verify_integrity(db)


def compact_database(database_path: Path, backups_dir: Path, *, timeout: float = 2) -> dict:
    """Back up and compact a database while holding SQLite's exclusive connection lock."""
    uri = database_path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as db:
        db.execute("PRAGMA locking_mode=EXCLUSIVE")
        try:
            db.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            if not _sqlite_busy(error):
                raise
            raise MaintenanceConflict("数据库仍在使用，请停止 API 和 Worker 后重试") from error
        before = _read_usage(db, database_path)
        if before["active_jobs"]:
            raise MaintenanceConflict("仍有任务处于运行或取消中，请等任务结束后再压缩")
        db.commit()

        # SQLite retains the exclusive lock across commits in this connection mode.
        _ensure_scratch_space(database_path, backups_dir)
        backup = _verified_backup(db, backups_dir)
        try:
            _rebuild_database(db)
            if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                raise MaintenanceConflict("无法截断 WAL")
        except (MaintenanceConflict, OSError, sqlite3.Error) as error:
            raise MaintenanceRecoveryRequired(f"数据库压缩或校验失败，回退备份保留在 {backup}") from error

        verified = backup.with_name(".nfc-verified-" + backup.name)
        backup.rename(verified)
        sync_directory(backups_dir)
        result = {"before": before, "after": _read_usage(db, database_path)}
        try:
            remove_verified_maintenance_backups(backups_dir)
        except OSError:
            result["temporary_backup_path"] = str(verified)
        return {**result, "temporary_backup_removed": not verified.exists()}


def _has_queued_or_running_jobs(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT 1 FROM work_jobs WHERE status IN ('queued', 'running', 'cancel_requested') LIMIT 1",
    ).fetchone() is not None


def reclaim_idle_database_space(
    database_path: Path, *,
    min_bytes: int = MIN_IDLE_RECLAIM_BYTES, max_pages: int = MAX_IDLE_RECLAIM_PAGES,
    fence: Callable[[], None] | None = None,
) -> bool:
    """Upgrade an old file once, then return a bounded number of free pages per idle pass."""
    if min_bytes < 1 or max_pages < 1:
        raise ValueError("Database maintenance limits must be positive")
    uri = database_path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as db:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        free_bytes = db.execute("PRAGMA freelist_count").fetchone()[0] * page_size
        logical_bytes = db.execute("PRAGMA page_count").fetchone()[0] * page_size
        pending_shrink = _size(database_path) > logical_bytes
        if (free_bytes < min_bytes and not pending_shrink) or _has_queued_or_running_jobs(db):
            return False
        mode = db.execute("PRAGMA auto_vacuum").fetchone()[0]
        reclaimed = False
        if free_bytes >= min_bytes and mode == 0:
            wal_path = database_path.with_name(database_path.name + "-wal")
            if shutil.disk_usage(database_path.parent).free < 2 * (_size(database_path) + _size(wal_path)):
                raise MaintenanceConflict("可用空间不足，无法启用增量回收")
            if fence is not None:
                fence()
            if _has_queued_or_running_jobs(db):
                return False
            # VACUUM is an atomic SQLite transaction. A separate online copy
            # could predate API writes and cannot serve as an exact rollback.
            try:
                _rebuild_database(db)
            except sqlite3.OperationalError as error:
                if _sqlite_busy(error):
                    return False
                raise
            except MaintenanceConflict as error:
                raise MaintenanceRecoveryRequired("旧库自动压缩后的完整性校验未通过") from error
            reclaimed = True
        elif free_bytes >= min_bytes and mode == 2:
            if fence is not None:
                fence()
            db.execute("BEGIN IMMEDIATE")
            if _has_queued_or_running_jobs(db):
                return False
            db.execute(f"PRAGMA incremental_vacuum({max_pages})").fetchall()
            db.commit()
            reclaimed = True
        if reclaimed or pending_shrink:
            # PASSIVE lets readers finish on their existing WAL snapshot.
            db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return reclaimed or pending_shrink
