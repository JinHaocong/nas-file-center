"""Worker-owned storage probes stop at real SQLite lease-loss boundaries.

These assertions require storage probes to stop initiating writes when their
real SQLite Worker lease expires. The observer calls the real OS operations.
Tests reaching scratch writes explicitly inject tmp_path-scoped custody.
This proves lease-fencing behavior, not production namespace exclusion.
"""
from datetime import timedelta
import os

import pytest
from sqlalchemy import select

from app.models import BatchPlan, BatchPlanItem, TaskLock, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.recovery import acquire_worker_ownership, assert_active_worker_lease
from app.tasks.state_machine import JobLeaseLost
from app.worker import process_work_job
from tests.test_plan_validation_worker_api import _create_hardlink_plan, _environment
from tests.storage_probe_custody import scoped_probe_namespace


def _expire(service, worker_id):
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock is not None and lock.owner == worker_id
        lock.acquired_at = utcnow() - timedelta(seconds=120)
        session.commit()
    with service.SessionLocal() as session:
        with pytest.raises(JobLeaseLost):
            assert_active_worker_lease(session, worker_id)


def _observer(monkeypatch, expired):
    events = []
    real_open, real_link = os.open, os.link

    def observe_open(name, flags, *args, **kwargs):
        fd = real_open(name, flags, *args, **kwargs)
        if flags & os.O_CREAT and str(name).startswith('.__nfc_') and expired[0]:
            events.append(('created', str(name)))
        return fd

    def observe_link(src, dst, *args, **kwargs):
        result = real_link(src, dst, *args, **kwargs)
        if str(dst).startswith('.__nfc_') and expired[0]:
            events.append(('linked', str(dst)))
        return result

    monkeypatch.setattr(os, 'open', observe_open)
    monkeypatch.setattr(os, 'link', observe_link)
    return events


def _enqueue_probe(client, data):
    response = client.post(
        "/api/storage-optimization/capabilities",
        json={"directory": str(data)},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 202, response.text
    return response.json()["work_job_id"]


def _process(service, job_id, worker_id):
    return process_work_job(
        service.settings, job_id, session_factory=service.SessionLocal,
        engine=service.engine, worker_id=worker_id,
    )


@pytest.mark.parametrize('operation', ['capability', 'validation'])
def test_expiry_at_last_checkpoint_prevents_scratch_writes(tmp_path, monkeypatch, operation):
    client, data, service = _environment(tmp_path)
    if operation == 'validation':
        plan_id = _create_hardlink_plan(service, data)
        response = client.post(
            f'/api/plans/{plan_id}/validate', headers={'Origin': 'http://testserver'},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()['work_job_id']
        target_checkpoint = f'Validating plan #{plan_id}: 1/1'
        with service.SessionLocal() as session:
            item = session.scalar(
                select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id),
            )
            original_item_state = item.state
    else:
        job_id = _enqueue_probe(client, data)
        target_checkpoint = 'Running storage capability probes'
    worker_id = f'review-403-{operation}'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    expired = [False]
    events = _observer(monkeypatch, expired)
    real_checkpoint = JobContext.checkpoint

    def checkpoint_then_expire(self, **kwargs):
        result = real_checkpoint(self, **kwargs)
        if kwargs.get('progress_message') == target_checkpoint and not expired[0]:
            _expire(service, worker_id)
            expired[0] = True
        return result

    monkeypatch.setattr(JobContext, 'checkpoint', checkpoint_then_expire)
    assert _process(service, job_id, worker_id) is False
    assert expired[0], 'lease-expiry boundary was not exercised'
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job.status == 'running'
        if operation == 'validation':
            item = session.scalar(
                select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id),
            )
            assert item.state == original_item_state
    assert events == [], 'storage scratch writes occurred after the real Worker lease expired'


def test_capability_expiry_after_first_create_stops_next_write(tmp_path, monkeypatch, scoped_probe_namespace):
    from app.storage_optimization import capability
    client, data, service = _environment(tmp_path)
    job_id = _enqueue_probe(client, data)
    worker_id = 'review-403-between-syscalls'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    expired = [False]
    events = _observer(monkeypatch, expired)
    real_probe_file = capability._probe_file

    def create_then_expire(*args, **kwargs):
        fd = real_probe_file(*args, **kwargs)
        if not expired[0]:
            _expire(service, worker_id)
            expired[0] = True
        return fd

    monkeypatch.setattr(capability, '_probe_file', create_then_expire)
    assert _process(service, job_id, worker_id) is False
    assert expired[0]
    assert events == [], 'a later link/create was executed after the real Worker lease expired'
    residue = list(data.glob('.__nfc_*'))
    assert len(residue) == 1 and residue[0].suffix == '.src'
    assert residue[0].read_bytes() == b'nas-file-center-hardlink-probe'


