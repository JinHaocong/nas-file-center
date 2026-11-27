import json
import sys
from pathlib import Path

import pytest

from app.db import create_engine_and_session
from app.models import WorkJob
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
def test_one_confirm_recycles_only_reviewed_download_extras(tmp_path, monkeypatch, mode):
    client, settings, luolcy, trash = _configured_fixture(tmp_path, monkeypatch)
    root = settings.data_mount / "Else" if mode == "semantic" else luolcy
    unit = root / "2611/261127/作者/作品 8G"
    unit.mkdir(parents=True)
    for name, content in {
        "原图.jpg": b"photo",
        "访问.URL": b"[InternetShortcut]\nURL=https://example.com\n",
        "地址.txt": b"https://example.com/share\n",
        "作品说明.txt": "这一套有室外场景和花絮。".encode(),
    }.items():
        (unit / name).write_bytes(content)

    preview = _preview(client, settings, unit)
    assert preview["summary"].get("recycle_count") == 2
    assert {Path(row["unit"]).name for row in preview["units"] if row.get("recycle_reason")} == {
        "访问.URL", "地址.txt",
    }
    assert not list(trash.iterdir())
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["failed_count"] == result["summary"]["conflict_count"] == 0
    assert {file.name for file in trash.iterdir()} == {"访问.URL", "地址.txt"}
    assert all(file.name not in {"访问.URL", "地址.txt"} for file in unit.rglob("*"))
    assert [file.read_bytes() for file in unit.rglob("作品说明.txt")] == ["这一套有室外场景和花絮。".encode()]
    assert [file.read_bytes() for file in unit.rglob("*.jpg")] == [b"photo"]


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
