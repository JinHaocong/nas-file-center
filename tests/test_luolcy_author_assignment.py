import errno
import json
import os
import stat

import pytest

from app.db import create_engine_and_session
from app.exceptions import StateConflictError
from app.tasks.recovery import recover_interrupted_jobs
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture


def _library(tmp_path):
    client, settings, root = _fixture(tmp_path)
    day = root / "2611/261123"
    author = day / "作者"
    package = author / "原有资源包"
    package.mkdir(parents=True)
    (package / "old.jpg").write_bytes(b"original")
    empty_author = day / "无子包作者"
    empty_author.mkdir()
    (empty_author / "独立图片.jpg").write_bytes(b"solo")
    (author / "a.jpg").write_bytes(b"image")
    (author / "b.mp4").write_bytes(b"video")
    (author / "c.txt").write_bytes(b"details")
    return client, settings, root, author, empty_author, package


def _loose_route(preview, author):
    unit = next(row for row in preview["units"] if row["unit"] == str(author))
    assert unit["status"] == "needs_assignment"
    return f"/api/media-organizer/previews/{preview['job_id']}/loose-files/{unit['loose_id']}"


def test_luolcy_scan_pages_real_loose_files_and_keeps_package_analysis(tmp_path):
    client, settings, root, author, empty_author, package = _library(tmp_path)
    preview = _preview(client, settings, root)
    assert preview["summary"]["needs_assignment_count"] == 2
    assert preview["summary"]["file_count"] == 5
    assert {row["unit"]: row["status"] for row in preview["units"]} == {
        str(author): "needs_assignment", str(empty_author): "needs_assignment", str(package): "ready",
    }
    route = _loose_route(preview, author)
    first = client.get(route, params={"page_size": 2}).json()
    assert first["files"] == [
        {"source": str(author / "a.jpg"), "kind": "P", "bytes": 5},
        {"source": str(author / "b.mp4"), "kind": "V", "bytes": 5},
    ]
    assert first["total_files"] == 3
    assert first["packages"] == [package.name]
    assert client.get(route, params={"page": 2, "page_size": 2}).json()["files"] == [
        {"source": str(author / "c.txt"), "kind": "Other", "bytes": 7},
    ]
    assert client.get(_loose_route(preview, empty_author)).json()["packages"] == []
    filtered = client.get(f"/api/media-organizer/previews/{preview['job_id']}",
                          params={"status_filter": "needs_assignment"}).json()
    assert filtered["filtered_total"] == 2

    batch_id = _batch(client, preview)
    assert _run_next(settings, batch_id)
    assert (author / "a.jpg").read_bytes() == b"image"
    assert (empty_author / "独立图片.jpg").read_bytes() == b"solo"
    assert (package / "001.jpg").read_bytes() == b"original"


