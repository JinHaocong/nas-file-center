import errno
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
import app.execution.utility_wrapper_pair as utility_wrapper_pair_module
from app.batch_utilities.errors import BatchUtilityPreviewChangedError
from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, IndexRoot, TaskLock, WorkJob, utcnow
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler
from app.workflows.errors import WorkflowDigestMismatchError
from app.worker import process_work_job
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


@pytest.fixture
def utility_service_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    root = data_dir / "root1"
    root.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=config_dir / "app.db",
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine,
        protect_last_file=True,
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        session.add(idx)
        session.commit()
        root_id = idx.id

    workflow = service.workflow_service.create_workflow(
        None,
        WorkflowCreateRequest(
            name="Collapse wrappers",
            definition=WorkflowDefinition(
                schema_version=1,
                mode="utility",
                steps=[
                    SingleChildWrapperCollapseStep(
                        id="collapse",
                        type="single_child_wrapper_collapse",
                        root_id=root_id,
                        subpath="",
                    )
                ],
            ),
        ),
    )

    return {
        "service": service,
        "workflow_id": workflow["id"],
        "root_id": root_id,
        "root": root,
        "tmp_path": tmp_path,
    }


def _preview(env):
    return env["service"].workflow_service.preview_workflow(
        env["workflow_id"],
        WorkflowPreviewRequest(page=1, page_size=50),
    )


def _candidate(preview: dict, wrapper_name: str) -> dict:
    return next(
        c
        for c in preview["utility_summary"]["candidates"]
        if Path(c["wrapper_path"]).name == wrapper_name
    )


def _plan_count(env) -> int:
    with env["service"].SessionLocal() as session:
        return len(session.scalars(select(BatchPlan)).all())


def test_generate_selected_subset_persists_exact_pair_and_no_filesystem_mutation(utility_service_env):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)
    (root / "B2" / "C2").mkdir(parents=True)

    preview = _preview(env)
    assert _plan_count(env) == 0
    b2 = _candidate(preview, "B2")

    generated = env["service"].workflow_service.generate_plan(
        None,
        env["workflow_id"],
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[b2["candidate_id"]],
        ),
    )

    assert generated["status"] == "draft"
    assert generated["expected_changes"] == 2
    assert (root / "B2" / "C2").is_dir()
    assert not (root / "C2").exists()

    with env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, generated["plan_id"])
        assert plan is not None
        assert plan.status == "draft"
        metadata = json.loads(plan.metadata_json or "{}")
        assert metadata["workflow_mode"] == "utility"
        assert metadata["runtime_inputs"] == {
            "root_id": env["root_id"],
            "subpath": "",
        }
        items = session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan.id)
            .order_by(BatchPlanItem.sequence.asc())
        ).all()
        assert [(item.operation, item.source_path, item.target_path) for item in items] == [
            ("move", str(root / "B2" / "C2"), str(root / "C2")),
            ("rmdir_empty", str(root / "B2"), None),
        ]
        assert all("B1" not in item.source_path for item in items)


def test_regular_file_wrapper_generate_freeze_validate_execute_with_no_clobber_fallback(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    service = env["service"]
    root = env["root"]
    wrapper = root / "001-1"
    wrapper.mkdir()
    child = wrapper / "001"
    child.write_bytes(b"payload")

    preview = _preview(env)
    candidate = _candidate(preview, "001-1")
    assert candidate["state"] == "READY"
    assert candidate["selectable"] is True
    assert candidate["child_object_type"] == "file"

    generated = service.workflow_service.generate_plan(
        None,
        env["workflow_id"],
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[candidate["candidate_id"]],
        ),
    )
    plan_id = generated["plan_id"]
    assert generated["status"] == "draft"

    with service.SessionLocal() as session:
        rows = session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence.asc())
        ).all()
        assert len(rows) == 2
        move_meta = json.loads(rows[0].metadata_json or "{}")
        remove_meta = json.loads(rows[1].metadata_json or "{}")
        assert move_meta["child_object_type"] == "file"
        assert remove_meta["child_object_type"] == "file"

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    validated = service.validate_plan(plan_id)
    assert validated["status"] == "ready"

    service.settings.allow_mutation = True
    assert service.settings.allow_delete is False

    def no_native_noreplace(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "forced compat path")

    import app.fs_ops as fs_ops_module

    monkeypatch.setattr(fs_ops_module, "rename_noreplace", no_native_noreplace)

    worker_id = "utility-regular-file-worker"
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan_id}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = int(job.id)

    handler = get_handler("batch-plan-execute")
    assert handler is not None

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(
            service.engine,
            service.SessionLocal,
            job_id,
            worker_id=worker_id,
        )
        handler.run(job, context, service.settings)

    target = root / "001"
    assert target.is_file()
    assert target.read_bytes() == b"payload"
    assert not child.exists()
    assert not wrapper.exists()

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"
        rows = session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence.asc())
        ).all()
        assert [row.state for row in rows] == ["completed", "completed"]


