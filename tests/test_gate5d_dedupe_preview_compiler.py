import json
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Base,
    ScanJob,
    DuplicateGroup,
    DuplicateFile,
    BatchPlan,
    BatchPlanItem,
    WorkJob,
    QuarantineEntry,
    utcnow,
)
from app.planning.dedupe_config import (
    AdvancedDedupeConfig,
    DedupeFactorsConfig,
    PathPriorityFactor,
    PathPriorityRule,
    PreferredExtensionFactor,
    MtimeFactor,
    validate_and_canonicalize_config,
)
from app.planning.dedupe_preview import (
    compile_advanced_dedupe_preview,
    DedupePreviewCompilation,
    DedupeScanNotFoundError,
    DedupeScanNotCompletedError,
    DedupeLimitExceededError,
)


@pytest.fixture
def db_session(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        yield session


def _create_completed_scan(
    session: Session,
    scan_id: int,
    roots: list[str],
    status: str = "completed",
) -> ScanJob:
    scan = ScanJob(
        id=scan_id,
        name=f"scan-{scan_id}",
        mode="normal",
        roots_json=json.dumps(roots),
        status=status,
        started_at=utcnow(),
        finished_at=utcnow(),
        total_groups=0,
        total_files_in_groups=0,
        reclaimable_bytes=0,
    )
    session.add(scan)
    session.commit()
    return scan


# =========================================================================
# 1. SCAN AUTHORITY TESTS
# =========================================================================

def test_scan_authority_not_found(db_session: Session, tmp_path: Path):
    cfg = AdvancedDedupeConfig()
    with pytest.raises(DedupeScanNotFoundError, match="DEDUPE_SCAN_NOT_FOUND"):
        compile_advanced_dedupe_preview(
            db_session,
            scan_job_id=999,
            config=cfg,
            allowed_roots=[str(tmp_path)],
        )


def test_scan_authority_not_completed(db_session: Session, tmp_path: Path):
    _create_completed_scan(db_session, scan_id=1, roots=[str(tmp_path)], status="running")
    cfg = AdvancedDedupeConfig()
    with pytest.raises(DedupeScanNotCompletedError, match="DEDUPE_SCAN_NOT_COMPLETED"):
        compile_advanced_dedupe_preview(
            db_session,
            scan_job_id=1,
            config=cfg,
            allowed_roots=[str(tmp_path)],
        )


def test_scan_authority_malformed_roots_json(db_session: Session, tmp_path: Path):
    scan = ScanJob(
        id=2,
        name="scan-malformed",
        mode="normal",
        roots_json="not-json",
        status="completed",
    )
    db_session.add(scan)
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    with pytest.raises(ValueError, match="Invalid scan roots_json"):
        compile_advanced_dedupe_preview(
            db_session,
            scan_job_id=2,
            config=cfg,
            allowed_roots=[str(tmp_path)],
        )


def test_scan_authority_empty_roots_json(db_session: Session, tmp_path: Path):
    scan = ScanJob(
        id=3,
        name="scan-empty-roots",
        mode="normal",
        roots_json="[]",
        status="completed",
    )
    db_session.add(scan)
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    with pytest.raises(ValueError, match="Invalid scan roots_json"):
        compile_advanced_dedupe_preview(
            db_session,
            scan_job_id=3,
            config=cfg,
            allowed_roots=[str(tmp_path)],
        )


def test_candidate_cap_exceeded(db_session: Session, tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=4, roots=[str(root)])

    # Mock count to simulate > 50,000 members
    import app.planning.dedupe_preview as dp_mod
    monkeypatch.setattr(dp_mod, "MAX_DEDUPE_CANDIDATES", 5)

    g = DuplicateGroup(scan_job_id=4, content_hash="h1", file_size=100, member_count=6)
    db_session.add(g)
    db_session.flush()
    for i in range(6):
        f = root / f"file_{i}.txt"
        f.write_text("x")
        db_session.add(DuplicateFile(
            group_id=g.id,
            root_id=0,
            absolute_path=str(f),
            relative_path=f"file_{i}.txt",
            top_level_dir=str(root),
            size=100,
            mtime_ns=1000,
        ))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    with pytest.raises(DedupeLimitExceededError, match="DEDUPE_LIMIT_EXCEEDED"):
        compile_advanced_dedupe_preview(
            db_session,
            scan_job_id=4,
            config=cfg,
            allowed_roots=[str(root)],
        )


# =========================================================================
# 2. SOURCE SAFETY TESTS
# =========================================================================

def test_source_safety_missing_member_skips_whole_group(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=10, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("dup")
    # f2 is NOT created on disk -> missing

    g = DuplicateGroup(scan_job_id=10, content_hash="hash_miss", file_size=3, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=3, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=3, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=10,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.planned_quarantine_count == 0
    assert res.expected_reclaim_bytes == 0
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason in {"SOURCE_SNAPSHOT_STALE", "FILESYSTEM_SAFETY_CHECK_FAILED"}


def test_source_safety_symlink_member_skips_whole_group(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=11, roots=[str(root)])

    f1 = root / "f1.txt"
    target = root / "target.txt"
    f2_link = root / "f2_link.txt"
    f1.write_text("dup")
    target.write_text("dup")
    os.symlink(str(target), str(f2_link))

    g = DuplicateGroup(scan_job_id=11, content_hash="hash_sym", file_size=3, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=3, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2_link), relative_path="f2_link.txt", top_level_dir=str(root), size=3, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=11,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason in {"SOURCE_SNAPSHOT_STALE", "FILESYSTEM_SAFETY_CHECK_FAILED"}


def test_source_safety_outside_allowed_root_skips_whole_group(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _create_completed_scan(db_session, scan_id=12, roots=[str(root), str(outside)])

    f1 = root / "f1.txt"
    f2 = outside / "f2.txt"
    f1.write_text("dup")
    f2.write_text("dup")

    g = DuplicateGroup(scan_job_id=12, content_hash="hash_out", file_size=3, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=3, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=1, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(outside), size=3, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    # allowed_roots ONLY contains root, not outside
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=12,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert "OUTSIDE" in res.groups[0].skip_reason or "SAFETY" in res.groups[0].skip_reason


# =========================================================================
# 3. PROTECT LAST FILE TESTS
# =========================================================================

def test_protect_last_file_excludes_unsafe_candidate(db_session: Session, tmp_path: Path):
    # Dir A has only 1 file (f_a)
    # Dir B has 2 files (f_b, extra_b)
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=20, roots=[str(root)])

    f_a = dir_a / "f.txt"
    f_b = dir_b / "f.txt"
    extra_b = dir_b / "extra.txt"
    f_a.write_text("content")
    f_b.write_text("content")
    extra_b.write_text("other")

    g = DuplicateGroup(scan_job_id=20, content_hash="h_plf", file_size=7, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_a), relative_path="dir_a/f.txt", top_level_dir=str(dir_a), size=7, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_b), relative_path="dir_b/f.txt", top_level_dir=str(dir_b), size=7, mtime_ns=1))
    db_session.commit()

    # Configure path priority favoring dir_b!
    # If f_b is kept -> f_a is deleted -> dir_a would have 0 regular files!
    # With protect_last_file=True:
    # Candidate f_b cannot be kept because deleting f_a empties dir_a!
    # Candidate f_a CAN be kept because deleting f_b leaves extra.txt in dir_b!
    # Therefore, f_a MUST win despite scorer favoring dir_b!
    cfg = AdvancedDedupeConfig(
        factors=DedupeFactorsConfig(
            path_priority=PathPriorityFactor(
                enabled=True,
                weight=100,
                rules=(PathPriorityRule(scope="relative", pattern="dir_b/*"),),
            )
        )
    )

    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=20,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res.actionable_group_count == 1
    group_res = res.groups[0]
    assert group_res.status == "actionable"
    assert group_res.recommended_keep.absolute_path == str(f_a)
    assert group_res.quarantine_candidates == [str(f_b)]

    # Explain shows f_b was ineligible due to PROTECT_LAST_FILE
    explain_fb = next(m for m in group_res.members if m.absolute_path == str(f_b))
    assert explain_fb.eligible_as_keep is False
    assert "PROTECT_LAST_FILE" in explain_fb.safety_reasons


def test_protect_last_file_zero_safe_candidates_skips_group(db_session: Session, tmp_path: Path):
    # Dir A has only 1 file (f_a)
    # Dir B has only 1 file (f_b)
    # Deleting either would empty a directory!
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=21, roots=[str(root)])

    f_a = dir_a / "f.txt"
    f_b = dir_b / "f.txt"
    f_a.write_text("content")
    f_b.write_text("content")

    g = DuplicateGroup(scan_job_id=21, content_hash="h_plf2", file_size=7, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_a), relative_path="dir_a/f.txt", top_level_dir=str(dir_a), size=7, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_b), relative_path="dir_b/f.txt", top_level_dir=str(dir_b), size=7, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=21,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.planned_quarantine_count == 0
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "PROTECT_LAST_FILE_NO_SAFE_SELECTION"


