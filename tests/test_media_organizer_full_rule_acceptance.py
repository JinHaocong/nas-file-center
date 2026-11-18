"""Complete V1.6 rule acceptance through authenticated API and real Worker.

Every file is synthetic and lives in pytest's disposable tmp_path. Expected
names, group boundaries, counts and byte labels are hand-derived below; no
planner or naming helper supplies the expected layout. The only replaced
dependency is the external namespace-custody issuer, scoped to tmp_path.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

import pytest

from app.batch.media_organizer_execute_jobs import approval_token
from app.batch.media_organizer_finalize import cleanup_confirmation
from app.worker import process_work_job
from tests.test_media_organizer_execute_jobs import setup, execute_request, worker
from tests.test_media_organizer_grouped_worker_custody import _install_issuer


def _picture_rows(count, destination="", *, source_start=1):
    """Expand a literal fixture range, without deciding its bucket boundary."""
    return tuple(
        (
            f"source-{source:03d}.JpG",
            f"{destination}/{ordinal:03d}.JpG".lstrip("/"),
            f"img-{source:04d}".encode(),
        )
        for ordinal, source in enumerate(
            range(source_start, source_start + count), start=1,
        )
    )


_VIDEO_FLAT = (("source-video.MP4", "001.MP4", b"vid-0001"),)
_VIDEO_GROUPED = (
    ("source-video.MP4", "V [1 8B]/001.MP4", b"vid-0001"),
)


_RULE_CASES = [
    pytest.param(_picture_rows(1), (), (1, 0, 0), id="1P-flat"),
    pytest.param(_VIDEO_FLAT, (), (0, 1, 0), id="1V-flat"),
    pytest.param(_picture_rows(200), (), (200, 0, 0), id="200P-flat"),
    pytest.param(
        _picture_rows(200, "P [200 1.6KiB]")
        + _picture_rows(1, "P_1 [1 8B]", source_start=201),
        (("P", "P [200 1.6KiB]", 200, 1600),
         ("P", "P_1 [1 8B]", 1, 8)),
        (201, 0, 0), id="201P-split-200-1",
    ),
    pytest.param(
        _picture_rows(200, "P [200 1.6KiB]")
        + _picture_rows(200, "P_1 [200 1.6KiB]", source_start=201)
        + _picture_rows(1, "P_2 [1 8B]", source_start=401),
        (("P", "P [200 1.6KiB]", 200, 1600),
         ("P", "P_1 [200 1.6KiB]", 200, 1600),
         ("P", "P_2 [1 8B]", 1, 8)),
        (401, 0, 0), id="401P-split-200-200-1",
    ),
    pytest.param(
        _picture_rows(1, "P [1 8B]") + _VIDEO_GROUPED,
        (("P", "P [1 8B]", 1, 8), ("V", "V [1 8B]", 1, 8)),
        (1, 1, 0), id="1P-plus-1V",
    ),
    pytest.param(
        _picture_rows(200, "P [200 1.6KiB]") + _VIDEO_GROUPED,
        (("P", "P [200 1.6KiB]", 200, 1600),
         ("V", "V [1 8B]", 1, 8)),
        (200, 1, 0), id="200P-plus-1V",
    ),
    pytest.param(
        (("P1/001.jpg", "P [3 15B]/001.jpg", b"oldP1"),
         ("photos/001.jpg", "P [3 15B]/002.jpg", b"photo"),
         ("root.jpg", "P [3 15B]/003.jpg", b"rootP"),
         ("videos/001.mp4", "V [1 5B]/001.mp4", b"video")),
        (("P", "P [3 15B]", 3, 15), ("V", "V [1 5B]", 1, 5)),
        (3, 1, 0), id="legacy-P1-photos-videos-duplicate-basenames",
    ),
    pytest.param(
        (("P/P1/old.jpg", "001.jpg", b"same-image"),
         ("photos/old.jpg", "002.jpg", b"same-image")),
        (), (2, 0, 0), id="nested-pure-wrappers-flatten-without-deduplication",
    ),
    pytest.param(
        (("P/movie.MP4", "V [1 5B]/001.MP4", b"movie"),
         ("V/photo.JPG", "P [1 5B]/001.JPG", b"photo")),
        (("P", "P [1 5B]", 1, 5), ("V", "V [1 5B]", 1, 5)),
        (1, 1, 0), id="misplaced-media-in-P-and-V",
    ),
    pytest.param(
        (("P [99 999B]/old.JPG", "P [1 5B]/001.JPG", b"photo"),
         ("V [88 888B]/old.mp4", "V [1 5B]/001.mp4", b"video")),
        (("P", "P [1 5B]", 1, 5), ("V", "V [1 5B]", 1, 5)),
        (1, 1, 0), id="stale-wrapper-count-and-byte-labels",
    ),
    pytest.param(
        (("captions.srt", "Other [1 5B]/captions.srt", b"words"),
         ("clip.MP4", "V [2 10B]/001.MP4", b"movie"),
         ("cover.WEBP", "P [2 10B]/001.WEBP", b"cover"),
         ("photo.jpg.mp4", "V [2 10B]/002.mp4", b"video"),
         ("video.mp4.png", "P [2 10B]/002.png", b"photo")),
        (("P", "P [2 10B]", 2, 10), ("V", "V [2 10B]", 2, 10),
         ("Other", "Other [1 5B]", 1, 5)),
        (2, 2, 1), id="extension-case-and-final-double-extension",
    ),
    pytest.param(
        (("Other/notes.txt", "Other [3 12B]/notes.txt", b"note"),
         ("Other/notes__dup002.txt", "Other [3 12B]/notes__dup002.txt", b"kept"),
         ("P/NOTES.TXT", "Other [3 12B]/NOTES__dup003.TXT", b"text"),
         ("photo.jpg", "P [1 5B]/001.jpg", b"photo")),
        (("P", "P [1 5B]", 1, 5), ("Other", "Other [3 12B]", 3, 12)),
        (1, 0, 3), id="Other-casefold-collision-preserves-existing-suffix",
    ),
    pytest.param(
        (("notes.txt", "Other [2 8B]/notes.txt", b"note"),
         ("readme", "Other [2 8B]/readme", b"text")),
        (("Other", "Other [2 8B]", 2, 8),),
        (0, 0, 2), id="Other-only-preserves-original-basenames",
    ),
]


def _empty_setup(tmp_path, monkeypatch):
    client, settings, unit = setup(tmp_path, enabled=True)
    (unit / "photo.jpg").unlink()
    (unit / "clip.png").unlink()
    _install_issuer(monkeypatch, tmp_path, allowed=True)
    return client, settings, unit


def _write_rows(unit, rows):
    for source, _target, payload in rows:
        path = unit / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _directories(root):
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_dir()
    }


def _byte_hash_multiset(files):
    return Counter(
        (len(payload), hashlib.sha256(payload).hexdigest())
        for payload in files.values()
    )


def _preview_selection(client, settings, selection):
    queued = client.post("/api/media-organizer/previews", json={
        "selection": str(selection),
    })
    assert queued.status_code == 200, queued.text
    preview_id = queued.json()["job_id"]
    assert process_work_job(settings, preview_id)
    response = client.get(f"/api/media-organizer/previews/{preview_id}?page_size=100")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "completed", report
    assert report["summary"]["blocked_count"] == 0, report
    return preview_id, report


def _assert_full_mapping(client, preview_id, unit, record, rows):
    actual = set()
    for page in range(1, (len(rows) + 99) // 100 + 1):
        response = client.get(
            f"/api/media-organizer/previews/{preview_id}/mappings/"
            f"{record['mapping_id']}?page={page}&page_size=100",
        )
        assert response.status_code == 200, response.text
        mapping = response.json()
        assert mapping["total_moves"] == len(rows)
        actual.update(
            (Path(move["source"]).relative_to(unit).as_posix(),
             Path(move["target"]).relative_to(unit).as_posix())
            for move in mapping["moves"]
        )
    assert actual == {(source, target) for source, target, _payload in rows}


def _publish_and_finalize(client, settings, unit, preview_id, report, rows, groups, totals):
    """Exercise publication and the separately confirmed cleanup WorkJob."""
    before = _files(unit)
    before_hashes = _byte_hash_multiset(before)
    assert before == {source: payload for source, _target, payload in rows}
    record = next(row for row in report["units"] if row["unit"] == str(unit))
    assert record["status"] == "ready"
    assert record["totals"] == dict(zip(("P", "V", "Other"), totals))
    assert record["needed_moves"] == len(rows)
    assert tuple(
        (group["kind"], group["name"], group["count"], group["bytes"])
        for group in record["groups"]
    ) == groups
    _assert_full_mapping(client, preview_id, unit, record, rows)
    execute_token = report["confirmation_tokens"][str(unit)]
    assert execute_token == approval_token(preview_id, str(unit))

    queued = execute_request(client, preview_id, unit, execute_token)
    assert queued.status_code == 200, queued.text
    execution_id = queued.json()["job_id"]
    assert _files(unit) == before  # The API only queues media mutation.
    assert worker(settings, execution_id, name="synthetic-rule-worker")
    published = client.get(f"/api/media-organizer/executions/{execution_id}").json()
    assert published["status"] == "completed", published
    assert published["finalized"] is False
    assert published["manual_cleanup_required"] is True
    for source, target, payload in rows:
        assert (unit / source).read_bytes() == payload
        assert (unit / target).read_bytes() == payload

    review = client.get(f"/api/media-organizer/executions/{execution_id}/cleanup-plan")
    assert review.status_code == 200, review.text
    plan = review.json()
    assert plan["unit"] == str(unit)
    assert plan["total_original_links"] == plan["total_staged_links"] == len(rows)
    assert plan["cleanup_authorized"] is False
    cleanup_token = cleanup_confirmation(plan["job_id"], str(unit), plan["plan_sha256"])
    assert cleanup_token != execute_token
    published_files = _files(unit)
    published_directories = _directories(unit)
    path = f"/api/media-organizer/executions/{execution_id}/cleanup"
    rejected = client.post(path, json={"confirmation": execute_token})
    assert rejected.status_code == 409
    cleanup = client.post(path, json={"confirmation": cleanup_token})
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["job_id"] != execution_id
    assert _files(unit) == published_files
    assert _directories(unit) == published_directories

    assert worker(settings, cleanup.json()["job_id"], name="synthetic-rule-worker")
    final = client.get(f"/api/media-organizer/executions/{execution_id}").json()
    assert final["status"] == "completed", final
    assert final["finalized"] is True
    assert final["manual_cleanup_required"] is False
    assert final["progress"]["phase"] == "completed"
    actual = _files(unit)
    assert actual == {target: payload for _source, target, payload in rows}
    assert len(actual) == len(rows)
    assert Counter(actual.values()) == Counter(before.values())
    assert _byte_hash_multiset(actual) == before_hashes
    assert _directories(unit) == {group[1] for group in groups}
    assert not any(path.name.startswith(".nfc-") for path in unit.rglob("*"))


def _assert_zero_rescan(client, settings, selection, units):
    _preview_id, report = _preview_selection(client, settings, selection)
    assert {row["unit"] for row in report["units"]} == {str(unit) for unit in units}
    assert report["summary"]["needed_moves"] == 0
    assert report["summary"]["renamed_count"] == 0
    assert report["summary"]["ready_count"] == 0
    assert report["confirmation_tokens"] == {}
    for row in report["units"]:
        assert row["status"] == "already_organized", row
        assert row["needed_moves"] == row["renamed_count"] == 0


@pytest.mark.parametrize("rows,groups,totals", _RULE_CASES)
def test_complete_rule_layout_survives_admin_worker_cleanup_and_zero_api_rescan(
    tmp_path, monkeypatch, rows, groups, totals,
):
    client, settings, unit = _empty_setup(tmp_path, monkeypatch)
    _write_rows(unit, rows)
    preview_id, report = _preview_selection(client, settings, unit.parent)
    assert len(report["units"]) == 1
    _publish_and_finalize(
        client, settings, unit, preview_id, report, rows, groups, totals,
    )
    _assert_zero_rescan(client, settings, unit.parent, [unit])


def test_recursive_collection_work_and_version_boundaries_remain_independent(
    tmp_path, monkeypatch,
):
    client, settings, unit = _empty_setup(tmp_path, monkeypatch)
    unit.rmdir()
    selection = unit.parent.parent
    unit.parent.rmdir()
    cases = (
        ("CollectionA/NO.001", (("a.jpg", "001.jpg", b"set-one"),), (), (1, 0, 0)),
        ("CollectionA/NO.002", (("a.jpg", "001.jpg", b"set-two"),), (), (1, 0, 0)),
        ("CollectionA/NO.003/4K", (("movie.mp4", "001.mp4", b"video-4k"),), (), (0, 1, 0)),
        ("CollectionA/NO.003/PT", (("movie.mp4", "001.mp4", b"video-pt"),), (), (0, 1, 0)),
        ("CollectionB/NO.001",
         (("P1/a.jpg", "P [1 5B]/001.jpg", b"photo"),
          ("videos/a.mp4", "V [1 5B]/001.mp4", b"video")),
         (("P", "P [1 5B]", 1, 5), ("V", "V [1 5B]", 1, 5)), (1, 1, 0)),
    )
    for relative, rows, _groups, _totals in cases:
        _write_rows(selection / relative, rows)
    original_files = _files(selection)
    original_hashes = _byte_hash_multiset(original_files)
    semantic_directories = {
        relative: (selection / relative).stat().st_ino
        for relative in (
            "CollectionA", "CollectionB", "CollectionA/NO.001",
            "CollectionA/NO.002", "CollectionA/NO.003", "CollectionA/NO.003/4K",
            "CollectionA/NO.003/PT", "CollectionB/NO.001",
        )
    }
    preview_id, report = _preview_selection(client, settings, selection)
    assert {row["unit"] for row in report["units"]} == {
        str(selection / relative) for relative, _rows, _groups, _totals in cases
    }
    expected_selection = dict(original_files)
    for relative, rows, groups, totals in cases:
        _publish_and_finalize(
            client, settings, selection / relative, preview_id, report,
            rows, groups, totals,
        )
        for source, target, payload in rows:
            del expected_selection[f"{relative}/{source}"]
            expected_selection[f"{relative}/{target}"] = payload
        # An individual execution cannot alter any sibling work or version.
        assert _files(selection) == expected_selection
        assert _byte_hash_multiset(_files(selection)) == original_hashes
        assert all(
            (selection / path).stat().st_ino == inode
            for path, inode in semantic_directories.items()
        )
    _assert_zero_rescan(
        client, settings, selection,
        [selection / relative for relative, _rows, _groups, _totals in cases],
    )


def test_existing_same_named_canonical_group_is_safely_refused_before_mutation(
    tmp_path, monkeypatch,
):
    """Known completeness gap: an unchanged P bucket cannot yet be reused."""
    client, settings, unit = _empty_setup(tmp_path, monkeypatch)
    _write_rows(unit, (
        ("P [1 5B]/001.jpg", "P [1 5B]/001.jpg", b"photo"),
        ("movie.mp4", "V [1 5B]/001.mp4", b"video"),
    ))
    before = _files(unit)
    before_hashes = _byte_hash_multiset(before)
    before_directories = _directories(unit)
    preview_id, report = _preview_selection(client, settings, unit.parent)
    assert report["units"][0]["status"] == "ready"
    result = execute_request(client, preview_id, unit)
    assert result.status_code == 200, result.text
    assert _files(unit) == before
    execution_id = result.json()["job_id"]
    assert worker(settings, execution_id, name="synthetic-rule-worker") is False
    refused = client.get(f"/api/media-organizer/executions/{execution_id}").json()
    assert refused["status"] == "failed"
    assert refused["finalized"] is False
    assert "old classification wrapper" in refused["error"]
    assert _files(unit) == before
    assert _byte_hash_multiset(_files(unit)) == before_hashes
    assert _directories(unit) == before_directories
    assert not any(path.name.startswith(".nfc-") for path in unit.rglob("*"))