@pytest.mark.parametrize("mutation", ["target", "hidden", "aba"])
def test_generate_rejects_discovery_change_and_persists_zero_draft(utility_service_env, mutation):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    if mutation == "target":
        (root / "C1").mkdir()
    elif mutation == "hidden":
        (root / "B1" / ".hidden").write_text("changed")
    else:
        old_child = env["tmp_path"] / "old-C1"
        (root / "B1" / "C1").rename(old_child)
        (root / "B1" / "C1").mkdir()

    with pytest.raises(WorkflowDigestMismatchError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0


def test_generate_wrapper_detach_during_recompile_is_preview_changed_with_zero_draft(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    root = env["root"]
    wrapper = root / "B1"
    (wrapper / "C1").mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    detached = env["tmp_path"] / "detached-B1"
    real_scandir = os.scandir
    scandir_count = 0
    swapped = False

    def swap_wrapper_before_generate_wrapper_scan(path):
        nonlocal scandir_count, swapped
        scandir_count += 1
        if scandir_count == 2:
            swapped = True
            wrapper.rename(detached)
            (wrapper / "C1").mkdir(parents=True)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_wrapper_before_generate_wrapper_scan)

    with pytest.raises(BatchUtilityPreviewChangedError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert swapped is True
    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0
    assert (detached / "C1").is_dir()
    assert (wrapper / "C1").is_dir()


def test_generate_child_replacement_during_recompile_is_preview_changed_with_zero_draft(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    root = env["root"]
    wrapper = root / "B1"
    child = wrapper / "C1"
    child.mkdir(parents=True)

    preview = _preview(env)
    candidate = _candidate(preview, "B1")
    assert _plan_count(env) == 0

    detached = env["tmp_path"] / "detached-C1"
    real_entry_exists_at = single_child_wrapper_module._entry_exists_at
    swapped = False

    def swap_child_before_generate_target_check(scope_fd, entry_name, target_path):
        nonlocal swapped
        if not swapped:
            swapped = True
            child.rename(detached)
            child.mkdir()
        return real_entry_exists_at(scope_fd, entry_name, target_path)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "_entry_exists_at",
        swap_child_before_generate_target_check,
    )

    with pytest.raises(BatchUtilityPreviewChangedError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=preview["compile_digest"],
                selected_candidate_ids=[candidate["candidate_id"]],
            ),
        )

    assert swapped is True
    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0
    assert detached.is_dir()
    assert child.is_dir()


def test_candidate_id_from_another_preview_is_rejected(utility_service_env):
    env = utility_service_env
    root = env["root"]
    (root / "B1" / "C1").mkdir(parents=True)

    first = _preview(env)
    old_id = _candidate(first, "B1")["candidate_id"]

    old_child = env["tmp_path"] / "old-C1"
    (root / "B1" / "C1").rename(old_child)
    (root / "B1" / "C1").mkdir()
    second = _preview(env)
    new_id = _candidate(second, "B1")["candidate_id"]
    assert new_id != old_id

    with pytest.raises(WorkflowDigestMismatchError) as exc:
        env["service"].workflow_service.generate_plan(
            None,
            env["workflow_id"],
            WorkflowGeneratePlanRequest(
                expected_compile_digest=second["compile_digest"],
                selected_candidate_ids=[old_id],
            ),
        )

    assert exc.value.code == "PREVIEW_CHANGED"
    assert _plan_count(env) == 0


def _prepare_directory_wrapper_plan_for_execution(env, wrapper_name: str = "B-live"):
    service = env["service"]
    root = env["root"]
    wrapper = root / wrapper_name
    child = wrapper / "C-live"
    (child / "nested").mkdir(parents=True)
    (child / "payload.txt").write_text("payload", encoding="utf-8")
    (child / "nested" / "nested.txt").write_text("nested", encoding="utf-8")

    preview = _preview(env)
    candidate = _candidate(preview, wrapper_name)
    assert candidate["state"] == "READY"
    assert candidate["selectable"] is True

    generated = service.workflow_service.generate_plan(
        None,
        env["workflow_id"],
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[candidate["candidate_id"]],
        ),
    )
    plan_id = generated["plan_id"]
    service.freeze_plan(plan_id)
    validated = service.validate_plan(plan_id)
    assert validated["status"] == "ready"
    service.settings.allow_mutation = True
    return plan_id, wrapper, child, root / "C-live"


