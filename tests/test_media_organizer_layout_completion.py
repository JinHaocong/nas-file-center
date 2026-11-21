"""Confirmed final layout completion when original and final names overlap.

These fixtures are disposable synthetic data. Expected final paths and payloads
are literal expectations, independent of the planner and cleanup role helpers.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from app.batch import media_organizer_cleanup_jobs as cleanup_jobs
from app.batch import media_organizer_finalize as finalize
from app.batch.media_organizer_planner import preview_semantic_unit
from app.tasks.recovery import acquire_worker_ownership, recover_interrupted_jobs
from app.worker import process_work_job
from tests.test_media_organizer_cleanup_recovery import (
    _db, _expire, _frozen, _queue, _recover, _row,
)
from tests.test_media_organizer_execute_jobs import setup, preview, execute_request, worker
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


OWNER = "synthetic-layout-worker"
SUCCESSOR = "synthetic-layout-successor"

_CASES = [
    pytest.param(
        (("001.jpg", "001.jpg", b"image"),
         ("z.jpg", "002.jpg", b"other")), 0, 1, 0, id="flat-retained-self",
    ),
    pytest.param(
        (("000.jpg", "001.jpg", b"first"),
         ("001.jpg", "002.jpg", b"image"),
         ("002.jpg", "003.jpg", b"other")), 2, 0, 0, id="flat-occupied-target-chain",
    ),
    pytest.param(
        (("P [1 5B]/001.jpg", "P [1 5B]/001.jpg", b"image"),
         ("new.mp4", "V [1 5B]/001.mp4", b"video")), 0, 1, 1,
        id="retained-canonical-P-plus-new-video",
    ),
    pytest.param(
        (("V [1 5B]/001.mp4", "V [1 5B]/001.mp4", b"video"),
         ("new.jpg", "P [1 5B]/001.jpg", b"image")), 0, 1, 1,
        id="retained-canonical-V-plus-new-picture",
    ),
    pytest.param(
        (("Other [1 4B]/notes.txt", "Other [1 4B]/notes.txt", b"note"),
         ("new.jpg", "P [1 5B]/001.jpg", b"image")), 0, 1, 1,
        id="retained-canonical-Other-plus-picture",
    ),
    pytest.param(
        (("P [1 5B]/001.mp4", "V [1 5B]/001.mp4", b"video"),
         ("V [1 5B]/001.jpg", "P [1 5B]/001.jpg", b"image")), 0, 0, 2,
        id="reused-canonical-group-with-wrong-media",
    ),
    pytest.param(
        (("P [1 5B]/P1/old.jpg", "P [1 5B]/001.jpg", b"image"),
         ("new.mp4", "V [1 5B]/001.mp4", b"video")), 0, 0, 1,
        id="retained-group-cleans-nested-wrapper",
    ),
    pytest.param(
        (("000.jpg", "P [2 2B]/001.jpg", b"B"),
         ("P [2 2B]/001.jpg", "P [2 2B]/002.jpg", b"A"),
         ("P [2 2B]/002.mp4", "V [1 1B]/001.mp4", b"V")), 1, 0, 1,
        id="retained-group-reclassification-and-insertion",
    ),
    pytest.param(
        (("notes.txt", "Other [2 2B]/notes.txt", b"N"),
         ("Other [2 2B]/notes.txt", "Other [2 2B]/notes__dup002.txt", b"M"),
         ("Other [2 2B]/cover.jpg", "P [1 1B]/001.jpg", b"P")), 1, 0, 1,
        id="Other-collision-and-media-reclassification",
    ),
    pytest.param(
        (("000.jpg", "P [200 200B]/001.jpg", b"\x00"),)
        + tuple((f"P [200 200B]/{n:03d}.jpg", f"P [200 200B]/{n+1:03d}.jpg", bytes([n]))
                for n in range(1, 200))
        + (("P [200 200B]/200.jpg", "P_1 [2 2B]/001.jpg", bytes([200])),
           ("P_1 [1 1B]/001.jpg", "P_1 [2 2B]/002.jpg", bytes([201]))),
        200, 0, 1, id="insertion-rebuckets-across-200-boundary",
    ),
]


def _files(unit):
    return {p.relative_to(unit).as_posix(): p.read_bytes()
            for p in unit.rglob("*") if p.is_file()}


def _hashes(files):
    return Counter((len(value), hashlib.sha256(value).hexdigest())
                   for value in files.values())


def _prepared(tmp_path, monkeypatch, rows, *, empty_wrappers=()):
    client, settings, unit = setup(tmp_path, enabled=True)
    for child in unit.iterdir():
        child.unlink()
    state = _install_issuer(monkeypatch, tmp_path, allowed=True)
    for source, _target, payload in rows:
        path = unit / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    for wrapper in empty_wrappers:
        (unit / wrapper).mkdir(parents=True, exist_ok=True)
    before = _files(unit)
    pid = preview(client, settings, unit)
    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200, queued.text
    jid = queued.json()["job_id"]
    assert _files(unit) == before
    ran = worker(settings, jid, name=OWNER)
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert ran and status["status"] == "completed", status
    assert status["finalized"] is False
    assert status["manual_cleanup_required"] is True
    # Separate approval remains a hard boundary even for true rename chains.
    for source, _target, payload in rows:
        assert (unit / source).read_bytes() == payload
    manifest, folder = _frozen(settings, jid)
    assert manifest["path_role_policy"] == "confirmed_relayout_v1"
    for row in manifest["moves"]:
        assert Path(row["target"]).read_bytes() == Path(row["source"]).read_bytes()
    response = client.get(f"/api/media-organizer/executions/{jid}/cleanup-plan")
    assert response.status_code == 200, response.text
    return client, settings, unit, jid, response.json(), manifest, folder, state


def _assert_final(client, settings, unit, jid, rows):
    expected = {target: payload for _source, target, payload in rows}
    actual = _files(unit)
    assert actual == expected
    assert _hashes(actual) == _hashes({source: payload for source, _, payload in rows})
    expected_dirs = {str(Path(target).parent) for _, target, _ in rows
                     if Path(target).parent != Path(".")}
    assert {p.relative_to(unit).as_posix() for p in unit.rglob("*") if p.is_dir()} == expected_dirs
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["finalized"] is True
    assert status["manual_cleanup_required"] is False
    assert status["publication_complete"] is True
    scan = preview_semantic_unit(unit, allowed_roots=settings.allowed_roots)
    assert scan["status"] == "already_organized"
    assert scan["needed_moves"] == scan["renamed_count"] == 0


@pytest.mark.parametrize("rows,deferred,retained,groups", _CASES)
def test_confirmed_layout_handles_retained_and_occupied_final_roles(
    tmp_path, monkeypatch, rows, deferred, retained, groups,
):
    client, settings, unit, jid, plan, manifest, _folder, _state = _prepared(
        tmp_path, monkeypatch, rows,
    )
    assert plan["total_deferred_publications"] == deferred
    assert len(plan["retained_original_links"]) == retained
    assert len(plan["retained_wrapper_directories"]) == groups
    assert plan["total_original_links"] == len(rows) - retained
    assert plan["total_staged_links"] == len(rows)
    status = client.get(f"/api/media-organizer/executions/{jid}").json()
    assert status["publication_complete"] is (deferred == 0)
    assert status["deferred_publication_count"] == deferred
    before = _files(unit)
    cid = _queue(client, jid, plan["confirmation"])
    assert _files(unit) == before
    assert worker(settings, cid, name=OWNER), _row(settings, cid)
    _assert_final(client, settings, unit, jid, rows)
    assert process_work_job(settings, cid)
    _assert_final(client, settings, unit, jid, rows)


@pytest.mark.parametrize("wrappers", [("P1",), ("photos/videos",)])
def test_retained_canonical_files_allow_only_confirmed_empty_wrapper_cleanup(
    tmp_path, monkeypatch, wrappers,
):
    rows = (("001.jpg", "001.jpg", b"image"),)
    client, settings, unit, jid, plan, manifest, _folder, _state = _prepared(
        tmp_path, monkeypatch, rows, empty_wrappers=wrappers,
    )
    assert manifest["needed_moves"] == manifest["renamed_count"] == 0
    assert plan["total_original_links"] == 0
    assert len(plan["retained_original_links"]) == 1
    assert plan["wrapper_directories"]
    cid = _queue(client, jid, plan["confirmation"])
    assert all((unit / wrapper).is_dir() for wrapper in wrappers)
    assert worker(settings, cid, name=OWNER), _row(settings, cid)
    _assert_final(client, settings, unit, jid, rows)


@pytest.mark.parametrize("crash_index", range(11))
def test_layout_completion_recovers_every_mutation_frontier(
    tmp_path, monkeypatch, crash_index,
):
    rows = _CASES[1].values[0]
    client, settings, unit, jid, plan, manifest, folder, _state = _prepared(
        tmp_path, monkeypatch, rows,
    )
    full_plan = json.loads((folder / "manifest.json.cleanup-plan.json").read_text())
    ops = finalize._operations(manifest, full_plan)
    assert len(ops) == 11
    assert [op["kind"] for op in ops[:4]] == [
        "release-source", "release-source", "publish-final", "publish-final",
    ]
    cid = _queue(client, jid, plan["confirmation"])
    finish = cleanup_jobs.finish_deferred_cleanup

    def interrupted(*args, **kwargs):
        def crash(index):
            if index == crash_index:
                raise SystemExit("synthetic layout process interruption")
        return finish(*args, **kwargs, after_mutation=crash)

    with monkeypatch.context() as fault:
        fault.setattr(cleanup_jobs, "finish_deferred_cleanup", interrupted)
        with pytest.raises(SystemExit, match="synthetic layout"):
            worker(settings, cid, name=OWNER)
    assert _row(settings, cid)[0] == "running"
    engine, factory = _db(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR) is False
    _expire(settings)
    assert acquire_worker_ownership(engine, factory, worker_id=SUCCESSOR)
    assert recover_interrupted_jobs(engine, factory, worker_id=SUCCESSOR)["failed_interrupted"] == 1
    before = _files(unit)
    journal = folder / "manifest.json.cleanup-progress.jsonl"
    log_before = journal.read_bytes()
    response = _recover(client, cid, plan["confirmation"])
    assert response.status_code == 200, response.text
    rid = response.json()["job_id"]
    assert _files(unit) == before and journal.read_bytes() == log_before
    assert process_work_job(settings, rid, factory, engine, OWNER) is False
    assert process_work_job(settings, rid, factory, engine, SUCCESSOR), _row(settings, rid)
    _assert_final(client, settings, unit, jid, rows)


def test_foreign_replacement_after_collision_release_cannot_be_published_over(
    tmp_path, monkeypatch,
):
    rows = _CASES[1].values[0]
    client, settings, unit, jid, plan, _manifest, folder, _state = _prepared(
        tmp_path, monkeypatch, rows,
    )
    cid = _queue(client, jid, plan["confirmation"])
    finish = cleanup_jobs.finish_deferred_cleanup

    def interrupted(*args, **kwargs):
        def crash(index):
            if index == 1:
                raise RuntimeError("synthetic stop after releasing collisions")
        return finish(*args, **kwargs, after_mutation=crash)

    with monkeypatch.context() as fault:
        fault.setattr(cleanup_jobs, "finish_deferred_cleanup", interrupted)
        assert worker(settings, cid, name=OWNER) is False
    (unit / "001.jpg").write_bytes(b"foreign-writer-payload")
    before = _files(unit)
    journal = folder / "manifest.json.cleanup-progress.jsonl"
    saved = journal.read_bytes()
    response = _recover(client, cid, plan["confirmation"])
    assert response.status_code == 200, response.text
    rid = response.json()["job_id"]
    assert worker(settings, rid, name=OWNER) is False
    assert _files(unit) == before and journal.read_bytes() == saved
    assert client.get(f"/api/media-organizer/executions/{jid}").json()["finalized"] is False
