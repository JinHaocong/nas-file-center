from __future__ import annotations

from pathlib import Path

import pytest

import app.batch_utilities.single_child_wrapper as single_child_wrapper_module
from app.batch_utilities.single_child_wrapper import discover_single_child_wrappers


@pytest.mark.parametrize("capability", [False, None])
def test_valid_wrapper_is_nonselectable_when_native_noreplace_is_unavailable(
    tmp_path,
    monkeypatch,
    capability,
):
    root = tmp_path / "root"
    scope = root / "A"
    (scope / "B" / "C").mkdir(parents=True)

    monkeypatch.setattr(
        single_child_wrapper_module,
        "probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: capability,
        raising=False,
    )

    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    decisions = discover_single_child_wrappers(str(scope), str(root))
    after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

    assert len(decisions) == 1
    decision = decisions[0]
    assert Path(decision.wrapper_path).name == "B"
    assert Path(decision.child_path or "").name == "C"
    assert decision.state == "UNSUPPORTED_FILESYSTEM"
    assert decision.selectable is False
    assert decision.capability_reason == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
    assert before == after
