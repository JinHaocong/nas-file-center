import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, IndexRoot, IndexedPath
from app.batch_utilities.compiler import (
    BatchUtilitySafetySnapshot,
    compile_quarantine_filtered_preview,
    compute_current_quarantine_filtered_db_lineage_digest,
)
from app.batch_utilities.schema import QuarantineFilteredAction
from app.batch_utilities.errors import (
    BatchUtilityScopeNotFoundError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
)
from app.filters.schema import FilterNode, LeafNode, LogicalNode


@pytest.fixture
def test_db_and_files(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    # Root 1
    root1_path = data_dir / "root1"
    root1_path.mkdir()

    f_keep = root1_path / "keep.bin"
    f_keep.write_bytes(b"12345")
    st_keep = f_keep.stat()

    f_a = root1_path / "a.txt"
    f_a.write_bytes(b"hello world")
    st_a = f_a.stat()

    sub_dir = root1_path / "sub"
    sub_dir.mkdir()
    f_b = sub_dir / "b.txt"
    f_b.write_bytes(b"b content")
    st_b = f_b.stat()

    # Root 2
    root2_path = data_dir / "root2"
    root2_path.mkdir()
    f_c = root2_path / "c.url"
    f_c.write_bytes(b"http://example.com")
    st_c = f_c.stat()


    with SessionLocal() as session:
        r1 = IndexRoot(id=1, root=str(root1_path))
        r2 = IndexRoot(id=2, root=str(root2_path))
        session.add_all([r1, r2])
        session.commit()

        p_keep = IndexedPath(
            root_key=str(root1_path),
            absolute_path=str(f_keep),
            relative_path="keep.bin",
            basename="keep.bin",
            stem="keep",
            suffix=".bin",
            size=st_keep.st_size,
            mtime_ns=st_keep.st_mtime_ns,
            device=st_keep.st_dev,
            inode=st_keep.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_a = IndexedPath(
            root_key=str(root1_path),
            absolute_path=str(f_a),
            relative_path="a.txt",
            basename="a.txt",
            stem="a",
            suffix=".txt",
            size=st_a.st_size,
            mtime_ns=st_a.st_mtime_ns,
            device=st_a.st_dev,
            inode=st_a.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_sub = IndexedPath(
            root_key=str(root1_path),
            absolute_path=str(sub_dir),
            relative_path="sub",
            basename="sub",
            stem="sub",
            suffix="",
            size=0,
            mtime_ns=0,
            device=0,
            inode=0,
            is_dir=True,
            scan_generation=1,
        )
        p_b = IndexedPath(
            root_key=str(root1_path),
            absolute_path=str(f_b),
            relative_path="sub/b.txt",
            basename="b.txt",
            stem="b",
            suffix=".txt",
            size=st_b.st_size,
            mtime_ns=st_b.st_mtime_ns,
            device=st_b.st_dev,
            inode=st_b.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_c = IndexedPath(
            root_key=str(root2_path),
            absolute_path=str(f_c),
            relative_path="c.url",
            basename="c.url",
            stem="c",
            suffix=".url",
            size=st_c.st_size,
            mtime_ns=st_c.st_mtime_ns,
            device=st_c.st_dev,
            inode=st_c.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([p_keep, p_a, p_sub, p_b, p_c])
        session.commit()

    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(data_dir.resolve(),),
        quarantine_root=quarantine_dir.resolve(),
        effective_policy={
            "protect_last_file": True,
            "allowed_roots": [str(data_dir.resolve())],
            "quarantine_root": str(quarantine_dir.resolve()),
        },
    )

    return {
        "engine": engine,
        "SessionLocal": SessionLocal,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
        "root1": root1_path,
        "root2": root2_path,
        "f_a": f_a,
        "f_b": f_b,
        "f_c": f_c,
        "f_keep": f_keep,
        "sub_dir": sub_dir,
        "snapshot": snapshot,
    }


def test_missing_root_id_raises_scope_not_found(test_db_and_files):
    SessionLocal = test_db_and_files["SessionLocal"]
    snapshot = test_db_and_files["snapshot"]

    with SessionLocal() as session:
        action = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[999])
        with pytest.raises(BatchUtilityScopeNotFoundError):
            compile_quarantine_filtered_preview(
                session=session,
                action=action,
                safety_snapshot=snapshot,
            )


def test_filter_candidate_discovery_and_order(test_db_and_files):
    SessionLocal = test_db_and_files["SessionLocal"]
    snapshot = test_db_and_files["snapshot"]

    with SessionLocal() as session:
        action = QuarantineFilteredAction(
            type="quarantine_filtered",
            root_ids=[2, 1],
            filter=LeafNode(field="extension", operator="in", value=["txt", "url"]),
        )
        compilation = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot,
        )

        assert compilation.matched_count == 3  # a.txt, b.txt, c.url
        assert compilation.planned_operations_count > 0

        # Stable order: normalized absolute path ascending
        paths = [r["source_path"] for r in compilation.rows]
        assert paths == sorted(paths)


def test_indexed_directory_becomes_skipped_not_regular_file(test_db_and_files):
    SessionLocal = test_db_and_files["SessionLocal"]
    snapshot = test_db_and_files["snapshot"]

    with SessionLocal() as session:
        # Match all files and dirs under root 1
        action = QuarantineFilteredAction(
            type="quarantine_filtered",
            root_ids=[1],
            filter=None,
        )
        compilation = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot,
        )

        dir_rows = [r for r in compilation.rows if r["object_type"] == "directory"]
        assert len(dir_rows) == 1
        assert dir_rows[0]["decision"] == "SKIPPED"
        assert dir_rows[0]["reason_code"] == "NOT_REGULAR_FILE"


def test_live_safety_missing_symlink_and_stale_observations(test_db_and_files):
    SessionLocal = test_db_and_files["SessionLocal"]
    snapshot = test_db_and_files["snapshot"]
    f_a = test_db_and_files["f_a"]
    f_b = test_db_and_files["f_b"]

    # 1. Stale stat: modify f_a
    f_a.write_bytes(b"modified content with different size")

    # 2. Symlink: replace f_b with symlink
    f_b.unlink()
    f_b.symlink_to(test_db_and_files["f_keep"])

    with SessionLocal() as session:
        action = QuarantineFilteredAction(
            type="quarantine_filtered",
            root_ids=[1],
            filter=LeafNode(field="extension", operator="eq", value="txt"),
        )
        compilation = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot,
        )

        row_a = next(r for r in compilation.rows if r["source_path"] == str(f_a))
        assert row_a["decision"] == "SKIPPED"
        assert row_a["reason_code"] == "SOURCE_SNAPSHOT_STALE"

        row_b = next(r for r in compilation.rows if r["source_path"] == str(f_b))
        assert row_b["decision"] == "SAFETY_EXCLUDED"
        assert row_b["reason_code"] == "SYMLINK_BLOCKED"