@pytest.mark.parametrize("new", [False, True])
def test_selected_loose_files_generate_only_a_move_draft(tmp_path, new):
    client, settings, _, author, _, existing = _library(tmp_path)
    preview = _preview(client, settings, author)
    route = _loose_route(preview, author)
    package = author / "新建资源包" if new else existing
    source = author / "b.mp4"
    response = client.post(f"{route}/assignments", json={
        "sources": [str(source)], "package_name": package.name, "new_package": new,
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert isinstance(receipt["plan_id"], str)
    assert receipt["status"] == "draft"
    detail = client.get(f"/api/plans/{receipt['plan_id']}").json()
    row, = detail["items"]
    assert row["operation"] == "move"
    assert row["source"] == str(source)
    assert row["target"] == str(package / "b.mp4")
    assert source.read_bytes() == b"video"
    assert (author / "a.jpg").read_bytes() == b"image"
    assert not (package / "b.mp4").exists()
    assert package.exists() is not new


@pytest.mark.parametrize("problem", ["inside_package", "other_author", "link_source", "parent_name",
                                     "new_exists", "link_target", "target_exists", "stale_source"])
def test_loose_file_draft_rejects_out_of_scope_stale_or_conflicting_requests(tmp_path, problem):
    client, settings, _, author, empty_author, package = _library(tmp_path)
    (author / "link.jpg").symlink_to(empty_author / "独立图片.jpg")
    preview = _preview(client, settings, author)
    route = _loose_route(preview, author)
    source = author / "a.jpg"
    request = {"sources": [str(source)], "package_name": package.name, "new_package": False}
    if problem == "inside_package":
        request["sources"] = [str(package / "old.jpg")]
    if problem == "other_author":
        request["sources"] = [str(empty_author / "独立图片.jpg")]
    if problem == "link_source":
        request["sources"] = [str(author / "link.jpg")]
    if problem == "parent_name":
        request.update(package_name=f"../{empty_author.name}", new_package=True)
    if problem == "new_exists":
        request["new_package"] = True
    if problem == "link_target":
        package.rename(author / "另一个包")
        package.symlink_to(empty_author, target_is_directory=True)
    if problem == "target_exists":
        (package / source.name).write_bytes(b"occupied")
    if problem == "stale_source":
        source.write_bytes(b"modified")
    response = client.post(f"{route}/assignments", json=request)
    assert response.status_code == 409, response.text
    assert source.is_file()
    assert client.get("/api/plans").json()["items"] == []


def test_luolcy_legacy_preview_rows_remain_readable(tmp_path):
    client, settings, _, _, _, package = _library(tmp_path)
    preview = _preview(client, settings, package)
    report = settings.reports_dir / "organizer-v1-previews" / preview["job_id"]
    path = report / "summary.json"
    summary = json.loads(path.read_text())
    summary.pop("needs_assignment_count")
    path.write_text(json.dumps(summary) + "\n")
    response = client.get(f"/api/media-organizer/previews/{preview['job_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["units"] == preview["units"]


def _queue_assignment(client, settings, author, package, *, new_package):
    route = _loose_route(_preview(client, settings, author), author)
    receipt = client.post(f"{route}/assignments", json={
        "sources": [str(author / "a.jpg"), str(author / "b.mp4")],
        "package_name": package.name, "new_package": new_package,
    })
    assert receipt.status_code == 200, receipt.text
    plan_route = f"/api/plans/{receipt.json()['plan_id']}"
    frozen = client.post(f"{plan_route}/freeze")
    assert frozen.status_code == 200, frozen.text
    validated = client.post(f"{plan_route}/validate")
    assert validated.status_code == 200, validated.text
    queued = client.post(f"{plan_route}/execute")
    assert queued.status_code == 200, queued.text
    return plan_route, str(queued.json()["work_job_id"])


@pytest.mark.parametrize("new_package", [False, True])
def test_frozen_loose_assignment_moves_only_selected_files_into_the_chosen_package(tmp_path, new_package):
    client, settings, _, author, _, existing = _library(tmp_path)
    package = author / "新资源包" if new_package else existing
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=new_package)
    assert package.exists() is not new_package
    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "completed", detail
    assert (package / "a.jpg").read_bytes() == b"image"
    assert (package / "b.mp4").read_bytes() == b"video"
    assert (author / "c.txt").read_bytes() == b"details"
    assert (existing / "old.jpg").read_bytes() == b"original"


@pytest.mark.parametrize("problem", ["replaced_package", "claimed_new_package", "occupied_leaf"])
def test_frozen_loose_assignment_does_not_enter_changed_target_or_overwrite(tmp_path, problem):
    client, settings, _, author, other_author, existing = _library(tmp_path)
    new_package = problem == "claimed_new_package"
    package = author / "新资源包" if new_package else existing
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=new_package)
    if problem == "replaced_package":
        package.rename(author / "旧包")
        package.symlink_to(other_author, target_is_directory=True)
    elif new_package:
        package.mkdir()
    else:
        (package / "a.jpg").write_bytes(b"occupied")

    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "partial", detail
    assert (author / "a.jpg").read_bytes() == b"image"
    if problem == "occupied_leaf":
        assert (package / "a.jpg").read_bytes() == b"occupied"
    else:
        assert (author / "b.mp4").read_bytes() == b"video"
        assert not (package / "a.jpg").exists()
        assert not (other_author / "a.jpg").exists()


def test_frozen_loose_assignment_can_resume_its_own_fuse_hardlink(tmp_path, monkeypatch):
    from app.execution import luolcy_assignment

    client, settings, _, author, _, _ = _library(tmp_path)
    package = author / "新资源包"
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=True)
    real_link = os.link

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "rename no-replace unsupported")

    def interrupt_after_publication(*args, **kwargs):
        real_link(*args, **kwargs)
        if kwargs.get("dst_dir_fd") is not None:
            raise SystemExit("Worker stopped before retiring the source hardlink")

    monkeypatch.setattr(luolcy_assignment, "rename_noreplace_at", unsupported_rename)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupt_after_publication)
        with pytest.raises(SystemExit):
            _run_next(settings, job_id)
    assert (author / "a.jpg").samefile(package / "a.jpg")
    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(engine, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        engine.dispose()

    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    assert detail["status"] == "completed", detail
    assert (package / "a.jpg").read_bytes() == b"image"
    assert (package / "b.mp4").read_bytes() == b"video"
    assert not (author / "a.jpg").exists()


@pytest.mark.parametrize("native_rename", [True, False])
def test_new_package_handles_unsupported_directory_fsync_without_losing_files(tmp_path, monkeypatch, native_rename):
    from app.execution import luolcy_assignment

    client, settings, _, author, _, _ = _library(tmp_path)
    package = author / "新资源包"
    plan_route, job_id = _queue_assignment(client, settings, author, package, new_package=True)
    real_fsync = os.fsync

    def fsync_without_nas_directory_sync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_ino == author.stat().st_ino or (
                package.is_dir() and info.st_ino == package.stat().st_ino)):
            raise OSError(errno.EINVAL, "directory fsync unsupported")
        return real_fsync(fd)

    def unsupported_rename(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "rename no-replace unsupported")

    monkeypatch.setattr(os, "fsync", fsync_without_nas_directory_sync)
    if not native_rename:
        monkeypatch.setattr(luolcy_assignment, "rename_noreplace_at", unsupported_rename)
    assert _run_next(settings, job_id)
    detail = client.get(plan_route).json()
    if native_rename:
        assert detail["status"] == "completed", detail
        assert (package / "a.jpg").read_bytes() == b"image"
    else:
        assert detail["status"] == "partial", detail
        assert (author / "a.jpg").read_bytes() == b"image"
        assert (author / "b.mp4").read_bytes() == b"video"
        assert not list(package.iterdir())


def test_luolcy_assignment_requires_the_scope_checked_worker(tmp_path):
    client, settings, _, author, _, package = _library(tmp_path)
    plan_route, _ = _queue_assignment(client, settings, author, package, new_package=False)
    plan_id = client.get(plan_route).json()["id"]
    with pytest.raises(StateConflictError):
        client.app.state.service.execute_plan(plan_id)
    assert (author / "a.jpg").read_bytes() == b"image"
    assert not (package / "a.jpg").exists()
