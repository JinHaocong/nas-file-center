from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.db import create_engine_and_session, init_db
from app.models import TaskLock, utcnow
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    renew_and_assert_worker_lease,
)
from app.tasks.state_machine import JobLeaseLost


def test_global_worker_lease_serializes_nfc_mutation_authority(tmp_path: Path):
    """Characterize the existing global lease contract used by Gate6-B execution.

    A fresh TaskLock(id=1) admits exactly one worker authority. After the lease is
    made stale and another worker takes over, the former owner must be rejected
    by the same short committed lease fence used immediately before filesystem
    mutation.
    """
    db_path = tmp_path / "gate6b_worker_serialization.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    old_worker = "gate6b-worker-old"
    new_worker = "gate6b-worker-new"

    assert acquire_worker_ownership(engine, SessionLocal, worker_id=old_worker) is True

    # A fresh global lease rejects every competing worker, which is stronger
    # than scope-local serialization for overlapping recursive-protection trees.
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=new_worker) is False

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock is not None
        assert lock.locked is True
        assert lock.owner == old_worker
        lock.acquired_at = utcnow() - timedelta(seconds=WORKER_LEASE_TIMEOUT_SECONDS + 1.0)
        session.commit()

    # Once the old lease is stale, takeover is allowed.
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=new_worker) is True

    # The former owner is fenced before filesystem mutation and cannot continue
    # using authority it held before takeover.
    with pytest.raises(JobLeaseLost):
        renew_and_assert_worker_lease(SessionLocal, old_worker)

    # The current owner still holds the valid mutation authority.
    renew_and_assert_worker_lease(SessionLocal, new_worker)