def test_protect_last_file_cumulative_scheduled_deletes(db_session: Session, tmp_path: Path):
    # Dir A has 2 duplicate files (f1_a, f2_a) and 0 extra files.
    # Dir B has plenty of files.
    # Group 1 (large size): f1_a and f1_b.
    # Group 2 (small size): f2_a and f2_b.
    # Group 1 is evaluated first due to size DESC.
    # Group 1 decides to quarantine f1_a (leaving 1 file in Dir A: f2_a).
    # When Group 2 is evaluated:
    # Dir A originally had 2 files, but 1 was already scheduled for quarantine by Group 1!
    # So Group 2 CANNOT quarantine f2_a because 2 - 1 - 1 = 0 < 1!
    # Thus in Group 2, f2_a MUST be kept and f2_b must be quarantined!
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=22, roots=[str(root)])

    f1_a = dir_a / "f1.txt"
    f1_b = dir_b / "f1.txt"
    f2_a = dir_a / "f2.txt"
    f2_b = dir_b / "f2.txt"
    extra_b = dir_b / "extra.txt"

    f1_a.write_text("large")
    f1_b.write_text("large")
    f2_a.write_text("small")
    f2_b.write_text("small")
    extra_b.write_text("extra")

    # Group 1 (large: 100 bytes)
    g1 = DuplicateGroup(scan_job_id=22, content_hash="h_large", file_size=100, member_count=2)
    db_session.add(g1)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_a), relative_path="dir_a/f1.txt", top_level_dir=str(dir_a), size=100, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_b), relative_path="dir_b/f1.txt", top_level_dir=str(dir_b), size=100, mtime_ns=1))

    # Group 2 (small: 10 bytes)
    g2 = DuplicateGroup(scan_job_id=22, content_hash="h_small", file_size=10, member_count=2)
    db_session.add(g2)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f2_a), relative_path="dir_a/f2.txt", top_level_dir=str(dir_a), size=10, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f2_b), relative_path="dir_b/f2.txt", top_level_dir=str(dir_b), size=10, mtime_ns=1))
    db_session.commit()

    # Preference strongly favors dir_b for KEEP
    cfg = AdvancedDedupeConfig(
        factors=DedupeFactorsConfig(
            path_priority=PathPriorityFactor(
                enabled=True,
                weight=100,
                rules=(PathPriorityRule(scope="relative", pattern="dir_b/*"),),
            )
        )
    )

    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=22,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res.actionable_group_count == 2
    # Find group results
    res_g1 = next(g for g in res.groups if g.file_size == 100)
    res_g2 = next(g for g in res.groups if g.file_size == 10)

    # In Group 1, dir_b winner keeps f1_b, quarantines f1_a
    assert res_g1.recommended_keep.absolute_path == str(f1_b)
    assert res_g1.quarantine_candidates == [str(f1_a)]

    # In Group 2, f2_b would normally win by score, but quarantining f2_a would leave dir_a with 0 files!
    # Because f1_a is already scheduled for quarantine!
    # Therefore f2_a MUST be kept!
    assert res_g2.recommended_keep.absolute_path == str(f2_a)
    assert res_g2.quarantine_candidates == [str(f2_b)]


