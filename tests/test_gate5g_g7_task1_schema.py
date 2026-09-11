import pytest
from app.models import QuarantineEntry
from app.db import create_engine_and_session, init_db


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_quarantine_entry_db2_columns(session_factory):
    with session_factory() as session:
        entry = QuarantineEntry(
            original_path="/vol/test.txt",
            quarantine_path="/vol/.quarantine/test.txt",
            state="preparing",
            tx_token="tx-12345",
            tx_phase="preparing",
            authoritative_anchor_path="/vol/.quarantine/.tx/entry-1/attempt-1/anchor",
            active_attempt_generation=1,
        )
        session.add(entry)
        session.commit()
        assert entry.tx_phase == "preparing"
        assert entry.tx_token == "tx-12345"
        assert entry.authoritative_anchor_path == "/vol/.quarantine/.tx/entry-1/attempt-1/anchor"
        assert entry.active_attempt_generation == 1


def test_legacy_rows_preserve_state_and_null_tx_phase(session_factory):
    with session_factory() as session:
        entry = QuarantineEntry(
            original_path="/vol/legacy.txt",
            quarantine_path="/vol/.quarantine/legacy.txt",
            state="active",
        )
        session.add(entry)
        session.commit()
        assert entry.state == "active"
        assert entry.tx_phase is None
        assert entry.tx_token is None
        assert entry.authoritative_anchor_path is None
        assert entry.active_attempt_generation == 0
