from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
import app.fs_ops as fs_ops
import app.tasks.handlers_base as handlers_base
from app.config import Settings
from app.execution.utility_wrapper_pair import (
    UtilityWrapperCleanupResult,
    UtilityWrapperLiveGuard,
)
from app.main import create_app
from app.models import AuditEvent, BatchPlan, BatchPlanItem, OperationJournal, WorkJob
from app.service import FileCenterService
from app.planning.stale import StaleItemDetail
from app.worker import process_work_job
from app.workflows.schema import (
    SingleChildWrapperCollapseStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
)


def _setup(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    root = data_dir / "root"
    root.mkdir()
    quarantine = data_dir / ".nas-file-center-trash"
    quarantine.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    settings = Settings(
        config_dir=config,
        database_path=config / "app.db",
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=False,
    )
    app = create_app(settings)
    service: FileCenterService = app.state.service
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: True,
    )

    with service.SessionLocal() as session:
        from app.models import IndexRoot

        row = IndexRoot(root=str(root))
        session.add(row)
        session.commit()
        root_id = int(row.id)

    workflow = service.workflow_service.create_workflow(
        None,
        WorkflowCreateRequest(
            name="zfuse identity convergence",
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

    return client, service, settings, root, int(workflow["id"])


def _enqueue_single_wrapper(client, service, workflow_id: int, root: Path) -> tuple[int, int]:
    source = root / "B" / "C"
    source.mkdir(parents=True)
    (source / "payload.txt").write_text("payload", encoding="utf-8")

    preview = service.workflow_service.preview_workflow(
        workflow_id,
        WorkflowPreviewRequest(page=1, page_size=50),
    )
    candidate = next(
        item
        for item in preview["utility_summary"]["candidates"]
        if Path(item["wrapper_path"]).name == "B"
    )
    generated = service.workflow_service.generate_plan(
        None,
        workflow_id,
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[candidate["candidate_id"]],
        ),
    )
    plan_id = int(generated["plan_id"])
    service.freeze_plan(plan_id)
    validation = service.validate_plan(plan_id)
    assert validation["status"] == "ready"

    response = client.post(f"/api/plans/{plan_id}/execute")
    assert response.status_code == 200
    return plan_id, int(response.json()["work_job_id"])


def test_move_finalizes_paired_cleanup_before_frozen_inode_can_stale(
    tmp_path: Path,
    monkeypatch,
):
    client, service, settings, root, workflow_id = _setup(tmp_path, monkeypatch)
    plan_id, job_id = _enqueue_single_wrapper(client, service, workflow_id, root)

    original_verify = handlers_base._verify_plan_item_and_keep_freshness

    def reject_legacy_cleanup(item_meta, current_settings):
        if item_meta.operation == "rmdir_empty":
            pytest.fail(
                "paired cleanup must be terminal before legacy frozen-inode freshness runs"
            )
        return original_verify(item_meta, current_settings)

    monkeypatch.setattr(
        handlers_base,
        "_verify_plan_item_and_keep_freshness",
        reject_legacy_cleanup,
    )

    assert process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=None,
    ) is True

    assert not (root / "B").exists()
    assert (root / "C" / "payload.txt").read_text(encoding="utf-8") == "payload"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        job = session.get(WorkJob, job_id)
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        journals = list(
            session.scalars(
                select(OperationJournal)
                .where(OperationJournal.plan_id == plan_id)
                .order_by(OperationJournal.sequence)
            )
        )

        assert plan is not None and plan.status == "completed"
        assert job is not None and job.status == "completed"
        assert [item.state for item in items] == ["completed", "completed"]
        assert items[1].reason == (
            "empty wrapper structurally removed under live descriptor authority"
        )
        assert [journal.operation for journal in journals] == ["move", "rmdir_empty"]


def test_cleanup_failure_makes_plan_partial_and_task_failed(
    tmp_path: Path,
    monkeypatch,
):
    client, service, settings, root, workflow_id = _setup(tmp_path, monkeypatch)
    plan_id, job_id = _enqueue_single_wrapper(client, service, workflow_id, root)

    monkeypatch.setattr(
        UtilityWrapperLiveGuard,
        "remove_if_empty",
        lambda self: UtilityWrapperCleanupResult(
            "failed",
            "simulated zfuse live-wrapper identity instability",
        ),
    )

    assert process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=None,
    ) is True

    assert (root / "C" / "payload.txt").read_text(encoding="utf-8") == "payload"
    assert (root / "B").is_dir()

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        job = session.get(WorkJob, job_id)
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )

        assert plan is not None and plan.status == "partial"
        assert [item.state for item in items] == ["completed", "failed"]
        assert "identity instability" in (items[1].reason or "")
        assert job is not None and job.status == "failed"
        assert job.error_code == "BATCH_PLAN_NOT_COMPLETED"
        assert "status partial" in (job.error_text or "")
        assert "item #2 rmdir_empty" in (job.error_text or "")
        assert "identity instability" in (job.error_text or "")



