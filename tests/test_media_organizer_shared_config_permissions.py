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

from app.db import create_engine_and_session
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