def test_protect_last_file_aggregate_planning(tmp_path):
    db_file = tmp_path / "test_protect.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    root_dir = tmp_path / "protect_root"
    root_dir.mkdir()

    # Sub1: exactly 1 file (matches) -> planned: 0, safety excluded: 1
    sub1 = root_dir / "sub1"
    sub1.mkdir()
    f1 = sub1 / "only.txt"
    f1.write_bytes(b"1")

    # Sub2: exactly 2 files (both match) -> planned: 1, safety excluded: 1
    sub2 = root_dir / "sub2"
    sub2.mkdir()
    f2_a = sub2 / "a.txt"
    f2_a.write_bytes(b"2a")
    f2_b = sub2 / "b.txt"
    f2_b.write_bytes(b"2b")

    # Sub3: exactly 3 files (all match) -> planned: 2, safety excluded: 1
    sub3 = root_dir / "sub3"
    sub3.mkdir()
    f3_a = sub3 / "a.txt"
    f3_a.write_bytes(b"3a")
    f3_b = sub3 / "b.txt"
    f3_b.write_bytes(b"3b")
    f3_c = sub3 / "c.txt"
    f3_c.write_bytes(b"3c")

    files = [f1, f2_a, f2_b, f3_a, f3_b, f3_c]
    with SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_dir))
        session.add(r)
        session.commit()

        for f in files:
            st = f.stat()
            p = IndexedPath(
                root_key=str(root_dir),
                absolute_path=str(f),
                relative_path=str(f.relative_to(root_dir)),
                basename=f.name,
                stem=f.stem,
                suffix=".txt",
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation=1,
            )
            session.add(p)
        session.commit()

    snapshot_protect = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root_dir.resolve(),),
        quarantine_root=tmp_path / "trash",
        effective_policy={"protect_last_file": True},
    )

    with SessionLocal() as session:
        action = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[1])
        comp = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot_protect,
        )

        sub1_rows = [r for r in comp.rows if Path(r["source_path"]).parent == sub1]
        assert len(sub1_rows) == 1
        assert sub1_rows[0]["decision"] == "SAFETY_EXCLUDED"
        assert sub1_rows[0]["reason_code"] == "PROTECT_LAST_FILE"

        sub2_rows = [r for r in comp.rows if Path(r["source_path"]).parent == sub2]
        assert len(sub2_rows) == 2
        sub2_quarantined = [r for r in sub2_rows if r["decision"] == "QUARANTINE"]
        sub2_excluded = [r for r in sub2_rows if r["decision"] == "SAFETY_EXCLUDED"]
        assert len(sub2_quarantined) == 1
        assert len(sub2_excluded) == 1

        sub3_rows = [r for r in comp.rows if Path(r["source_path"]).parent == sub3]
        assert len(sub3_rows) == 3
        sub3_quarantined = [r for r in sub3_rows if r["decision"] == "QUARANTINE"]
        sub3_excluded = [r for r in sub3_rows if r["decision"] == "SAFETY_EXCLUDED"]
        assert len(sub3_quarantined) == 2
        assert len(sub3_excluded) == 1

        # Total planned operations
        assert comp.planned_operations_count == 3
        assert comp.safety_excluded_count == 3
        assert len(comp.intents) == 3


