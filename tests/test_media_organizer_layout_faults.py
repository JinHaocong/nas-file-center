"""Adversarial boundaries for confirmed occupied-final layout completion."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.batch import media_organizer_cleanup_jobs as cleanup_jobs
from app.batch import media_organizer_finalize as finalize
from app.batch import media_organizer_publish as publishing
from app.batch import media_organizer_custody as custody
from tests.test_media_organizer_cleanup_recovery import _queue, _recover, _row
from tests.test_media_organizer_execute_jobs import worker
from tests.test_media_organizer_layout_completion import OWNER, _files, _prepared
from tests.test_media_organizer_grouped_worker_custody import ScopedSyntheticCustody


GROUP = "P [3 15B]"
GROUPED_CHAIN = (
    (f"{GROUP}/000.jpg", f"{GROUP}/001.jpg", b"first"),
    (f"{GROUP}/001.jpg", f"{GROUP}/002.jpg", b"image"),
    (f"{GROUP}/002.jpg", f"{GROUP}/003.jpg", b"other"),
    ("new.mp4", "V [1 5B]/001.mp4", b"video"),
)
FLAT_CHAIN = (
    ("000.jpg", "001.jpg", b"first"),
    ("001.jpg", "002.jpg", b"image"),
    ("002.jpg", "003.jpg", b"other"),
)


def _interrupted_run(monkeypatch, settings, cleanup_id, callback):
    finish = cleanup_jobs.finish_deferred_cleanup

    def injected(*args, **kwargs):
        return finish(*args, **kwargs, after_mutation=callback)

    with monkeypatch.context() as fault:
        fault.setattr(cleanup_jobs, "finish_deferred_cleanup", injected)
        return worker(settings, cleanup_id, name=OWNER)


@pytest.mark.parametrize("replacement", ["reused_group", "stage", "unit"])
def test_parent_replacement_after_first_release_stops_all_further_media_mutation(
    tmp_path, monkeypatch, replacement,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, GROUPED_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    observed = {}

    def swap_parent(index):
        if index != 0:
            return
        directory = {"reused_group": unit / GROUP,
                     "stage": unit / manifest["stage_directory"], "unit": unit}[replacement]
        detached = tmp_path / "detached-original-parent"
        directory.rename(detached)
        directory.mkdir(mode=0o700)
        # Same file inodes in a different parent are still foreign namespace.
        for child in detached.iterdir():
            child.rename(directory / child.name)
        observed["files"] = _files(unit)

    assert _interrupted_run(monkeypatch, settings, cid, swap_parent) is False

    assert observed, "fixture never reached the durable release boundary"
    assert _files(unit) == observed["files"]
    assert (unit / GROUP / "002.jpg").read_bytes() == b"other"
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False


@pytest.mark.parametrize("unexpected_state", ["missing_source", "unbegun_publication"])
def test_future_operation_cannot_gain_begin_for_an_already_changed_name(
    tmp_path, monkeypatch, unexpected_state,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    journal = folder / "manifest.json.cleanup-progress.jsonl"
    observed = []
    next_index = 1 if unexpected_state == "missing_source" else 2

    def alter_before_next_begin(index):
        if index != next_index - 1:
            return
        if unexpected_state == "missing_source":
            (unit / "002.jpg").unlink()
        else:
            row = next(row for row in manifest["moves"] if row["final"] == str(unit / "001.jpg"))
            os.link(row["target"], unit / "001.jpg")
        observed.append(_files(unit))

    assert _interrupted_run(monkeypatch, settings, cid, alter_before_next_begin) is False

    assert observed
    records = [json.loads(line) for line in journal.read_bytes().splitlines()]
    assert not any(record.get("kind") == "begin" and record.get("index") == next_index
                   for record in records), "failed validation minted new replay authority"
    assert _files(unit) == observed[0]
    preserved = journal.read_bytes()
    recovery = _recover(client, cid, plan["confirmation"])
    assert recovery.status_code == 200, recovery.text
    assert worker(settings, recovery.json()["job_id"], name=OWNER) is False
    assert journal.read_bytes() == preserved
    assert _files(unit) == observed[0]


def test_replaced_stage_after_publication_is_not_drained_during_link_cleanup(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, plan, manifest, _, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    stage = unit / manifest["stage_directory"]
    observed = {}

    def replace_after_publication(index):
        if index != 3:
            return
        detached = tmp_path / "detached-owned-stage"
        stage.rename(detached)
        stage.mkdir(mode=0o700)
        for child in detached.iterdir():
            child.rename(stage / child.name)
        observed["stage"] = _files(stage)

    assert _interrupted_run(monkeypatch, settings, cid, replace_after_publication) is False

    assert observed
    assert _files(stage) == observed["stage"]
    assert all((unit / target).read_bytes() == data for _, target, data in FLAT_CHAIN)
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False


def test_foreign_target_created_at_link_boundary_is_preserved_with_all_staged_copies(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, plan, manifest, _, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    staged = {row["target"]: Path(row["target"]).read_bytes() for row in manifest["moves"]}
    link = publishing.link_pinned_inode_noreplace
    observed = []

    def occupy_then_link(source_fd, parent_fd, name):
        assert name == "001.jpg"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
        try:
            os.write(fd, b"unrelated target at exact link boundary")
        finally:
            os.close(fd)
        observed.append(name)
        return link(source_fd, parent_fd, name)

    with monkeypatch.context() as fault:
        fault.setattr(publishing, "link_pinned_inode_noreplace", occupy_then_link)
        assert worker(settings, cid, name=OWNER) is False

    assert observed == ["001.jpg"]
    assert (unit / "001.jpg").read_bytes() == b"unrelated target at exact link boundary"
    assert (unit / "000.jpg").read_bytes() == b"first"
    assert all(Path(path).read_bytes() == value for path, value in staged.items())
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False


def test_revocation_between_release_and_publication_retains_copies_until_explicit_recovery(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    revoked = {"value": False}

    class RevocableCustody(ScopedSyntheticCustody):
        def assert_exclusive(self, parent):
            super().assert_exclusive(parent)
            if revoked["value"]:
                raise PermissionError("synthetic custody revoked after release")

    monkeypatch.setattr(custody, "verified_namespace_custody",
                        lambda settings, selected: RevocableCustody(tmp_path))
    cid = _queue(client, jid, plan["confirmation"])
    observed = {}

    def revoke(index):
        if index == 1:
            observed["files"] = _files(unit)
            observed["journal"] = (folder / "manifest.json.cleanup-progress.jsonl").read_bytes()
            revoked["value"] = True

    assert _interrupted_run(monkeypatch, settings, cid, revoke) is False

    assert observed
    assert _files(unit) == observed["files"]
    assert (folder / "manifest.json.cleanup-progress.jsonl").read_bytes() == observed["journal"]
    assert not (unit / "001.jpg").exists() and not (unit / "002.jpg").exists()
    assert all(Path(row["target"]).is_file() for row in manifest["moves"])
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False
    revoked["value"] = False
    recovery = _recover(client, cid, plan["confirmation"])
    assert recovery.status_code == 200, recovery.text
    assert worker(settings, recovery.json()["job_id"], name=OWNER)
    assert _files(unit) == {target: data for _, target, data in FLAT_CHAIN}


@pytest.mark.parametrize("revoked_scope", ["unit", "group_parent", "stage_parent"])
def test_revocation_after_pre_begin_validation_cannot_persist_new_intent(
    tmp_path, monkeypatch, revoked_scope,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, GROUPED_CHAIN,
    )
    revoked = {"value": False}
    revoked_parent = {
        "unit": unit,
        "group_parent": unit / GROUP,
        "stage_parent": unit / manifest["stage_directory"],
    }[revoked_scope]

    class RevocableCustody(ScopedSyntheticCustody):
        def assert_exclusive(self, parent):
            super().assert_exclusive(parent)
            if revoked["value"] and Path(parent) == revoked_parent:
                raise PermissionError("synthetic custody revoked after pre-BEGIN validation")

    proof = RevocableCustody(tmp_path)
    monkeypatch.setattr(custody, "verified_namespace_custody",
                        lambda settings, selected: proof)
    cid = _queue(client, jid, plan["confirmation"])
    journal = folder / "manifest.json.cleanup-progress.jsonl"
    observed = {}
    validate = finalize._check_unbegun_layout_operation

    def revoke_after_validation(*args, **kwargs):
        validate(*args, **kwargs)
        observed["files"] = _files(unit)
        observed["journal"] = journal.read_bytes()
        revoked["value"] = True

    with monkeypatch.context() as fault:
        fault.setattr(finalize, "_check_unbegun_layout_operation", revoke_after_validation)
        assert worker(settings, cid, name=OWNER) is False

    assert observed, "fixture did not reach per-operation validation"
    if revoked_scope != "unit":
        proof.assert_exclusive(unit)
    with pytest.raises(PermissionError, match="revoked after pre-BEGIN validation"):
        proof.assert_exclusive(revoked_parent)
    assert _files(unit) == observed["files"]
    assert journal.read_bytes() == observed["journal"]
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False
    revoked["value"] = False
    recovery = _recover(client, cid, plan["confirmation"])
    assert recovery.status_code == 200, recovery.text
    assert worker(settings, recovery.json()["job_id"], name=OWNER)
    assert _files(unit) == {target: data for _, target, data in GROUPED_CHAIN}


def test_every_final_is_verified_before_ordinary_or_staged_copies_are_deleted(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, plan, manifest, _, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    staged = {row["target"]: Path(row["target"]).read_bytes() for row in manifest["moves"]}
    observed = []

    def replace_after_publication(index):
        if index == 3:
            target = unit / "003.jpg"
            target.rename(tmp_path / "detached-owned-final.jpg")
            target.write_bytes(b"foreign final before cleanup frontier")
            observed.append(True)

    assert _interrupted_run(monkeypatch, settings, cid, replace_after_publication) is False

    assert observed
    assert (unit / "003.jpg").read_bytes() == b"foreign final before cleanup frontier"
    assert (unit / "000.jpg").read_bytes() == b"first"
    assert all(Path(path).read_bytes() == value for path, value in staged.items())
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False


@pytest.mark.parametrize("copy_kind", ["original", "stage-link"])
def test_final_parent_revocation_at_unlink_fence_preserves_remaining_copy(
    tmp_path, monkeypatch, copy_kind,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, GROUPED_CHAIN,
    )
    original = unit / ("new.mp4" if copy_kind == "original" else f"{GROUP}/000.jpg")
    row = next(row for row in manifest["moves"] if row["source"] == str(original))
    source = original if copy_kind == "original" else Path(row["target"])
    final = Path(row["final"])
    expected = b"video" if copy_kind == "original" else b"first"
    assert source.parent != final.parent
    final_parent_identity = final.parent.stat().st_dev, final.parent.stat().st_ino
    state = {"active": False, "armed": False, "revoked": False}
    observed = {}

    class RevocableFinalCustody(ScopedSyntheticCustody):
        def assert_exclusive(self, parent):
            super().assert_exclusive(parent)
            if (state["active"] and state["armed"] and not state["revoked"]
                    and Path(parent) == source.parent):
                # The final inode was just checked. Simulate its writer gaining
                # custody at the exact source-unlink fence, after pre-BEGIN.
                final.unlink()
                state["revoked"] = True
                observed["files"] = _files(unit)
                observed["remaining_links"] = source.stat().st_nlink
                if copy_kind == "stage-link":
                    assert not original.exists()
                    assert observed["remaining_links"] == 1
                observed["journal"] = (folder / "manifest.json.cleanup-progress.jsonl").read_bytes()
            if state["revoked"] and Path(parent) == final.parent:
                raise PermissionError("synthetic final-parent custody revoked at unlink fence")

    proof = RevocableFinalCustody(tmp_path)
    monkeypatch.setattr(custody, "verified_namespace_custody",
                        lambda settings, selected: proof)
    cid = _queue(client, jid, plan["confirmation"])
    mutate = finalize._mutate_one
    entry = finalize._entry

    def selected_mutation(op, **kwargs):
        state["active"] = op["kind"] == copy_kind and op["path"] == str(source)
        try:
            return mutate(op, **kwargs)
        finally:
            state["active"] = False

    def arm_after_final_stat(fd, name):
        info = entry(fd, name)
        if state["active"] and not state["armed"] and name == final.name:
            parent_info = os.fstat(fd)
            if (parent_info.st_dev, parent_info.st_ino) == final_parent_identity:
                assert info is not None and info.st_ino == row["identity"][1]
                state["armed"] = True
        return info

    with monkeypatch.context() as fault:
        fault.setattr(finalize, "_mutate_one", selected_mutation)
        fault.setattr(finalize, "_entry", arm_after_final_stat)
        assert worker(settings, cid, name=OWNER) is False

    assert observed, "fixture never reached the final-checked unlink fence"
    proof.assert_exclusive(unit)
    proof.assert_exclusive(source.parent)
    assert not final.exists()
    assert source.is_file(), "cleanup removed the remaining copy after losing its final"
    assert source.read_bytes() == expected
    if copy_kind == "stage-link":
        assert not original.exists()
        assert observed["remaining_links"] == 1
    assert _files(unit) == observed["files"]
    assert (folder / "manifest.json.cleanup-progress.jsonl").read_bytes() == observed["journal"]
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False


def test_failed_stage_copy_fsync_prevents_first_release_and_remains_recoverable(
    tmp_path, monkeypatch,
):
    client, settings, unit, jid, plan, manifest, _, _ = _prepared(
        tmp_path, monkeypatch, FLAT_CHAIN,
    )
    cid = _queue(client, jid, plan["confirmation"])
    first_released = next(row for row in manifest["moves"] if row["source"] == str(unit / "001.jpg"))
    identity = tuple(first_released["identity"][:2])
    fsync = os.fsync
    before = _files(unit)
    observed = []

    def failed_copy_flush(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == identity:
            observed.append(True)
            raise OSError("synthetic staged-copy durability failure")
        return fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(finalize.os, "fsync", failed_copy_flush)
        assert worker(settings, cid, name=OWNER) is False

    assert observed, "original was released without attempting to flush its staged copy"
    assert _files(unit) == before
    recovery = _recover(client, cid, plan["confirmation"])
    assert recovery.status_code == 200, recovery.text
    assert worker(settings, recovery.json()["job_id"], name=OWNER)
    assert _files(unit) == {target: data for _, target, data in FLAT_CHAIN}


@pytest.mark.parametrize("grouped", [False, True])
def test_pending_published_final_flushes_its_parent_before_recovered_done(
    tmp_path, monkeypatch, grouped,
):
    rows = GROUPED_CHAIN if grouped else FLAT_CHAIN
    client, settings, unit, jid, plan, manifest, _, _ = _prepared(tmp_path, monkeypatch, rows)
    cid = _queue(client, jid, plan["confirmation"])
    parent = unit / GROUP if grouped else unit
    target = parent / "001.jpg"
    target_row = next(row for row in manifest["moves"] if row["final"] == str(target))
    parent_identity = parent.stat().st_dev, parent.stat().st_ino
    expected_inode = tuple(target_row["identity"][:2])
    fsync = os.fsync
    observed = []

    def crash_before_parent_flush(fd):
        info = os.fstat(fd)
        if ((info.st_dev, info.st_ino) == parent_identity and target.exists()
                and (target.stat().st_dev, target.stat().st_ino) == expected_inode):
            observed.append(True)
            raise RuntimeError("synthetic crash before publication parent fsync")
        return fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(finalize.os, "fsync", crash_before_parent_flush)
        assert worker(settings, cid, name=OWNER) is False
    assert observed
    assert target.read_bytes() == b"first"
    assert _row(settings, cid)[0] == "failed"
    recovery = _recover(client, cid, plan["confirmation"])
    assert recovery.status_code == 200, recovery.text
    flushed = []
    append = finalize._append

    def record_flush(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity:
            flushed.append(True)
        return fsync(fd)

    def require_flush_before_done(path, cursor, event):
        if event == {"kind": "done", "index": 2}:
            assert flushed, "recovered publication DONE preceded a fresh parent fsync"
        return append(path, cursor, event)

    with monkeypatch.context() as fault:
        fault.setattr(finalize.os, "fsync", record_flush)
        fault.setattr(finalize, "_append", require_flush_before_done)
        assert worker(settings, recovery.json()["job_id"], name=OWNER)
    assert _files(unit) == {target: data for _, target, data in rows}


@pytest.mark.parametrize("extra_marker", [False, True])
def test_partial_reused_group_never_adopts_an_unissued_completion_marker(
    tmp_path, monkeypatch, extra_marker,
):
    client, settings, unit, jid, plan, manifest, folder, _ = _prepared(
        tmp_path, monkeypatch, GROUPED_CHAIN,
    )
    marker = unit / GROUP / ".nfc-publish-complete"
    assert not marker.exists()
    cid = _queue(client, jid, plan["confirmation"])
    if extra_marker:
        marker.write_bytes(finalize._authority(manifest))
        marker.chmod(0o600)
        before = _files(unit)
        assert worker(settings, cid, name=OWNER) is False
        assert _files(unit) == before
        assert not (folder / "manifest.json.cleanup-progress.jsonl").exists()
        assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False
    else:
        assert worker(settings, cid, name=OWNER)
        assert _files(unit) == {target: data for _, target, data in GROUPED_CHAIN}
