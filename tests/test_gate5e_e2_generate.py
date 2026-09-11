import json
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem
from app.service import FileCenterService
from app.batch_utilities.schema import SuffixTransformAction
from app.batch_utilities.errors import (
    BatchUtilityPreviewChangedError,
    BatchUtilityEmptyPlanError,
    BatchUtilityConflictError,
)


@pytest.fixture
def service_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
    )

    svc = FileCenterService(settings)
    return svc, svc.SessionLocal, data_dir, quarantine_dir


def test_generate_suffix_transform_plan_success(service_env):
    svc, Session, allowed, _ = service_env

    f1 = allowed / "file1.png"
    f1.write_text("content1")
    f2 = allowed / "file2.jpg"
    f2.write_text("content2")

    st1 = f1.stat()
    st2 = f2.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()

        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.png",
            basename="file1.png",
            stem="file1",
            suffix=".png",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        ip2 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f2),
            relative_path="file2.jpg",
            basename="file2.jpg",
            stem="file2",
            suffix=".jpg",
            size=st2.st_size,
            mtime_ns=st2.st_mtime_ns,
            device=st2.st_dev,
            inode=st2.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([ip1, ip2])
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="change",
        suffix=".webp",
    )

    # 1. Preview
    preview = svc.get_batch_utility_preview(action=action)
    assert preview["utility_action"] == "suffix_transform"
    assert preview["planned_operations_count"] == 2
    assert preview["blocking_conflict_count"] == 0
    digest = preview["preview_digest"]

    # 2. Generate
    plan_info = svc.create_batch_utility_plan(
        action=action,
        expected_preview_digest=digest,
    )
    assert plan_info["status"] == "draft"
    assert plan_info["utility_action"] == "suffix_transform"
    assert plan_info["expected_changes"] == 2

    # 3. Verify DB Draft
    with Session() as session:
        plan = session.get(BatchPlan, plan_info["id"])
        assert plan is not None
        assert plan.status == "draft"
        assert plan.kind == "batch-utility"

        items = session.query(BatchPlanItem).filter_by(plan_id=plan.id).order_by(BatchPlanItem.sequence.asc()).all()
        assert len(items) == 2

        it1 = items[0]
        assert it1.operation == "rename"
        assert it1.source_path == str(f1)
        assert it1.target_path == str(allowed / "file1.webp")
        assert it1.expected_device == 0
        assert it1.expected_inode == 0
        assert it1.expected_mtime_ns == 0
        assert it1.expected_hash is None

        meta1 = json.loads(it1.metadata_json)
        assert meta1["utility_action"] == "suffix_transform"
        assert meta1["mode"] == "change"
        assert meta1["suffix"] == ".webp"
        assert meta1["source_basename"] == "file1.png"
        assert meta1["target_basename"] == "file1.webp"


def test_generate_suffix_transform_digest_mismatch_fails(service_env):
    svc, Session, allowed, _ = service_env
    f1 = allowed / "file1.png"
    f1.write_text("content1")
    st1 = f1.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.png",
            basename="file1.png",
            stem="file1",
            suffix=".png",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip1)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="append",
        suffix=".bak",
    )

    with pytest.raises(BatchUtilityPreviewChangedError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest="0" * 64,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0


def test_generate_suffix_transform_blocking_conflict_fails(service_env):
    svc, Session, allowed, _ = service_env
    # Target file exists and will not vacate
    f1 = allowed / "file1.png"
    f1.write_text("content1")
    f_target = allowed / "file1.png.bak"
    f_target.write_text("already exists")

    st1 = f1.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.png",
            basename="file1.png",
            stem="file1",
            suffix=".png",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip1)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="append",
        suffix=".bak",
    )

    preview = svc.get_batch_utility_preview(action=action)
    assert preview["blocking_conflict_count"] == 1
    digest = preview["preview_digest"]

    with pytest.raises(BatchUtilityConflictError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0


def test_generate_suffix_transform_safe_and_conflict_coexistence(service_env):
    """Reviewer reproduction D: safe.jpg -> safe.txt (RENAME) survives in preview, but generate rejects with 409, 0 draft."""
    svc, Session, allowed, _ = service_env
    f_safe = allowed / "safe.jpg"
    f_safe.write_text("safe")
    f_bad = allowed / "bad.jpg"
    f_bad.write_text("bad")

    # Existing conflict target
    f_occ = allowed / "bad.jpg.txt"
    f_occ.write_text("occupied")

    st_safe = f_safe.stat()
    st_bad = f_bad.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()

        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f_safe),
            relative_path="safe.jpg",
            basename="safe.jpg",
            stem="safe",
            suffix=".jpg",
            size=st_safe.st_size,
            mtime_ns=st_safe.st_mtime_ns,
            device=st_safe.st_dev,
            inode=st_safe.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        ip2 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f_bad),
            relative_path="bad.jpg",
            basename="bad.jpg",
            stem="bad",
            suffix=".jpg",
            size=st_bad.st_size,
            mtime_ns=st_bad.st_mtime_ns,
            device=st_bad.st_dev,
            inode=st_bad.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([ip1, ip2])
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="append",
        suffix=".txt",
    )

    preview = svc.get_batch_utility_preview(action=action)
    assert preview["planned_operations_count"] == 1
    assert preview["blocking_conflict_count"] == 1
    digest = preview["preview_digest"]

    with pytest.raises(BatchUtilityConflictError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0



def test_generate_suffix_transform_empty_plan_fails(service_env):
    svc, Session, allowed, _ = service_env
    f1 = allowed / "file1.txt"
    f1.write_text("content1")
    st1 = f1.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.txt",
            basename="file1.txt",
            stem="file1",
            suffix=".txt",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip1)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="change",
        suffix=".txt",
    )

    preview = svc.get_batch_utility_preview(action=action)
    assert preview["planned_operations_count"] == 0
    digest = preview["preview_digest"]

    with pytest.raises(BatchUtilityEmptyPlanError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0


def test_generate_suffix_transform_phase_b_zero_filter_compilation(service_env):
    svc, Session, allowed, _ = service_env
    f1 = allowed / "file1.png"
    f1.write_text("content1")
    st1 = f1.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.png",
            basename="file1.png",
            stem="file1",
            suffix=".png",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip1)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="append",
        suffix=".bak",
    )

    preview = svc.get_batch_utility_preview(action=action)
    digest = preview["preview_digest"]

    with patch("app.batch_utilities.compiler.compile_filter_to_sql") as mock_compile_sql:
        plan_info = svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )
        assert plan_info["status"] == "draft"
        assert mock_compile_sql.call_count == 0