def test_later_compat_move_can_rebase_inode_after_trusted_pair_completed(
    tmp_path: Path,
    monkeypatch,
):
    client, service, settings, root, workflow_id = _setup(tmp_path, monkeypatch)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda *_args, **_kwargs: True,
    )

    for wrapper_name, child_name, payload in (
        ("B", "C", "alpha"),
        ("D", "E", "beta"),
    ):
        child = root / wrapper_name / child_name
        child.mkdir(parents=True)
        (child / "payload.txt").write_text(payload, encoding="utf-8")

    preview = service.workflow_service.preview_workflow(
        workflow_id,
        WorkflowPreviewRequest(page=1, page_size=50),
    )
    selected = [
        item["candidate_id"]
        for item in preview["utility_summary"]["candidates"]
        if Path(item["wrapper_path"]).name in {"B", "D"}
    ]
    assert len(selected) == 2

    generated = service.workflow_service.generate_plan(
        None,
        workflow_id,
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=selected,
        ),
    )
    plan_id = int(generated["plan_id"])
    service.freeze_plan(plan_id)
    validation = service.validate_plan(plan_id)
    assert validation["status"] == "ready"

    response = client.post(f"/api/plans/{plan_id}/execute")
    assert response.status_code == 200
    job_id = int(response.json()["work_job_id"])

    original_verify = handlers_base._verify_plan_item_and_keep_freshness
    simulated_source = str(root / "D" / "E")

    def simulate_post_mutation_inode_drift(item_meta, current_settings):
        meta = handlers_base._utility_single_child_meta(item_meta)
        if (
            item_meta.operation == "move"
            and item_meta.source_path == simulated_source
            and meta is not None
            and "identity_rebase" not in meta
        ):
            return False, StaleItemDetail(
                item_id=item_meta.id,
                source_path=item_meta.source_path,
                reason="filesystem_identity_changed",
                expected={
                    "device": item_meta.expected_device,
                    "inode": item_meta.expected_inode,
                },
                actual={
                    "device": item_meta.expected_device,
                    "inode": int(item_meta.expected_inode or 0) + 999,
                    "object_type": "directory",
                },
            )
        return original_verify(item_meta, current_settings)

    monkeypatch.setattr(
        handlers_base,
        "_verify_plan_item_and_keep_freshness",
        simulate_post_mutation_inode_drift,
    )

    assert process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=None,
    ) is True

    assert not (root / "B").exists()
    assert not (root / "D").exists()
    assert (root / "C" / "payload.txt").read_text(encoding="utf-8") == "alpha"
    assert (root / "E" / "payload.txt").read_text(encoding="utf-8") == "beta"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        job = session.get(WorkJob, job_id)
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        rebases = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.operation == "utility.identity_rebase"
                )
            )
        )

        assert plan is not None and plan.status == "completed"
        assert job is not None and job.status == "completed"
        assert [item.state for item in items] == [
            "completed",
            "completed",
            "completed",
            "completed",
        ]
        second_move_meta = json.loads(items[2].metadata_json or "{}")
        assert second_move_meta["identity_rebase"]["reason"] == (
            "trusted_predecessor_completed_and_logical_binding_unchanged"
        )
        assert len(rebases) == 1


