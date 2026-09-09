from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, IndexRoot, IndexedPath
from app.batch_utilities.schema import SuffixTransformAction
from app.batch_utilities.compiler import (
    BatchUtilitySafetySnapshot,
    compile_suffix_transform_preview,
)


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_compile_suffix_transform_append(tmp_path, db_session):
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    f1 = root_dir / "a"
    f1.write_text("hello a")
    f2 = root_dir / "b.jpg"
    f2.write_text("hello b")

    st1 = f1.stat()
    st2 = f2.stat()

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    ip1 = IndexedPath(
        root_key=str(root_dir),
        absolute_path=str(f1),
        relative_path="a",
        basename="a",
        stem="a",
        suffix="",
        size=st1.st_size,
        mtime_ns=st1.st_mtime_ns,
        device=st1.st_dev,
        inode=st1.st_ino,
        is_dir=False,
        scan_generation=1,
    )
    ip2 = IndexedPath(
        root_key=str(root_dir),
        absolute_path=str(f2),
        relative_path="b.jpg",
        basename="b.jpg",
        stem="b",
        suffix=".jpg",
        size=st2.st_size,
        mtime_ns=st2.st_mtime_ns,
        device=st2.st_dev,
        inode=st2.st_ino,
        is_dir=False,
        scan_generation=1,
    )
    db_session.add_all([ip1, ip2])
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="append",
        suffix="txt",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    comp = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )

    assert comp.matched_count == 2
    assert comp.planned_operations_count == 2
    assert comp.blocking_conflict_count == 0
    assert len(comp.intents) == 2

    # Verify intent details
    intents_by_src = {i.source_path: i for i in comp.intents}
    assert intents_by_src[str(f1)].operation == "rename"
    assert intents_by_src[str(f1)].target_path == str(root_dir / "a.txt")
    assert intents_by_src[str(f2)].target_path == str(root_dir / "b.jpg.txt")


def test_compile_suffix_transform_change(tmp_path, db_session):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    f_jpg = root_dir / "a.jpg"
    f_jpg.write_text("jpg")
    f_tar = root_dir / "archive.tar.gz"
    f_tar.write_text("tar")
    f_noext = root_dir / "noext"
    f_noext.write_text("noext")
    f_already = root_dir / "already.txt"
    f_already.write_text("already")

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    for f in [f_jpg, f_tar, f_noext, f_already]:
        st = f.stat()
        ip = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f),
            relative_path=f.name,
            basename=f.name,
            stem=f.stem,
            suffix=f.suffix,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        db_session.add(ip)
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="change",
        suffix=".txt",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    comp = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )

    assert comp.matched_count == 4
    assert comp.planned_operations_count == 2
    assert comp.skipped_count == 2
    assert comp.blocking_conflict_count == 0

    rows_by_src = {r["source_path"]: r for r in comp.rows}
    assert rows_by_src[str(f_jpg)]["decision"] == "RENAME"
    assert rows_by_src[str(f_jpg)]["target_path"] == str(root_dir / "a.txt")

    assert rows_by_src[str(f_tar)]["decision"] == "RENAME"
    assert rows_by_src[str(f_tar)]["target_path"] == str(root_dir / "archive.tar.txt")

    assert rows_by_src[str(f_noext)]["decision"] == "SKIPPED"
    assert rows_by_src[str(f_noext)]["reason_code"] == "NO_EXISTING_SUFFIX"

    assert rows_by_src[str(f_already)]["decision"] == "SKIPPED"
    assert rows_by_src[str(f_already)]["reason_code"] == "NO_CHANGE"


def test_compile_suffix_transform_vacating_order(tmp_path, db_session):
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    f_a = root_dir / "a"
    f_a.write_text("a")
    f_atxt = root_dir / "a.txt"
    f_atxt.write_text("atxt")

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    for f in [f_a, f_atxt]:
        st = f.stat()
        ip = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f),
            relative_path=f.name,
            basename=f.name,
            stem=f.stem,
            suffix=f.suffix,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        db_session.add(ip)
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="append",
        suffix="txt",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    comp = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )

    assert comp.planned_operations_count == 2
    assert comp.blocking_conflict_count == 0
    # a.txt -> a.txt.txt must be sequence 1, a -> a.txt must be sequence 2
    assert comp.intents[0].source_path == str(f_atxt)
    assert comp.intents[0].sequence == 1
    assert comp.intents[1].source_path == str(f_a)
    assert comp.intents[1].sequence == 2


