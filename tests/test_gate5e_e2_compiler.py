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
