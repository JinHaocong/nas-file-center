"""Fail-closed replay of interrupted cleanup on disposable synthetic media."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.batch import media_organizer_finalize as finalizer
from tests.test_media_organizer_actual_finalization import (
    ExclusiveSyntheticCustody, _flat, _finish,
)


def _header_only(tmp_path, manifest, frozen, plan, monkeypatch):
    """Crash after the initial audit and durable header, before any deletion."""
    create = finalizer._new_journal

    def interrupted(path, header):
        create(path, header)
        raise RuntimeError("synthetic interruption after journal creation")

    with monkeypatch.context() as patch:
        patch.setattr(finalizer, "_new_journal", interrupted)
        with pytest.raises(RuntimeError, match="after journal creation"):
            _finish(tmp_path, manifest, frozen, plan)
    return finalizer._journal_path(frozen)


def _retained_paths(manifest):
    return [Path(row[field]) for row in manifest["moves"]
            for field in ("source", "target", "final")]


def test_missing_pending_entry_flushes_parent_before_recovery_done(tmp_path, monkeypatch):
    _, manifest, frozen, plan = _flat(tmp_path)
    source = Path(manifest["moves"][0]["source"])
    info = source.parent.stat()
    parent_identity = (info.st_dev, info.st_ino)
    fsync = os.fsync

    def fail_before_directory_flush(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity and not source.exists():
            raise RuntimeError("synthetic crash before unlink directory fsync")
        return fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(finalizer.os, "fsync", fail_before_directory_flush)
        with pytest.raises(RuntimeError, match="before unlink directory fsync"):
            _finish(tmp_path, manifest, frozen, plan)
    assert not source.exists()
    flushed = []

    def record_flush(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity:
            flushed.append(True)
        return fsync(fd)

    append = finalizer._append

    def verify_done(path, cursor, event):
        if event == {"kind": "done", "index": 0}:
            assert flushed, "pending deletion must be durable before DONE"
        return append(path, cursor, event)

    monkeypatch.setattr(finalizer.os, "fsync", record_flush)
    monkeypatch.setattr(finalizer, "_append", verify_done)
    assert _finish(tmp_path, manifest, frozen, plan)["finalized"] is True


def test_unbegun_missing_source_cannot_acquire_a_recovery_begin(tmp_path):
    _, manifest, frozen, plan = _flat(tmp_path)

    def interrupted(index):
        if index == 0:
            raise RuntimeError("synthetic interruption after unlink")

    with pytest.raises(RuntimeError, match="after unlink"):
        _finish(tmp_path, manifest, frozen, plan, after_mutation=interrupted)
    journal = finalizer._journal_path(frozen)
    before = journal.read_bytes()
    Path(manifest["moves"][1]["source"]).unlink()

    # Refusal must not persist BEGIN for an absence the finalizer did not cause.
    for _ in range(2):
        with pytest.raises(finalizer.CleanupExecutionBlocked):
            _finish(tmp_path, manifest, frozen, plan)
        assert journal.read_bytes() == before
        assert all(Path(row["target"]).is_file() for row in manifest["moves"])


@pytest.mark.parametrize("directory_kind", ["wrapper", "stage"])
def test_replaced_cleanup_parent_blocks_all_resumed_unlinks(
    tmp_path, monkeypatch, directory_kind,
):
    unit, manifest, frozen, plan = _flat(tmp_path)
    journal = _header_only(tmp_path, manifest, frozen, plan, monkeypatch)
    before = journal.read_bytes()
    directory = (unit / "P1" if directory_kind == "wrapper"
                 else unit / manifest["stage_directory"])
    detached = tmp_path / f"detached-{directory_kind}"
    directory.rename(detached)
    directory.mkdir(mode=0o700)
    for child in detached.iterdir():
        child.rename(directory / child.name)
    retained = _retained_paths(manifest)

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert all(path.is_file() for path in retained)
    assert journal.read_bytes() == before
    assert directory.is_dir()
    assert detached.is_dir()


def test_invalid_late_marker_blocks_earlier_resumed_unlinks(tmp_path, monkeypatch):
    unit, manifest, frozen, plan = _flat(tmp_path)
    journal = _header_only(tmp_path, manifest, frozen, plan, monkeypatch)
    before = journal.read_bytes()
    marker = unit / manifest["stage_directory"] / ".nfc-stage-complete"
    marker.write_bytes(b"foreign completion marker")
    retained = _retained_paths(manifest)

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert all(path.is_file() for path in retained)
    assert marker.read_bytes() == b"foreign completion marker"
    assert journal.read_bytes() == before


def test_fifo_marker_is_refused_before_a_blocking_open(tmp_path, monkeypatch):
    unit, manifest, frozen, plan = _flat(tmp_path)
    journal = _header_only(tmp_path, manifest, frozen, plan, monkeypatch)
    before = journal.read_bytes()
    marker = unit / manifest["stage_directory"] / ".nfc-stage-complete"
    marker.unlink()
    os.mkfifo(marker)
    original_open = os.open

    def refuse_fifo_open(path, flags, *args, **kwargs):
        if path == marker.name:
            pytest.fail("cleanup attempted a potentially blocking FIFO read")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(finalizer.os, "open", refuse_fifo_open)
    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert all(path.is_file() for path in _retained_paths(manifest))
    assert journal.read_bytes() == before


@pytest.mark.parametrize("directory_kind", ["wrapper", "stage"])
def test_unrecognized_retained_child_blocks_all_resumed_unlinks(
    tmp_path, monkeypatch, directory_kind,
):
    unit, manifest, frozen, plan = _flat(tmp_path)
    journal = _header_only(tmp_path, manifest, frozen, plan, monkeypatch)
    before = journal.read_bytes()
    directory = (unit / "P1" if directory_kind == "wrapper"
                 else unit / manifest["stage_directory"])
    foreign = directory / "unrecognized.txt"
    foreign.write_bytes(b"preserve this unrelated file")
    retained = _retained_paths(manifest)

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert all(path.is_file() for path in retained)
    assert foreign.read_bytes() == b"preserve this unrelated file"
    assert journal.read_bytes() == before


@pytest.mark.parametrize("events", [
    [{"kind": "begin", "index": 0}, {"kind": "done", "index": 0},
     {"kind": "begin", "index": 1}],
    [{"kind": "begin", "index": False}],
    [{"kind": "begin", "index": 0}, {"kind": "done", "index": False}],
    [{"kind": "begin", "index": 0}, {"kind": "done", "index": 0},
     {"kind": "finalized", "count": True}],
])
def test_journal_rejects_out_of_bounds_and_boolean_operation_indexes(tmp_path, events):
    journal = tmp_path / "private-progress.jsonl"
    header = {"kind": "header", "operations_count": 1}
    chain = finalizer._new_journal(journal, header)
    for event in events:
        chain = finalizer._append(journal, chain, event)
    before = journal.read_bytes()

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        finalizer._load_journal(journal, header, 1)

    assert journal.read_bytes() == before


@pytest.mark.parametrize("answer", [False, True])
def test_direct_cleanup_refuses_boolean_custody_result_before_journal(tmp_path, answer):
    _, manifest, frozen, plan = _flat(tmp_path)

    class InvalidCustody:
        def assert_exclusive(self, parent):
            return answer

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        finalizer.finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            custody=InvalidCustody(), confirmation=finalizer.cleanup_confirmation(
                manifest["job_id"], manifest["unit"], plan["plan_sha256"],
            ),
        )

    assert all(path.is_file() for path in _retained_paths(manifest))
    assert not finalizer._journal_path(frozen).exists()


@pytest.mark.parametrize("boundary", ["audit", "preflight", "mutation", "scan"])
def test_revoked_custody_cannot_extend_cleanup_journal(tmp_path, monkeypatch, boundary):
    _, manifest, frozen, plan = _flat(tmp_path)
    journal = finalizer._journal_path(frozen)
    observed = []

    class RevocableCustody(ExclusiveSyntheticCustody):
        revoked = False

        def assert_exclusive(self, parent):
            super().assert_exclusive(parent)
            if self.revoked:
                raise PermissionError("synthetic namespace custody revoked")

    proof = RevocableCustody(tmp_path)

    def revoke():
        observed.append(journal.read_bytes() if journal.exists() else None)
        proof.revoked = True

    kwargs = {}
    if boundary == "mutation":
        kwargs["after_mutation"] = lambda index: revoke()
    else:
        name = {"audit": "audit_deferred_cleanup_inventory",
                "preflight": "_check_replay_inventory",
                "scan": "_verify_finished_scan"}[boundary]
        original = getattr(finalizer, name)

        def revoke_after(*args, **kwargs):
            result = original(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(finalizer, name, revoke_after)

    with pytest.raises(finalizer.CleanupExecutionBlocked, match="custody"):
        finalizer.finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            custody=proof, confirmation=finalizer.cleanup_confirmation(
                manifest["job_id"], manifest["unit"], plan["plan_sha256"],
            ), **kwargs,
        )

    assert len(observed) == 1
    assert (journal.read_bytes() if journal.exists() else None) == observed[0]
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])
