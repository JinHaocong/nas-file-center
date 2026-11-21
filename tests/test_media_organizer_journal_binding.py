"""Journal authority must retain its inode, parent and exact validated contents."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.batch import media_organizer_finalize as finalizer
from tests.test_media_organizer_actual_finalization import _flat, _finish


def _retained(manifest):
    return {Path(row[field]): Path(row[field]).read_bytes()
            for row in manifest["moves"] for field in ("source", "target", "final")}


def _prepare_resume(tmp_path, manifest, frozen, plan, monkeypatch, state):
    if state == "fresh":
        return
    with monkeypatch.context() as fault:
        if state == "header":
            create = finalizer._new_journal

            def stop_after_header(path, header):
                create(path, header)
                raise RuntimeError("synthetic stop before BEGIN")

            fault.setattr(finalizer, "_new_journal", stop_after_header)
        else:
            def stop_before_unlink(*args, **kwargs):
                raise RuntimeError("synthetic stop after BEGIN")

            fault.setattr(finalizer, "_mutate_one", stop_before_unlink)
        with pytest.raises(RuntimeError, match="synthetic stop"):
            _finish(tmp_path, manifest, frozen, plan)


def _replace_journal(path, attack, tmp_path):
    raw = path.read_bytes()
    if attack == "journal":
        path.rename(tmp_path / "detached-progress.jsonl")
        path.write_bytes(raw)
        path.chmod(0o600)
    elif attack == "parent":
        parent = path.parent
        detached = tmp_path / "detached-evidence"
        parent.rename(detached)
        parent.mkdir(mode=0o700)
        # Preserve the actual journal inode. Parent replacement alone must
        # invalidate the grant, even if every evidence file is moved intact.
        for child in detached.iterdir():
            child.rename(parent / child.name)
    elif attack == "parent-symlink":
        parent = path.parent
        detached = tmp_path / "detached-evidence"
        parent.rename(detached)
        parent.symlink_to(detached, target_is_directory=True)
    elif attack == "journal-symlink":
        detached = tmp_path / "detached-progress.jsonl"
        path.rename(detached)
        path.symlink_to(detached)
    elif attack == "tail":
        digest = json.loads(raw.splitlines()[-1])["chain_sha256"]
        extra, _ = finalizer._line(digest, {"kind": "begin", "index": 0})
        with path.open("ab") as stream:
            stream.write(extra)
    elif attack == "prefix":
        changed = raw.replace(b'"job_id":3331', b'"job_id":3332', 1)
        assert changed != raw and len(changed) == len(raw)
        path.write_bytes(changed)
    return path.read_bytes()


@pytest.mark.parametrize("state", ["fresh", "header", "pending"])
@pytest.mark.parametrize("attack", [
    "journal", "parent", "parent-symlink", "journal-symlink", "tail", "prefix",
])
def test_rebound_or_changed_journal_blocks_next_media_mutation(
    tmp_path, monkeypatch, state, attack,
):
    _, manifest, frozen, plan = _flat(tmp_path)
    _prepare_resume(tmp_path, manifest, frozen, plan, monkeypatch, state)
    retained = _retained(manifest)
    path = finalizer._journal_path(frozen)
    inventory = finalizer._check_replay_inventory
    evidence = {}

    def replace_after_inventory(*args, **kwargs):
        inventory(*args, **kwargs)
        evidence["bytes"] = _replace_journal(path, attack, tmp_path)

    monkeypatch.setattr(finalizer, "_check_replay_inventory", replace_after_inventory)
    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert all(p.is_file() and p.read_bytes() == data for p, data in retained.items())
    assert path.read_bytes() == evidence["bytes"]


def test_journal_swap_at_write_keeps_foreign_file_untouched_and_refuses_unlink(
    tmp_path, monkeypatch,
):
    _, manifest, frozen, plan = _flat(tmp_path)
    retained = _retained(manifest)
    path = finalizer._journal_path(frozen)
    write = os.write
    evidence = {}

    def replace_before_write(fd, data):
        if (path.exists() and not evidence
                and json.loads(data).get("kind") == "begin"):
            opened = os.fstat(fd)
            named = path.stat()
            if (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino):
                evidence["bytes"] = _replace_journal(path, "journal", tmp_path)
        return write(fd, data)

    monkeypatch.setattr(finalizer.os, "write", replace_before_write)
    with pytest.raises(finalizer.CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)

    assert evidence
    assert path.read_bytes() == evidence["bytes"]
    assert all(p.is_file() and p.read_bytes() == data for p, data in retained.items())


def test_unbound_digest_cannot_authorize_a_journal_append(tmp_path):
    path = tmp_path / "private-progress.jsonl"
    finalizer._new_journal(path, {"kind": "header", "operations_count": 1})
    before = path.read_bytes()
    digest = json.loads(before)["chain_sha256"]

    with pytest.raises(finalizer.CleanupExecutionBlocked):
        finalizer._append(path, digest, {"kind": "begin", "index": 0})

    assert path.read_bytes() == before
