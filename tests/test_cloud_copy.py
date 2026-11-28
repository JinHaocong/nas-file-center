"""One-way OpenList copies publish new local folders through the actual API and Worker."""
import errno
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_media_organizer_batch import _run_next


@pytest.fixture
def copy_app(tmp_path):
    data = (tmp_path / "data").resolve()
    imports = data / "Download"
    imports.mkdir(parents=True)
    password = tmp_path / "rc-password"
    password.write_text("fixture-rclone-password")
    password.chmod(0o600)
    settings = Settings(
        _env_file=None, CONFIG_DIR=tmp_path / "config", DATA_MOUNT=data,
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=data / "trash",
        ALLOW_MUTATION=True, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
        CLOUD_COPY_SOURCE_ID="1", CLOUD_COPY_LOCAL_ROOT=imports, CLOUD_COPY_RCLONE_LOCAL_ROOT="/nfc-import",
        CLOUD_COPY_RCLONE_REMOTE="openlist", CLOUD_COPY_RCLONE_URL="http://rclone:5572",
        CLOUD_COPY_RCLONE_USERNAME="fixture", CLOUD_COPY_RCLONE_PASSWORD_FILE=password,
    )
    with TestClient(create_app(settings)) as client:
        client.headers.update({"Origin": "http://testserver"})
        assert client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        }).status_code == 200
        source = client.post("/api/download-verifications/sources", json={
            "provider": "openlist", "name": "fixture", "base_url": "http://openlist:5244",
        })
        assert source.status_code == 201
        assert str(source.json()["id"]) == "1"
        yield client, settings, imports


def submit(client, imports, **extra):
    return client.post("/api/cloud-copy", json={
        "source_id": "1", "remote_root": "PikPak/摄影作品", "local_parent": str(imports),
        "folder_name": "摄影作品", **extra,
    })


def test_configured_source_is_visible_and_saves_an_exact_background_copy(copy_app):
    client, _, imports = copy_app
    response = client.get("/api/cloud-copy/configuration")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "source_id": "1", "local_root": str(imports)}
    queued = submit(client, imports)
    assert queued.status_code == 202, queued.text
    assert submit(client, imports).status_code == 409
    data = queued.json()
    assert data["status"] == "queued" and isinstance(data["job_id"], str)
    task = client.get("/api/tasks/" + data["job_id"]).json()
    assert task["job_type"] == "cloud-copy"
    assert task["payload"]["local_root"] == str(imports / "摄影作品")
    assert task["payload"]["remote_root"] == "PikPak/摄影作品"
    assert task["payload"]["source_id"] == "1"
    assert not list(imports.iterdir())
    assert "fixture-rclone-password" not in str(task)


def test_protected_paths_and_existing_destinations_are_rejected(copy_app):
    client, _, imports = copy_app
    occupied = imports / "已有目录"
    occupied.mkdir()
    (occupied / "原件.txt").write_text("keep")
    escaped = imports / "alias"
    escaped.symlink_to(imports.parent, target_is_directory=True)
    assert submit(client, imports, local_parent=str(escaped)).status_code == 422
    assert submit(client, imports, local_parent=str(imports.parent)).status_code == 422
    assert submit(client, imports, source_id="2").status_code == 422
    assert submit(client, imports, remote_root="").status_code == 422
    assert submit(client, imports, remote_root="PikPak/../other").status_code == 422
    assert submit(client, imports, folder_name=".nfc-other").status_code == 422
    assert submit(client, imports, folder_name=occupied.name).status_code == 409
    assert (occupied / "原件.txt").read_text() == "keep"


