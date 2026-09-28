from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch.plans import OperationItem
from app.config import Settings
from app.execution.executor import execute_item
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexRoot, utcnow
from app.tasks.utility_structural_cleanup_compat import reconcile_utility_structural_cleanup
from app.worker import process_work_job


def _client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        allow_mutation=True,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login.status_code == 200
    return app, client, data, settings


def _rules() -> dict:
    return {
        "version": 1,
        "directory_depth": {"enabled": False, "rename_from_depth": 2},
        "file_numbering": {
            "enabled": False,
            "start": 1,
            "padding": 3,
            "sort": "natural_name",
            "extension_mode": "preserve",
        },
        "latest_child_prefix": {
            "enabled": False,
            "prefix": "New ",
            "timestamp": "mtime_ns",
        },
        "single_child_wrapper_collapse": {
            "enabled": True,
            "wrapper_depth": 2,
            "child_type": "directory",
        },
    }


def _profile(client: TestClient, root: Path) -> int:
    response = client.post(
        "/api/organizer-profiles",
        json={
            "name": "C3 structural",
            "root": str(root),
            "recursive": True,
            "rename_template": "{name}",
            "advanced_rules": _rules(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _force_native_probe(monkeypatch):
    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: True,
    )


def _load_items(app, plan_id: int) -> list[BatchPlanItem]:
    with app.state.service.SessionLocal() as session:
        return list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )


def _as_operation(row: BatchPlanItem) -> OperationItem:
    return OperationItem(
        sequence=row.sequence,
        operation=row.operation,
        source=Path(row.source_path),
        target=Path(row.target_path) if row.target_path else None,
        expected_size=row.expected_size,
        expected_hash=row.expected_hash,
        state=row.state,
        expected_mtime_ns=row.expected_mtime_ns,
        expected_device=row.expected_device,
        expected_inode=row.expected_inode,
    )


def test_standalone_stage_a_generates_exact_move_rmdir_pair_and_executes_with_delete_disabled(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)
    (child / "one.txt").write_text("1")
    (child / "two.txt").write_text("2")

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    assert preview["structural_required"] is True

    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        metadata = json.loads(plan.metadata_json)
        assert metadata["source"] == "organizer"
        assert metadata["organizer_advanced"] is True
        assert metadata["organizer_stage"] == "structural"
        assert metadata["organizer_structural_action"] == "single_child_wrapper_collapse"
        assert metadata["preview_digest"] == preview["preview_digest"]

        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert [item.operation for item in items] == ["move", "rmdir_empty"]
        assert items[0].source_path == str(child)
        assert items[0].target_path == str(root / "A" / "Child")
        assert items[1].source_path == str(wrapper)
        move_meta = json.loads(items[0].metadata_json)
        cleanup_meta = json.loads(items[1].metadata_json)
        assert move_meta["candidate_id"] == cleanup_meta["candidate_id"]
        assert move_meta["organizer_structural"] is True

    freeze = client.post(f"/api/plans/{plan_id}/freeze")
    assert freeze.status_code == 200, freeze.text
    validate = client.post(f"/api/plans/{plan_id}/validate")
    assert validate.status_code == 200, validate.text
    assert validate.json()["status"] == "ready"

    execute = client.post(f"/api/plans/{plan_id}/execute")
    assert execute.status_code == 200, execute.text
    process_work_job(settings, execute.json()["work_job_id"])

    assert (root / "A" / "Child").is_dir()
    assert not wrapper.exists()
    assert (root / "A" / "Child" / "one.txt").read_text() == "1"

    plan_after = client.get(f"/api/plans/{plan_id}").json()
    assert plan_after["status"] == "completed"
    assert [item["state"] for item in plan_after["items"]] == ["completed", "completed"]


def test_stage_a_freeze_rejects_candidate_identity_change_after_generate(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 200
    plan_id = created.json()["id"]

    old_child = data / "old-child"
    child.rename(old_child)
    child.mkdir()

    freeze = client.post(f"/api/plans/{plan_id}/freeze")
    assert freeze.status_code == 409
    assert "WRAPPER_CHILD_IDENTITY_CHANGED" in freeze.json()["detail"]

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"


def test_stage_a_target_appearance_after_freeze_marks_plan_stale(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    child = root / "A" / "Wrapper" / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200

    target = root / "A" / "Child"
    target.mkdir()
    (target / "foreign.txt").write_text("must survive")

    validation = app.state.service.validate_plan(plan_id)
    assert validation["status"] == "stale"
    move = next(item for item in validation["items"] if item["operation"] == "move")
    assert move["reason"] == "target_appeared"
    assert (target / "foreign.txt").read_text() == "must survive"
    assert child.is_dir()


def test_stage_a_cleanup_authority_requires_exact_organizer_structural_context(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    rows = _load_items(app, plan_id)
    move_item, cleanup_item = map(_as_operation, rows)

    moved = execute_item(
        move_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
    )
    assert moved.state == "completed"

    with app.state.service.SessionLocal() as session:
        move_row = session.get(BatchPlanItem, rows[0].id)
        plan = session.get(BatchPlan, plan_id)
        assert move_row is not None and plan is not None
        move_row.state = "completed"
        metadata = json.loads(plan.metadata_json)
        metadata["organizer_stage"] = "rename"
        plan.metadata_json = json.dumps(metadata)
        session.commit()

    cleanup = execute_item(
        cleanup_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert cleanup.state == "skipped"
    assert cleanup.reason == "permanent deletion is disabled"
    assert wrapper.is_dir()


def test_stage_a_third_party_entry_after_move_prevents_wrapper_removal(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    rows = _load_items(app, plan_id)
    move_item, cleanup_item = map(_as_operation, rows)

    assert execute_item(
        move_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
    ).state == "completed"

    with app.state.service.SessionLocal() as session:
        move_row = session.get(BatchPlanItem, rows[0].id)
        assert move_row is not None
        move_row.state = "completed"
        session.commit()

    intruder = wrapper / "third-party.txt"
    intruder.write_text("must survive")

    cleanup = execute_item(
        cleanup_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert cleanup.state != "completed"
    assert wrapper.is_dir()
    assert intruder.read_text() == "must survive"
    assert (root / "A" / "Child").is_dir()


def test_workflow_organizer_stage_a_generates_structural_pair(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "WorkflowOrganizer"
    (root / "A" / "Wrapper" / "Child").mkdir(parents=True)

    with app.state.service.SessionLocal() as session:
        index_root = IndexRoot(root=str(root))
        session.add(index_root)
        session.commit()
        session.refresh(index_root)
        root_id = index_root.id

    created_workflow = client.post(
        "/api/workflows",
        json={
            "name": "C3 organizer workflow",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "scan", "type": "scan", "root_ids": [root_id]},
                    {
                        "id": "organize",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "C3 workflow",
                            "recursive": True,
                            "rename_template": "{name}",
                            "statistics_template": "[{files}F]",
                            "advanced_rules": _rules(),
                        },
                    },
                ],
            },
        },
    )
    assert created_workflow.status_code == 201, created_workflow.text
    workflow_id = created_workflow.json()["id"]

    preview = client.post(f"/api/workflows/{workflow_id}/preview", json={}).json()
    organizer_summary = preview["organizer_summary"]
    assert organizer_summary["structural_required"] is True

    generated = client.post(
        f"/api/workflows/{workflow_id}/generate-plan",
        json={
            "expected_compile_digest": preview["compile_digest"],
            "expected_preview_digest": organizer_summary["preview_digest"],
        },
    )
    assert generated.status_code == 201, generated.text
    plan_id = generated.json()["plan_id"]

    with app.state.service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        metadata = json.loads(plan.metadata_json)
        assert metadata["source"] == "workflow"
        assert metadata["workflow_mode"] == "organizer"
        assert metadata["organizer_stage"] == "structural"
        assert metadata["organizer_structural_action"] == "single_child_wrapper_collapse"
        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert [item.operation for item in items] == ["move", "rmdir_empty"]
        assert json.loads(items[1].metadata_json)["candidate_id"]


@pytest.mark.parametrize(
    ("shape", "expected_conflict"),
    [
        ("hidden_second_entry", None),
        ("file_child", "WRAPPER_CHILD_NOT_DIRECTORY"),
        ("wrapper_symlink", None),
        ("child_symlink", "WRAPPER_CHILD_SYMLINK"),
        ("target_exists", "WRAPPER_TARGET_EXISTS"),
    ],
)
def test_organizer_preview_blocks_unsafe_wrapper_shapes(
    tmp_path: Path,
    shape: str,
    expected_conflict: str | None,
):
    _app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    parent = root / "A"
    parent.mkdir(parents=True)
    wrapper = parent / "Wrapper"
    outside = data / "outside"
    outside.mkdir()

    if shape == "wrapper_symlink":
        os.symlink(outside, wrapper)
    else:
        wrapper.mkdir()
        if shape == "file_child":
            (wrapper / "Child").write_text("not a directory")
        elif shape == "child_symlink":
            target = outside / "Child"
            target.mkdir()
            os.symlink(target, wrapper / "Child")
        else:
            (wrapper / "Child").mkdir()
            if shape == "hidden_second_entry":
                (wrapper / ".hidden").write_text("must count")
            elif shape == "target_exists":
                (parent / "Child").mkdir()

    profile_id = _profile(client, root)
    response = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["structural_required"] is False

    wrapper_rows = [
        row for row in preview["proposals"]
        if row.get("proposal_type") == "wrapper_collapse"
    ]
    if expected_conflict is None:
        assert wrapper_rows == []
    else:
        assert any(row.get("conflict_reason") == expected_conflict for row in wrapper_rows)


def test_stage_a_generate_rejects_unsupported_filesystem(
    tmp_path: Path,
    monkeypatch,
):
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    (root / "A" / "Wrapper" / "Child").mkdir(parents=True)
    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    assert preview["structural_required"] is True

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
        lambda *_args, **_kwargs: False,
    )

    with app.state.service.SessionLocal() as session:
        before = len(list(session.scalars(select(BatchPlan))))

    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    assert created.status_code == 400
    assert "UNSUPPORTED_FILESYSTEM" in created.json()["detail"]

    with app.state.service.SessionLocal() as session:
        after = len(list(session.scalars(select(BatchPlan))))
    assert after == before


def test_stage_a_freeze_rejects_wrapper_aba_and_candidate_digest_mismatch(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    (wrapper / "Child").mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]

    with app.state.service.SessionLocal() as session:
        first = session.scalar(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence)
        )
        assert first is not None
        metadata = json.loads(first.metadata_json)
        metadata["candidate_id"] = "0" * 64
        first.metadata_json = json.dumps(metadata)
        session.commit()

    digest_reject = client.post(f"/api/plans/{plan_id}/freeze")
    assert digest_reject.status_code == 409
    assert "STRUCTURAL_CANDIDATE_DIGEST_MISMATCH" in digest_reject.json()["detail"]

    # Generate a fresh plan, then replace the wrapper pathname with a new inode.
    preview2 = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created2 = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview2["preview_digest"]},
    )
    plan2 = created2.json()["id"]
    detached = root / "A" / "Wrapper-old"
    wrapper.rename(detached)
    (wrapper / "Child").mkdir(parents=True)

    aba_reject = client.post(f"/api/plans/{plan2}/freeze")
    assert aba_reject.status_code == 409
    assert "WRAPPER_IDENTITY_CHANGED" in aba_reject.json()["detail"]


