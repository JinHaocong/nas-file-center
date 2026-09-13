from __future__ import annotations

from pathlib import Path

import pytest


def test_transactional_purge_capture_requires_worker_authority(tmp_path: Path) -> None:
    from app.quarantine.purge import execute_transactional_purge_capture

    def unreachable_session_factory():
        raise AssertionError("capture must reject missing worker authority before DB access")

    with pytest.raises(PermissionError, match="worker authority"):
        execute_transactional_purge_capture(
            unreachable_session_factory,
            entry_id=1,
            worker_id=None,
            frozen_manifest={},
            quarantine_root=tmp_path / "trash",
            allowed_roots=[tmp_path],
        )
