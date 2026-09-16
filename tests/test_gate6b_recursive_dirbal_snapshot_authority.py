from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.planning.dedupe_preview import (
    DedupePreviewChangedError,
    _count_real_regular_files_recursive,
)
from app.service import FileCenterService


def test_recursive_count_protected_directory_aba_fails_closed(tmp_path: Path, monkeypatch):
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "only.bin").write_bytes(b"one")

    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "evil-1.bin").write_bytes(b"evil")
    (attacker / "evil-2.bin").write_bytes(b"evil")
    detached = tmp_path / "detached-protected"

    real_scandir = os.scandir
    swapped = False

    def swap_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            protected.rename(detached)
            os.symlink(attacker, protected)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_before_first_scan)

    assert _count_real_regular_files_recursive(protected) == 0


def test_recursive_count_intermediate_parent_aba_fails_closed(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    managed = root / "managed"
    protected = managed / "scope" / "protected"
    protected.mkdir(parents=True)
    (protected / "only.bin").write_bytes(b"one")

    attacker = tmp_path / "attacker"
    attacker_protected = attacker / "scope" / "protected"
    attacker_protected.mkdir(parents=True)
    (attacker_protected / "evil-1.bin").write_bytes(b"evil")
    (attacker_protected / "evil-2.bin").write_bytes(b"evil")
    detached = root / "detached-managed"

    real_scandir = os.scandir
    swapped = False

    def swap_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            managed.rename(detached)
            os.symlink(attacker, managed)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_before_first_scan)

    assert _count_real_regular_files_recursive(protected) == 0


def test_recursive_count_descendant_directory_aba_after_open_fails_closed(tmp_path: Path, monkeypatch):
    protected = tmp_path / "protected"
    descendant = protected / "descendant"
    descendant.mkdir(parents=True)
    (descendant / "one.bin").write_bytes(b"one")
    (descendant / "two.bin").write_bytes(b"two")

    descendant_st = os.lstat(descendant)
    detached = tmp_path / "detached-descendant"
    real_scandir = os.scandir
    swapped = False

    def swap_after_descendant_fd_open(path):
        nonlocal swapped
        if not swapped and isinstance(path, int):
            opened_st = os.fstat(path)
            if (
                int(opened_st.st_dev) == int(descendant_st.st_dev)
                and int(opened_st.st_ino) == int(descendant_st.st_ino)
            ):
                swapped = True
                descendant.rename(detached)
                descendant.mkdir()
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_after_descendant_fd_open)

    assert _count_real_regular_files_recursive(protected) == 0
    assert swapped is True
    assert list(descendant.iterdir()) == []


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
        "data_dir": data_dir,
        "tmp_path": tmp_path,
    }


def _recursive_config(*, favor_b: bool = False):
    factors = {}
    if favor_b:
        factors = {
            "path_priority": {
                "enabled": True,
                "weight": 1000,
                "rules": [{"scope": "absolute", "pattern": "*/B/*"}],
            }
        }
    return {
        "schema_version": 1,
        "selection_mode": "recursive_directory_balanced_by_bytes",
        "factors": factors,
    }


def _create_recursive_fixture(env, *, scan_id: int):
    root = env["data_dir"]
    a_dir = root / "A" / "deep"
    b_dir = root / "B" / "deep"
    a_dir.mkdir(parents=True)
    b_dir.mkdir(parents=True)

    left = a_dir / "dup.bin"
    right = b_dir / "dup.bin"
    left.write_bytes(b"same-bytes")
    right.write_bytes(b"same-bytes")
    a_extra = a_dir / "extra.bin"
    b_extra = b_dir / "extra.bin"
    a_extra.write_bytes(b"keep-a-subtree-alive")
    b_extra.write_bytes(b"keep-b-subtree-alive")

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
                reclaimable_bytes=len(b"same-bytes"),
            )
        )
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"recursive-snapshot-{scan_id}",
            file_size=len(b"same-bytes"),
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

    return root, left, right, a_extra, b_extra


def _replace_a_ancestor_preserving_file_inodes(env, root: Path) -> None:
    old_a = root / "A"
    detached = env["tmp_path"] / "detached-A"
    old_a.rename(detached)

    new_deep = root / "A" / "deep"
    new_deep.mkdir(parents=True)
    for name in ("dup.bin", "extra.bin"):
        os.link(detached / "deep" / name, new_deep / name)

    assert os.lstat(detached).st_ino != os.lstat(root / "A").st_ino
    assert os.lstat(detached / "deep").st_ino != os.lstat(new_deep).st_ino
    for name in ("dup.bin", "extra.bin"):
        before = os.lstat(detached / "deep" / name)
        after = os.lstat(new_deep / name)
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def _plan_counts(service: FileCenterService):
    with service.SessionLocal() as session:
        return (
            session.scalar(select(func.count(BatchPlan.id))) or 0,
            session.scalar(select(func.count(BatchPlanItem.id))) or 0,
        )


def test_recursive_preview_digest_binds_protection_directory_identity(service_env):
    scan_id = 921
    root, _left, _right, _a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = _recursive_config()

    first = service.get_dedupe_preview(scan_id, scorer_config=config)
    _replace_a_ancestor_preserving_file_inodes(service_env, root)
    second = service.get_dedupe_preview(scan_id, scorer_config=config)

    assert second["preview_digest"] != first["preview_digest"]


def test_recursive_generate_directory_identity_aba_returns_preview_changed_and_zero_draft(service_env):
    scan_id = 922
    root, _left, _right, _a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = _recursive_config()

    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    before_counts = _plan_counts(service)
    _replace_a_ancestor_preserving_file_inodes(service_env, root)

    with pytest.raises(DedupePreviewChangedError):
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config=config,
            expected_preview_digest=preview["preview_digest"],
        )

    assert _plan_counts(service) == before_counts


def test_recursive_generate_descendant_membership_aba_returns_preview_changed_and_zero_draft(
    service_env,
    monkeypatch,
):
    scan_id = 923
    root, left, right, a_extra, _b_extra = _create_recursive_fixture(service_env, scan_id=scan_id)
    service = service_env["service"]
    config = _recursive_config(favor_b=True)

    padding = left.parent / "padding"
    padding.mkdir()
    a_extra.rename(padding / "extra.bin")

    preview = service.get_dedupe_preview(scan_id, scorer_config=config)
    quarantine_paths = {
        row["absolute_path"]
        for row in preview["rows"]
        if row["member_decision"] == "QUARANTINE"
    }
    assert str(left) in quarantine_paths
    assert str(right) not in quarantine_paths

    padding_st = os.lstat(padding)
    detached = service_env["tmp_path"] / "detached-padding"
    real_scandir = os.scandir
    padding_scan_count = 0
    swapped = False

    def swap_on_third_padding_scan(path):
        nonlocal padding_scan_count, swapped
        if isinstance(path, int):
            opened_st = os.fstat(path)
            if (
                int(opened_st.st_dev) == int(padding_st.st_dev)
                and int(opened_st.st_ino) == int(padding_st.st_ino)
            ):
                padding_scan_count += 1
                if padding_scan_count == 3:
                    swapped = True
                    padding.rename(detached)
                    padding.mkdir()
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_on_third_padding_scan)
    before_counts = _plan_counts(service)

    with pytest.raises(DedupePreviewChangedError):
        service.create_advanced_dedupe_plan(
            scan_id,
            scorer_config=config,
            expected_preview_digest=preview["preview_digest"],
        )

    assert swapped is True
    assert list(padding.iterdir()) == []
    assert left.exists()
    assert _plan_counts(service) == before_counts
