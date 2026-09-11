import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.service import FileCenterService
from app.config import Settings


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_api_boot_defers_transactional_entry(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    anchor = q_dir / ".tx" / "entry-1" / "attempt-1" / "anchor"
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"DATA")

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=q_dir,
    )
    service = FileCenterService(settings=settings)

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = QuarantineEntry(
            id=1,
            original_path=str(data_dir / "file.txt"),
            quarantine_path=str(q_dir / "file.txt"),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=1,
            inode=100,
            size=4,
            content_hash="hash",
        )
        session.add(entry)
        session.commit()

    # Forbid any filesystem mutation
    def forbidden(*args, **kwargs):
        raise AssertionError("Filesystem mutation called during API boot deferral!")

    monkeypatch.setattr(os, "link", forbidden)
    monkeypatch.setattr(os, "rename", forbidden)
    monkeypatch.setattr(os, "unlink", forbidden)

    res = service._reconcile_single_transitional_entry(1)
    assert res["reconciled"] is False
    assert "Deferred transactional entry" in res.get("reason", "")

    # Verify database was not mutated
    with service.SessionLocal() as session:
        e = session.get(QuarantineEntry, 1)
        assert e.state == "preparing"
        assert e.tx_phase == "authoritative_anchored"