def test_generate_scandir_failure_raises_case_collision(service_env, monkeypatch):
    """Reviewer reproduction 26: scandir failure results in BatchUtilityCaseCollisionError and 0 Draft."""
    import os
    from app.batch_utilities.errors import BatchUtilityCaseCollisionError
    svc, Session, allowed, _ = service_env
    f1 = allowed / "file1.png"
    f1.write_text("content1")
    st1 = f1.stat()

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip1 = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(f1),
            relative_path="file1.png",
            basename="file1.png",
            stem="file1",
            suffix=".png",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip1)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="append",
        suffix=".bak",
    )

    orig_scandir = os.scandir

    def fake_scandir(path):
        if str(path) == str(allowed):
            raise PermissionError("Simulated scandir error")
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    preview = svc.get_batch_utility_preview(action=action)
    assert preview["planned_operations_count"] == 0
    assert preview["blocking_conflict_count"] == 1
    digest = preview["preview_digest"]

    with pytest.raises(BatchUtilityCaseCollisionError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0


def test_generate_same_source_symlink_and_casefold_raises_symlink_blocked(service_env):
    """Reviewer reproduction 27: same-source TARGET_SYMLINK + CASE_ONLY_COLLISION raises BatchUtilitySymlinkBlockedError."""
    from app.batch_utilities.errors import BatchUtilitySymlinkBlockedError
    svc, Session, allowed, _ = service_env

    src = allowed / "src.jpg"
    src.write_text("content")
    st = src.stat()

    # Case collision target existing on disk
    case_target = allowed / "SRC.TXT"
    case_target.write_text("case collision")

    # Symlink target pointing elsewhere
    other_file = allowed / "dummy.dat"
    other_file.write_text("dummy")
    symlink_target = allowed / "src.txt"
    try:
        symlink_target.symlink_to(other_file)
    except FileExistsError:
        pytest.skip("Filesystem is case-insensitive, cannot have both SRC.TXT and src.txt in the same directory")

    with Session() as session:
        iroot = IndexRoot(root=str(allowed))
        session.add(iroot)
        session.flush()
        ip = IndexedPath(
            root_key=str(allowed),
            absolute_path=str(src),
            relative_path="src.jpg",
            basename="src.jpg",
            stem="src",
            suffix=".jpg",
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(ip)
        session.commit()
        root_id = iroot.id

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[root_id],
        mode="change",
        suffix=".txt",
    )

    preview = svc.get_batch_utility_preview(action=action)
    assert preview["planned_operations_count"] == 0
    assert preview["blocking_conflict_count"] == 1
    digest = preview["preview_digest"]

    with pytest.raises(BatchUtilitySymlinkBlockedError):
        svc.create_batch_utility_plan(
            action=action,
            expected_preview_digest=digest,
        )

    with Session() as session:
        assert session.query(BatchPlan).count() == 0

