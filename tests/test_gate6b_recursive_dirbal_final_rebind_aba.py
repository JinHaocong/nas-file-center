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

    descendant_st = os.lstat(descendant)
    detached = tmp_path / "detached-descendant"
    real_fstat = os.fstat
    descendant_fstat_count = 0
    swapped = False

    def swap_after_final_rebind_parent_fstat(fd):
        nonlocal descendant_fstat_count, swapped

        opened_st = real_fstat(fd)
        if (
            int(opened_st.st_dev) == int(descendant_st.st_dev)
            and int(opened_st.st_ino) == int(descendant_st.st_ino)
        ):
            descendant_fstat_count += 1
            if descendant_fstat_count == 4:
                swapped = True
                descendant.rename(detached)
                descendant.mkdir()
        return opened_st

    monkeypatch.setattr(os, "fstat", swap_after_final_rebind_parent_fstat)

    assert _count_real_regular_files_recursive(protected) == 0
    assert swapped is True
    assert descendant_fstat_count == 4
    assert list(descendant.iterdir()) == []
    assert (detached / "only.bin").exists()