def test_protect_last_file_disabled(db_session: Session, tmp_path: Path):
    # Same as test_protect_last_file_zero_safe_candidates_skips_group,
    # but protect_last_file=False -> both files can be planned without exclusion!
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=23, roots=[str(root)])

    f_a = dir_a / "f.txt"
    f_b = dir_b / "f.txt"
    f_a.write_text("content")
    f_b.write_text("content")

    g = DuplicateGroup(scan_job_id=23, content_hash="h_plf_off", file_size=7, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_a), relative_path="dir_a/f.txt", top_level_dir=str(dir_a), size=7, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_b), relative_path="dir_b/f.txt", top_level_dir=str(dir_b), size=7, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=23,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    assert res.actionable_group_count == 1
    assert res.skipped_group_count == 0
    assert res.planned_quarantine_count == 1


# =========================================================================
# 4. BALANCE + SAFETY
# =========================================================================

def test_balancer_never_chooses_ineligible_candidate(db_session: Session, tmp_path: Path):
    # Two roots (root 0 and root 1)
    # root 0 has dir_a with 1 file (f_0)
    # root 1 has dir_b with 2 files (f_1, extra_1)
    # Balanced-by-bytes selection mode
    root0 = tmp_path / "r0"
    root1 = tmp_path / "r1"
    root0.mkdir()
    root1.mkdir()
    dir_a = root0 / "a"
    dir_b = root1 / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    _create_completed_scan(db_session, scan_id=30, roots=[str(root0), str(root1)])

    f_0 = dir_a / "f.bin"
    f_1 = dir_b / "f.bin"
    extra_1 = dir_b / "extra.bin"
    f_0.write_text("x")
    f_1.write_text("x")
    extra_1.write_text("y")

    g = DuplicateGroup(scan_job_id=30, content_hash="h_bal", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_0), relative_path="a/f.bin", top_level_dir=str(dir_a), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=1, absolute_path=str(f_1), relative_path="b/f.bin", top_level_dir=str(dir_b), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig(selection_mode="balanced_by_bytes")
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=30,
        config=cfg,
        allowed_roots=[str(root0), str(root1)],
        protect_last_file=True,
    )

    # Balancer cannot pick f_1 as keep because that would quarantine f_0 and empty dir_a!
    # f_0 must be kept!
    assert res.groups[0].recommended_keep.absolute_path == str(f_0)
    assert res.released_bytes_by_scan_root[1] == 1
    assert res.released_bytes_by_scan_root[0] == 0


