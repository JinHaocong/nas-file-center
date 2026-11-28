import json
import os
import sys
from pathlib import Path

import pytest

from app.batch import media_organizer_jobs, media_organizer_recycle
from app.batch.zspace_recycle import ZSpaceRecycleClient, ZSpaceRecycleError
from app.db import create_engine_and_session
from app.models import WorkJob
from app.tasks.recovery import recover_interrupted_jobs
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_package_execute_jobs import _fixture
from tests.test_organizer_report_cleanup import _cleanup


def _configured_fixture(tmp_path, monkeypatch):
    data = tmp_path / "data"
    trash = tmp_path / "native-recycle"
    trash.mkdir()
    cli = tmp_path / "zspace-fixture"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path, PurePosixPath\n"
        f"data, trash = Path({str(data)!r}), Path({str(trash)!r})\n"
        "args = sys.argv[1:]\n"
        "payload = json.loads(args[args.index('--params') + 1])\n"
        "def path(value):\n"
        "    return data / PurePosixPath(value).relative_to('/sata11/my/data')\n"
        "assert 'delete' in args and '--yes' in args and not payload.get('select_all')\n"
        "assert str(payload.get('skip_bin', '0')) == '0' and len(payload['paths']) == 1\n"
        "source = path(payload['paths'][0])\n"
        "source.rename(trash / source.name)\n"
        "print(json.dumps({'ok': True, 'data': {}}))\n",
        encoding="utf-8",
    )
    cli.chmod(0o700)
    monkeypatch.setenv("MEDIA_ORGANIZER_ZSPACE_CLI", str(cli))
    monkeypatch.setenv("MEDIA_ORGANIZER_ZSPACE_REMOTE_ROOT", "/sata11/my/data")
    monkeypatch.setenv("MEDIA_ORGANIZER_ZSPACE_PROFILE", "fixture")
    client, settings, luolcy = _fixture(tmp_path)
    return client, settings, luolcy, trash


@pytest.mark.parametrize("mode", ["semantic", "luolcy"])
def test_one_confirm_recycles_every_reviewed_txt_and_url(tmp_path, monkeypatch, mode):
    client, settings, luolcy, trash = _configured_fixture(tmp_path, monkeypatch)
    root = settings.data_mount / "Else" if mode == "semantic" else luolcy
    unit = root / "2611/261127/作者/作品 8G"
    unit.mkdir(parents=True)
    for name, content in {
        "原图.jpg": b"photo",
        "访问.URL": b"[InternetShortcut]\nURL=https://example.com\n",
        "地址.txt": b"https://example.com/share\n",
        "作品说明.txt": "这一套有室外场景和花絮。".encode(),
        ".URL": b"",
        "空.TXT": b"",
        "字幕.srt": b"subtitle",
    }.items():
        (unit / name).write_bytes(content)

    preview = _preview(client, settings, unit)
    recycled = {"访问.URL", "地址.txt", "作品说明.txt", ".URL", "空.TXT"}
    assert preview["summary"].get("recycle_count") == len(recycled)
    assert {Path(row["unit"]).name for row in preview["units"] if row.get("recycle_reason")} == recycled
    assert not list(trash.iterdir())
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["failed_count"] == result["summary"]["conflict_count"] == 0
    assert {file.name for file in trash.iterdir()} == recycled
    assert all(file.name not in recycled for file in unit.rglob("*"))
    assert (trash / "作品说明.txt").read_bytes() == "这一套有室外场景和花絮。".encode()
    assert [file.read_bytes() for file in unit.rglob("*.srt")] == [b"subtitle"]
    assert [file.read_bytes() for file in unit.rglob("*.jpg")] == [b"photo"]