def test_validation_expiry_after_last_probe_prevents_result_commit(tmp_path, monkeypatch, scoped_probe_namespace):
    import app.service as service_module
    client, data, service = _environment(tmp_path)
    plan_id = _create_hardlink_plan(service, data)
    with service.SessionLocal() as session:
        session.get(BatchPlan, plan_id).status = 'frozen'
        session.commit()
    response = client.post(
        f'/api/plans/{plan_id}/validate', headers={'Origin': 'http://testserver'},
    )
    assert response.status_code == 202
    job_id = response.json()['work_job_id']
    worker_id = 'review-403-validation-result-commit'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    original = service_module.probe_hardlink_capability
    expired = [False]

    def last_probe_then_expire(*args, **kwargs):
        result = original(*args, **kwargs)
        _expire(service, worker_id)
        expired[0] = True
        return result

    monkeypatch.setattr(service_module, 'probe_hardlink_capability', last_probe_then_expire)
    assert _process(service, job_id, worker_id) is False
    assert expired[0]
    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id),
        )
        assert item.state == 'planned'
        assert session.get(BatchPlan, plan_id).status == 'frozen'


def test_ordinary_validation_stays_synchronous_without_media_mutations(tmp_path):
    client, data, service = _environment(tmp_path)
    source = data / 'source.txt'
    source.write_bytes(b'ordinary-read-only-validation')
    target = data / 'renamed.txt'
    plan = service.create_plan(name='ordinary', kind='rename', items=[{
        'operation': 'rename', 'source': str(source), 'target': str(target),
    }])
    service.freeze_plan(plan.id)
    service.settings.allow_mutation = False
    before_ctime = data.stat().st_ctime_ns
    response = client.post(
        f'/api/plans/{plan.id}/validate', headers={'Origin': 'http://testserver'},
    )
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'ready'
    assert source.read_bytes() == b'ordinary-read-only-validation'
    assert not target.exists()
    assert data.stat().st_ctime_ns == before_ctime
    with service.SessionLocal() as session:
        assert session.scalar(
            select(WorkJob.id).where(WorkJob.kind == 'batch-plan-validate'),
        ) is None


def test_expired_lease_before_dispatch_does_not_start_probes(tmp_path):
    client, data, service = _environment(tmp_path)
    job_id = _enqueue_probe(client, data)
    worker_id = 'review-403-before-dispatch'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    _expire(service, worker_id)
    before_ctime = data.stat().st_ctime_ns
    assert _process(service, job_id, worker_id) is False
    assert list(data.iterdir()) == []
    assert data.stat().st_ctime_ns == before_ctime
    with service.SessionLocal() as session:
        assert session.get(WorkJob, job_id).status == 'queued'


@pytest.mark.parametrize('probe_name', ['probe_hardlink_capability', 'probe_reflink_capability'])
@pytest.mark.parametrize('error_type', [PermissionError, ValueError])
def test_authority_errors_propagate_without_becoming_capability_results(tmp_path, probe_name, error_type):
    from app.storage_optimization import capability
    failure = error_type('mutation authority refused')

    def denied():
        raise failure

    with pytest.raises(error_type) as raised:
        getattr(capability, probe_name)(tmp_path, [tmp_path], mutation_fence=denied)
    assert raised.value is failure
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('boundary', ['created', 'linked', 'first_unlink'])
def test_expiry_preserves_scratch_evidence_without_later_mutations(tmp_path, monkeypatch, boundary, scoped_probe_namespace):
    client, data, service = _environment(tmp_path)
    job_id = _enqueue_probe(client, data)
    worker_id = f'review-403-retained-evidence-{boundary}'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    expired = [False]
    events = _observer(monkeypatch, expired)
    original_open, original_link, original_unlink = os.open, os.link, os.unlink

    def expire():
        if not expired[0]:
            _expire(service, worker_id)
            expired[0] = True

    def create_then_expire(name, flags, *args, **kwargs):
        fd = original_open(name, flags, *args, **kwargs)
        if flags & os.O_CREAT and str(name).startswith('.__nfc_'):
            expire()
        return fd

    def link_then_expire(*args, **kwargs):
        result = original_link(*args, **kwargs)
        expire()
        return result

    def unlink_then_expire(name, *args, **kwargs):
        result = original_unlink(name, *args, **kwargs)
        if str(name).startswith('.__nfc_'):
            expire()
        return result

    if boundary == 'created':
        monkeypatch.setattr(os, 'open', create_then_expire)
    elif boundary == 'linked':
        monkeypatch.setattr(os, 'link', link_then_expire)
    else:
        monkeypatch.setattr(os, 'unlink', unlink_then_expire)
    assert _process(service, job_id, worker_id) is False
    assert expired[0]
    assert events == []
    residue = sorted(data.glob('.__nfc_*'))
    if boundary == 'linked':
        assert len(residue) == 2
        assert {path.suffix for path in residue} == {'.src', '.dst'}
        assert residue[0].stat().st_ino == residue[1].stat().st_ino
        assert all(path.read_bytes() == b'nas-file-center-hardlink-probe' for path in residue)
    else:
        assert len(residue) == 1 and residue[0].suffix == '.src'
        expected = b'' if boundary == 'created' else b'nas-file-center-hardlink-probe'
        assert residue[0].read_bytes() == expected