# =========================================================================
# 5. DETERMINISM & DIGESTS
# =========================================================================

def test_db_query_order_invariance(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=40, roots=[str(root)])

    for i in range(3):
        p1 = root / f"g{i}_1.txt"
        p2 = root / f"g{i}_2.txt"
        p1.write_text(f"content_{i}")
        p2.write_text(f"content_{i}")
        g = DuplicateGroup(scan_job_id=40, content_hash=f"h_{i}", file_size=10 + i, member_count=2)
        db_session.add(g)
        db_session.flush()
        db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(p1), relative_path=f"g{i}_1.txt", top_level_dir=str(root), size=10 + i, mtime_ns=1))
        db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(p2), relative_path=f"g{i}_2.txt", top_level_dir=str(root), size=10 + i, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res1 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=40,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    res2 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=40,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    assert res1.source_snapshot_digest == res2.source_snapshot_digest
    assert res1.decision_digest == res2.decision_digest
    assert res1.planned_quarantine_count == res2.planned_quarantine_count


# =========================================================================
# 6. NO MUTATION PROOF
# =========================================================================

def test_no_mutation_proof(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=50, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("data")
    f2.write_text("data")

    mtime_f1_before = f1.stat().st_mtime_ns
    mtime_f2_before = f2.stat().st_mtime_ns
    content_f1_before = f1.read_bytes()
    content_f2_before = f2.read_bytes()

    g = DuplicateGroup(scan_job_id=50, content_hash="h_nomut", file_size=4, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=4, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=4, mtime_ns=1))
    db_session.commit()

    plan_count_before = db_session.scalar(select(func.count(BatchPlan.id))) or 0
    item_count_before = db_session.scalar(select(func.count(BatchPlanItem.id))) or 0
    work_count_before = db_session.scalar(select(func.count(WorkJob.id))) or 0
    quarantine_count_before = db_session.scalar(select(func.count(QuarantineEntry.id))) or 0

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=50,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=False,
    )

    plan_count_after = db_session.scalar(select(func.count(BatchPlan.id))) or 0
    item_count_after = db_session.scalar(select(func.count(BatchPlanItem.id))) or 0
    work_count_after = db_session.scalar(select(func.count(WorkJob.id))) or 0
    quarantine_count_after = db_session.scalar(select(func.count(QuarantineEntry.id))) or 0

    assert plan_count_after == plan_count_before == 0
    assert item_count_after == item_count_before == 0
    assert work_count_after == work_count_before == 0
    assert quarantine_count_after == quarantine_count_before == 0

    assert f1.exists() and f2.exists()
    assert f1.read_bytes() == content_f1_before
    assert f2.read_bytes() == content_f2_before
    assert f1.stat().st_mtime_ns == mtime_f1_before
    assert f2.stat().st_mtime_ns == mtime_f2_before