def test_protect_last_file_false_allows_all(tmp_path):
    db_file = tmp_path / "test_no_protect.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    root_dir = tmp_path / "no_protect_root"
    root_dir.mkdir()
    sub = root_dir / "sub"
    sub.mkdir()
    f1 = sub / "a.txt"
    f1.write_bytes(b"1")

    with SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_dir))
        session.add(r)
        st = f1.stat()
        p = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(f1),
            relative_path="sub/a.txt",
            basename="a.txt",
            stem="a",
            suffix=".txt",
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            device=st.st_dev,
            inode=st.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add(p)
        session.commit()

    snapshot_no_protect = BatchUtilitySafetySnapshot(
        protect_last_file=False,
        allowed_roots=(root_dir.resolve(),),
        quarantine_root=tmp_path / "trash",
        effective_policy={"protect_last_file": False},
    )

    with SessionLocal() as session:
        action = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[1])
        comp = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot_no_protect,
        )
        assert comp.planned_operations_count == 1
        assert comp.rows[0]["decision"] == "QUARANTINE"


def test_db_lineage_digest_changes_on_indexed_path_mutation(test_db_and_files):
    SessionLocal = test_db_and_files["SessionLocal"]
    action = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[1])
    canonical_action = {"type": "quarantine_filtered", "root_ids": [1], "filter": None}

    with SessionLocal() as session:
        d1 = compute_current_quarantine_filtered_db_lineage_digest(session, canonical_action)
        assert d1 is not None

        # Mutate an IndexedPath row
        row = session.query(IndexedPath).filter_by(relative_path="a.txt").first()
        row.size = 999999
        session.commit()

        d2 = compute_current_quarantine_filtered_db_lineage_digest(session, canonical_action)
        assert d2 is not None
        assert d1 != d2


