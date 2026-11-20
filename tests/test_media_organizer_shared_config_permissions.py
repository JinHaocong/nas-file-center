"""#403: shared config channels must work for distinct non-root API/Worker UIDs.

All fixtures live inside pytest tmp_path.  These unit checks cover mode/GID
contracts; a separate actual Docker two-UID acceptance is still required.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.db import create_engine_and_session, _db_init_lock, DB_INIT_LOCK_NAME
from app.archive_recovery.integration import write_report, report_path


def _shared_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    config = tmp_path / "shared-config"
    config.mkdir()
    config.chmod(0o2770)
    return config


def test_shared_db_first_creation_and_wal_files_are_group_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    db_path = config / "app.db"

    engine, _ = create_engine_and_session(db_path)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE test_shared_sqlite (a INTEGER)"))
            conn.execute(text("INSERT INTO test_shared_sqlite VALUES (7)"))
            assert conn.execute(text("SELECT a FROM test_shared_sqlite")).scalar_one() == 7
            for suffix in ("", "-wal", "-shm"):
                current = Path(str(db_path) + suffix)
                assert current.exists(), f"Missing SQLite file: {suffix}"
                assert (current.stat().st_mode & 0o777) == 0o660, current
                assert current.stat().st_gid == os.getegid()
    finally:
        engine.dispose()


def test_shared_db_refuses_existing_private_database_without_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    db_path = config / "app.db"
    db_path.write_bytes(b"")
    db_path.chmod(0o600)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        create_engine_and_session(db_path)
    assert (db_path.stat().st_mode & 0o777) == 0o600


def test_shared_db_refuses_symlink_before_engine_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"unchanged")
    (config / "app.db").symlink_to(outside)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        create_engine_and_session(config / "app.db")
    assert outside.read_bytes() == b"unchanged"


def test_shared_archive_report_directory_and_json_are_group_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    settings = SimpleNamespace(config_dir=config)
    write_report(settings, 44, {"safe": True})
    directory = config / "archive-recovery-reports"
    report = report_path(settings, 44)
    assert (directory.stat().st_mode & 0o7777) == 0o2770
    assert directory.stat().st_gid == os.getegid()
    assert (report.stat().st_mode & 0o777) == 0o640
    assert report.stat().st_gid == os.getegid()
    assert report.read_text(encoding="utf-8") == '{"safe": true}'


def test_shared_archive_report_refuses_preexisting_private_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    directory = config / "archive-recovery-reports"
    directory.mkdir(mode=0o700)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        write_report(SimpleNamespace(config_dir=config), 44, {"safe": True})
    assert not (directory / "44.json").exists()
    assert (directory.stat().st_mode & 0o777) == 0o700


def test_legacy_report_mode_remains_private_without_shared_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NFC_SHARED_CONFIG_GID", raising=False)
    settings = SimpleNamespace(config_dir=tmp_path)
    write_report(settings, 33, {"private": True})
    assert (report_path(settings, 33).stat().st_mode & 0o777) == 0o600


def test_db_init_lock_uses_non_hidden_name_for_zfuse():
    assert DB_INIT_LOCK_NAME == "db-init.lock"
    assert not DB_INIT_LOCK_NAME.startswith(".")


def test_shared_group_file_creation_uses_exclusive_create_without_nofollow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.config_sharing as sharing_module

    config = _shared_config(monkeypatch, tmp_path)
    lock = config / DB_INIT_LOCK_NAME
    original_open = os.open
    observed_flags: list[int] = []

    def zfuse_open(path, flags, *args, **kwargs):
        if os.fspath(path) == os.fspath(lock) and flags & os.O_CREAT:
            observed_flags.append(flags)
            assert flags & os.O_EXCL
            assert not flags & getattr(os, "O_NOFOLLOW", 0)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(sharing_module.os, "open", zfuse_open)
    with _db_init_lock(lock):
        assert lock.is_file()
    assert len(observed_flags) == 1


def test_shared_db_init_lock_is_group_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    lock = config / DB_INIT_LOCK_NAME
    with _db_init_lock(lock):
        assert (lock.stat().st_mode & 0o777) == 0o660
        assert lock.stat().st_gid == os.getegid()


def test_shared_db_init_lock_uses_pinned_proc_fd_when_zfuse_openat_returns_enoent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db as db_module

    config = _shared_config(monkeypatch, tmp_path)
    lock = config / DB_INIT_LOCK_NAME
    lock.write_bytes(b"")
    lock.chmod(0o660)
    original_open = os.open

    def zfuse_open(path, flags, *args, **kwargs):
        if Path(path).name == lock.name and kwargs.get("dir_fd") is not None:
            raise FileNotFoundError(2, "simulated zfuse openat lookup failure", str(path))
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(db_module.os, "open", zfuse_open)
    with _db_init_lock(lock):
        assert lock.stat().st_gid == os.getegid()
        assert (lock.stat().st_mode & 0o777) == 0o660


def test_pinned_directory_entry_path_requires_a_real_directory_fd(tmp_path):
    from app.config_sharing import pinned_directory_entry_path

    directory_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        entry = pinned_directory_entry_path(directory_fd, DB_INIT_LOCK_NAME)
        assert entry == f"/proc/self/fd/{directory_fd}/{DB_INIT_LOCK_NAME}"
        assert os.stat(f"/proc/self/fd/{directory_fd}").st_ino == os.fstat(directory_fd).st_ino
        for invalid in ("", ".", "..", "../escape", "nested/name"):
            with pytest.raises(PermissionError, match="SHARED_CONFIG"):
                pinned_directory_entry_path(directory_fd, invalid)
    finally:
        os.close(directory_fd)

    regular_file = tmp_path / "not-a-directory"
    regular_file.write_text("x")
    file_fd = os.open(regular_file, os.O_RDONLY)
    try:
        with pytest.raises(PermissionError, match="SHARED_CONFIG"):
            pinned_directory_entry_path(file_fd, DB_INIT_LOCK_NAME)
    finally:
        os.close(file_fd)


def test_shared_db_init_lock_rejects_symlink_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    target = tmp_path / "outside.lock"
    target.write_bytes(b"unchanged")
    lock = config / DB_INIT_LOCK_NAME
    lock.symlink_to(target)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        with _db_init_lock(lock):
            pytest.fail("followed a database init lock symlink")
    assert target.read_bytes() == b"unchanged"


def test_shared_config_rejects_world_writable_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _shared_config(monkeypatch, tmp_path)
    config.chmod(0o2777)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        create_engine_and_session(config / "app.db")
    assert not (config / "app.db").exists()


def _file_center_settings(config: Path, data: Path):
    from app.config import Settings
    return Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        allow_mutation=False,
        allow_delete=False,
    )


def test_shared_api_worker_service_creates_all_config_directories_group_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group access must extend beyond app.db to reports, logs, backups and fclones."""
    from app.service import FileCenterService

    config = _shared_config(monkeypatch, tmp_path)
    settings = _file_center_settings(config, tmp_path)
    service = FileCenterService(settings)
    try:
        for directory in (
            settings.reports_dir,
            settings.backups_dir,
            settings.logs_dir,
            settings.fclones_home,
        ):
            st = directory.lstat()
            assert (st.st_mode & 0o7777) == 0o2770, directory
            assert st.st_gid == os.getegid(), directory
    finally:
        service.engine.dispose()