def test_first_compat_move_identity_change_still_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    client, service, settings, root, workflow_id = _setup(tmp_path, monkeypatch)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda *_args, **_kwargs: True,
    )

    plan_id, job_id = _enqueue_single_wrapper(client, service, workflow_id, root)

    original_verify = handlers_base._verify_plan_item_and_keep_freshness

    def reject_first_move_identity(item_meta, current_settings):
        meta = handlers_base._utility_single_child_meta(item_meta)
        if (
            item_meta.operation == "move"
            and meta is not None
            and "identity_rebase" not in meta
        ):
            return False, StaleItemDetail(
                item_id=item_meta.id,
                source_path=item_meta.source_path,
                reason="filesystem_identity_changed",
                expected={
                    "device": item_meta.expected_device,
                    "inode": item_meta.expected_inode,
                },
                actual={
                    "device": item_meta.expected_device,
                    "inode": int(item_meta.expected_inode or 0) + 111,
                    "object_type": "directory",
                },
            )
        return original_verify(item_meta, current_settings)

    monkeypatch.setattr(
        handlers_base,
        "_verify_plan_item_and_keep_freshness",
        reject_first_move_identity,
    )

    assert process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=None,
    ) is True

    assert (root / "B" / "C" / "payload.txt").read_text(encoding="utf-8") == "payload"
    assert not (root / "C").exists()

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        job = session.get(WorkJob, job_id)
        assert plan is not None and plan.status == "partial"
        assert job is not None and job.status == "failed"
        assert "filesystem_identity_changed" in (job.error_text or "")


def test_directory_transplant_transaction_namespace_survives_reused_plan_id(
    tmp_path: Path,
    monkeypatch,
):
    client, service, settings, root, workflow_id = _setup(tmp_path, monkeypatch)

    # Force the exact NAS/zfuse fallback that owns the durable transplant state.
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_directory_rename_noreplace_compat_at",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        single_child_wrapper_module,
        "directory_transplant_preflight",
        lambda *_args, **_kwargs: True,
    )

    def unsupported_noreplace(*_args, **_kwargs):
        raise OSError(errno.EOPNOTSUPP, "simulated NAS noreplace fallback")

    monkeypatch.setattr(fs_ops, "rename_noreplace", unsupported_noreplace)
    monkeypatch.setattr(
        fs_ops,
        "rename_directory_noreplace_compat",
        unsupported_noreplace,
    )

    plan_id, job_id = _enqueue_single_wrapper(
        client,
        service,
        workflow_id,
        root,
    )

    with service.SessionLocal() as session:
        move_row = session.scalar(
            select(BatchPlanItem).where(
                BatchPlanItem.plan_id == plan_id,
                BatchPlanItem.operation == "move",
            )
        )
        assert move_row is not None
        move_sequence = int(move_row.sequence)

    # Reproduce a NAS that retained transaction metadata from an older database
    # whose autoincrement IDs also started at Plan #1 / item #1. Before this
    # fix, the new move loads this legacy state solely by plan_id + sequence and
    # fails with:
    #   EEXIST Existing directory MOVE transaction does not match this frozen item
    legacy_tx_dir = (
        Path(settings.quarantine_root)
        / ".utility-move-tx"
        / str(plan_id)
        / f"item-{move_sequence}"
    )
    legacy_tx_dir.mkdir(parents=True)
    legacy_state = {
        "version": 1,
        "token": "historical-plan-id-reuse",
        "phase": "migrating",
        "source": str(root / "historical" / "child"),
        "target": str(root / "historical-child"),
        "source_device": 999,
        "source_inode": 999,
        "created_dirs": {"": [999, 999]},
        "published_symlinks": {},
    }
    legacy_state_path = legacy_tx_dir / "state.json"
    legacy_state_path.write_text(
        json.dumps(legacy_state),
        encoding="utf-8",
    )

    assert process_work_job(
        settings,
        job_id,
        session_factory=service.SessionLocal,
        engine=service.engine,
        worker_id=None,
    ) is True

    assert not (root / "B").exists()
    assert (root / "C" / "payload.txt").read_text(encoding="utf-8") == "payload"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        job = session.get(WorkJob, job_id)
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert plan is not None and plan.status == "completed"
        assert job is not None and job.status == "completed"
        assert [item.state for item in items] == ["completed", "completed"]

        move_meta = json.loads(items[0].metadata_json or "{}")
        transaction_id = move_meta["execution"]["directory_move_transaction_id"]
        assert isinstance(transaction_id, str)
        assert len(transaction_id) == 32

    # The live transaction used a unique namespace and was cleaned after
    # completion. The unrelated legacy state is deliberately retained as
    # forensic evidence rather than being silently deleted.
    live_tx_dir = (
        Path(settings.quarantine_root)
        / ".utility-move-tx"
        / str(plan_id)
        / f"item-{move_sequence}-{transaction_id}"
    )
    assert not live_tx_dir.exists()
    assert json.loads(legacy_state_path.read_text(encoding="utf-8")) == legacy_state
