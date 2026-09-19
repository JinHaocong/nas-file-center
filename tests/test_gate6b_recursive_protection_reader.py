from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib
import json
import os
from pathlib import Path

import pytest


def _reader_api():
    module = importlib.import_module("app.planning.recursive_protection")
    snapshot_type = getattr(module, "RecursiveProtectionSnapshot")
    snapshot_reader = getattr(module, "snapshot_recursive_regular_files")
    return snapshot_type, snapshot_reader


def test_recursive_protection_reader_returns_public_immutable_snapshot(tmp_path: Path):
    snapshot_type, snapshot_reader = _reader_api()
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "only.bin").write_bytes(b"one")

    snapshot = snapshot_reader(protected)

    assert isinstance(snapshot, snapshot_type)
    assert snapshot.count == 1
    assert snapshot.stable is True
    assert isinstance(snapshot.device, int)
    assert isinstance(snapshot.inode, int)
    assert isinstance(snapshot.tree_identity_digest, str)
    assert len(snapshot.tree_identity_digest) == 64
    with pytest.raises(FrozenInstanceError):
        snapshot.count = 99


def test_recursive_protection_reader_excludes_symlink_files_and_directories(tmp_path: Path):
    _snapshot_type, snapshot_reader = _reader_api()
    protected = tmp_path / "protected"
    real_dir = protected / "real-dir"
    real_dir.mkdir(parents=True)
    (protected / "root.bin").write_bytes(b"root")
    (real_dir / "nested.bin").write_bytes(b"nested")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.bin").write_bytes(b"outside")
    os.symlink(protected / "root.bin", protected / "linked-file.bin")
    os.symlink(outside, protected / "linked-dir")

    snapshot = snapshot_reader(protected)

    assert snapshot.stable is True
    assert snapshot.count == 2


def test_recursive_protection_reader_missing_or_symlink_root_is_unstable(tmp_path: Path):
    _snapshot_type, snapshot_reader = _reader_api()
    missing = tmp_path / "missing"
    target = tmp_path / "target"
    target.mkdir()
    (target / "one.bin").write_bytes(b"one")
    linked = tmp_path / "linked"
    os.symlink(target, linked)

    missing_snapshot = snapshot_reader(missing)
    linked_snapshot = snapshot_reader(linked)

    assert missing_snapshot.stable is False
    assert missing_snapshot.count == 0
    assert linked_snapshot.stable is False
    assert linked_snapshot.count == 0


def test_recursive_protection_reader_identity_instability_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    _snapshot_type, snapshot_reader = _reader_api()
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "only.bin").write_bytes(b"one")

    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "evil-1.bin").write_bytes(b"evil")
    (attacker / "evil-2.bin").write_bytes(b"evil")
    detached = tmp_path / "detached-protected"

    real_scandir = os.scandir
    swapped = False

    def swap_before_first_scan(path):
        nonlocal swapped
        if not swapped:
            swapped = True
            protected.rename(detached)
            os.symlink(attacker, protected)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_before_first_scan)

    snapshot = snapshot_reader(protected)

    assert swapped is True
    assert snapshot.stable is False
    assert snapshot.count == 0


def test_recursive_protection_reader_digest_is_deterministic_and_ctime_free(tmp_path: Path):
    _snapshot_type, snapshot_reader = _reader_api()
    protected = tmp_path / "protected"
    nested = protected / "nested"
    nested.mkdir(parents=True)
    (protected / "a.bin").write_bytes(b"a")
    (nested / "b.bin").write_bytes(b"b")

    first = snapshot_reader(protected)
    second = snapshot_reader(protected)

    assert first.stable is True
    assert second.stable is True
    assert first.count == second.count == 2
    assert first.tree_identity_digest == second.tree_identity_digest
    payload = first.digest_payload()
    assert set(payload) == {"stable", "device", "inode", "tree_identity_digest"}
    assert "ctime" not in json.dumps(payload).lower()


def test_execute_chain_reader_counts_nested_ancestors_with_two_root_passes(
    tmp_path: Path,
    monkeypatch,
):
    module = importlib.import_module("app.planning.recursive_protection")
    chain_reader = getattr(module, "live_count_recursive_regular_file_chain")
    real_pass = module._count_live_regular_files_chain_pass

    root = tmp_path / "root"
    parent = root / "A"
    deep = parent / "deep"
    deep.mkdir(parents=True)
    (deep / "one.bin").write_bytes(b"1")
    (deep / "two.bin").write_bytes(b"2")
    (parent / "parent.bin").write_bytes(b"3")
    (root / "root.bin").write_bytes(b"4")

    pass_calls = []

    def tracked_pass(root_fd, **kwargs):
        pass_calls.append(tuple(kwargs["protected_relative_dirs"]))
        return real_pass(root_fd, **kwargs)

    monkeypatch.setattr(module, "_count_live_regular_files_chain_pass", tracked_pass)

    result = chain_reader([str(deep), str(parent), str(root)])

    assert result.stable is True
    assert result.failure_path is None
    assert [path for path, _sample in result.samples] == [
        str(deep),
        str(parent),
        str(root),
    ]
    assert [sample.count for _path, sample in result.samples] == [2, 3, 4]
    assert all(sample.stable for _path, sample in result.samples)
    assert len(pass_calls) == 2
    assert pass_calls[0] == pass_calls[1] == ("A/deep", "A", ".")


def test_execute_chain_reader_excludes_reserved_quarantine_subtree(tmp_path: Path):
    module = importlib.import_module("app.planning.recursive_protection")
    chain_reader = getattr(module, "live_count_recursive_regular_file_chain")

    root = tmp_path / "root"
    protected = root / "A"
    protected.mkdir(parents=True)
    quarantine = root / ".nas-file-center-trash"
    quarantine.mkdir()
    (protected / "keep.bin").write_bytes(b"keep")
    (protected / "delete.bin").write_bytes(b"delete")
    (root / "root-extra.bin").write_bytes(b"root")
    (quarantine / "already-quarantined.bin").write_bytes(b"old")

    result = chain_reader(
        [str(protected), str(root)],
        quarantine_root=quarantine,
    )

    assert result.stable is True
    assert [sample.count for _path, sample in result.samples] == [2, 3]


def test_execute_chain_reader_count_change_between_passes_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    module = importlib.import_module("app.planning.recursive_protection")
    chain_reader = getattr(module, "live_count_recursive_regular_file_chain")

    root = tmp_path / "root"
    protected = root / "A"
    protected.mkdir(parents=True)
    (protected / "one.bin").write_bytes(b"1")
    (protected / "two.bin").write_bytes(b"2")

    calls = 0

    def drifting_pass(root_fd, **_kwargs):
        nonlocal calls
        calls += 1
        os.close(root_fd)
        return (2, 2) if calls == 1 else (1, 2)

    monkeypatch.setattr(module, "_count_live_regular_files_chain_pass", drifting_pass)

    result = chain_reader([str(protected), str(root)])

    assert calls == 2
    assert result.stable is False
    assert result.failure_path == str(protected)
    assert all(sample.stable is False for _path, sample in result.samples)
