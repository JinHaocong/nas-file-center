"""Review regressions for Worker lease timing and service lifecycle boundaries."""
from datetime import timedelta, timezone
import threading

from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.batch.media_sort_jobs import enqueue_plan_stage
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.recovery import acquire_worker_ownership, renew_and_assert_worker_lease
from app.tasks.state_machine import JobLeaseLost
from app.worker import process_work_job
from tests.test_plan_validation_worker_api import _create_hardlink_plan, _environment


def _expire(service, worker_id):
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock is not None and lock.owner == worker_id
        lock.acquired_at = utcnow() - timedelta(seconds=120)
        session.commit()


def _ordinary_plan(service, data, *, kind='rename'):
    source = data / 'source.jpg'
    source.write_bytes(b'ordinary-media-validation')
    plan = service.create_plan(name='lease-review', kind=kind, items=[{
        'operation': 'move' if kind == 'media-sort' else 'rename',
        'source': str(source), 'target': str(data / 'target.jpg'),
    }])
    service.freeze_plan(plan.id)
    return plan.id


def _run_job(service, job_id, worker_id):
    return process_work_job(
        service.settings, job_id, session_factory=service.SessionLocal,
        engine=service.engine, worker_id=worker_id,
    )


def test_validation_flush_expiry_rolls_back_item_plan_and_audit(tmp_path, monkeypatch):
    from app.tasks import recovery

    _client, data, service = _environment(tmp_path)
    plan_id = _ordinary_plan(service, data)
    worker_id = 'review-validation-flush'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    clock = [utcnow()]
    advanced = []
    monkeypatch.setattr(recovery, 'utcnow', lambda: clock[0])

    def expire_after_validation_flush(session, _flush_context):
        if not advanced and any(
            isinstance(row, AuditEvent) and row.operation == 'validate'
            for row in session.new
        ):
            # The real INSERT/UPDATE flush has completed. Model disk/DB work
            # crossing the lease deadline without waiting 30 seconds in CI.
            clock[0] += timedelta(seconds=120)
            advanced.append(True)

    event.listen(Session, 'after_flush', expire_after_validation_flush)
    refused = False
    try:
        try:
            service.validate_plan(plan_id, worker_id=worker_id)
        except JobLeaseLost:
            refused = True
    finally:
        event.remove(Session, 'after_flush', expire_after_validation_flush)

    assert advanced, 'the actual validation write flush was not exercised'
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == 'planned'
        assert session.get(BatchPlan, plan_id).status == 'frozen'
        assert session.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.operation == 'validate',
        )) == 0
    assert refused, 'validation committed using a time sampled before its write flush'


def test_renewal_waiting_for_sqlite_writer_cannot_revive_expired_lease(tmp_path, monkeypatch):
    from app.tasks import recovery

    _client, _data, service = _environment(tmp_path)
    worker_id = 'review-renewal-lock-wait'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    with service.SessionLocal() as session:
        original_acquired = session.get(TaskLock, 1).acquired_at
    initial_time = original_acquired.replace(tzinfo=timezone.utc)
    clock = [initial_time + timedelta(seconds=1)]
    monkeypatch.setattr(recovery, 'utcnow', lambda: clock[0])
    started = threading.Event()
    errors = []

    def before_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement == 'BEGIN IMMEDIATE':
            started.set()

    def renew():
        try:
            renew_and_assert_worker_lease(service.SessionLocal, worker_id)
        except Exception as exc:
            errors.append(exc)

    blocker = service.engine.connect()
    blocker.execute(text('BEGIN IMMEDIATE'))
    event.listen(service.engine, 'before_cursor_execute', before_statement)
    thread = threading.Thread(target=renew)
    try:
        thread.start()
        assert started.wait(timeout=5), 'renewal never attempted its SQLite writer lock'
        clock[0] = initial_time + timedelta(seconds=120)
        blocker.commit()
        thread.join(timeout=5)
        assert not thread.is_alive(), 'renewal did not finish after releasing the writer lock'
    finally:
        blocker.rollback()
        blocker.close()
        thread.join(timeout=5)
        event.remove(service.engine, 'before_cursor_execute', before_statement)

    assert len(errors) == 1 and isinstance(errors[0], JobLeaseLost), errors
    with service.SessionLocal() as session:
        assert session.get(TaskLock, 1).acquired_at == original_acquired


def test_validation_handler_does_not_replay_startup_after_lease_expiry(tmp_path, monkeypatch):
    client, data, service = _environment(tmp_path)
    plan_id = _create_hardlink_plan(service, data)
    response = client.post(
        f'/api/plans/{plan_id}/validate', headers={'Origin': 'http://testserver'},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()['work_job_id']
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / 'unrelated.jpg'),
            quarantine_path=str(service.settings.quarantine_root / 'unrelated-missing.jpg'),
            state='restoring',
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    worker_id = 'review-validation-startup'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    original_checkpoint = JobContext.checkpoint
    expired = []

    def checkpoint_then_expire(self, **kwargs):
        original_checkpoint(self, **kwargs)
        if kwargs.get('progress_message') == f'Validating plan #{plan_id}':
            _expire(service, worker_id)
            expired.append(True)

    monkeypatch.setattr(JobContext, 'checkpoint', checkpoint_then_expire)
    assert _run_job(service, job_id, worker_id) is False
    assert expired
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state == 'restoring'
        assert entry.last_error is None
        assert session.get(WorkJob, job_id).status == 'running'


def test_media_sort_validation_uses_worker_lease_for_result_commit(tmp_path, monkeypatch):
    _client, data, service = _environment(tmp_path)
    plan_id = _ordinary_plan(service, data, kind='media-sort')
    queued = enqueue_plan_stage(service.SessionLocal, plan_id, 'validate')
    worker_id = 'review-media-sort-validation'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    original_checkpoint = JobContext.checkpoint
    expired = []

    def checkpoint_then_expire(self, **kwargs):
        original_checkpoint(self, **kwargs)
        if str(kwargs.get('progress_message', '')).startswith('正在校验文件 '):
            _expire(service, worker_id)
            expired.append(True)

    monkeypatch.setattr(JobContext, 'checkpoint', checkpoint_then_expire)
    assert _run_job(service, queued['job_id'], worker_id) is False
    assert expired
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == 'planned'
        assert session.get(BatchPlan, plan_id).status == 'frozen'
