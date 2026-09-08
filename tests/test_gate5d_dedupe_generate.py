from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, QuarantineEntry, ScanJob, WorkJob, utcnow
from app.planning.dedupe_generate import DedupeDraftIntent, build_advanced_dedupe_draft_intents
from app.planning.dedupe_preview import (
    DedupeEmptyPlanError,
    DedupePreviewChangedError,
    compile_advanced_dedupe_preview,
    compute_current_dedupe_db_lineage_digest,
)
from app.service import FileCenterService


@pytest.fixture
def service_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        quarantine_root=quarantine_dir,
        allowed_roots_raw=str(data_dir),
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    return {
        "service": service,
        "SessionLocal": service.SessionLocal,
        "settings": settings,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def _create_completed_scan(env, *, scan_id: int) -> None:
    with env["SessionLocal"]() as session:
        session.add(ScanJob(
            id=scan_id,
            name=f"scan-{scan_id}",
            mode="normal",
            roots_json=json.dumps([str(env["data_dir"])]),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=0,
            total_files_in_groups=0,
            reclaimable_bytes=0,
        ))
        session.commit()


def _create_duplicate_fixture(env, *, scan_id: int) -> list[int]:
    _create_completed_scan(env, scan_id=scan_id)
    first = env["data_dir"] / f"dup-{scan_id}-a.bin"
    second = env["data_dir"] / f"dup-{scan_id}-b.bin"
    first.write_bytes(b"x" * 128)
    second.write_bytes(b"x" * 128)
    with env["SessionLocal"]() as session:
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"group-hash-{scan_id}",
            file_size=128,
            member_count=2,
        )
        session.add(group)
        session.flush()
        rows = [
            DuplicateFile(
                group_id=group.id, root_id=0, absolute_path=str(first),
                relative_path=first.name, top_level_dir=str(env["data_dir"]),
                size=128, mtime_ns=1000, device=0, inode=0,
            ),
            DuplicateFile(
                group_id=group.id, root_id=0, absolute_path=str(second),
                relative_path=second.name, top_level_dir=str(env["data_dir"]),
                size=128, mtime_ns=2000, device=0, inode=0,
            ),
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def test_compilation_exposes_db_lineage_digest(service_env):
    _create_duplicate_fixture(service_env, scan_id=300)
    with service_env["SessionLocal"]() as session:
        res = compile_advanced_dedupe_preview(
            session, 300, {},
            allowed_roots=service_env["settings"].allowed_roots,
            quarantine_root=service_env["settings"].quarantine_root,
            protect_last_file=service_env["settings"].protect_last_file,
        )
    assert len(res.db_lineage_digest) == 64
    assert all(c in "0123456789abcdef" for c in res.db_lineage_digest)


def test_db_lineage_digest_changes_when_duplicate_file_row_changes(service_env):
    file_ids = _create_duplicate_fixture(service_env, scan_id=301)
    with service_env["SessionLocal"]() as session:
        first = compile_advanced_dedupe_preview(
            session, 301, {},
            allowed_roots=service_env["settings"].allowed_roots,
            quarantine_root=service_env["settings"].quarantine_root,
            protect_last_file=service_env["settings"].protect_last_file,
        )
        row = session.get(DuplicateFile, file_ids[0])
        assert row is not None
        row.mtime_ns += 1
        session.commit()
        second = compute_current_dedupe_db_lineage_digest(session, 301)
    assert second != first.db_lineage_digest


def test_db_lineage_digest_matches_fresh_db_read(service_env):
    _create_duplicate_fixture(service_env, scan_id=302)
    with service_env["SessionLocal"]() as session:
        first = compile_advanced_dedupe_preview(
            session, 302, {},
            allowed_roots=service_env["settings"].allowed_roots,
            quarantine_root=service_env["settings"].quarantine_root,
            protect_last_file=service_env["settings"].protect_last_file,
        )
        current = compute_current_dedupe_db_lineage_digest(session, 302)
    assert current == first.db_lineage_digest


def test_draft_intents_are_server_derived_and_preserve_keep_path(service_env):
    _create_duplicate_fixture(service_env, scan_id=305)
    with service_env["SessionLocal"]() as session:
        compilation = compile_advanced_dedupe_preview(
            session, 305, {},
            allowed_roots=service_env["settings"].allowed_roots,
            quarantine_root=service_env["settings"].quarantine_root,
            protect_last_file=service_env["settings"].protect_last_file,
        )
    intents = build_advanced_dedupe_draft_intents(compilation, protect_last_file=True)
    assert len(intents) == compilation.planned_quarantine_count
    assert [intent.sequence for intent in intents] == list(range(1, len(intents) + 1))
    assert all(intent.operation == "quarantine" for intent in intents)
    assert all(intent.keep_path for intent in intents)
    assert all(intent.source_path != intent.keep_path for intent in intents)
    assert all(intent.expected_size > 0 for intent in intents)


def test_draft_intents_never_carry_frozen_identity(service_env):
    _create_duplicate_fixture(service_env, scan_id=306)
    with service_env["SessionLocal"]() as session:
        compilation = compile_advanced_dedupe_preview(
            session, 306, {},
            allowed_roots=service_env["settings"].allowed_roots,
            quarantine_root=service_env["settings"].quarantine_root,
            protect_last_file=service_env["settings"].protect_last_file,
        )
    intents = build_advanced_dedupe_draft_intents(compilation, protect_last_file=True)
    for intent in intents:
        assert intent.expected_device == 0
        assert intent.expected_inode == 0
        assert intent.expected_mtime_ns == 0
        assert intent.expected_hash is None

    for intent in intents:
        meta = json.loads(intent.metadata_json)
        assert meta["scan_job_id"] == 306
        assert "group_provenance_id" in meta
        assert "group_decision_fingerprint" in meta
        assert "scan_root_index" in meta
        assert "scan_root_path" in meta
        assert "keep_scan_root_index" in meta
        assert "keep_scan_root_path" in meta
        assert "selection_reason" in meta
        assert "protected_dir" in meta


def test_advanced_generate_bad_digest_stops_before_persistence(service_env, monkeypatch):
    _create_duplicate_fixture(service_env, scan_id=310)
    service = service_env["service"]
    called = False

    def forbidden_persist(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("persistence must not run on PREVIEW_CHANGED")

    monkeypatch.setattr(service, "_persist_advanced_dedupe_draft", forbidden_persist, raising=False)
    with pytest.raises(DedupePreviewChangedError) as exc_info:
        service.create_advanced_dedupe_plan(
            310,
            scorer_config={},
            expected_preview_digest="0" * 64,
        )
    assert exc_info.value.code == "PREVIEW_CHANGED"
    assert called is False


def test_advanced_generate_empty_compilation_stops_before_persistence(service_env, monkeypatch):
    _create_completed_scan(service_env, scan_id=311)
    service = service_env["service"]
    called = False

    def forbidden_persist(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("persistence must not run for empty advanced Generate")

    monkeypatch.setattr(service, "_persist_advanced_dedupe_draft", forbidden_persist, raising=False)
    preview = service.get_dedupe_preview(311, scorer_config={})
    with pytest.raises(DedupeEmptyPlanError):
        service.create_advanced_dedupe_plan(
            311,
            scorer_config={},
            expected_preview_digest=preview["preview_digest"],
        )
    assert called is False


def test_matching_preview_digest_creates_exactly_one_draft_and_expected_items(service_env):
    scan_id = 315
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    result = service.create_advanced_dedupe_plan(
        scan_id,
        scorer_config=config,
        expected_preview_digest=preview["preview_digest"],
    )

    with service.SessionLocal() as session:
        plans = list(session.scalars(select(BatchPlan).where(BatchPlan.id == result["id"])))
        assert len(plans) == 1
        plan = plans[0]
        assert plan.kind == "dedupe"
        assert plan.status == "draft"
        assert plan.expected_changes == preview["planned_quarantine_count"]
        assert plan.expected_reclaim_bytes == preview["expected_reclaim_bytes"]

        items = list(session.scalars(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan.id)
            .order_by(BatchPlanItem.sequence)
        ))
        assert len(items) == preview["planned_quarantine_count"]
        assert [item.sequence for item in items] == list(range(1, len(items) + 1))
        for item in items:
            assert item.operation == "quarantine"
            assert item.target_path is None
            assert item.keep_path
            assert item.source_path != item.keep_path
            assert item.expected_size > 0
            assert item.expected_device == 0
            assert item.expected_inode == 0
            assert item.expected_mtime_ns == 0
            assert item.expected_hash is None
            assert item.state == "planned"

        metadata = json.loads(plan.metadata_json)
        assert metadata["source"] == "dedupe"
        assert metadata["dedupe_engine_version"] == 1
        assert metadata["scan_job_id"] == scan_id
        assert metadata["scorer_config_digest"] == preview["scorer_config_digest"]
        assert metadata["source_snapshot_digest"] == preview["source_snapshot_digest"]
        assert metadata["decision_digest"] == preview["decision_digest"]
        assert metadata["preview_digest"] == preview["preview_digest"]
        assert metadata["effective_safety_policy"] == preview["effective_safety_policy"]
        assert isinstance(metadata["scorer_config"], dict)
        assert len(metadata["db_lineage_digest"]) == 64


def test_advanced_generate_zero_side_effects(service_env):
    scan_id = 316
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)

    file_a = service_env["data_dir"] / f"dup-{scan_id}-a.bin"
    file_b = service_env["data_dir"] / f"dup-{scan_id}-b.bin"
    bytes_a_before = file_a.read_bytes()
    bytes_b_before = file_b.read_bytes()

    with service.SessionLocal() as session:
        plans_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        items_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        work_jobs_before = session.scalar(select(func.count(WorkJob.id))) or 0
        quarantine_before = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    result = service.create_advanced_dedupe_plan(
        scan_id,
        scorer_config=config,
        expected_preview_digest=preview["preview_digest"],
    )

    with service.SessionLocal() as session:
        plans_after = session.scalar(select(func.count(BatchPlan.id))) or 0
        items_after = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        work_jobs_after = session.scalar(select(func.count(WorkJob.id))) or 0
        quarantine_after = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    assert plans_after == plans_before + 1
    assert items_after == items_before + preview["planned_quarantine_count"]
    assert work_jobs_after == work_jobs_before
    assert quarantine_after == quarantine_before
    assert file_a.read_bytes() == bytes_a_before
    assert file_b.read_bytes() == bytes_b_before


def test_db_lineage_race_group_change_after_phase_a_fails(service_env, monkeypatch):
    import app.service
    scan_id = 317
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)

    real_compile = app.service.compile_advanced_dedupe_preview

    def race_compile(*args, **kwargs):
        res = real_compile(*args, **kwargs)
        with service.SessionLocal() as session:
            grp = session.scalar(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id))
            assert grp is not None
            grp.file_size += 1
            session.commit()
        return res

    monkeypatch.setattr(app.service, "compile_advanced_dedupe_preview", race_compile)

    with service.SessionLocal() as session:
        plans_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        items_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0

    with pytest.raises(DedupePreviewChangedError) as exc_info:
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config=config,
            expected_preview_digest=preview["preview_digest"],
        )
    assert exc_info.value.details["reason"] == "db_lineage_changed"

    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == plans_before
        assert session.scalar(select(func.count(BatchPlanItem.id))) == items_before


