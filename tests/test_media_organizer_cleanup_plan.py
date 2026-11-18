"""#400: immutable *non-destructive* cleanup plan, not deletion authority.

No NAS data are ever used. A durable cleanup plan is necessary to eventually
support separate confirmation and crash recovery, but does not by itself
authorize any file unlink or rmdir.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.test_media_organizer_full_cleanup_audit import _completed, _contents
from tests.test_media_organizer_execute_jobs import setup, preview, execute_request, worker


def _plan_path(folder: Path) -> Path:
    return folder / "manifest.json.cleanup-plan.json"


def test_completed_worker_writes_readonly_cleanup_plan_bound_to_all_links(tmp_path):
    client, settings, work, jid, manifest, folder = _completed(tmp_path, extra=4)
    plan_file = _plan_path(folder)
    assert plan_file.is_file(), "Worker must persist a cleanup plan before handoff"
    assert plan_file.stat().st_mode & 0o777 == 0o600
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    assert plan["schema_version"] == 1
    assert plan["job_id"] == jid
    assert plan["unit"] == str(work)
    assert plan["cleanup_authorized"] is False
    assert plan["plan_kind"] == "review_only"
    assert plan["stage"]["path"] == str(work / manifest["stage_directory"])
    assert len(plan["original_links"]) == len(manifest["moves"]) == 7
    assert len(plan["staged_links"]) == 7
    assert len(plan["wrapper_directories"]) == 1
    assert plan["wrapper_directories"][0]["path"] == str(work / "P1")
    assert plan["manifest_checksum"]
    assert len(plan["plan_sha256"]) == 64
    digest = hashlib.sha256(json.dumps(
        {k: v for k, v in plan.items() if k != "plan_sha256"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert plan["plan_sha256"] == digest
    for item in plan["original_links"]:
        assert item["path"] in {row["source"] for row in manifest["moves"]}
        assert item["identity"] in [row["identity"] for row in manifest["moves"]]
    assert all(Path(row["source"]).is_file() for row in manifest["moves"])
    assert all(Path(row["final"]).is_file() for row in manifest["moves"])


def test_admin_can_page_cleanup_plan_without_modifying_media(tmp_path):
    client, settings, work, jid, manifest, folder = _completed(tmp_path, extra=27)
    before = _contents(work)
    response = client.get(
        f"/api/media-organizer/executions/{jid}/cleanup-plan",
        params={"page": 2, "page_size": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == jid
    assert body["cleanup_authorized"] is False
    assert body["finalized"] is False
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert body["total_original_links"] == 30
    assert len(body["original_links"]) == 10
    assert len(body["staged_links"]) == 10
    assert len(body["plan_sha256"]) == 64
    assert body["wrapper_directories"][0]["path"] == str(work / "P1")
    assert _contents(work) == before


def test_cleanup_plan_reader_refuses_modified_plan_without_mutation(tmp_path):
    client, settings, work, jid, _, folder = _completed(tmp_path)
    path = _plan_path(folder)
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["original_links"][0]["identity"][1] += 1
    path.write_text(json.dumps(plan), encoding="utf-8")
    before = _contents(work)
    response = client.get(f"/api/media-organizer/executions/{jid}/cleanup-plan")
    assert response.status_code == 409, response.text
    assert _contents(work) == before


def test_cleanup_plan_refuses_foreign_existing_path_and_keeps_originals(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200, queued.text
    jid = queued.json()["job_id"]
    folder = settings.reports_dir / "media_organizer-executions" / str(jid)
    folder.mkdir(parents=True, exist_ok=True)
    foreign = _plan_path(folder)
    foreign.write_bytes(b"foreign-record")
    assert worker(settings, jid, name="synthetic-worker-collision") is False
    assert foreign.read_bytes() == b"foreign-record"
    assert (work / "photo.jpg").read_bytes() == b"photo-1"
    assert (work / "clip.png").read_bytes() == b"image-2"
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-plan")
    assert result.status_code == 409


def test_cleanup_plan_requires_admin_and_finished_publication(tmp_path):
    client, settings, work = setup(tmp_path, enabled=True)
    pid = preview(client, settings, work)
    queued = execute_request(client, pid, work)
    assert queued.status_code == 200
    jid = queued.json()["job_id"]
    assert client.get(
        f"/api/media-organizer/executions/{jid}/cleanup-plan"
    ).status_code == 409
    client.cookies.clear()
    assert client.get(
        f"/api/media-organizer/executions/{jid}/cleanup-plan"
    ).status_code == 401