@pytest.mark.parametrize(("scenario", "error_code"), [
    ("complete", None),
    ("occupied_late", "CLOUD_COPY_DESTINATION_EXISTS"),
    ("remote_error", "CLOUD_COPY_TRANSFER_FAILED"),
    ("unexpected_content", "CLOUD_COPY_MANIFEST_MISMATCH"),
    ("mount_mismatch", "CLOUD_COPY_RCLONE_UNAVAILABLE"),
    ("source_changed", "CLOUD_COPY_SOURCE_CHANGED"),
    ("source_files_changed", "CLOUD_COPY_MANIFEST_MISMATCH"),
    ("unconfirmed_status", "CLOUD_COPY_RCLONE_UNAVAILABLE"),
    ("unsafe_publish", "CLOUD_COPY_PUBLISH_UNAVAILABLE"),
    ("symlink", "CLOUD_COPY_NAS_UNAVAILABLE"),
])
def test_worker_uses_a_private_stage_and_atomic_new_folder(copy_app, monkeypatch, scenario, error_code):
    from app.cloud_copy import handler

    client, settings, imports = copy_app
    final = imports / "摄影作品"
    requests = []
    inventories = []
    seen_status = []
    monkeypatch.setattr(handler, "_POLL_INTERVAL", 0)

    def remote_inventory(source, settings, parts, checkpoint):
        assert parts == ("PikPak", "摄影作品")
        inventories.append(parts)
        return {"原件.jpg": {"kind": "file", "size": 9 if scenario == "source_files_changed" and len(inventories) == 2 else 5},
                "空目录": {"kind": "directory", "size": None}}

    def refuse_atomic_rename(*args):
        raise OSError(errno.EOPNOTSUPP, "fixture lacks atomic rename")

    monkeypatch.setattr(handler, "_remote_inventory", remote_inventory)
    if scenario == "unsafe_publish":
        monkeypatch.setattr(handler, "rename_noreplace_at", refuse_atomic_rename)
        monkeypatch.setattr(handler, "probe_directory_rename_noreplace_compat_at", lambda *_: False)

    class FakeRclone:
        def __init__(self, **kwargs):
            self.stage = None

        def require_staging_directory(self, destination):
            requests.append("stat")
            self.stage = imports / Path(destination).relative_to("/nfc-import")
            assert self.stage.is_dir() and not final.exists()
            if scenario == "mount_mismatch":
                raise handler.RcloneError("rclone 无法看到 NAS 暂存目录")

        def start_copy(self, source, destination):
            assert source == "openlist:PikPak/摄影作品"
            requests.append("copy")
            stage_name = Path(destination).relative_to("/nfc-import")
            assert stage_name.name.startswith(".nfc-cloud-copy-")
            assert self.stage == imports / stage_name
            if scenario == "symlink":
                unrelated = imports.parent / "protected.jpg"
                unrelated.write_bytes(b"photo")
                (self.stage / "原件.jpg").symlink_to(unrelated)
            else:
                (self.stage / "原件.jpg").write_bytes(b"photo")
            (self.stage / "空目录").mkdir()
            if scenario == "occupied_late":
                final.mkdir()
                (final / "保留.txt").write_text("existing")
            if scenario == "unexpected_content":
                (self.stage / "extra.jpg").write_bytes(b"photo")
            if scenario == "source_changed":
                assert client.put("/api/download-verifications/sources/1", json={"name": "renamed"}).status_code == 200
            return 17, "server-instance"

        def status(self, job_id, execute_id):
            assert (job_id, execute_id) == (17, "server-instance")
            seen_status.append(job_id)
            if scenario == "unconfirmed_status":
                raise handler.RcloneError("rclone 实例已变化")
            if scenario == "complete" and len(seen_status) == 1:
                return {"finished": False, "success": False}
            return {"finished": True, "success": scenario != "remote_error",
                    "error": "NAS 暂存空间不足" if scenario == "remote_error" else ""}

        def stats(self, job_id):
            assert job_id == 17
            requests.append("stats")
            return {"transfers": 1, "speed": 1048576}

        def stop(self, job_id, execute_id):
            assert (job_id, execute_id) == (17, "server-instance")
            requests.append("stop")

    monkeypatch.setattr(handler, "RcloneClient", FakeRclone)
    queued = submit(client, imports)
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job_id"]
    _run_next(settings, job_id)
    task = client.get("/api/tasks/" + job_id).json()
    stage = Path(task["payload"]["staging_path"])
    if scenario == "complete":
        assert task["status"] == "completed", task
        assert requests == ["stat", "copy", "stats"]
        assert task["progress"]["current"] == task["progress"]["total"] == 1
        assert (final / "原件.jpg").read_bytes() == b"photo"
        assert (final / "空目录").is_dir()
        assert not stage.exists()
    else:
        assert task["status"] == "failed", task
        assert task["error_code"] == error_code, task
        assert stage.is_dir()
        if scenario == "mount_mismatch":
            assert requests == ["stat"]
            assert list(stage.iterdir()) == []
        if scenario in {"source_changed", "unconfirmed_status"}:
            assert requests == ["stat", "copy", "stop"]
        if scenario == "remote_error":
            assert "暂存空间不足" in task["error"]
            assert requests == ["stat", "copy"]
        if scenario == "occupied_late":
            assert list(final.iterdir()) == [final / "保留.txt"]
            assert (final / "保留.txt").read_text() == "existing"
        else:
            assert not final.exists()