@pytest.mark.parametrize("bucket_name", ["Other", "Other [2 7B]"])
def test_recycle_cleans_only_other_buckets_emptied_by_this_batch(tmp_path, monkeypatch, bucket_name):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "作品"
    bucket = unit / bucket_name
    ordinary = unit / "附注"
    misleading = unit / "Other [2 手写说明]"
    inactive = unit / "Other [1 8B]"
    retained = unit / "Other [2 8B]"
    for directory in (bucket, ordinary, misleading, inactive, retained):
        directory.mkdir(parents=True)
    (bucket / "说明.txt").write_bytes(b"read")
    (bucket / "地址.url").write_bytes(b"url")
    (ordinary / "附注.txt").write_bytes(b"note")
    (misleading / "笔记.TXT").write_bytes(b"memo")
    (retained / "更多.url").write_bytes(b"url")

    preview = _preview(client, settings, unit)
    assert preview["summary"]["recycle_count"] == 5
    assert not list(trash.iterdir())
    retained.joinpath("本地保留.bin").write_bytes(b"keep")
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    assert {file.name for file in trash.iterdir()} == {"说明.txt", "地址.url", "附注.txt", "笔记.TXT", "更多.url"}
    assert not bucket.exists()
    assert ordinary.is_dir() and misleading.is_dir() and inactive.is_dir()
    assert retained.joinpath("本地保留.bin").read_bytes() == b"keep"


def test_recycle_preserves_empty_other_bucket_when_one_receipt_is_uncertain(tmp_path, monkeypatch):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "作品"
    bucket = unit / "Other"
    bucket.mkdir(parents=True)
    for name in ("a.txt", "b.url"):
        (bucket / name).write_bytes(b"link")
    preview = _preview(client, settings, unit)
    batch = _batch(client, preview)
    recycle = ZSpaceRecycleClient.recycle

    def uncertain(instance, source, **kwargs):
        recycle(instance, source, **kwargs)
        if source.name == "b.url":
            raise ZSpaceRecycleError("模拟极空间未确认结果")

    monkeypatch.setattr(ZSpaceRecycleClient, "recycle", uncertain)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == result["summary"]["failed_count"] == 1
    assert {file.name for file in trash.iterdir()} == {"a.txt", "b.url"}
    assert bucket.is_dir() and not list(bucket.iterdir())


@pytest.mark.parametrize("replacement", ["empty", "link", "mount"])
def test_recycle_bypasses_replaced_or_mounted_other_bucket(tmp_path, monkeypatch, replacement):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "作品"
    bucket = unit / "Other [1 4B]"
    moved = unit / "旧桶"
    bucket.mkdir(parents=True)
    (bucket / "a.txt").write_bytes(b"read")
    preview = _preview(client, settings, unit)
    batch = _batch(client, preview)
    recycle = ZSpaceRecycleClient.recycle
    actual_mount = media_organizer_recycle._mount_identity
    bucket_inode = bucket.stat().st_ino

    def replace_after_recycle(instance, source, **kwargs):
        recycle(instance, source, **kwargs)
        bucket.rename(moved)
        if replacement == "empty":
            bucket.mkdir()
        else:
            bucket.symlink_to(moved, target_is_directory=True)

    def mount_identity(fd):
        identity = actual_mount(fd)
        return (identity[0], b"simulated-different-mount") if os.fstat(fd).st_ino == bucket_inode else identity

    if replacement == "mount":
        monkeypatch.setattr(media_organizer_recycle, "_mount_identity", mount_identity)
    else:
        monkeypatch.setattr(ZSpaceRecycleClient, "recycle", replace_after_recycle)
    assert _run_next(settings, batch)
    assert (trash / "a.txt").is_file()
    assert bucket.is_dir() and not list(bucket.iterdir())
    if replacement == "link":
        assert bucket.is_symlink() and moved.is_dir()


def test_recycle_keeps_bucket_until_media_manifest_has_run(tmp_path, monkeypatch):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "作品 8G"
    bucket = unit / "Other"
    bucket.mkdir(parents=True)
    attach = bucket / "链接.url"
    attach.write_bytes(b"link")
    (unit / "原图.jpg").write_bytes(b"photo")
    preview = _preview(client, settings, unit)
    batch = _batch(client, preview)
    finish = media_organizer_jobs._finish_unit
    witnessed = []

    def check_before_freeze(row, *args, **kwargs):
        if row["status"] == "ready":
            witnessed.append(bucket.is_dir() and not attach.exists())
        return finish(row, *args, **kwargs)

    monkeypatch.setattr(media_organizer_jobs, "_finish_unit", check_before_freeze)
    assert _run_next(settings, batch)
    assert witnessed == [True]
    assert not bucket.exists() and (trash / "链接.url").is_file()
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 2


