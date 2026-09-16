from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, DuplicateFile, DuplicateGroup, ScanJob, utcnow
from app.planning.dedupe_config import validate_and_canonicalize_config
from app.planning.dedupe_engine import (
    DedupeGroupSnapshot,
    DedupeMemberSnapshot,
    run_advanced_dedupe,
)
from app.planning.dedupe_preview import compile_advanced_dedupe_preview


@pytest.fixture
def db_session(tmp_path: Path):
    db_file = tmp_path / "gate6b-last-file.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        yield session


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
    return validate_and_canonicalize_config(
        {
            "schema_version": 1,
            "selection_mode": "recursive_directory_balanced_by_bytes",
            "factors": factors,
        }
    )


def _member(path: str, *, size: int, top_level_dir: str) -> DedupeMemberSnapshot:
    return DedupeMemberSnapshot(
        absolute_path=path,
        relative_path=Path(path).relative_to("/root").as_posix(),
        scan_root_index=0,
        scan_root_path="/root",
        mtime_ns=100,
        size=size,
        top_level_dir=top_level_dir,
    )


def _group(
    provenance_id: str,
    *,
    file_size: int,
    left_path: str,
    right_path: str,
) -> DedupeGroupSnapshot:
    return DedupeGroupSnapshot(
        provenance_id=provenance_id,
        content_hash=(provenance_id.encode("utf-8").hex() + "0" * 64)[:64],
        file_size=file_size,
        members=(
            _member(left_path, size=file_size, top_level_dir="/root/A"),
            _member(right_path, size=file_size, top_level_dir="/root/B"),
        ),
    )


def test_recursive_protection_checks_every_ancestor_and_proposed_quarantine():
    group = _group(
        "deep-ancestor",
        file_size=100,
        left_path="/root/A/deep/a.bin",
        right_path="/root/B/deep/b.bin",
    )

    result = run_advanced_dedupe(
        [group],
        _recursive_config(),
        scan_roots=["/root"],
        protect_last_file_counts={
            "/root": 4,
            "/root/A": 2,
            "/root/A/deep": 1,
            "/root/B": 2,
            "/root/B/deep": 1,
        },
    )

    decision = result.groups[0]
    assert decision.status == "skipped"
    assert decision.quarantine_candidates == []
    assert "RECURSIVE_PROTECT_LAST_FILE" in (decision.skip_reason or "")
    assert any(
        "RECURSIVE_PROTECT_LAST_FILE" in member.safety_reasons
        for member in decision.members
    )


def test_recursive_protection_subtracts_already_scheduled_and_does_not_fallback_to_lower_scorer():
    groups = [
        _group(
            "01-large",
            file_size=200,
            left_path="/root/A/deep/one.bin",
            right_path="/root/B/one.bin",
        ),
        _group(
            "02-small",
            file_size=100,
            left_path="/root/A/deep/two.bin",
            right_path="/root/B/two.bin",
        ),
    ]

    result = run_advanced_dedupe(
        groups,
        _recursive_config(favor_b=True),
        scan_roots=["/root"],
        protect_last_file_counts={
            "/root": 8,
            "/root/A": 3,
            "/root/A/deep": 2,
            "/root/B": 3,
            "/root/B/deep": 2,
        },
    )

    large = next(group for group in result.groups if group.group_provenance_id == "01-large")
    small = next(group for group in result.groups if group.group_provenance_id == "02-small")

    assert large.status == "actionable"
    assert large.recommended_keep is not None
    assert large.recommended_keep.absolute_path == "/root/B/one.bin"
    assert large.quarantine_candidates == ["/root/A/deep/one.bin"]

    # /root/A/deep started at 2. The first planned quarantine consumes one;
    # the second proposed quarantine would leave 0. B remains the unique top
    # scorer, so recursive protection must SKIP rather than fall back to A.
    assert small.status == "skipped"
    assert small.quarantine_candidates == []
    assert "RECURSIVE_PROTECT_LAST_FILE" in (small.skip_reason or "")


def test_recursive_protection_exact_threshold_one_remains_safe():
    group = _group(
        "threshold-one",
        file_size=100,
        left_path="/root/A/deep/a.bin",
        right_path="/root/B/deep/b.bin",
    )

    result = run_advanced_dedupe(
        [group],
        _recursive_config(),
        scan_roots=["/root"],
        protect_last_file_counts={
            "/root": 4,
            "/root/A": 2,
            "/root/A/deep": 2,
            "/root/B": 2,
            "/root/B/deep": 2,
        },
    )

    assert result.groups[0].status == "actionable"
    assert len(result.groups[0].quarantine_candidates) == 1


def _create_completed_scan(session: Session, scan_id: int, root: Path) -> None:
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
            reclaimable_bytes=3,
        )
    )
    session.commit()


