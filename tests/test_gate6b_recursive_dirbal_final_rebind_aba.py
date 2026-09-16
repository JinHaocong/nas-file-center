from __future__ import annotations

import os
from pathlib import Path

from app.planning.dedupe_preview import _count_real_regular_files_recursive


def test_recursive_count_descendant_aba_during_final_rebind_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    protected = tmp_path / "protected"
    descendant = protected / "descendant"
    descendant.mkdir(parents=True)
    (descendant / "only.bin").write_bytes(b"one")

    detached = tmp_path / "detached-descendant"
    real_open = os.open
    descendant_open_count = 0
    swapped = False

    def swap_after_final_rebind_parent_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal descendant_open_count, swapped

        if path == "descendant" and dir_fd is not None:
            descendant_open_count += 1
            opened_fd = real_open(path, flags, mode, dir_fd=dir_fd)
            if descendant_open_count == 4:
                swapped = True
                descendant.rename(detached)
                descendant.mkdir()
            return opened_fd

        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_after_final_rebind_parent_open)

    assert _count_real_regular_files_recursive(protected) == 0
    assert swapped is True
    assert descendant_open_count == 4
    assert list(descendant.iterdir()) == []
    assert (detached / "only.bin").exists()
