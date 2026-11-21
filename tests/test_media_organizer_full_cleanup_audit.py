"""#400 full frozen-inventory audit before any future destructive cleanup.

Audit is read-only; it cannot authorize unlink/rmdir, and must inspect every
frozen row, not just the first paginated cleanup review. All files are fake
bytes under tmp_path; no NAS path or production data is ever accessed.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.test_media_organizer_execute_jobs import (
    setup, preview, execute_request, worker, scoped_namespace,
)


def _completed(tmp_path, *, extra=0, wrapper=True):
    client, settings, unit = setup(tmp_path, enabled=True)
    if wrapper:
        old = unit / "P1"
        old.mkdir()
        (old / "from-old.jpg").write_bytes(b"original-in-wrapper")
    for index in range(extra):
        (unit / f"image-{index:04d}.jpg").write_bytes(
            f"original:{index:04d}".encode()
        )
    pid = preview(client, settings, unit)
    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    assert worker(settings, job_id, name="synthetic-audit-owner")
    folder = settings.reports_dir / "media_organizer-executions" / str(job_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["manifest"]
    return client, settings, unit, job_id, manifest, folder


def _contents(directory: Path) -> dict[str, tuple[int, int, bytes]]:
    """Snapshot is only a test assertion; production audit never reads bytes."""
    return {str(p.relative_to(directory)): (
        p.stat().st_ino, p.stat().st_size, p.read_bytes()
    ) for p in directory.rglob("*") if p.is_file()}


def test_full_audit_verifies_every_frozen_source_stage_public_link_and_wrapper(tmp_path, scoped_namespace):
    client, settings, unit, jid, manifest, folder = _completed(tmp_path, extra=27)
    before = _contents(unit)
    journal = folder / "manifest.json.manual-cleanup.json"
    preserved = journal.read_bytes()
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["job_id"] == jid
    assert data["frozen_file_count"] == 30
    assert data["verified_source_links"] == 30
    assert data["verified_stage_links"] == 30
    assert data["verified_final_links"] == 30
    assert data["verified_wrapper_count"] == 1
    assert data["frozen_inventory_matches"] is True
    assert data["read_only"] is True
    assert data["cleanup_authorized"] is False
    assert data["finalized"] is False
    assert data["zero_change_rescan_verified"] is False
    assert data["namespace_exclusive_custody_proven"] is False
    assert _contents(unit) == before
    assert journal.read_bytes() == preserved


def test_full_audit_checks_late_file_beyond_first_review_page(tmp_path, scoped_namespace):
    client, settings, unit, jid, manifest, folder = _completed(tmp_path, extra=27)
    last = Path(manifest["moves"][-1]["final"])
    detached = last.with_name("detached-for-audit.jpg")
    last.rename(detached)
    last.write_bytes(b"foreign-file-unchanged")
    before = _contents(unit)
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 409, result.text
    assert _contents(unit) == before
    assert last.read_bytes() == b"foreign-file-unchanged"
    assert detached.is_file()


def test_full_audit_refuses_unexpected_file_inside_old_classification(tmp_path, scoped_namespace):
    client, settings, unit, jid, manifest, folder = _completed(tmp_path)
    unknown = unit / "P1" / "foreign-keep.txt"
    unknown.write_bytes(b"do-not-delete")
    before = _contents(unit)
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 409, result.text
    assert _contents(unit) == before
    assert unknown.read_bytes() == b"do-not-delete"


def test_full_audit_refuses_unexpected_private_stage_entry(tmp_path, scoped_namespace):
    client, settings, unit, jid, manifest, folder = _completed(tmp_path)
    foreign = unit / manifest["stage_directory"] / "unexpected.bin"
    foreign.write_bytes(b"preserve-foreign")
    before = _contents(unit)
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 409, result.text
    assert _contents(unit) == before
    assert foreign.read_bytes() == b"preserve-foreign"


def test_full_audit_refuses_tampered_journal_and_remains_read_only(tmp_path, scoped_namespace):
    client, settings, unit, jid, manifest, folder = _completed(tmp_path)
    journal = folder / "manifest.json.manual-cleanup.json"
    journal.write_bytes(b'{"tampered":true}')
    before = _contents(unit)
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 409, result.text
    assert _contents(unit) == before
    assert journal.read_bytes() == b'{"tampered":true}'


def test_full_audit_is_admin_only_and_denies_unfinished_job(tmp_path, scoped_namespace):
    client, settings, unit = setup(tmp_path, enabled=True)
    pid = preview(client, settings, unit)
    queued = execute_request(client, pid, unit)
    assert queued.status_code == 200
    jid = queued.json()["job_id"]
    result = client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit")
    assert result.status_code == 409, result.text
    client.cookies.clear()
    assert client.get(f"/api/media-organizer/executions/{jid}/cleanup-audit").status_code == 401