def _seed_running_plan_job(service, plan_id: int, worker_id: str) -> int:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan_id}),
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.commit()
        return int(job.id)


def test_directory_wrapper_cleanup_ignores_frozen_wrapper_inode_drift_under_live_fd_authority(
    utility_service_env,
):
    env = utility_service_env
    service = env["service"]
    plan_id, wrapper, child, target = _prepare_directory_wrapper_plan_for_execution(env)

    # Simulate the real zfuse symptom: the frozen wrapper identity no longer
    # matches by cleanup time. The paired MOVE source identity remains valid.
    with service.SessionLocal() as session:
        rows = list(session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence.asc())
        ))
        assert [row.operation for row in rows] == ["move", "rmdir_empty"]
        cleanup = rows[1]
        cleanup.expected_inode = int(cleanup.expected_inode or 1) + 10_000_000
        session.commit()

    worker_id = "utility-live-wrapper-worker"
    job_id = _seed_running_plan_job(service, plan_id, worker_id)
    handler = get_handler("batch-plan-execute")
    assert handler is not None

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        context = JobContext(
            service.engine,
            service.SessionLocal,
            job_id,
            worker_id=worker_id,
        )
        handler.run(job, context, service.settings)

    assert not child.exists()
    assert not wrapper.exists()
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"
    assert (target / "nested" / "nested.txt").read_text(encoding="utf-8") == "nested"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        rows = list(session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence.asc())
        ))
        assert plan is not None
        assert plan.status == "completed"
        assert [row.state for row in rows] == ["completed", "completed"]
        assert rows[1].reason == (
            "empty wrapper structurally removed under live descriptor authority"
        )


def test_incomplete_wrapper_cleanup_marks_work_job_failed_instead_of_completed(
    utility_service_env,
    monkeypatch,
):
    env = utility_service_env
    service = env["service"]
    plan_id, wrapper, child, target = _prepare_directory_wrapper_plan_for_execution(
        env,
        wrapper_name="B-partial",
    )

    def fail_cleanup(_self):
        return utility_wrapper_pair_module.UtilityWrapperCleanupResult(
            "failed",
            "simulated live cleanup failure",
        )

    monkeypatch.setattr(
        utility_wrapper_pair_module.UtilityWrapperLiveGuard,
        "remove_if_empty",
        fail_cleanup,
    )

    worker_id = "utility-partial-worker"
    job_id = _seed_running_plan_job(service, plan_id, worker_id)

    ok = process_work_job(
        service.settings,
        job_id,
        service.SessionLocal,
        service.engine,
        worker_id=worker_id,
    )
    assert ok is False

    assert not child.exists()
    assert wrapper.is_dir()
    assert list(wrapper.iterdir()) == []
    assert (target / "payload.txt").read_text(encoding="utf-8") == "payload"

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        plan = session.get(BatchPlan, plan_id)
        rows = list(session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence.asc())
        ))
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "UTILITY_PLAN_NOT_COMPLETED"
        assert plan is not None
        assert plan.status == "partial"
        assert [row.state for row in rows] == ["completed", "failed"]
        assert rows[1].reason == "simulated live cleanup failure"
