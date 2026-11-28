"""Exercise native cloud transfers through the independent admin API."""
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def cloud_app(tmp_path: Path):
    data = (tmp_path / "data").resolve()
    landing = data / "Download"
    landing.mkdir(parents=True)
    secret = tmp_path / "rc-password"
    secret.write_text("fixture-rclone-password")
    settings = Settings(
        _env_file=None, CONFIG_DIR=tmp_path / "config", DATA_MOUNT=data,
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=data / ".trash",
        ALLOW_MUTATION=True, INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
        CLOUD_COPY_LOCAL_ROOT=landing, CLOUD_COPY_RCLONE_LOCAL_ROOT=str(landing),
        CLOUD_COPY_RCLONE_URL="http://rclone:5533", CLOUD_COPY_RCLONE_USERNAME="fixture",
        CLOUD_COPY_RCLONE_PASSWORD_FILE=secret,
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Origin"] = "http://testserver"
        assert client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"}).status_code == 200
        yield client, settings, landing


def test_rclone_can_be_used_without_an_openlist_remote(cloud_app):
    client, _, landing = cloud_app
    response = client.get("/api/cloud-files/configuration")
    assert response.status_code == 200
    payload = response.json()
    assert payload["rclone"]["enabled"] is True
    assert payload["openlist"]["enabled"] is False
    assert payload["local_root"] == str(landing)
    assert payload["writable"] is True


def start_rclone(client, landing, **updates):
    return client.post("/api/cloud-files/transfers", json={
        "provider": "rclone", "remote": "PikPak WebDAV", "path": "相册",
        "names": ["封面.jpg", "视频"], "destination": str(landing), **updates,
    })


def test_native_rclone_ids_file_speeds_cancel_and_delete_record(cloud_app, monkeypatch):
    from app.cloud_files import router
    client, _, landing = cloud_app
    started = []
    cancelled = set()
    cleared = set()

    class Provider:
        def __init__(self, **kwargs):
            pass

        def remotes(self):
            return ["PikPak WebDAV"]

        def entries(self, remote, path):
            assert (remote, path) == ("PikPak WebDAV", ("相册",))
            return [{"name":"封面.jpg","kind":"file","size":600}, {"name":"视频","kind":"directory","size":None}]

        def require_destination(self, destination):
            assert destination == landing

        def list_transfers(self):
            return [record for job_id, *_ in started
                    if (record := self.get(job_id, "server-instance")) is not None]

        def start(self, remote, path, name, is_directory, destination):
            assert remote == "PikPak WebDAV"
            assert destination == landing / name
            job_id = str(9007199254740993 + len(started))
            started.append((job_id, name, is_directory))
            return {"id": job_id, "instance": "server-instance"}

        def get(self, job_id, instance):
            assert instance == "server-instance"
            if job_id in cleared or job_id not in {entry[0] for entry in started}:
                return None
            finished = job_id in cancelled
            return {"id":job_id,"instance":instance,"status":"cancelled" if finished else "running","progress":30,
                    "bytes":180,"total_bytes":600,"speed":None if finished else 70,"error":None,
                    "name":"视频" if job_id.endswith("4") else "封面.jpg","destination":str(landing),
                    "files":[{"name":"视频/原始片段.mp4","status":"running","progress":30,"bytes":180,
                              "total_bytes":600,"speed":38}] if job_id.endswith("4") and not finished else []}

        def cancel(self, job_id, instance):
            assert instance == "server-instance"
            cancelled.add(job_id)
            return True

        def delete_history(self, job_id, instance):
            assert job_id in cancelled
            cleared.add(job_id)
            return True

    monkeypatch.setattr(router, "RcloneProvider", Provider, raising=False)
    listing = client.get("/api/cloud-files/rclone/remotes")
    assert listing.status_code == 200 and listing.json() == {"items": [{"name":"PikPak WebDAV"}]}
    response = start_rclone(client, landing)
    assert response.status_code == 202, response.text
    body = response.json()
    assert isinstance(body["id"], str)
    assert body["native_ids"] == ["9007199254740993", "9007199254740994"]
    assert started == [("9007199254740993", "封面.jpg", False), ("9007199254740994", "视频", True)]
    native_list = client.get("/api/cloud-files/transfers").json()["items"]
    assert {entry["native_ids"][0] for entry in native_list} == set(body["native_ids"])
    video_job = next(entry for entry in native_list if entry["names"] == ["视频"])
    url = "/api/cloud-files/transfers/" + video_job["id"]
    details = client.get(url).json()
    assert any(item["name"] == "视频/原始片段.mp4" and item["speed"] == 38 for item in details["files"])
    assert client.delete(url).status_code == 409
    assert client.post(url + "/cancel").status_code == 200
    assert cancelled == {"9007199254740994"}
    assert client.get(url).json()["status"] == "cancelled"
    (landing / "现有文件.txt").write_text("keep")
    assert client.delete(url).json() == {"deleted": True}
    assert (landing / "现有文件.txt").read_text() == "keep"
    assert client.get(url).status_code == 404



def test_openlist_calls_native_jobs_and_does_not_write_a_nfc_transfer_table(cloud_app, monkeypatch):
    import sqlite3
    from app.cloud_files import router

    client, settings, landing = cloud_app
    settings.cloud_files_openlist_source_id = "1"
    settings.cloud_files_openlist_nas_path = "/NAS-Download"
    assert client.post("/api/download-verifications/sources", json={
        "provider": "openlist", "name": "Fixture OpenList", "base_url": "http://openlist:5244",
    }).status_code == 201
    native = {}

    class Provider:
        def __init__(self, source, config):
            assert str(source.id) == "1"

        def require_destination(self, path):
            assert path == ("NAS-Download",)

        def entries(self, path):
            assert path == ()
            return [{"name": "NAS-Download", "kind": "directory", "size": None},
                    {"name": "相册", "kind": "directory", "size": None}]

        def start(self, path, names, destination):
            assert (path, names, destination) == ((), ("相册",), ("NAS-Download",))
            native["native-root"] = {"id": "native-root", "name": "相册", "status": "running",
                                     "progress": None, "source_path": "/相册", "destination_path": "/NAS-Download/相册",
                                     "is_directory": True, "total_bytes": None}
            # OpenList places recursively discovered native children in the same task list.
            native["native-file"] = {"id":"native-file","name":"章一.jpg","status":"running","progress":40,
                                     "source_path":"/相册/章一.jpg","destination_path":"/NAS-Download/相册/章一.jpg",
                                     "is_directory":False,"total_bytes":1000}
            return [native["native-root"]]

        def list_tasks(self):
            return list(native.values())

        def get(self, task_id):
            return native.get(task_id)

        def cancel(self, task_id):
            native[task_id]["status"] = "cancelled"

        def delete(self, task_id):
            del native[task_id]

    monkeypatch.setattr(router, "OpenListProvider", Provider)
    source_list = client.get("/api/cloud-files/entries", params={"provider":"openlist"}).json()["items"]
    assert [entry["name"] for entry in source_list] == ["相册"]
    response = client.post("/api/cloud-files/transfers", json={
        "provider":"openlist","names":["相册"],"path":"","destination":str(landing),
    })
    assert response.status_code == 202, response.text
    assert response.json()["id"] == "openlist.native-root"
    path = "/api/cloud-files/transfers/openlist.native-file"
    row = client.get(path).json()
    assert row["destination"] == str(landing / "相册")
    assert row["files"] == [{"name":"章一.jpg","status":"running","progress":40,"bytes":400,
                             "total_bytes":1000,"speed":None}]
    assert client.post(path + "/cancel").status_code == 200
    assert client.get(path).json()["status"] == "cancelled"
    assert client.delete(path).json() == {"deleted": True}
    assert client.get(path).status_code == 404
    with sqlite3.connect(settings.database_path.as_uri() + "?mode=ro", uri=True) as db:
        assert not db.execute("select name from sqlite_master where type='table' and name like 'cloud_file%'").fetchall()
        assert db.execute("select count(*) from work_jobs where kind like 'cloud%'").fetchone() == (0,)


def test_bad_destinations_fail_before_any_native_submission(cloud_app):
    client, settings, landing = cloud_app
    (landing / "封面.JPG").write_text("original")
    assert start_rclone(client, landing).status_code == 409
    assert start_rclone(client, landing, destination=str(landing.parent)).status_code == 422
    assert start_rclone(client, landing, names=["../original"]).status_code == 422
    settings.allow_mutation = False
    assert start_rclone(client, landing).status_code == 403
