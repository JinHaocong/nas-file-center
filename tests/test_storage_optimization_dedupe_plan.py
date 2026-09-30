from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.planning.dedupe_preview import DedupeEmptyPlanError, DedupePreviewChangedError
from app.storage_optimization.capability import (
    CapabilityProbeResult,
    StorageOptimizationCapability,
)
from app.service import FileCenterService


@pytest.fixture
def storage_dedupe_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_root=quarantine,
        allowed_roots_raw=str(data),
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    service = FileCenterService(settings)
    return service, data


def _seed_duplicate(service: FileCenterService, data: Path, scan_id: int = 900):
    left = data / "left.bin"
    right = data / "right.bin"
    left.write_bytes(b"x" * 1024)
    right.write_bytes(b"x" * 1024)
    with service.SessionLocal() as session:
        scan = ScanJob(
            id=scan_id,
            name="storage-opt",
            mode="normal",
            roots_json=json.dumps([str(data)]),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=1,
            total_files_in_groups=2,
            reclaimable_bytes=1024,
        )
        session.add(scan)
        group = DuplicateGroup(
            scan_job_id=scan_id,
            content_hash="candidate-discovery-hash",
            file_size=1024,
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path, mtime in ((left, 1000), (right, 2000)):
            session.add(DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(path),
                relative_path=path.name,
                top_level_dir=str(data),
                size=1024,
                mtime_ns=mtime,
                device=0,
                inode=0,
            ))
        session.commit()
    return left, right


@pytest.mark.parametrize(
    ("storage_action", "operation", "decision"),
    [
        ("quarantine", "quarantine", "QUARANTINE"),
        ("hardlink", "hardlink_optimize", "HARDLINK"),
        ("reflink", "reflink_optimize", "REFLINK"),
    ],
)
def test_storage_action_changes_preview_and_draft_operation(
    storage_dedupe_env,
    storage_action: str,
    operation: str,
    decision: str,
):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action=storage_action,
    )
    assert preview["storage_action"] == storage_action
    assert preview["planned_action_count"] == 1
    assert any(row["member_decision"] == decision for row in preview["rows"])

    result = service.create_advanced_dedupe_plan(
        900,
        scorer_config={},
        storage_action=storage_action,
        expected_preview_digest=preview["preview_digest"],
    )

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, result["id"])
        assert plan is not None
        meta = json.loads(plan.metadata_json)
        assert meta["storage_action"] == storage_action
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)
        )
        assert item is not None
        assert item.operation == operation
        item_meta = json.loads(item.metadata_json)
        assert item_meta["storage_action"] == storage_action


def test_storage_action_is_bound_into_preview_digest(storage_dedupe_env):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    quarantine = service.get_dedupe_preview(900, scorer_config={}, storage_action="quarantine")
    hardlink = service.get_dedupe_preview(900, scorer_config={}, storage_action="hardlink")
    reflink = service.get_dedupe_preview(900, scorer_config={}, storage_action="reflink")

    assert len({quarantine["preview_digest"], hardlink["preview_digest"], reflink["preview_digest"]}) == 3

    with pytest.raises(DedupePreviewChangedError):
        service.create_advanced_dedupe_plan(
            900,
            scorer_config={},
            storage_action="hardlink",
            expected_preview_digest=quarantine["preview_digest"],
        )


def test_default_storage_action_remains_quarantine(storage_dedupe_env):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    preview = service.get_dedupe_preview(900, scorer_config={})
    assert preview["storage_action"] == "quarantine"
    assert preview["planned_quarantine_count"] == 1

    result = service.create_advanced_dedupe_plan(
        900,
        scorer_config={},
        expected_preview_digest=preview["preview_digest"],
    )

    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == result["id"])
        )
        assert item is not None
        assert item.operation == "quarantine"


def _supported_probe(operation: str) -> CapabilityProbeResult:
    return CapabilityProbeResult(
        capability=StorageOptimizationCapability.SUPPORTED,
        operation=operation,
        reason=f"{operation}_test_supported",
    )


