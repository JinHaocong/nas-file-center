import pytest
from pathlib import Path
from app.batch_utilities.graph import TargetItemCandidate, BlockingConflict
from app.batch_utilities.flatten_graph import resolve_flatten_graph

def test_resolve_flatten_graph_success(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("a")
    
    items = [
        TargetItemCandidate(
            source_path=str(wrapper / "a.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=1,
            index_root_path=str(root),
            relative_path="wrapper/a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1
        )
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert not res.has_blocking_conflicts
    assert len(res.ordered_items) == 1
    assert res.ordered_items[0].target_path == str(root / "a.txt")

def test_resolve_flatten_graph_collision(tmp_path):
    root = tmp_path / "root"
    wrapper1 = root / "wrapper1"
    wrapper2 = root / "wrapper2"
    wrapper1.mkdir(parents=True)
    wrapper2.mkdir(parents=True)
    (wrapper1 / "a.txt").write_text("1")
    (wrapper2 / "a.txt").write_text("2")
    
    items = [
        TargetItemCandidate(
            source_path=str(wrapper1 / "a.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=1,
            index_root_path=str(root),
            relative_path="wrapper1/a.txt",
            size=10,
            mtime_ns=0, device=0, inode=0, original_cand_id=1
        ),
        TargetItemCandidate(
            source_path=str(wrapper2 / "a.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=1,
            index_root_path=str(root),
            relative_path="wrapper2/a.txt",
            size=10,
            mtime_ns=0, device=0, inode=0, original_cand_id=2
        )
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert res.has_blocking_conflicts
    assert len(res.conflicts) == 2
    assert res.conflicts[0].conflict_type == "PLANNED_TARGET_COLLISION"


def test_casefold_existing_sibling_collision(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    # Existing sibling with different case
    (root / "A.JPG").write_text("existing")
    (wrapper / "a.jpg").write_text("src")
    
    items = [
        TargetItemCandidate(
            source_path=str(wrapper / "a.jpg"),
            target_path=str(root / "a.jpg"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/a.jpg",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(wrapper),
        )
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert res.has_blocking_conflicts
    assert len(res.ordered_items) == 0
    assert len(res.conflicts) == 1
    assert res.conflicts[0].conflict_type == "CASE_ONLY_COLLISION"
    parent_obs = [o for o in res.directory_observations if o.get("parent") == str(root) and "scan_status" in o]
    assert len(parent_obs) == 1
    assert parent_obs[0]["scan_status"] == "OK"


def test_casefold_planned_vs_planned_collision(tmp_path):
    root = tmp_path / "root"
    w1 = root / "w1"
    w2 = root / "w2"
    w1.mkdir(parents=True)
    w2.mkdir(parents=True)
    (w1 / "File.TXT").write_text("1")
    (w2 / "file.txt").write_text("2")
    
    items = [
        TargetItemCandidate(
            source_path=str(w1 / "File.TXT"),
            target_path=str(root / "File.TXT"),
            index_root_id=None,
            index_root_path=None,
            relative_path="w1/File.TXT",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(w1),
        ),
        TargetItemCandidate(
            source_path=str(w2 / "file.txt"),
            target_path=str(root / "file.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="w2/file.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=2,
            wrapper_path=str(w2),
        ),
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert res.has_blocking_conflicts
    assert len(res.ordered_items) == 0
    assert len(res.conflicts) == 2
    for c in res.conflicts:
        assert c.conflict_type == "CASE_ONLY_COLLISION"


def test_casefold_scandir_oserror_fails_closed(tmp_path):
    from unittest.mock import patch
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    (wrapper / "a.txt").write_text("a")
    
    items = [
        TargetItemCandidate(
            source_path=str(wrapper / "a.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(wrapper),
        )
    ]
    
    with patch("os.scandir", side_effect=PermissionError(13, "Permission denied")):
        res = resolve_flatten_graph(
            items=items,
            allowed_roots=[root],
            quarantine_root=None,
        )
    assert res.has_blocking_conflicts
    assert len(res.ordered_items) == 0
    assert len(res.conflicts) == 1
    assert res.conflicts[0].conflict_type == "CASE_ONLY_COLLISION"
    parent_obs = [o for o in res.directory_observations if o.get("parent") == str(root) and "scan_status" in o]
    assert len(parent_obs) == 1
    assert parent_obs[0]["scan_status"] == "FAILED"


def test_dependency_edges_and_vacating_occupant(tmp_path):
    root = tmp_path / "root"
    w1 = root / "w1"
    w1.mkdir(parents=True)
    (w1 / "a.txt").write_text("a")
    # Target b.txt exists on disk
    (root / "b.txt").write_text("occupant")
    
    # Item 1 moves w1/a.txt -> root/b.txt
    # Item 2 moves root/b.txt -> root/c.txt (vacating root/b.txt)
    items = [
        TargetItemCandidate(
            source_path=str(w1 / "a.txt"),
            target_path=str(root / "b.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="w1/a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(w1),
        ),
        TargetItemCandidate(
            source_path=str(root / "b.txt"),
            target_path=str(root / "c.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="b.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=2,
            wrapper_path=str(root),
        ),
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert not res.has_blocking_conflicts
    assert len(res.ordered_items) == 2
    # Item 2 must execute before Item 1 to vacate root/b.txt
    assert res.ordered_items[0].source_path == str(root / "b.txt")
    assert res.ordered_items[1].source_path == str(w1 / "a.txt")
    assert {"from_source": str(root / "b.txt"), "to_source": str(w1 / "a.txt")} in res.dependency_edges


def test_rename_cycle_detection(tmp_path):
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "b.txt").write_text("b")
    
    items = [
        TargetItemCandidate(
            source_path=str(root / "a.txt"),
            target_path=str(root / "b.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(root),
        ),
        TargetItemCandidate(
            source_path=str(root / "b.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="b.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=2,
            wrapper_path=str(root),
        ),
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert res.has_blocking_conflicts
    assert len(res.ordered_items) == 0
    cycle_conflicts = [c for c in res.conflicts if c.conflict_type == "RENAME_CYCLE"]
    assert len(cycle_conflicts) == 2


def test_blocked_occupant_propagation(tmp_path):
    root = tmp_path / "root"
    w1 = root / "w1"
    w1.mkdir(parents=True)
    (w1 / "a.txt").write_text("a")
    # root/b.txt exists, and root/c.txt exists (static occupant)
    (root / "b.txt").write_text("occupant1")
    (root / "c.txt").write_text("occupant2_static")
    
    # Item 1 moves w1/a.txt -> root/b.txt
    # Item 2 moves root/b.txt -> root/c.txt (blocked by static occupant root/c.txt)
    items = [
        TargetItemCandidate(
            source_path=str(w1 / "a.txt"),
            target_path=str(root / "b.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="w1/a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(w1),
        ),
        TargetItemCandidate(
            source_path=str(root / "b.txt"),
            target_path=str(root / "c.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="b.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=2,
            wrapper_path=str(root),
        ),
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert res.has_blocking_conflicts
    assert len(res.ordered_items) == 0
    target_exists_conflicts = [c for c in res.conflicts if c.conflict_type == "TARGET_EXISTS"]
    # Both Item 2 (direct target exists) and Item 1 (blocked occupant) must be TARGET_EXISTS
    assert len(target_exists_conflicts) == 2


def test_stable_topo_sort(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    (wrapper / "z.txt").write_text("z")
    (wrapper / "m.txt").write_text("m")
    (wrapper / "a.txt").write_text("a")
    
    items = [
        TargetItemCandidate(
            source_path=str(wrapper / "z.txt"),
            target_path=str(root / "z.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/z.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=1,
            wrapper_path=str(wrapper),
        ),
        TargetItemCandidate(
            source_path=str(wrapper / "m.txt"),
            target_path=str(root / "m.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/m.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=2,
            wrapper_path=str(wrapper),
        ),
        TargetItemCandidate(
            source_path=str(wrapper / "a.txt"),
            target_path=str(root / "a.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/a.txt",
            size=10,
            mtime_ns=0,
            device=0,
            inode=0,
            original_cand_id=3,
            wrapper_path=str(wrapper),
        ),
    ]
    
    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
    )
    assert not res.has_blocking_conflicts
    assert len(res.ordered_items) == 3
    sources = [it.source_path for it in res.ordered_items]
    assert sources == [str(wrapper / "a.txt"), str(wrapper / "m.txt"), str(wrapper / "z.txt")]


def test_continuity_wrapper_rescan_race_directory_replacement_blocks_child_acquisition(tmp_path):
    """Gate5-E / E3-hotfix10 Test 4:
    Continuity re-scan race: Replacement directory created before child acquisition.
    Must report WRAPPER_IDENTITY_CHANGED and 0 children enumerated from replacement directory.
    """
    import os
    import shutil

    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    (wrapper / "before.txt").write_text("before")
    st_orig = os.stat(wrapper)

    obs = [{
        "wrapper_path": str(wrapper),
        "device": st_orig.st_dev,
        "inode": st_orig.st_ino,
        "mtime_ns": st_orig.st_mtime_ns,
        "scan_status": "OK",
        "direct_children": ["before.txt"],
    }]

    items = [
        TargetItemCandidate(
            source_path=str(wrapper / "before.txt"),
            target_path=str(root / "before.txt"),
            index_root_id=None,
            index_root_path=None,
            relative_path="wrapper/before.txt",
            size=6,
            mtime_ns=st_orig.st_mtime_ns,
            device=st_orig.st_dev,
            inode=st_orig.st_ino,
            original_cand_id=1,
            wrapper_path=str(wrapper),
        )
    ]

    # Spy scandir to track entries read
    enumerated_entries = []
    real_scandir = os.scandir

    def spy_scandir(path_or_fd):
        res = real_scandir(path_or_fd)
        if hasattr(res, "__enter__"):
            with res as it:
                for e in it:
                    enumerated_entries.append(e.name)
        else:
            for e in res:
                enumerated_entries.append(e.name)
        return real_scandir(path_or_fd)

    def racing_lstat(path):
        res = os.lstat(path)
        # Immediately after lstat sees identity #1, swap directory before child acquisition
        w_old = root / "wrapper_old"
        if not w_old.exists():
            os.rename(str(wrapper), str(w_old))
            os.mkdir(str(wrapper))
            (wrapper / "secret.txt").write_text("secret")
        return res

    res = resolve_flatten_graph(
        items=items,
        allowed_roots=[root],
        quarantine_root=None,
        wrapper_observations=obs,
        lstat_func=racing_lstat,
        scandir_func=spy_scandir,
    )

    assert res.has_blocking_conflicts
    wrapper_conflicts = [c for c in res.conflicts if c.conflict_type == "WRAPPER_IDENTITY_CHANGED"]
    assert len(wrapper_conflicts) > 0
    # Zero children from identity #2 may be acquired
    assert "secret.txt" not in enumerated_entries