def test_shared_service_refuses_existing_private_report_dir_before_db_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.service import FileCenterService

    config = _shared_config(monkeypatch, tmp_path)
    reports = config / "reports"
    reports.mkdir(mode=0o700)
    settings = _file_center_settings(config, tmp_path)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        FileCenterService(settings)
    assert (reports.stat().st_mode & 0o777) == 0o700
    assert not settings.database_path.exists()


def test_shared_service_rejects_symlinked_config_child_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.service import FileCenterService

    config = _shared_config(monkeypatch, tmp_path)
    foreign = tmp_path / "foreign-reports"
    foreign.mkdir(mode=0o700)
    (foreign / "leave-alone.txt").write_text("unchanged", encoding="utf-8")
    (config / "reports").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        FileCenterService(_file_center_settings(config, tmp_path))
    assert (foreign / "leave-alone.txt").read_text(encoding="utf-8") == "unchanged"
    assert not (config / "app.db").exists()


def test_shared_service_refuses_unprovisioned_config_root_without_changing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.service import FileCenterService

    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", str(os.getegid()))
    config = tmp_path / "legacy-private-config"
    config.mkdir(mode=0o700)
    old_mode = config.stat().st_mode & 0o7777
    with pytest.raises(PermissionError, match="SHARED_CONFIG"):
        FileCenterService(_file_center_settings(config, tmp_path))
    assert (config.stat().st_mode & 0o7777) == old_mode
    assert list(config.iterdir()) == []