def test_scan_authority_root_index_out_of_bounds(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=60, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("x")
    f2.write_text("x")

    g = DuplicateGroup(scan_job_id=60, content_hash="h_badroot", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    # root_id=99 is out of bounds for roots list of length 1
    db_session.add(DuplicateFile(group_id=g.id, root_id=99, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=60,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "INVALID_SCAN_ROOT_INDEX"


def test_source_safety_directory_as_member_skips_whole_group(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=61, roots=[str(root)])

    f1 = root / "f1.txt"
    dir_member = root / "dir_member"
    f1.write_text("x")
    dir_member.mkdir()  # directory instead of regular file

    g = DuplicateGroup(scan_job_id=61, content_hash="h_dir_mem", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(dir_member), relative_path="dir_member", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=61,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "SOURCE_SNAPSHOT_STALE"


def test_digest_changes_when_file_snapshot_changes(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=62, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("orig")
    f2.write_text("orig")

    g = DuplicateGroup(scan_job_id=62, content_hash="h_snap", file_size=4, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=4, mtime_ns=100))
    f2_row = DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=4, mtime_ns=100)
    db_session.add(f2_row)
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res1 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=62,
        config=cfg,
        allowed_roots=[str(root)],
    )

    # Change mtime_ns in DB snapshot
    f2_row.mtime_ns = 9999
    db_session.commit()

    res2 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=62,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res1.source_snapshot_digest != res2.source_snapshot_digest
    assert res1.decision_digest != res2.decision_digest


def test_digest_changes_when_directory_file_count_changes(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=63, roots=[str(root)])

    f1 = dir_a / "f.txt"
    f2 = dir_b / "f.txt"
    f1.write_text("c")
    f2.write_text("c")

    g = DuplicateGroup(scan_job_id=63, content_hash="h_dircnt", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="dir_a/f.txt", top_level_dir=str(dir_a), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="dir_b/f.txt", top_level_dir=str(dir_b), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res1 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=63,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    # Add a new file to dir_a on filesystem
    (dir_a / "extra_file.txt").write_text("extra")

    res2 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=63,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res1.source_snapshot_digest != res2.source_snapshot_digest


def test_cumulative_logic_obeys_d1_order_regardless_of_db_id(db_session: Session, tmp_path: Path):
    # Insert smaller file size group first with ID 1
    # Insert larger file size group second with ID 2
    # In D1 sort order, Group with larger file size (100) must be evaluated FIRST!
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=64, roots=[str(root)])

    f_small_a = dir_a / "small.txt"
    f_small_b = dir_b / "small.txt"
    f_large_a = dir_a / "large.txt"
    f_large_b = dir_b / "large.txt"
    extra_b = dir_b / "extra.txt"

    f_small_a.write_text("s")
    f_small_b.write_text("s")
    f_large_a.write_text("l" * 100)
    f_large_b.write_text("l" * 100)
    extra_b.write_text("e")

    # DB ID 1 is SMALL (size 1)
    g_small = DuplicateGroup(id=1, scan_job_id=64, content_hash="h_small", file_size=1, member_count=2)
    db_session.add(g_small)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=1, root_id=0, absolute_path=str(f_small_a), relative_path="dir_a/small.txt", top_level_dir=str(dir_a), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=1, root_id=0, absolute_path=str(f_small_b), relative_path="dir_b/small.txt", top_level_dir=str(dir_b), size=1, mtime_ns=1))

    # DB ID 2 is LARGE (size 100)
    g_large = DuplicateGroup(id=2, scan_job_id=64, content_hash="h_large", file_size=100, member_count=2)
    db_session.add(g_large)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=2, root_id=0, absolute_path=str(f_large_a), relative_path="dir_a/large.txt", top_level_dir=str(dir_a), size=100, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=2, root_id=0, absolute_path=str(f_large_b), relative_path="dir_b/large.txt", top_level_dir=str(dir_b), size=100, mtime_ns=1))
    db_session.commit()

    # Preference favors dir_b
    cfg = AdvancedDedupeConfig(
        factors=DedupeFactorsConfig(
            path_priority=PathPriorityFactor(
                enabled=True,
                weight=100,
                rules=(PathPriorityRule(scope="relative", pattern="dir_b/*"),),
            )
        )
    )

    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=64,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    # First group in compilation output MUST be the large group (file_size=100)
    assert res.groups[0].file_size == 100
    assert res.groups[1].file_size == 1

    # Large group keeps f_large_b, quarantines f_large_a
    assert res.groups[0].recommended_keep.absolute_path == str(f_large_b)

    # Small group cannot quarantine f_small_a because dir_a only had 2 files, and f_large_a is already scheduled!
    # So small group MUST keep f_small_a!
    assert res.groups[1].recommended_keep.absolute_path == str(f_small_a)


