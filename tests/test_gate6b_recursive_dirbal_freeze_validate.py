from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.planning.recursive_protection import RecursiveProtectionSnapshot
from app.planning.recursive_protection_authority import parse_recursive_protection_authority
from app.service import FileCenterService


RECURSIVE_MODE = "recursive_directory_balanced_by_bytes"


@pytest.fixture
def service_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    quarantine_dir = tmp_path / "quarantine"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    quarantine_dir.mkdir()
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
    }


def _recursive_config() -> dict:
    return {
        "schema_version": 1,
        "selection_mode": RECURSIVE_MODE,
        "factors": {},
    }


def _create_recursive_fixture(env, *, scan_id: int) -> None:
    root = env["data_dir"]
    left_dir = root / "A" / "deep"
    right_dir = root / "B" / "deep"
    left_dir.mkdir(parents=True)
    right_dir.mkdir(parents=True)

    left = left_dir / "dup.bin"
    right = right_dir / "dup.bin"
    payload = b"gate6b-freeze-authority"
    left.write_bytes(payload)
    right.write_bytes(payload)
    (left_dir / "extra.bin").write_bytes(b"keep-left-alive")
    (right_dir / "extra.bin").write_bytes(b"keep-right-alive")

    with env["SessionLocal"]() as session:
        session.add(
            ScanJob(
                id=scan_id,
                name=f"scan-{scan_id}",
                mode="normal",
                roots_json=json.dumps([str(root)]),
                status="completed",
                started_at=utcnow(),
                finished_at=utcnow(),
                total_groups=1,
                total_files_in_groups=2,
                reclaimable_bytes=len(payload),
            )
        )
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"freeze-{scan_id}",
            file_size=len(payload),
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path in (left, right):
            st = os.lstat(path)
            relative = path.relative_to(root)
            session.add(
                DuplicateFile(
                    group_id=group.id,
                    root_id=0,
                    absolute_path=str(path),
                    relative_path=relative.as_posix(),
                    top_level_dir=str(root / relative.parts[0]),
                    size=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    device=st.st_dev,
                    inode=st.st_ino,
                )
            )
        session.commit()


def _generate_recursive_plan(env, *, scan_id: int) -> int:
    _create_recursive_fixture(env, scan_id=scan_id)
    service = env["service"]
    config = _recursive_config()
    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    result = service.create_advanced_dedupe_plan(
        scan_id,
        scorer_config=config,
        expected_preview_digest=preview["preview_digest"],
    )
    return int(result["id"])


def _first_item(env, plan_id: int) -> BatchPlanItem:
    with env["SessionLocal"]() as session:
        item = session.scalar(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence)
        )
        assert item is not None
        session.expunge(item)
        return item


def _plan_state_and_item_metadata(env, plan_id: int) -> tuple[str, dict]:
    with env["SessionLocal"]() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        item = session.scalar(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence)
        )
        assert item is not None
        return plan.status, json.loads(item.metadata_json or "{}")


def _plan_item_validation_state(env, plan_id: int) -> tuple[str, str, str | None]:
    with env["SessionLocal"]() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        item = session.scalar(
            select(BatchPlanItem)
            .where(BatchPlanItem.plan_id == plan_id)
            .order_by(BatchPlanItem.sequence)
        )
        assert item is not None
        return plan.status, item.state, item.reason


def _freeze_recursive_plan(env, *, scan_id: int) -> int:
    plan_id = _generate_recursive_plan(env, scan_id=scan_id)
    env["service"].freeze_plan(plan_id)
    return plan_id


def test_recursive_freeze_seals_exact_scope_and_live_ancestor_samples(service_env):
    plan_id = _generate_recursive_plan(service_env, scan_id=1201)
    service = service_env["service"]
    settings = service_env["settings"]
    item_before = _first_item(service_env, plan_id)
    authority = parse_recursive_protection_authority(
        item_before.metadata_json,
        expected_source_path=item_before.source_path,
        allowed_roots=settings.allowed_roots,
        quarantine_root=settings.quarantine_root,
    )
    assert authority is not None

    service.freeze_plan(plan_id)

    status, metadata = _plan_state_and_item_metadata(service_env, plan_id)
    assert status == "frozen"
    frozen = metadata["frozen_recursive_protection"]
    assert frozen["schema_version"] == 1
    assert frozen["scope_digest"] == authority.scope_digest
    assert list(frozen["frozen_ancestors"].keys()) == list(authority.protected_ancestors)

    for ancestor in authority.protected_ancestors:
        sample = frozen["frozen_ancestors"][ancestor]
        assert sample["count"] >= 2
        assert isinstance(sample["device"], int)
        assert isinstance(sample["inode"], int)
        assert isinstance(sample["tree_identity_digest"], str)
        assert len(sample["tree_identity_digest"]) == 64


