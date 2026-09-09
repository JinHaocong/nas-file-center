import pytest
from pathlib import Path
from app.batch_utilities.graph import TargetItemCandidate, BlockingConflict
from app.batch_utilities.flatten_graph import resolve_flatten_graph

def test_resolve_flatten_graph_success(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
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