@pytest.mark.parametrize('boundary', ['probe_entry', 'first_create'])
def test_storage_execution_probe_stops_after_lease_expiry(tmp_path, monkeypatch, boundary, scoped_probe_namespace):
    from app.storage_optimization import capability, executor
    from tests.test_storage_optimization_execution import WORKER_ID, _journal_phases, _seed

    env = _seed(tmp_path)
    service = env['service']
    expired = [False]
    events = _observer(monkeypatch, expired)
    original_probe = executor._ensure_initial_capability
    original_create = capability._probe_file

    def expire():
        if not expired[0]:
            _expire(service, WORKER_ID)
            expired[0] = True

    def expire_then_probe(*args, **kwargs):
        expire()
        return original_probe(*args, **kwargs)

    def create_then_expire(*args, **kwargs):
        fd = original_create(*args, **kwargs)
        expire()
        return fd

    if boundary == 'probe_entry':
        monkeypatch.setattr(executor, '_ensure_initial_capability', expire_then_probe)
    else:
        monkeypatch.setattr(capability, '_probe_file', create_then_expire)
    with pytest.raises(JobLeaseLost):
        executor.execute_storage_optimization(
            env['item'], plan_id=str(env['plan_id']),
            allowed_roots=env['settings'].allowed_roots,
            session_factory=service.SessionLocal, worker_id=WORKER_ID,
        )
    assert expired[0]
    assert events == [], 'storage execution continued probing after lease expiry'
    assert env['source'].read_bytes() == env['payload']
    assert env['keep'].read_bytes() == env['payload']
    assert env['source'].stat().st_ino == env['source_original_inode']
    assert env['keep'].stat().st_ino == env['keep_original_inode']
    assert _journal_phases(env) == []
    parent = env['source'].parent
    assert not (parent / f".__nfc_opt_{env['tx_id']}.new").exists()
    assert not (parent / f".__nfc_opt_{env['tx_id']}.old").exists()
    residue = list(parent.glob('.__nfc_*'))
    if boundary == 'probe_entry':
        assert residue == []
    else:
        assert len(residue) == 1 and residue[0].suffix == '.src'
        assert residue[0].read_bytes() == b'nas-file-center-hardlink-probe'


def test_storage_validation_with_mutation_disabled_writes_no_probe(tmp_path):
    client, data, service = _environment(tmp_path)
    plan_id = _create_hardlink_plan(service, data)
    service.settings.allow_mutation = False
    before_ctime = data.stat().st_ctime_ns
    response = client.post(
        f'/api/plans/{plan_id}/validate', headers={'Origin': 'http://testserver'},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()['work_job_id']
    worker_id = 'review-403-storage-validation-disabled'
    assert acquire_worker_ownership(service.engine, service.SessionLocal, worker_id=worker_id)
    assert _process(service, job_id, worker_id) is True
    assert data.stat().st_ctime_ns == before_ctime
    assert sorted(path.name for path in data.iterdir()) == ['keep.bin', 'source.bin']
    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id),
        )
        assert item.state == 'skipped'
        assert item.reason == 'STORAGE_OPTIMIZATION_MUTATION_DISABLED'
        assert session.get(BatchPlan, plan_id).status == 'partial'
        assert session.get(WorkJob, job_id).status == 'completed'