def test_recursive_freeze_rejects_missing_authority_without_freezing(service_env):
    plan_id = _generate_recursive_plan(service_env, scan_id=1202)
    service = service_env["service"]

    with service_env["SessionLocal"]() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        plan_meta = json.loads(plan.metadata_json or "{}")
        assert plan_meta["selection_mode"] == RECURSIVE_MODE
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        metadata.pop("recursive_protection", None)
        item.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        session.commit()

    with pytest.raises(ValueError, match="RECURSIVE_PROTECTION|recursive_protection"):
        service.freeze_plan(plan_id)

    status, metadata = _plan_state_and_item_metadata(service_env, plan_id)
    assert status == "draft"
    assert "frozen_recursive_protection" not in metadata


def test_recursive_freeze_rejects_malformed_authority_without_freezing(service_env):
    plan_id = _generate_recursive_plan(service_env, scan_id=1203)
    service = service_env["service"]

    with service_env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        metadata["recursive_protection"]["schema_version"] = 2
        item.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        session.commit()

    with pytest.raises(ValueError, match="recursive_protection"):
        service.freeze_plan(plan_id)

    status, metadata = _plan_state_and_item_metadata(service_env, plan_id)
    assert status == "draft"
    assert "frozen_recursive_protection" not in metadata


def test_recursive_freeze_rejects_unstable_ancestor_without_partial_persistence(service_env, monkeypatch):
    plan_id = _generate_recursive_plan(service_env, scan_id=1204)
    service = service_env["service"]

    import app.planning.recursive_protection as recursive_protection

    monkeypatch.setattr(
        recursive_protection,
        "snapshot_recursive_regular_files",
        lambda _path, **_kwargs: RecursiveProtectionSnapshot(
            count=0,
            stable=False,
            device=None,
            inode=None,
            tree_identity_digest=None,
        ),
    )

    with pytest.raises(ValueError, match="RECURSIVE_PROTECTION_UNSTABLE"):
        service.freeze_plan(plan_id)

    status, metadata = _plan_state_and_item_metadata(service_env, plan_id)
    assert status == "draft"
    assert "frozen_recursive_protection" not in metadata


def test_recursive_freeze_rejects_live_last_file_violation(service_env):
    plan_id = _generate_recursive_plan(service_env, scan_id=1205)
    service = service_env["service"]
    item = _first_item(service_env, plan_id)
    source = Path(item.source_path)

    for sibling in source.parent.iterdir():
        if sibling != source and sibling.is_file() and not sibling.is_symlink():
            sibling.unlink()

    assert source.exists()
    assert sum(1 for p in source.parent.iterdir() if p.is_file() and not p.is_symlink()) == 1

    with pytest.raises(ValueError, match="RECURSIVE_PROTECT_LAST_FILE"):
        service.freeze_plan(plan_id)

    status, metadata = _plan_state_and_item_metadata(service_env, plan_id)
    assert status == "draft"
    assert "frozen_recursive_protection" not in metadata


def test_nonrecursive_freeze_path_remains_compatible(service_env):
    service = service_env["service"]
    source = service_env["data_dir"] / "legacy.bin"
    source.write_bytes(b"legacy-freeze")
    plan = service.create_plan(
        name="legacy nonrecursive quarantine",
        kind="dedupe",
        items=[{"source": str(source), "operation": "quarantine"}],
    )

    frozen = service.freeze_plan(plan.id)

    assert frozen.status == "frozen"
    status, metadata = _plan_state_and_item_metadata(service_env, plan.id)
    assert status == "frozen"
    assert "frozen_recursive_protection" not in metadata


@pytest.mark.parametrize(
    "tamper_kind",
    ["source", "root", "ancestors", "scope_digest"],
)
def test_recursive_validate_rejects_authority_tampering_after_freeze(service_env, tamper_kind):
    plan_id = _freeze_recursive_plan(service_env, scan_id=1301)
    service = service_env["service"]

    with service_env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        authority = metadata["recursive_protection"]
        frozen = metadata["frozen_recursive_protection"]
        if tamper_kind == "source":
            authority["source_path"] = str(Path(item.source_path).with_name("other.bin"))
        elif tamper_kind == "root":
            authority["scan_root_path"] = str(Path(authority["scan_root_path"]) / "A")
        elif tamper_kind == "ancestors":
            authority["protected_ancestors"] = list(reversed(authority["protected_ancestors"]))
        else:
            frozen["scope_digest"] = "0" * 64
        item.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()

    service.validate_plan(plan_id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan_id)
    assert plan_status == "stale"
    assert item_state == "stale"
    assert reason is not None and "RECURSIVE_PROTECTION_UNSTABLE" in reason