def test_top_level_dir_mismatch_fails_closed(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    dir_b = root / "dir_b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=70, roots=[str(root)])

    f_a = dir_a / "f.txt"
    f_b = dir_b / "f.txt"
    (dir_b / "extra.txt").write_text("extra")
    f_a.write_text("content")
    f_b.write_text("content")

    g = DuplicateGroup(scan_job_id=70, content_hash="h_tlm", file_size=7, member_count=2)
    db_session.add(g)
    db_session.flush()
    # Malformed row: f_a is in dir_a, but DB top_level_dir is erroneously set to dir_b!
    db_session.add(DuplicateFile(
        group_id=g.id,
        root_id=0,
        absolute_path=str(f_a),
        relative_path="dir_a/f.txt",
        top_level_dir=str(dir_b),  # WRONG! Derived is dir_a
        size=7,
        mtime_ns=1,
    ))
    db_session.add(DuplicateFile(
        group_id=g.id,
        root_id=0,
        absolute_path=str(f_b),
        relative_path="dir_b/f.txt",
        top_level_dir=str(dir_b),
        size=7,
        mtime_ns=1,
    ))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=70,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.planned_quarantine_count == 0
    assert res.expected_reclaim_bytes == 0
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "TOP_LEVEL_DIR_MISMATCH"
    # The mismatched member explain has TOP_LEVEL_DIR_MISMATCH
    explain_a = next(m for m in res.groups[0].members if m.absolute_path == str(f_a))
    assert explain_a.eligible_as_keep is False
    assert "TOP_LEVEL_DIR_MISMATCH" in explain_a.safety_reasons


def test_skipped_group_does_not_traverse_untrusted_top_level_dir(db_session: Session, tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    dir_a = root / "dir_a"
    untrusted_dir = tmp_path / "huge_untrusted_dir"
    dir_a.mkdir(parents=True)
    untrusted_dir.mkdir(parents=True)

    _create_completed_scan(db_session, scan_id=71, roots=[str(root)])

    f_a = dir_a / "f.txt"
    f_missing = root / "missing.txt"
    f_a.write_text("content")
    # f_missing does not exist -> group will be skipped for SOURCE_NOT_FOUND / SOURCE_SNAPSHOT_STALE

    g = DuplicateGroup(scan_job_id=71, content_hash="h_trav", file_size=7, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(
        group_id=g.id,
        root_id=0,
        absolute_path=str(f_a),
        relative_path="dir_a/f.txt",
        top_level_dir=str(dir_a),
        size=7,
        mtime_ns=1,
    ))
    db_session.add(DuplicateFile(
        group_id=g.id,
        root_id=0,
        absolute_path=str(f_missing),
        relative_path="missing.txt",
        top_level_dir=str(untrusted_dir),
        size=7,
        mtime_ns=1,
    ))
    db_session.commit()

    traversed_dirs = []
    orig_rglob = Path.rglob

    def spy_rglob(self, pattern):
        traversed_dirs.append(str(self))
        return orig_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", spy_rglob)

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=71,
        config=cfg,
        allowed_roots=[str(root)],
        protect_last_file=True,
    )

    assert res.skipped_group_count == 1
    # Untrusted dir or dirs from skipped group must NOT be traversed!
    assert str(untrusted_dir) not in traversed_dirs
    assert str(dir_a) not in traversed_dirs


def test_missing_member_explain_contains_safety_reason(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=72, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("x")
    # f2 missing

    g = DuplicateGroup(scan_job_id=72, content_hash="h_miss_exp", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=72,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    explain_f2 = next(m for m in res.groups[0].members if m.absolute_path == str(f2))
    assert explain_f2.eligible_as_keep is False
    assert "SOURCE_NOT_FOUND" in explain_f2.safety_reasons


def test_symlink_member_explain_contains_safety_reason(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=73, roots=[str(root)])

    f1 = root / "f1.txt"
    target = root / "target.txt"
    f2 = root / "f2.txt"
    f1.write_text("x")
    target.write_text("x")
    os.symlink(str(target), str(f2))

    g = DuplicateGroup(scan_job_id=73, content_hash="h_sym_exp", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=73,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    explain_f2 = next(m for m in res.groups[0].members if m.absolute_path == str(f2))
    assert explain_f2.eligible_as_keep is False
    assert "SYMLINK" in explain_f2.safety_reasons


def test_invalid_raw_root_id_changes_source_snapshot_digest(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=74, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f1.write_text("x")
    f2.write_text("x")

    g = DuplicateGroup(scan_job_id=74, content_hash="h_raw_rid", file_size=1, member_count=2)
    db_session.add(g)
    db_session.flush()
    db_session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    f2_row = DuplicateFile(group_id=g.id, root_id=99, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=1, mtime_ns=1)
    db_session.add(f2_row)
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res1 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=74,
        config=cfg,
        allowed_roots=[str(root)],
    )

    # Change invalid root_id from 99 to 100
    f2_row.root_id = 100
    db_session.commit()

    res2 = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=74,
        config=cfg,
        allowed_roots=[str(root)],
    )

    # Digest MUST change even though both are invalid/skipped!
    assert res1.source_snapshot_digest != res2.source_snapshot_digest


def test_cross_group_duplicate_member_path_fails_closed(db_session: Session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    _create_completed_scan(db_session, scan_id=75, roots=[str(root)])

    f1 = root / "f1.txt"
    f2 = root / "f2.txt"
    f3 = root / "f3.txt"
    f1.write_text("x")
    f2.write_text("x")
    f3.write_text("x")

    # Inconsistent DB: f1 appears in both group 1 and group 2
    g1 = DuplicateGroup(scan_job_id=75, content_hash="h1", file_size=1, member_count=2)
    g2 = DuplicateGroup(scan_job_id=75, content_hash="h2", file_size=1, member_count=2)
    db_session.add_all([g1, g2])
    db_session.flush()

    db_session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f2), relative_path="f2.txt", top_level_dir=str(root), size=1, mtime_ns=1))

    db_session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f1), relative_path="f1.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f3), relative_path="f3.txt", top_level_dir=str(root), size=1, mtime_ns=1))
    db_session.commit()

    cfg = AdvancedDedupeConfig()
    res = compile_advanced_dedupe_preview(
        db_session,
        scan_job_id=75,
        config=cfg,
        allowed_roots=[str(root)],
    )

    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 2
    for g_res in res.groups:
        assert g_res.status == "skipped"
        assert g_res.skip_reason == "SOURCE_SNAPSHOT_INCONSISTENT"


