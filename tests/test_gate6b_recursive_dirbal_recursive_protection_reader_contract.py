from __future__ import annotations

import importlib


def test_shared_recursive_protection_reader_public_api_exists():
    module = importlib.import_module("app.planning.recursive_protection")

    assert hasattr(module, "RecursiveProtectionSnapshot")
    assert callable(getattr(module, "snapshot_recursive_regular_files"))