@pytest.mark.parametrize("malformation", ["missing", "schema"])
def test_recursive_validate_rejects_missing_or_malformed_frozen_authority(service_env, malformation):
    plan_id = _freeze_recursive_plan(service_env, scan_id=1302)
    service = service_env["service"]

    with service_env["SessionLocal"]() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item is not None
        metadata = json.loads(item.metadata_json or "{}")
        if malformation == "missing":
            metadata.pop("frozen_recursive_protection", None)
        else:
            metadata["frozen_recursive_protection"]["schema_version"] = 2
        item.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()

    service.validate_plan(plan_id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan_id)
    assert plan_status == "stale"
    assert item_state == "stale"
    assert reason is not None and "RECURSIVE_PROTECTION_UNSTABLE" in reason


def test_recursive_validate_blocks_live_last_file_change_after_freeze_without_replanning(service_env):
    plan_id = _freeze_recursive_plan(service_env, scan_id=1303)
    service = service_env["service"]
    item_before = _first_item(service_env, plan_id)
    source = Path(item_before.source_path)

    for sibling in source.parent.iterdir():
        if sibling != source and sibling.is_file() and not sibling.is_symlink():
            sibling.unlink()

    assert source.exists()
    assert sum(1 for p in source.parent.iterdir() if p.is_file() and not p.is_symlink()) == 1

    service.validate_plan(plan_id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan_id)
    assert plan_status == "stale"
    assert item_state == "stale"
    assert reason is not None and "RECURSIVE_PROTECT_LAST_FILE" in reason
    item_after = _first_item(service_env, plan_id)
    assert item_after.source_path == item_before.source_path
    with service_env["SessionLocal"]() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)))
        assert len(items) == 1


def test_recursive_validate_rejects_unstable_live_protection_read(service_env, monkeypatch):
    plan_id = _freeze_recursive_plan(service_env, scan_id=1304)
    service = service_env["service"]

    import app.planning.recursive_protection as recursive_protection

    monkeypatch.setattr(
        recursive_protection,
        "snapshot_recursive_regular_files",
        lambda _path, **_kwargs: RecursiveProtectionSnapshot(
            count=0,
            stable=False,
            device=None,
            inode=None,
            tree_identity_digest=None,
        ),
    )

    service.validate_plan(plan_id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan_id)
    assert plan_status == "stale"
    assert item_state == "stale"
    assert reason is not None and "RECURSIVE_PROTECTION_UNSTABLE" in reason


def test_recursive_validate_accepts_safe_current_state_when_tree_identity_changed(service_env):
    plan_id = _freeze_recursive_plan(service_env, scan_id=1305)
    service = service_env["service"]
    item = _first_item(service_env, plan_id)
    metadata = json.loads(item.metadata_json or "{}")
    authority = parse_recursive_protection_authority(
        item.metadata_json,
        expected_source_path=item.source_path,
        allowed_roots=service_env["settings"].allowed_roots,
        quarantine_root=service_env["settings"].quarantine_root,
    )
    assert authority is not None

    source_parent = str(Path(item.source_path).parent)
    old_digest = metadata["frozen_recursive_protection"]["frozen_ancestors"][source_parent]["tree_identity_digest"]
    benign = Path(item.source_path).parent / "benign-external-addition.bin"
    benign.write_bytes(b"benign external change")

    import app.planning.recursive_protection as recursive_protection

    current = recursive_protection.snapshot_recursive_regular_files(source_parent)
    assert current.stable is True
    assert current.count >= 3
    assert current.tree_identity_digest != old_digest

    service.validate_plan(plan_id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan_id)
    assert plan_status == "ready"
    assert item_state == "validated"
    assert reason is not None


def test_nonrecursive_validate_path_remains_compatible(service_env):
    service = service_env["service"]
    source = service_env["data_dir"] / "legacy-validate.bin"
    source.write_bytes(b"legacy-validate")
    plan = service.create_plan(
        name="legacy nonrecursive validate",
        kind="dedupe",
        items=[{"source": str(source), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)

    service.validate_plan(plan.id)

    plan_status, item_state, reason = _plan_item_validation_state(service_env, plan.id)
    assert plan_status == "ready"
    assert item_state == "validated"
    assert reason is not None