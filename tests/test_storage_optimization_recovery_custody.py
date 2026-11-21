"""Storage recovery must reacquire live custody before media or journal writes.

Historical interrupted states are prepared only under the explicit tmp_path
proof fixture. Recovery refusal uses the unchanged production provider.
"""
import hashlib
import json
import os
import signal
import stat

import pytest
from sqlalchemy import select

from app.batch.media_organizer_custody import NamespaceCustodyUnavailable
from app.exceptions import StateConflictError
from app.models import AuditEvent, BatchPlanItem, OperationJournal
from app.storage_optimization import capability, executor
from tests.storage_probe_custody import scoped_probe_namespace
from tests.test_storage_optimization_execution import WORKER_ID, _seed


_LIVE_PROVIDER = capability.verified_probe_namespace_custody


def _execute(env):
    return executor.execute_storage_optimization(
        env["item"], plan_id=str(env["plan_id"]),
        allowed_roots=env["settings"].allowed_roots,
        session_factory=env["service"].SessionLocal, worker_id=WORKER_ID,
    )


def _media_snapshot(env):
    return {
        path.name: (
            path.stat().st_dev, path.stat().st_ino, path.stat().st_nlink,
            path.stat().st_mode, path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in env["source"].parent.iterdir()
    }


def _evidence_snapshot(env):
    with env["service"].SessionLocal() as session:
        journals = list(session.scalars(select(OperationJournal).where(
            OperationJournal.plan_item_id == env["item_id"],
        ).order_by(OperationJournal.id)))
        audits = list(session.scalars(select(AuditEvent).where(
            AuditEvent.operation == env["item"].operation,
        ).order_by(AuditEvent.id)))
        item = session.get(BatchPlanItem, env["item_id"])
        return (
            [(row.id, row.before_json, row.after_json) for row in journals],
            [(row.id, row.operation, row.result, row.details_json) for row in audits],
            (item.state, item.metadata_json),
        )


def _interrupt_after_phase(env, monkeypatch, phase):
    real_journal = executor._phase_journal

    def interrupt(*args, **kwargs):
        result = real_journal(*args, **kwargs)
        if kwargs["phase"] == phase:
            raise RuntimeError(f"disposable interruption after {phase}")
        return result

    with monkeypatch.context() as interruption:
        interruption.setattr(executor, "_phase_journal", interrupt)
        with pytest.raises(RuntimeError, match=f"disposable interruption after {phase}"):
            _execute(env)
    phases = [json.loads(row[1])["phase"] for row in _evidence_snapshot(env)[0]]
    assert phases[-1] == phase


@pytest.mark.parametrize("phase", ["prepared_new", "captured_old", "published"])
def test_interrupted_recovery_refuses_live_provider_before_any_media_or_journal_change(
    tmp_path, monkeypatch, scoped_probe_namespace, phase,
):
    env = _seed(tmp_path)
    _interrupt_after_phase(env, monkeypatch, phase)
    before_media = _media_snapshot(env)
    before_evidence = _evidence_snapshot(env)
    assert any(row[1] == env["source_original_inode"] for row in before_media.values())
    assert all(proof.closed for proof in scoped_probe_namespace["proofs"])

    # Restore the live refusal, not a synthetic denying implementation.
    monkeypatch.setattr(capability, "verified_probe_namespace_custody", _LIVE_PROVIDER)
    try:
        _execute(env)
    except Exception as exc:
        error = exc
    else:
        error = None

    assert _media_snapshot(env) == before_media, "recovery mutated media without live custody"
    assert _evidence_snapshot(env) == before_evidence, "recovery rewrote journal authority without custody"
    assert isinstance(error, NamespaceCustodyUnavailable), repr(error)


def test_published_recovery_refreshes_custody_after_final_new_identity_check(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    env = _seed(tmp_path)
    _interrupt_after_phase(env, monkeypatch, "published")
    before_media = _media_snapshot(env)
    before_evidence = _evidence_snapshot(env)
    real_qualify = executor._qualify_new
    revoked = []

    def qualify_then_revoke(*args, **kwargs):
        result = real_qualify(*args, **kwargs)
        scoped_probe_namespace["allowed"] = False
        revoked.append(True)
        return result

    monkeypatch.setattr(executor, "_qualify_new", qualify_then_revoke)
    try:
        _execute(env)
    except Exception as exc:
        error = exc
    else:
        error = None

    assert revoked
    assert _media_snapshot(env) == before_media, "revoked recovery unlinked a retained alias"
    assert _evidence_snapshot(env) == before_evidence
    assert isinstance(error, NamespaceCustodyUnavailable), repr(error)
    assert all(proof.closed for proof in scoped_probe_namespace["proofs"])


def test_recovery_rechecks_custody_before_committing_journal_authority(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    env = _seed(tmp_path)
    _interrupt_after_phase(env, monkeypatch, "published")
    real_journal = executor._phase_journal
    boundary = {}

    def revoke_before_intent(*args, **kwargs):
        if kwargs["phase"] == "old_retire_intent":
            boundary["media"] = _media_snapshot(env)
            boundary["evidence"] = _evidence_snapshot(env)
            scoped_probe_namespace["allowed"] = False
        return real_journal(*args, **kwargs)

    monkeypatch.setattr(executor, "_phase_journal", revoke_before_intent)
    try:
        _execute(env)
    except Exception as exc:
        error = exc
    else:
        error = None

    assert boundary, "recovery never reached its journal boundary"
    assert _media_snapshot(env) == boundary["media"]
    assert _evidence_snapshot(env) == boundary["evidence"], "revoked custody extended journal authority"
    assert isinstance(error, NamespaceCustodyUnavailable), repr(error)
    assert all(proof.closed for proof in scoped_probe_namespace["proofs"])


def test_completed_readonly_reconciliation_does_not_require_a_new_mutation_proof(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    env = _seed(tmp_path)
    assert "completed" in _execute(env)
    before_media = _media_snapshot(env)
    before_evidence = _evidence_snapshot(env)
    monkeypatch.setattr(capability, "verified_probe_namespace_custody", _LIVE_PROVIDER)

    assert "already completed" in _execute(env)
    assert _media_snapshot(env) == before_media
    assert _evidence_snapshot(env) == before_evidence


class _BlockingRegularOpen(RuntimeError):
    pass


@pytest.mark.parametrize("role", ["keep", "source"])
def test_precustody_fifo_substitution_fails_without_waiting_for_a_writer(
    tmp_path, monkeypatch, role,
):
    """Use the live provider; the read-only opens must reach their type guards."""
    env = _seed(tmp_path)
    assert capability.verified_probe_namespace_custody is _LIVE_PROVIDER
    victim = env[role]
    detached = tmp_path / f"detached-{role}"
    original_inode = victim.stat().st_ino
    before_evidence = _evidence_snapshot(env)
    real_open = os.open
    swapped = []

    def alarm(_signum, _frame):
        raise _BlockingRegularOpen(f"{role} FIFO open blocked until audit alarm")

    def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
        if (dir_fd is not None and str(path) == victim.name
                and not flags & (os.O_DIRECTORY | os.O_CREAT) and not swapped):
            victim.rename(detached)
            os.mkfifo(victim, mode=0o600)
            swapped.append(True)
            signal.setitimer(signal.ITIMER_REAL, 0.5)
            try:
                return real_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    previous_handler = signal.signal(signal.SIGALRM, alarm)
    try:
        monkeypatch.setattr(os, "open", swap_before_open)
        try:
            _execute(env)
        except Exception as exc:
            error = exc
        else:
            error = None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert swapped, "the actual regular-file open boundary was not exercised"
    assert stat.S_ISFIFO(victim.lstat().st_mode)
    assert detached.stat().st_ino == original_inode
    assert detached.read_bytes() == env["payload"]
    other = env["source" if role == "keep" else "keep"]
    assert other.read_bytes() == env["payload"]
    assert {path.name for path in victim.parent.iterdir()} == {"source.bin", "keep.bin"}
    assert _evidence_snapshot(env) == before_evidence
    assert isinstance(error, StateConflictError), repr(error)
    assert str(error) == f"STORAGE_OPTIMIZATION_{role.upper()}_NOT_REGULAR"
