import pytest
from pathlib import Path
from app.batch_utilities.schema import FlattenOneLevelAction
from app.batch_utilities.compiler import compile_flatten_one_level_preview, BatchUtilitySafetySnapshot
from app.batch_utilities.errors import BatchUtilityScopeOverlapError

def test_compile_flatten_overlap(tmp_path):
    root = tmp_path / "root"
    wrapper = root / "wrapper"
    wrapper.mkdir(parents=True)
    
    action = FlattenOneLevelAction(
        type="flatten_one_level",
        wrapper_paths=[str(root), str(wrapper)]
    )
    
    snapshot = BatchUtilitySafetySnapshot(
        protect_last_file=True,
        allowed_roots=(root,),
        quarantine_root=None,
        effective_policy={},
    )
    
    with pytest.raises(BatchUtilityScopeOverlapError):
        compile_flatten_one_level_preview(session=None, action=action, safety_snapshot=snapshot)