def test_preview_digest_graph_authority_reviewer_case_h(tmp_path, db_session):
    """
    Reviewer reproduction H: Verify preview digest authority binds target observations,
    casefold directory observations, and dependency facts.
    """
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    f_src = root_dir / "src.jpg"
    f_src.write_text("src")
    st = f_src.stat()

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    ip = IndexedPath(
        root_key=str(root_dir),
        absolute_path=str(f_src),
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
    db_session.add(ip)
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="append",
        suffix=".bak",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    # Base compilation
    comp1 = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )
    digest1 = comp1.source_snapshot_digest

    # 1. Add a file in the directory that changes casefold observations (e.g. unrelated.TXT)
    other = root_dir / "unrelated.TXT"
    other.write_text("unrelated")

    comp2 = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )
    digest2 = comp2.source_snapshot_digest
    assert digest1 != digest2, "Digest must change when casefold directory occupant is added"

    # 2. Add target on disk (target appears)
    target = root_dir / "src.jpg.bak"
    target.write_text("target exists now")

    comp3 = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )
    digest3 = comp3.source_snapshot_digest
    assert digest2 != digest3, "Digest must change when target appears on disk"


def test_scandir_failure_fails_closed_and_changes_digest(tmp_path, db_session, monkeypatch):
    """Reviewer reproduction 26 / Blocker 1: scandir failure fails closed with CASE_ONLY_COLLISION and changes digest."""
    import os
    root_dir = tmp_path / "root_scandir_fail"
    root_dir.mkdir()

    f_src = root_dir / "src.jpg"
    f_src.write_text("src")
    st = f_src.stat()

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    ip = IndexedPath(
        root_key=str(root_dir),
        absolute_path=str(f_src),
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
    db_session.add(ip)
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="append",
        suffix=".txt",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    # 1. Success scan
    comp_success = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )
    assert comp_success.blocking_conflict_count == 0
    assert comp_success.planned_operations_count == 1

    # 2. Failure scan
    orig_scandir = os.scandir

    def mock_scandir(path):
        if str(path) == str(root_dir):
            raise PermissionError("Simulated scandir permission error")
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    comp_failure = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )

    assert comp_failure.planned_operations_count == 0
    assert comp_failure.blocking_conflict_count == 1
    assert comp_failure.rows[0]["decision"] == "BLOCKING_CONFLICT"
    assert comp_failure.rows[0]["reason_code"] == "CASE_ONLY_COLLISION"
    assert comp_failure.source_snapshot_digest != comp_success.source_snapshot_digest


def test_same_source_conflict_priority_reviewer_case_b(tmp_path, db_session):
    """Reviewer reproduction 27 / Blocker 2: Same source with TARGET_SYMLINK and CASE_ONLY_COLLISION selects TARGET_SYMLINK."""
    root_dir = tmp_path / "root_priority"
    root_dir.mkdir()

    f_src = root_dir / "src.jpg"
    f_src.write_text("src")
    st = f_src.stat()

    f_case = root_dir / "SRC.TXT"
    f_case.write_text("uppercase")

    other_file = root_dir / "other.dat"
    other_file.write_text("other")

    # target is a symlink: src.txt -> other.dat
    symlink_target = root_dir / "src.txt"
    symlink_target.symlink_to(other_file)

    iroot = IndexRoot(root=str(root_dir))
    db_session.add(iroot)
    db_session.flush()

    ip = IndexedPath(
        root_key=str(root_dir),
        absolute_path=str(f_src),
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
    db_session.add(ip)
    db_session.commit()

    action = SuffixTransformAction(
        type="suffix_transform",
        root_ids=[iroot.id],
        mode="change",
        suffix=".txt",
    )
    safety = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir,),
        quarantine_root=None,
        effective_policy={},
    )

    comp = compile_suffix_transform_preview(
        session=db_session,
        action=action,
        safety_snapshot=safety,
    )

    # Exactly 1 blocking row for this source
    assert comp.blocking_conflict_count == 1
    assert comp.planned_operations_count == 0
    assert len(comp.rows) == 1
    assert comp.rows[0]["decision"] == "BLOCKING_CONFLICT"
    # Primary reason MUST be TARGET_SYMLINK, not CASE_ONLY_COLLISION
    assert comp.rows[0]["reason_code"] == "TARGET_SYMLINK"