def _add_db_group(
    session: Session,
    *,
    scan_id: int,
    root: Path,
    left: Path,
    right: Path,
    content_hash: str,
) -> None:
    file_size = left.stat().st_size
    assert right.stat().st_size == file_size
    group = DuplicateGroup(
        scan_job_id=scan_id,
        content_hash=content_hash,
        file_size=file_size,
        member_count=2,
    )
    session.add(group)
    session.flush()

    for path in (left, right):
        relative = path.relative_to(root)
        parts = relative.parts
        top_level = root / parts[0] if len(parts) > 1 else root
        session.add(
            DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(path),
                relative_path=relative.as_posix(),
                top_level_dir=str(top_level),
                size=file_size,
                mtime_ns=path.stat().st_mtime_ns,
            )
        )
    session.commit()


def _make_two_branch_fixture(tmp_path: Path, *, nested_extra_in_a: bool = False):
    root = tmp_path / "root"
    a_deep = root / "A" / "deep"
    b_deep = root / "B" / "deep"
    a_deep.mkdir(parents=True)
    b_deep.mkdir(parents=True)

    left = a_deep / "dup.bin"
    right = b_deep / "dup.bin"
    left.write_bytes(b"dup")
    right.write_bytes(b"dup")

    # Top-level extras ensure a legacy top-level-only check cannot detect that
    # the deep duplicate branch itself would become empty.
    (root / "A" / "top-extra.bin").write_bytes(b"x")
    (root / "B" / "top-extra.bin").write_bytes(b"x")

    if nested_extra_in_a:
        nested = a_deep / "nested"
        nested.mkdir()
        (nested / "real-extra.bin").write_bytes(b"x")

    return root, left, right, a_deep, b_deep


def test_recursive_preview_protection_is_mandatory_even_when_flag_false(
    db_session: Session,
    tmp_path: Path,
):
    root, left, right, _a_deep, _b_deep = _make_two_branch_fixture(tmp_path)
    _create_completed_scan(db_session, 101, root)
    _add_db_group(
        db_session,
        scan_id=101,
        root=root,
        left=left,
        right=right,
        content_hash="recursive-mandatory",
    )

    result = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=101,
        config=_recursive_config(),
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    assert result.actionable_group_count == 0
    assert result.skipped_group_count == 1
    assert result.planned_quarantine_count == 0
    assert result.groups[0].status == "skipped"
    assert "RECURSIVE_PROTECT_LAST_FILE" in (result.groups[0].skip_reason or "")


def test_recursive_preview_counts_regular_files_recursively_in_subtree(
    db_session: Session,
    tmp_path: Path,
):
    root, left, right, _a_deep, _b_deep = _make_two_branch_fixture(
        tmp_path,
        nested_extra_in_a=True,
    )
    _create_completed_scan(db_session, 102, root)
    _add_db_group(
        db_session,
        scan_id=102,
        root=root,
        left=left,
        right=right,
        content_hash="recursive-subtree",
    )

    result = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=102,
        config=_recursive_config(),
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    # Keeping A would quarantine B's only real file and is unsafe. Keeping B
    # quarantines A/dup.bin but A/deep still contains nested/real-extra.bin.
    decision = result.groups[0]
    assert decision.status == "actionable"
    assert decision.recommended_keep is not None
    assert decision.recommended_keep.absolute_path == str(right)
    assert decision.quarantine_candidates == [str(left)]


def test_recursive_preview_symlink_file_and_directory_do_not_count_as_regular_files(
    db_session: Session,
    tmp_path: Path,
):
    root, left, right, a_deep, b_deep = _make_two_branch_fixture(tmp_path)

    target_file = root / "target-file.bin"
    target_file.write_bytes(b"real")
    os.symlink(target_file, a_deep / "symlink-file.bin")

    target_dir = root / "target-dir"
    target_dir.mkdir()
    (target_dir / "real-inside.bin").write_bytes(b"real")
    os.symlink(target_dir, b_deep / "symlink-dir")

    _create_completed_scan(db_session, 103, root)
    _add_db_group(
        db_session,
        scan_id=103,
        root=root,
        left=left,
        right=right,
        content_hash="recursive-symlink-count",
    )

    result = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=103,
        config=_recursive_config(),
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    assert result.groups[0].status == "skipped"
    assert result.groups[0].quarantine_candidates == []
    assert "RECURSIVE_PROTECT_LAST_FILE" in (result.groups[0].skip_reason or "")


def test_old_weighted_mode_can_still_disable_historical_last_file_protection(
    db_session: Session,
    tmp_path: Path,
):
    root, left, right, _a_deep, _b_deep = _make_two_branch_fixture(tmp_path)
    _create_completed_scan(db_session, 104, root)
    _add_db_group(
        db_session,
        scan_id=104,
        root=root,
        left=left,
        right=right,
        content_hash="old-mode-compatible",
    )

    weighted = validate_and_canonicalize_config(
        {"schema_version": 1, "selection_mode": "weighted", "factors": {}}
    )
    result = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=104,
        config=weighted,
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    assert result.groups[0].status == "actionable"
    assert result.planned_quarantine_count == 1