@pytest.mark.parametrize(
    ("storage_action", "operation", "probe_name"),
    [
        ("hardlink", "hardlink_optimize", "probe_hardlink_between"),
        ("reflink", "reflink_optimize", "probe_reflink_between"),
    ],
)
def test_optimization_freeze_and_validate_require_frozen_metadata_and_live_capability(
    storage_dedupe_env,
    monkeypatch,
    storage_action: str,
    operation: str,
    probe_name: str,
):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action=storage_action,
    )
    result = service.create_advanced_dedupe_plan(
        900,
        scorer_config={},
        storage_action=storage_action,
        expected_preview_digest=preview["preview_digest"],
    )

    frozen = service.freeze_plan(result["id"])
    assert frozen.status == "frozen"

    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == result["id"])
        )
        assert item is not None
        assert item.operation == operation
        assert item.expected_hash is not None
        assert len(item.expected_hash) == 64
        metadata = json.loads(item.metadata_json)
        tx_id = metadata["storage_optimization_transaction_id"]
        assert isinstance(tx_id, str) and tx_id
        frozen_opt = metadata["storage_optimization"]
        assert frozen_opt["transaction_id"] == tx_id
        assert frozen_opt["operation"] == operation
        assert frozen_opt["frozen_source_metadata"]["size"] == 1024
        assert frozen_opt["frozen_keep_metadata"]["size"] == 1024

    monkeypatch.setattr(
        f"app.service.{probe_name}",
        lambda *_args, **_kwargs: _supported_probe(storage_action),
    )

    validated = service.validate_plan(result["id"])
    assert validated["status"] == "ready"
    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == result["id"])
        )
        assert item is not None
        assert item.state == "validated"
        assert "capability verified" in (item.reason or "")


def test_hardlink_metadata_mismatch_is_visible_in_preview_and_not_generated(
    storage_dedupe_env,
):
    service, data = storage_dedupe_env
    left, right = _seed_duplicate(service, data)
    left.chmod(0o600)
    right.chmod(0o644)

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action="hardlink",
    )

    assert preview["planned_action_count"] == 0
    assert preview["storage_blocked_count"] == 1
    assert preview["expected_reclaim_bytes"] == 0
    assert sum(preview["released_bytes_by_scan_root"].values()) == 0
    blocked = [
        row for row in preview["rows"]
        if row["member_decision"] == "SKIPPED"
        and row["storage_blocking_reason"]
    ]
    assert len(blocked) == 1
    assert blocked[0]["storage_blocking_reason"].startswith(
        "HARDLINK_METADATA_MISMATCH:mode"
    )

    with pytest.raises(DedupeEmptyPlanError):
        service.create_advanced_dedupe_plan(
            900,
            scorer_config={},
            storage_action="hardlink",
            expected_preview_digest=preview["preview_digest"],
        )


def test_validate_blocks_unsupported_live_capability(storage_dedupe_env, monkeypatch):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action="hardlink",
    )
    result = service.create_advanced_dedupe_plan(
        900,
        scorer_config={},
        storage_action="hardlink",
        expected_preview_digest=preview["preview_digest"],
    )
    service.freeze_plan(result["id"])

    monkeypatch.setattr(
        "app.service.probe_hardlink_between",
        lambda *_args, **_kwargs: CapabilityProbeResult(
            capability=StorageOptimizationCapability.UNSUPPORTED,
            operation="hardlink",
            reason="synthetic_cross_area_unsupported",
        ),
    )

    validated = service.validate_plan(result["id"])
    assert validated["status"] == "partial"
    with service.SessionLocal() as session:
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == result["id"])
        )
        assert item is not None
        assert item.state == "skipped"
        assert "CAPABILITY_UNSUPPORTED" in (item.reason or "")


@pytest.mark.parametrize("storage_action", ["hardlink", "reflink"])
def test_existing_source_hardlink_blocks_false_reclaim_estimate(
    storage_dedupe_env,
    storage_action: str,
):
    service, data = storage_dedupe_env
    _seed_duplicate(service, data)

    baseline = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action="quarantine",
    )
    source_row = next(
        row for row in baseline["rows"]
        if row["member_decision"] == "QUARANTINE"
    )
    source_path = Path(source_row["absolute_path"])
    alias = data / "preexisting-source-hardlink.bin"
    os.link(source_path, alias)
    assert source_path.stat().st_nlink == 2

    preview = service.get_dedupe_preview(
        900,
        scorer_config={},
        storage_action=storage_action,
    )

    assert preview["planned_action_count"] == 0
    assert preview["storage_blocked_count"] == 1
    assert preview["expected_reclaim_bytes"] == 0
    assert sum(preview["released_bytes_by_scan_root"].values()) == 0
    blocked = [
        row for row in preview["rows"]
        if row.get("storage_blocking_reason") == "SOURCE_HAS_MULTIPLE_HARDLINKS"
    ]
    assert len(blocked) == 1