def test_db_lineage_race_file_change_after_phase_a_fails(service_env, monkeypatch):
    import app.service
    scan_id = 318
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)

    real_compile = app.service.compile_advanced_dedupe_preview

    def race_compile(*args, **kwargs):
        res = real_compile(*args, **kwargs)
        with service.SessionLocal() as session:
            file_row = session.scalar(
                select(DuplicateFile).join(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)
            )
            assert file_row is not None
            file_row.mtime_ns += 1
            session.commit()
        return res

    monkeypatch.setattr(app.service, "compile_advanced_dedupe_preview", race_compile)

    with service.SessionLocal() as session:
        plans_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        items_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0

    with pytest.raises(DedupePreviewChangedError) as exc_info:
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config=config,
            expected_preview_digest=preview["preview_digest"],
        )
    assert exc_info.value.details["reason"] == "db_lineage_changed"

    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == plans_before
        assert session.scalar(select(func.count(BatchPlanItem.id))) == items_before


def test_db_lineage_race_scan_deleted_between_phases_fails(service_env, monkeypatch):
    import app.service
    scan_id = 319
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)

    real_compile = app.service.compile_advanced_dedupe_preview

    def race_compile(*args, **kwargs):
        res = real_compile(*args, **kwargs)
        with service.SessionLocal() as session:
            scan = session.get(ScanJob, scan_id)
            assert scan is not None
            session.delete(scan)
            session.commit()
        return res

    monkeypatch.setattr(app.service, "compile_advanced_dedupe_preview", race_compile)

    with pytest.raises(DedupePreviewChangedError) as exc_info:
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config=config,
            expected_preview_digest=preview["preview_digest"],
        )
    assert exc_info.value.details["reason"] == "db_lineage_changed"


def test_persistence_rollback_on_item_failure(service_env, monkeypatch):
    scan_id = 320
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    import app.service as service_module

    real_item_cls = service_module.BatchPlanItem
    calls = 0

    def exploding_item(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic item insert failure")
        return real_item_cls(*args, **kwargs)

    monkeypatch.setattr(service_module, "BatchPlanItem", exploding_item)
    preview = service.get_dedupe_preview(scan_id, scorer_config={})

    with service.SessionLocal() as session:
        plans_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        items_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0

    with pytest.raises(RuntimeError, match="synthetic item insert failure"):
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config={},
            expected_preview_digest=preview["preview_digest"],
        )

    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == plans_before
        assert session.scalar(select(func.count(BatchPlanItem.id))) == items_before


def test_scan_dependency_guard_sees_advanced_draft(service_env):
    scan_id = 321
    _create_duplicate_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = {"selection_mode": "weighted"}
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    service.create_advanced_dedupe_plan(
        scan_id,
        scorer_config=config,
        expected_preview_digest=preview["preview_digest"],
    )
    with pytest.raises(ValueError, match="关联计划"):
        service.delete_scan(scan_id)




