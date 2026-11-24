"""Archive-layer recovery through the organizer preview and Worker."""

import errno
from pathlib import Path

import pytest

from app.db import create_engine_and_session
from app.tasks.recovery import recover_interrupted_jobs
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def _put(path: Path, content: bytes = b"media") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_repeated_archive_promotes_whole_children_after_media_organization(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "Else/2610/261001/作者/260617/old"
    wrapper = archive / "old"
    _put(wrapper / "部分下载/独立作品/封面.jpg", b"picture")
    _put(wrapper / "另一套/clip.mp4", b"movie")
    _put(archive / "独立旧合集/001.jpg", b"existing")

    report = _preview(client, settings, archive.parent)
    assert [r["unit"] for r in report["units"] if r["status"] == "ready"] == [
        str(wrapper / "另一套"), str(wrapper / "部分下载/独立作品"), str(wrapper),
    ]
    assert report["summary"]["file_count"] == 3
    structural, = (row for row in report["units"] if row["unit"] == str(wrapper))
    assert structural["sample_moves"] == [
        {"source": str(wrapper / child), "target": str(archive / child), "target_name": child,
         "kind": "Directory", "bytes": 0} for child in ("另一套", "部分下载")
    ]
    job_id = _batch(client, report)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["success_count"] == 3, result
    assert (archive / "部分下载/独立作品/001.jpg").read_bytes() == b"picture"
    assert (archive / "另一套/001.mp4").read_bytes() == b"movie"
    assert (archive / "独立旧合集/001.jpg").read_bytes() == b"existing"
    assert not wrapper.exists()
    assert _preview(client, settings, archive.parent)["summary"]["ready_count"] == 0


@pytest.mark.parametrize("late_name", ["作品A", "作品a", "café", "cafe\u0301"])
def test_archive_rejects_late_targets_with_exact_or_folded_names(tmp_path, late_name):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    for name in ("作品A", "café"):
        _put(wrapper / name / "001.jpg", name.encode())
    report = _preview(client, settings, archive)
    assert report["summary"]["ready_count"] == 1
    _put(archive / late_name / "occupant.txt", b"do not overwrite")

    job_id = _batch(client, report)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert (archive / late_name / "occupant.txt").read_bytes() == b"do not overwrite"
    assert (wrapper / "作品A/001.jpg").read_bytes() == "作品A".encode()
    assert (wrapper / "café/001.jpg").read_bytes() == "café".encode()


@pytest.mark.parametrize("blocked_by", ["direct-file", "symlink", "selection"])
def test_archive_wrapper_cannot_escape_boundaries(tmp_path, blocked_by):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    _put(wrapper / "作品A/001.jpg")
    if blocked_by == "direct-file":
        _put(wrapper / "保留说明.txt")
    if blocked_by == "symlink":
        target = settings.data_mount / "其他目录"
        target.mkdir()
        (wrapper / "作品A/不移动").symlink_to(target, target_is_directory=True)

    preview = _preview(client, settings, wrapper if blocked_by == "selection" else archive)
    assert all(row["operation"] != "promote_repeated_archive_children" for row in preview["units"])
    assert (wrapper / "作品A/001.jpg").read_bytes() == b"media"


@pytest.mark.parametrize("edit_published_child", [False, True])
def test_archive_resumes_after_its_first_directory_was_published(tmp_path, monkeypatch, edit_published_child):
    from app.batch import media_organizer_archive as implementation

    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    _put(wrapper / "first/001.jpg", b"first")
    _put(wrapper / "second/001.jpg", b"second")
    report = _preview(client, settings, archive)
    assert report["summary"]["ready_count"] == 1
    job_id = _batch(client, report)
    rename = implementation.rename_noreplace_at

    def stop_after_first_move(*args):
        rename(*args)
        raise SystemExit("interruption after publication")

    with monkeypatch.context() as mock:
        mock.setattr(implementation, "rename_noreplace_at", stop_after_first_move)
        with pytest.raises(SystemExit, match="interruption"):
            _run_next(settings, job_id)

    assert (archive / "first/001.jpg").read_bytes() == b"first"
    assert (wrapper / "second/001.jpg").read_bytes() == b"second"
    if edit_published_child:
        _put(archive / "first/unseen.jpg", b"not included in the confirmed batch")
    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        recovery = recover_interrupted_jobs(engine, sessions, worker_id="organizer-test-worker")
        assert recovery["recovered_requeued"] == 1, recovery
    finally:
        engine.dispose()
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    if edit_published_child:
        assert result["summary"]["conflict_count"] == 1, result
        assert (archive / "first/unseen.jpg").read_bytes() == b"not included in the confirmed batch"
        assert (wrapper / "second/001.jpg").read_bytes() == b"second"
        assert not (archive / "second").exists()
        return
    assert result["summary"]["success_count"] == 1, result
    assert (archive / "first/001.jpg").read_bytes() == b"first"
    assert (archive / "second/001.jpg").read_bytes() == b"second"
    assert not wrapper.exists()


@pytest.mark.parametrize("change", ["add", "remove", "replace"])
def test_archive_rejects_a_changed_file_inventory_at_freeze(tmp_path, change):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    existing = wrapper / "first/001.jpg"
    _put(existing, b"existing")
    report = _preview(client, settings, archive)
    assert report["summary"]["ready_count"] == 1
    extra = wrapper / "first/unseen.jpg"
    if change == "add":
        _put(extra, b"new")
    elif change == "remove":
        existing.unlink()
    else:
        _put(extra, b"same size")
        extra.replace(existing)
    job_id = _batch(client, report)

    assert _run_next(settings, job_id)

    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert (wrapper / "first").is_dir()
    assert not (archive / "first").exists()
    if change == "add":
        assert extra.read_bytes() == b"new"
    if change == "remove":
        assert not existing.exists()
    if change == "replace":
        assert existing.read_bytes() == b"same size"


def test_archive_stays_in_place_when_a_preceding_descendant_plan_conflicts(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    path = wrapper / "first/old-name.jpg"
    _put(path)
    report = _preview(client, settings, archive)
    assert report["summary"]["ready_count"] == 2
    _put(path, b"changed after the media preview")

    job_id = _batch(client, report)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert result["summary"]["skipped_count"] == 1, result
    assert "子目录" in result["items"][-1]["reason"]
    assert path.read_bytes() == b"changed after the media preview"
    assert not (archive / "first").exists()


def test_archive_rechecks_target_after_fuse_capability_probe(tmp_path, monkeypatch):
    from app.batch import media_organizer_archive as implementation

    client, settings, _ = _fixture(tmp_path)
    settings.media_package_fuse_compat_enabled = True
    archive = settings.data_mount / "old"
    wrapper = archive / "old"
    _put(wrapper / "first/001.jpg", b"first")
    report = _preview(client, settings, archive)
    job_id = _batch(client, report)

    def unsupported(*args):
        raise OSError(errno.EOPNOTSUPP, "simulated native rename unavailable")

    def probe(*args):
        _put(archive / "first/foreign.txt", b"do not overwrite")
        return True

    monkeypatch.setattr(implementation, "rename_noreplace_at", unsupported)
    monkeypatch.setattr(implementation, "probe_directory_rename_noreplace_compat_at", probe)
    assert _run_next(settings, job_id)
    result = client.get(f"/api/media-organizer/batches/{job_id}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert (wrapper / "first/001.jpg").read_bytes() == b"first"
    assert (archive / "first/foreign.txt").read_bytes() == b"do not overwrite"