def test_parent_symlink_and_resolved_path_safety(tmp_path):
    """Blocker A: verify parent symlinks resolving outside allowed roots or into quarantine are excluded."""
    from app.path_safety import require_allowed_path, is_reserved_quarantine_path, UnsafePathError

    db_file = tmp_path / "test_symlink_safety.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    allowed_root = tmp_path / "allowed_root"
    allowed_root.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    quarantine_root = tmp_path / "quarantine_root"
    quarantine_root.mkdir()
    internal_target_dir = allowed_root / "real_sub"
    internal_target_dir.mkdir()

    # Case A: root/link -> outside ALLOWED_ROOTS
    # target file is outside_dir/victim.txt
    victim_file = outside_dir / "victim.txt"
    victim_file.write_text("outside victim content")
    st_victim = victim_file.stat()

    link_to_outside = allowed_root / "link_outside"
    link_to_outside.symlink_to(outside_dir, target_is_directory=True)
    indexed_victim_path = link_to_outside / "victim.txt"

    # Case B: root/alias -> quarantine_root
    q_file = quarantine_root / "q.txt"
    q_file.write_text("quarantine content")
    st_q = q_file.stat()

    link_to_quarantine = allowed_root / "alias_quarantine"
    link_to_quarantine.symlink_to(quarantine_root, target_is_directory=True)
    indexed_q_path = link_to_quarantine / "q.txt"

    # Case C: root/internal_link -> real_sub (inside ALLOWED_ROOTS and not quarantine)
    internal_file = internal_target_dir / "valid.txt"
    internal_file.write_text("internal valid content")
    st_internal = internal_file.stat()

    link_to_internal = allowed_root / "link_internal"
    link_to_internal.symlink_to(internal_target_dir, target_is_directory=True)
    indexed_internal_path = link_to_internal / "valid.txt"

    # Sibling file in real_sub to ensure PROTECT_LAST_FILE does not exclude valid.txt
    sibling_file = internal_target_dir / "sibling.txt"
    sibling_file.write_text("sibling content")

    # Case D: Symlink loop (fail closed)
    loop_a = allowed_root / "loop_a"
    loop_b = allowed_root / "loop_b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)
    indexed_loop_path = loop_a / "loop_file.txt"

    with SessionLocal() as session:
        r = IndexRoot(id=1, root=str(allowed_root))
        session.add(r)
        session.commit()

        # Add indexed paths
        p_victim = IndexedPath(
            root_key=str(allowed_root),
            absolute_path=str(indexed_victim_path),
            relative_path="link_outside/victim.txt",
            basename="victim.txt",
            stem="victim",
            suffix=".txt",
            size=st_victim.st_size,
            mtime_ns=st_victim.st_mtime_ns,
            device=st_victim.st_dev,
            inode=st_victim.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_q = IndexedPath(
            root_key=str(allowed_root),
            absolute_path=str(indexed_q_path),
            relative_path="alias_quarantine/q.txt",
            basename="q.txt",
            stem="q",
            suffix=".txt",
            size=st_q.st_size,
            mtime_ns=st_q.st_mtime_ns,
            device=st_q.st_dev,
            inode=st_q.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_internal = IndexedPath(
            root_key=str(allowed_root),
            absolute_path=str(indexed_internal_path),
            relative_path="link_internal/valid.txt",
            basename="valid.txt",
            stem="valid",
            suffix=".txt",
            size=st_internal.st_size,
            mtime_ns=st_internal.st_mtime_ns,
            device=st_internal.st_dev,
            inode=st_internal.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_loop = IndexedPath(
            root_key=str(allowed_root),
            absolute_path=str(indexed_loop_path),
            relative_path="loop_a/loop_file.txt",
            basename="loop_file.txt",
            stem="loop_file",
            suffix=".txt",
            size=100,
            mtime_ns=0,
            device=0,
            inode=0,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([p_victim, p_q, p_internal, p_loop])
        session.commit()

        snapshot = BatchUtilitySafetySnapshot(
            protect_last_file=True,
            allowed_roots=(allowed_root.resolve(),),
            quarantine_root=quarantine_root.resolve(),
            effective_policy={
                "protect_last_file": True,
                "allowed_roots": [str(allowed_root.resolve())],
                "quarantine_root": str(quarantine_root.resolve()),
            },
        )

        action = QuarantineFilteredAction(type="quarantine_filtered", root_ids=[1], filter=None)
        compilation = compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=snapshot,
        )

        # Cross-lifecycle consistency assertions
        with pytest.raises(UnsafePathError):
            require_allowed_path(indexed_victim_path, snapshot.allowed_roots)
        assert is_reserved_quarantine_path(indexed_q_path, snapshot.quarantine_root) is True
        assert require_allowed_path(indexed_internal_path, snapshot.allowed_roots) is not None

        # Check Row A (outside allowed roots via symlink parent)
        row_victim = next(r for r in compilation.rows if r["source_path"] == str(indexed_victim_path))
        assert row_victim["decision"] == "SAFETY_EXCLUDED"
        assert row_victim["reason_code"] == "PATH_OUTSIDE_ALLOWED_ROOT"
        assert not any(i.source_path == str(indexed_victim_path) for i in compilation.intents)

        # Check Row B (quarantine storage via symlink parent)
        row_q = next(r for r in compilation.rows if r["source_path"] == str(indexed_q_path))
        assert row_q["decision"] == "SAFETY_EXCLUDED"
        assert row_q["reason_code"] == "RESERVED_QUARANTINE_PATH"
        assert not any(i.source_path == str(indexed_q_path) for i in compilation.intents)

        # Check Row C (internal symlink parent: inside allowed roots, not quarantine)
        row_internal = next(r for r in compilation.rows if r["source_path"] == str(indexed_internal_path))
        assert row_internal["decision"] == "QUARANTINE"
        assert any(i.source_path == str(indexed_internal_path) for i in compilation.intents)

        # Check Row D (symlink loop fails closed)
        row_loop = next(r for r in compilation.rows if r["source_path"] == str(indexed_loop_path))
        assert row_loop["decision"] == "SAFETY_EXCLUDED"
        assert row_loop["reason_code"] == "PATH_OUTSIDE_ALLOWED_ROOT"
        assert not any(i.source_path == str(indexed_loop_path) for i in compilation.intents)