def test_recycle_resumes_empty_bucket_cleanup_from_confirmed_results(tmp_path, monkeypatch):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "作品"
    bucket = unit / "Other"
    bucket.mkdir(parents=True)
    (bucket / "notes.txt").write_bytes(b"read")
    preview = _preview(client, settings, unit)
    batch = _batch(client, preview)

    def interrupt(*args):
        raise SystemExit("stop after committing recycle results")

    with monkeypatch.context() as patch:
        patch.setattr(media_organizer_jobs, "cleanup_empty_recycle_buckets", interrupt)
        with pytest.raises(SystemExit):
            _run_next(settings, batch)
    assert bucket.is_dir() and (trash / "notes.txt").is_file()

    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        recovered = recover_interrupted_jobs(engine, sessions, worker_id="organizer-test-worker")
        assert recovered["recovered_requeued"] == 1
    finally:
        engine.dispose()
    assert _run_next(settings, batch)
    assert not bucket.exists()
    assert (trash / "notes.txt").read_bytes() == b"read"


@pytest.mark.parametrize("change", ["edited", "interrupted"])
def test_recycle_never_submits_edited_or_unconfirmed_previous_request(tmp_path, monkeypatch, change):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "Download" / "演示目录"
    unit.mkdir(parents=True)
    source = unit / "下载地址.txt"
    source.write_bytes(b"https://example.com\n")
    preview = _preview(client, settings, unit)
    assert preview["summary"]["recycle_count"] == 1
    batch = _batch(client, preview)

    if change == "edited":
        source.write_text("补充作品说明，保留原文件。")
    else:
        engine, sessions = create_engine_and_session(settings.database_path)
        try:
            with sessions() as session:
                job = session.get(WorkJob, batch)
                job.checkpoint_json = json.dumps({"schema_version": 1, "_zspace_recycle_ordinal": 0})
                session.commit()
        finally:
            engine.dispose()

    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    outcome = "conflict" if change == "edited" else "failed"
    assert {row["status"] for row in result["items"] if row.get("operation") == "recycle_download_extras"} == {outcome}
    assert not list(trash.iterdir())
    assert source.is_file()


def test_recycle_only_batch_reports_can_be_cleaned_without_touching_trash(tmp_path, monkeypatch):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "演示目录"
    unit.mkdir()
    (unit / "访问.url").write_bytes(b"link")
    preview = _preview(client, settings, unit)
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 1
    assert client.delete(f"/api/tasks/{batch}").json()["report_cleanup"]["queued_count"] == 1
    _cleanup(client, settings)
    assert not (settings.reports_dir / "organizer-v1-executions" / batch).exists()
    assert (trash / "访问.url").read_bytes() == b"link"


@pytest.mark.parametrize("cause", ["new_mapping", "legacy_binding"])
def test_stale_recycle_binding_requires_a_fresh_preview(tmp_path, monkeypatch, cause):
    client, settings, _, trash = _configured_fixture(tmp_path, monkeypatch)
    unit = settings.data_mount / "演示目录"
    unit.mkdir()
    source = unit / "链接.url"
    source.write_bytes(b"link")
    preview = _preview(client, settings, unit)
    if cause == "new_mapping":
        monkeypatch.setattr(settings, "media_organizer_zspace_remote_root", "/other-pool/my/data")
    else:
        summary = settings.reports_dir / "organizer-v1-previews" / preview["job_id"] / "summary.json"
        record = json.loads(summary.read_text(encoding="utf-8"))
        record["recycle_binding"] = "a" * 64
        summary.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rejected = client.post(f"/api/media-organizer/previews/{preview['job_id']}/batches", json={})
    assert rejected.status_code == 409
    assert "请重新扫描" in rejected.json()["detail"]
    assert source.is_file() and not list(trash.iterdir())
