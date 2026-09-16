from __future__ import annotations

import importlib
from pathlib import Path


def test_shared_recursive_protection_reader_public_api_exists():
    module = importlib.import_module("app.planning.recursive_protection")

    assert hasattr(module, "RecursiveProtectionSnapshot")
    assert callable(getattr(module, "snapshot_recursive_regular_files"))


def test_shared_recursive_protection_reader_excludes_reserved_quarantine_subtree(tmp_path: Path):
    module = importlib.import_module("app.planning.recursive_protection")
    snapshot_reader = getattr(module, "snapshot_recursive_regular_files")

    protected = tmp_path / "root"
    quarantine = protected / ".nas-file-center-trash"
    protected.mkdir()
    quarantine.mkdir()
    (protected / "a.bin").write_bytes(b"a")
    (protected / "b.bin").write_bytes(b"b")
    (quarantine / "already-quarantined.bin").write_bytes(b"old")

    snapshot = snapshot_reader(protected, quarantine_root=quarantine)

    assert snapshot.stable is True
    assert snapshot.count == 2
