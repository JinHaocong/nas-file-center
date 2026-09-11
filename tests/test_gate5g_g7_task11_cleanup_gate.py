import errno
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.service import FileCenterService
from app.config import Settings


def test_purge_refuses_active_compat_entry(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    anchor = q_dir / ".tx" / "entry-1" / "attempt-1" / "anchor"
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"DATA")

    pub_file = q_dir / "file.txt"
    pub_file.write_bytes(b"DATA")

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=q_dir,
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings=settings)

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = QuarantineEntry(
            id=1,
            original_path=str(data_dir / "file.txt"),
            quarantine_path=str(pub_file),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=1,
            inode=100,
            size=4,
            content_hash="hash",
        )
        session.add(entry)
        session.commit()

    with pytest.raises(OSError) as exc:
        service.purge_quarantine_entry(1, confirmation="DELETE", is_admin=True)

    assert exc.value.errno == errno.EOPNOTSUPP

    # Ensure anchor and payload were NOT unlinked
    assert anchor.exists()
    assert pub_file.exists()
