import json
import threading
from time import monotonic, sleep

import pytest

from app.config import Settings
from app.archive_recovery.integration import cleanup_recovery_after_worker_restart
from app.db import create_engine_and_session, init_db
from app.models import WorkJob
from app.tasks.media_mutation_lock import media_mutation_lock
from app.tasks.recovery import acquire_worker_ownership, claim_next_job, recover_interrupted_jobs
from app.tasks.service import TaskService
from app.worker import process_work_job, worker_loop
from test_media_mutation_lock import external_holder


@pytest.fixture
def database(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings = Settings(
        config_dir=config_dir,
        data_mount=tmp_path,
        allowed_roots_raw=str(tmp_path),
        media_organizer_execution_mode="strict",
    )
    engine, sessions = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    yield settings, engine, sessions
    engine.dispose()


def _job(sessions, kind, *, status="queued", state=None, checkpoint=None, retry_of=None):
    with sessions.begin() as session:
        job = WorkJob(
            kind=kind, status=status, state_json=json.dumps(state or {}),
            checkpoint_json=json.dumps(checkpoint or {}), retry_of=retry_of,
        )
        session.add(job)
        session.flush()
        if kind in {"media-organizer-execute", "media-organizer-cleanup"}:
            job.state_json = json.dumps({**(state or {}), "approved_job_id": job.id})
        return job.id


def _status(sessions, job_id):
    with sessions() as session:
        return session.get(WorkJob, job_id).status


def _failed_frozen_execution(sessions, *, mode="maintenance_window", status="failed"):
    state = {"execution_mode": mode, "maintenance_window_confirmed": True,
             "unit": "/media/unit", "selection": "/media", "preview_job_id": 25}
    execution_id = _job(sessions, "media-organizer-execute", status=status, state=state)
    with sessions.begin() as session:
        session.get(WorkJob, execution_id).checkpoint_json = json.dumps({
            "schema_version": 1, "phase": "frozen", "execution_mode": mode,
            "frozen_job_id": execution_id, "manifest_checksum": "a" * 64,
            "unit": state["unit"], "preview_job_id": state["preview_job_id"],
        })
    return execution_id


def test_failed_frozen_family_recovered_on_worker_restart_blocks_foreign_queue(database):
    settings, engine, sessions = database
    original = _failed_frozen_execution(sessions, status="running")
    foreign = _job(sessions, "unclassified-mutation")
    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    assert recover_interrupted_jobs(engine, sessions, worker_id="worker")["failed_interrupted"] == 1
    assert _status(sessions, original) == "failed"
    assert claim_next_job(engine, sessions, worker_id="worker") is None
    assert not process_work_job(settings, foreign, sessions, engine)
    assert _status(sessions, foreign) == "queued"


def _recovery_state(original):
    return {
        "execution_mode": "maintenance_window", "maintenance_window_confirmed": True,
        "preview_job_id": 25, "unit": "/media/unit", "selection": "/media",
        "recovery_of_job_id": original, "recovery_manifest_checksum": "a" * 64,
        "recovery_phase": "frozen",
    }


@pytest.mark.parametrize("forgery", ["alias", "missing-retry", "digest", "none"])
def test_only_bound_execution_recovery_can_pass_older_foreign_jobs(database, forgery):
    _, engine, sessions = database
    original = _failed_frozen_execution(sessions)
    foreign = _job(sessions, "batch-plan-execute")
    state = _recovery_state(original)
    retry_of = original
    if forgery == "alias":
        state["recover_from_job_id"] = state.pop("recovery_of_job_id")
        retry_of = None
    elif forgery == "missing-retry":
        retry_of = None
    elif forgery == "digest":
        state["recovery_manifest_checksum"] = "e" * 64
    recovery = _job(sessions, "media-organizer-execute", state=state, retry_of=retry_of)
    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    assert claim_next_job(engine, sessions, worker_id="worker") == (recovery if forgery == "none" else None)
    assert _status(sessions, foreign) == "queued"


def test_preview_can_pass_reserved_mutation_queue(database):
    _, engine, sessions = database
    _failed_frozen_execution(sessions)
    _job(sessions, "unclassified-mutation")
    preview = _job(sessions, "media-organizer-preview")
    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    assert claim_next_job(engine, sessions, worker_id="worker") == preview


@pytest.mark.parametrize("finalizer_evidence", [
    "complete", "crash-gap", "plan", "checkpoint", "malformed-checkpoint", "approval", "root",
])
def test_only_bound_cleanup_releases_immutable_failed_family(database, finalizer_evidence):
    _, engine, sessions = database
    original = _failed_frozen_execution(sessions)
    foreign = _job(sessions, "batch-plan-execute")
    state = {"execution_mode": "maintenance_window", "maintenance_window_confirmed": True,
             "unit": "/media/unit"}
    publication_checkpoint = {
        "schema_version": 1, "phase": "manual_cleanup_required",
        "frozen_job_id": original, "manifest_checksum": "a" * 64,
        "cleanup_plan_sha256": "b" * 64,
        "unit": state["unit"], "preview_job_id": 25, "execution_mode": "maintenance_window",
    }
    recovery = _job(sessions, "media-organizer-execute", status="completed",
                    state=_recovery_state(original), checkpoint=publication_checkpoint, retry_of=original)
    cleanup_state = {
        **state, "execution_job_id": recovery, "frozen_job_id": original,
        "plan_sha256": "b" * 64, "manifest_checksum": "a" * 64,
    }
    cleanup = _job(sessions, "media-organizer-cleanup", state=cleanup_state)
    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    assert claim_next_job(engine, sessions, worker_id="worker") == cleanup
    with sessions.begin() as session:
        session.get(WorkJob, recovery).checkpoint_json = json.dumps({
            **publication_checkpoint, "phase": "completed",
            "finalized_by_cleanup_job_id": cleanup,
            "second_scan_needed_moves": 0, "second_scan_renamed_count": 0,
        })
        finalizer = session.get(WorkJob, cleanup)
        finalizer_checkpoint = {
            **cleanup_state, "cleanup_job_id": cleanup, "schema_version": 1,
            "phase": "cleanup-scanned-zero" if finalizer_evidence == "crash-gap" else "completed",
        }
        if finalizer_evidence == "plan":
            finalizer.state_json = json.dumps({**cleanup_state, "approved_job_id": cleanup, "plan_sha256": "e" * 64})
            finalizer_checkpoint["plan_sha256"] = "e" * 64
        elif finalizer_evidence == "checkpoint":
            finalizer_checkpoint["phase"] = "cleanup-verified"
        elif finalizer_evidence == "malformed-checkpoint":
            finalizer_checkpoint["phase"] = ["completed"]
        elif finalizer_evidence == "approval":
            finalizer.state_json = json.dumps({**cleanup_state, "approved_job_id": foreign})
        elif finalizer_evidence == "root":
            root_job = session.get(WorkJob, original)
            root_job.checkpoint_json = json.dumps({
                **json.loads(root_job.checkpoint_json), "manifest_checksum": "e" * 64,
            })
        finalizer.checkpoint_json = json.dumps(finalizer_checkpoint)
        if finalizer_evidence != "crash-gap":
            finalizer.status = "completed"
    if finalizer_evidence == "crash-gap":
        assert recover_interrupted_jobs(engine, sessions, worker_id="worker")["failed_interrupted"] == 1
        assert _status(sessions, cleanup) == "failed"
    assert _status(sessions, original) == "failed"
    want = foreign if finalizer_evidence in {"complete", "crash-gap"} else None
    assert claim_next_job(engine, sessions, worker_id="worker") == want


def test_strict_frozen_job_does_not_reserve(database):
    _, engine, sessions = database
    _failed_frozen_execution(sessions, mode="strict")
    foreign = _job(sessions, "batch-plan-execute")
    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    assert claim_next_job(engine, sessions, worker_id="worker") == foreign


def test_direct_work_job_dispatch_waits_for_filesystem_lock(database):
    settings, engine, sessions = database
    work_id = _job(sessions, "unclassified-mutation")
    returned = threading.Event()

    def dispatch():
        process_work_job(settings, work_id, sessions, engine)
        returned.set()

    with external_holder(settings) as holder:
        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        try:
            assert not returned.wait(0.25)
            assert _status(sessions, work_id) == "queued"
        finally:
            holder.stdin.write("\n")
            holder.stdin.flush()
    assert returned.wait(4)
    thread.join(timeout=4)
    assert _status(sessions, work_id) == "failed"


def _archive_state(settings, name):
    output = settings.data_mount / name
    output.mkdir()
    info = output.stat()
    parent = output.parent.stat()
    return output, {
        "output": str(output), "source": str(output.with_name("source.zip")),
        "output_identity": [str(info.st_dev), str(info.st_ino)],
        "parent_identity": [str(parent.st_dev), str(parent.st_ino)],
    }


def _wait_until(predicate):
    deadline = monotonic() + 4
    while not predicate() and monotonic() < deadline:
        sleep(0.01)
    assert predicate()


def test_startup_recovery_and_archive_cleanup_wait_for_filesystem_lock(database):
    settings, _, sessions = database
    output, state = _archive_state(settings, "interrupted-output")
    part = output / (".nfc-part-" + "6" * 24)
    part.write_text("registered interrupted archive member")
    job_id = _job(sessions, "archive-recovery", status="running", state=state)
    stop = threading.Event()
    worker = threading.Thread(target=worker_loop, args=(settings,),
                              kwargs={"poll_seconds": 0.01, "stop_event": stop}, daemon=True)
    try:
        with external_holder(settings) as holder:
            worker.start()
            sleep(0.25)
            assert _status(sessions, job_id) == "running"
            assert part.exists()
            holder.stdin.write("\n")
            holder.stdin.flush()
        _wait_until(lambda: not part.exists())
        assert _status(sessions, job_id) == "failed"
    finally:
        stop.set()
        worker.join(timeout=4)


def test_archive_task_cancellation_leaves_media_cleanup_to_worker(database):
    settings, _, sessions = database
    output, state = _archive_state(settings, "cancelled-output")
    job_id = _job(sessions, "archive-recovery", state=state)
    with external_holder(settings):
        assert TaskService(sessions).cancel_task(job_id)["status"] == "cancelled"
        assert output.is_dir()
    stop = threading.Event()
    worker = threading.Thread(target=worker_loop, args=(settings,),
                              kwargs={"poll_seconds": 0.01, "stop_event": stop}, daemon=True)
    worker.start()
    try:
        _wait_until(lambda: not output.exists())
    finally:
        stop.set()
        worker.join(timeout=4)


@pytest.mark.parametrize("first_observation", ["missing", "nonempty", "legacy"])
def test_archive_cancellation_does_not_revisit_consumed_or_legacy_output(database, first_observation):
    settings, engine, sessions = database
    output, state = _archive_state(settings, "cancelled-output")
    archived_output = output.with_name("moved-output")
    user_file = output / "user-content"
    if first_observation == "legacy":
        _job(sessions, "archive-recovery", status="cancelled", state=state)
    else:
        job_id = _job(sessions, "archive-recovery", state=state)
        TaskService(sessions).cancel_task(job_id)
        if first_observation == "missing":
            output.rename(archived_output)
        else:
            user_file.write_text("owned by operator")

    assert acquire_worker_ownership(engine, sessions, worker_id="worker")
    with media_mutation_lock(settings):
        cleanup_recovery_after_worker_restart(settings, sessions, "worker", cancelled_only=True)
    if first_observation == "missing":
        archived_output.rename(output)
    elif first_observation == "nonempty":
        assert user_file.read_text() == "owned by operator"
        user_file.unlink()
    with media_mutation_lock(settings):
        cleanup_recovery_after_worker_restart(settings, sessions, "worker", cancelled_only=True)
    assert output.is_dir()