def test_stage_a_cleanup_requires_completed_move_and_full_candidate_binding(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    (wrapper / "Child").mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    rows = _load_items(app, plan_id)
    move_item, cleanup_item = map(_as_operation, rows)

    moved = execute_item(
        move_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
    )
    assert moved.state == "completed"

    incomplete = execute_item(
        cleanup_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert incomplete.state == "skipped"
    assert incomplete.reason == "permanent deletion is disabled"
    assert wrapper.is_dir()

    with app.state.service.SessionLocal() as session:
        move_row = session.get(BatchPlanItem, rows[0].id)
        assert move_row is not None
        move_row.state = "completed"
        metadata = json.loads(move_row.metadata_json)
        metadata["child_inode"] = int(metadata["child_inode"]) + 1
        move_row.metadata_json = json.dumps(metadata)
        session.commit()

    mismatched = execute_item(
        cleanup_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert mismatched.state == "skipped"
    assert mismatched.reason == "permanent deletion is disabled"
    assert wrapper.is_dir()


def test_stage_a_cleanup_recovery_resumes_only_empty_rmdir_without_repeating_move(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    rows = _load_items(app, plan_id)
    move_item, cleanup_item = map(_as_operation, rows)

    assert execute_item(
        move_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
    ).state == "completed"
    target = root / "A" / "Child"
    assert target.is_dir()
    assert not child.exists()

    with app.state.service.SessionLocal() as session:
        move_row = session.get(BatchPlanItem, rows[0].id)
        cleanup_row = session.get(BatchPlanItem, rows[1].id)
        assert move_row is not None and cleanup_row is not None
        move_row.state = "completed"
        cleanup_row.state = "executing"
        meta = json.loads(cleanup_row.metadata_json)
        meta["execution"] = {
            "phase": "intent",
            "operation": "rmdir_empty",
            "source_stat": {
                "device": cleanup_row.expected_device,
                "inode": cleanup_row.expected_inode,
            },
        }
        cleanup_row.metadata_json = json.dumps(meta)
        handled = reconcile_utility_structural_cleanup(
            session,
            cleanup_row,
            plan_id,
            999,
            1,
            settings,
            utcnow(),
        )
        assert handled is True
        assert cleanup_row.state == "planned"
        session.commit()

    cleanup_row = _load_items(app, plan_id)[1]
    resumed = execute_item(
        _as_operation(cleanup_row),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert resumed.state == "completed"
    assert target.is_dir()
    assert not wrapper.exists()


def test_stage_a_cleanup_uses_only_one_non_recursive_rmdir(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    (wrapper / "Child").mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    rows = _load_items(app, plan_id)
    move_item, cleanup_item = map(_as_operation, rows)
    assert execute_item(
        move_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
    ).state == "completed"
    with app.state.service.SessionLocal() as session:
        move_row = session.get(BatchPlanItem, rows[0].id)
        assert move_row is not None
        move_row.state = "completed"
        session.commit()

    real_rmdir = os.rmdir
    calls: list[tuple[object, object]] = []

    def guarded_rmdir(path, *args, **kwargs):
        calls.append((path, kwargs.get("dir_fd")))
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", lambda *_a, **_k: pytest.fail("recursive/payload unlink forbidden"))
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: pytest.fail("recursive delete forbidden"))
    monkeypatch.setattr(os, "rmdir", guarded_rmdir)

    result = execute_item(
        cleanup_item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=data / ".trash",
        plan_id=str(plan_id),
        session_factory=app.state.service.SessionLocal,
    )
    assert result.state == "completed"
    assert len(calls) == 1
    assert not wrapper.exists()


def test_stage_a_completion_invalidates_old_preview_for_stage_b(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, settings = _client(tmp_path)
    root = data / "Organizer"
    child = root / "A" / "Wrapper" / "Child"
    child.mkdir(parents=True)
    (child / "photo.JPG").write_bytes(b"x")

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    old_digest = preview["preview_digest"]
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": old_digest},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    assert client.post(f"/api/plans/{plan_id}/validate").json()["status"] == "ready"
    execution = client.post(f"/api/plans/{plan_id}/execute")
    assert execution.status_code == 200
    process_work_job(settings, execution.json()["work_job_id"])

    stale = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": old_digest},
    )
    assert stale.status_code == 400
    assert "Preview 已变化" in stale.json()["detail"]

    fresh = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert fresh.status_code == 200
    assert fresh.json()["preview_digest"] != old_digest


def test_stage_a_validate_rejects_hidden_entry_added_after_freeze(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, _settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    (wrapper / "Child").mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200

    (wrapper / ".hidden-after-freeze").write_text("must block move")
    validation = app.state.service.validate_plan(plan_id)
    assert validation["status"] == "stale"
    move = next(item for item in validation["items"] if item["operation"] == "move")
    assert move["reason"] == "wrapper_shape_changed"
    assert (wrapper / "Child").is_dir()
    assert not (root / "A" / "Child").exists()


def test_stage_a_execute_rejects_candidate_digest_drift_without_moving_child(
    tmp_path: Path,
    monkeypatch,
):
    _force_native_probe(monkeypatch)
    app, client, data, settings = _client(tmp_path)
    root = data / "Organizer"
    wrapper = root / "A" / "Wrapper"
    child = wrapper / "Child"
    child.mkdir(parents=True)

    profile_id = _profile(client, root)
    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview").json()
    created = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"expected_preview_digest": preview["preview_digest"]},
    )
    plan_id = created.json()["id"]
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    assert client.post(f"/api/plans/{plan_id}/validate").json()["status"] == "ready"

    with app.state.service.SessionLocal() as session:
        rows = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert len(rows) == 2
        for row in rows:
            meta = json.loads(row.metadata_json)
            meta["candidate_id"] = "f" * 64
            row.metadata_json = json.dumps(meta)
        session.commit()

    execution = client.post(f"/api/plans/{plan_id}/execute")
    assert execution.status_code == 200
    ok = process_work_job(settings, execution.json()["work_job_id"])
    assert ok is True
    assert child.is_dir()
    assert wrapper.is_dir()
    assert not (root / "A" / "Child").exists()
