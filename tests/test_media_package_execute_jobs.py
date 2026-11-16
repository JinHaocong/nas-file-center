"""MediaPackage execute queue and Worker e2e run on isolated temporary files."""
import errno
from pathlib import Path

from fastapi.testclient import TestClient

from app.batch import media_package_execution as executor

from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.tasks.recovery import acquire_worker_ownership
from app.worker import process_work_job


def _fixture(tmp_path: Path, *, mutation=True, deletion=True, fuse_compat=False):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    settings = Settings(
        _env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data), MEDIA_PACKAGE_ROOT=str(data / "Else" / "Collection"),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=mutation, ALLOW_DELETE=deletion,
        MEDIA_PACKAGE_FUSE_COMPAT_ENABLED=fuse_compat,
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "test-password-123",
    }).status_code == 200
    root = data / "Else" / "Collection"
    return client, settings, root


def _preview(client, settings, package: Path):
    created = client.post("/api/media_package/previews", json={
        "selection": str(package),
    })
    assert created.status_code == 200, created.text
    pid = created.json()["job_id"]
    assert process_work_job(settings, pid)
    result = client.get(f"/api/media_package/previews/{pid}")
    assert result.status_code == 200, result.text
    assert result.json()["summary"]["ready_count"] == 1
    return pid


def test_confirmed_media_package_execute_moves_only_inner_files_and_deletes_empty_wrapper(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "SampleBundle"
    a = package / "视频A"
    b = package / "视频B"
    a.mkdir(parents=True)
    b.mkdir()
    (a / "001.mp4").write_bytes(b"one")
    (b / "002.mp4").write_bytes(b"two")
    preview_id = _preview(client, settings, package)

    path = f"/api/media_package/previews/{preview_id}/execute"
    assert client.post(path, json={"confirmation": "wrong"}).status_code == 409
    assert not (package / "001.mp4").exists()
    start = client.post(path, json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]
    dup = client.post(path, json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert dup.status_code == 200
    assert dup.json()["job_id"] == job_id

    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-test-owner"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)
    assert process_work_job(settings, job_id, session_factory=factory,
                            engine=engine, worker_id=worker_id)
    result = client.get(f"/api/media_package/executions/{job_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert (package / "001.mp4").read_bytes() == b"one"
    assert (package / "002.mp4").read_bytes() == b"two"
    assert not a.exists()
    assert not b.exists()
    assert package.name == "SampleBundle"
    assert package.parent.name == "作者"


def test_stale_snapshot_cannot_move_a_changed_package(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "New"
    inner = package / "video"
    inner.mkdir(parents=True)
    source = inner / "001.mp4"
    source.write_bytes(b"source")
    preview_id = _preview(client, settings, package)
    source.write_bytes(b"changed after preview")
    start = client.post(f"/api/media_package/previews/{preview_id}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert start.status_code == 200
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-stale-test"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)
    assert process_work_job(settings, start.json()["job_id"], session_factory=factory,
                            engine=engine, worker_id=worker_id) is False
    assert source.read_bytes() == b"changed after preview"
    assert not (package / "001.mp4").exists()


def test_mutation_gates_block_execution_queue_and_no_approval_is_implicit(tmp_path):
    client, settings, root = _fixture(tmp_path, deletion=False)
    package = root / "2611" / "261115" / "作者" / "New"
    inner = package / "sub"
    inner.mkdir(parents=True)
    (inner / "001.mp4").write_bytes(b"one")
    pid = _preview(client, settings, package)
    result = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert result.status_code == 409
    assert (inner / "001.mp4").exists()


def test_execute_queue_rejects_preview_with_any_conflict(tmp_path):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "作者" / "New"
    (package / "A").mkdir(parents=True)
    (package / "B").mkdir()
    (package / "A" / "same.jpg").write_bytes(b"one")
    (package / "B" / "same.jpg").write_bytes(b"two")
    (package / "extra.mp4").write_bytes(b"video")
    (package / "P_1").mkdir()
    created = client.post("/api/media_package/previews", json={
        "selection": str(package),
    })
    assert created.status_code == 200
    pid = created.json()["job_id"]
    assert process_work_job(settings, pid)
    body = client.get(f"/api/media_package/previews/{pid}").json()
    assert body["summary"]["blocked_count"] == 1
    result = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert result.status_code == 409
    assert (package / "A" / "same.jpg").exists()
    assert (package / "B" / "same.jpg").exists()


def test_explicit_failed_publish_recovery_reuses_original_manifest_without_reexecution(
    tmp_path, monkeypatch,
):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "SampleAuthor" / "SampleBundle"
    nested = package / "clips"
    nested.mkdir(parents=True)
    for i in range(201):
        (nested / f"{i:03d}.mp4").write_bytes(f"video-{i}".encode())
    pid = _preview(client, settings, package)
    start = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert start.status_code == 200
    failed_id = start.json()["job_id"]
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-recover-test"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)

    original_publish = executor._publish_group

    def simulated_old_failure(*args, **kwargs):
        raise executor.MediaPackageExecutionConflict(
            "Package directory changed before publish"
        )

    monkeypatch.setattr(executor, "_publish_group", simulated_old_failure)
    assert process_work_job(settings, failed_id, session_factory=factory,
                            engine=engine, worker_id=worker_id) is False
    failed = client.get(f"/api/media_package/executions/{failed_id}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "Package directory changed before publish"
    # Task deletion and generic failed-history cleanup must preserve the
    # original job ID and audit trail needed by the frozen stage.
    assert client.delete(f"/api/tasks/{failed_id}").status_code == 409
    cleared = client.post("/api/tasks/clear-history", json={"statuses": ["failed"]})
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"/api/media_package/executions/{failed_id}").status_code == 200
    # An earlier operator action may have deleted the *completed preview*
    # task after it was used for approval. Its immutable report remains.
    assert client.delete(f"/api/tasks/{pid}").status_code == 200
    assert not nested.joinpath("000.mp4").exists()
    assert any(p.name.startswith(".nfc-media_package-stage-") for p in package.iterdir())

    recover_url = f"/api/media_package/executions/{failed_id}/recover"
    assert client.post(recover_url, json={"confirmation": "wrong"}).status_code == 409
    token = f"RECOVER_MEDIA_PACKAGE_EXECUTION_{failed_id}"
    recovery = client.post(recover_url, json={"confirmation": token})
    assert recovery.status_code == 200, recovery.text
    recovered_id = recovery.json()["job_id"]
    assert recovered_id != failed_id
    duplicate = client.post(recover_url, json={"confirmation": token})
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["job_id"] == recovered_id

    monkeypatch.setattr(executor, "_publish_group", original_publish)
    assert process_work_job(settings, recovered_id, session_factory=factory,
                            engine=engine, worker_id=worker_id)
    done = client.get(f"/api/media_package/executions/{recovered_id}").json()
    assert done["status"] == "completed"
    assert client.get(f"/api/media_package/executions/{failed_id}").json()["status"] == "failed"
    assert any(p.name.startswith("V [200 ") for p in package.iterdir())
    visible = list(package.glob("V*/*.mp4"))
    assert len(visible) == 201
    assert not nested.exists()
    assert not any(p.name.startswith(".nfc-") for p in package.iterdir())
    assert client.post(recover_url, json={"confirmation": token}).json()["job_id"] == recovered_id


def test_failed_recovery_rejects_unknown_stage_without_running(tmp_path, monkeypatch):
    client, settings, root = _fixture(tmp_path)
    package = root / "2611" / "261115" / "SampleAuthor" / "SampleBundle"
    nested = package / "clips"
    nested.mkdir(parents=True)
    for i in range(201):
        (nested / f"{i:03d}.mp4").write_bytes(b"x")
    pid = _preview(client, settings, package)
    start = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    failed_id = start.json()["job_id"]
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media_package-recover-forgery"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)

    def old_failure(*args, **kwargs):
        raise executor.MediaPackageExecutionConflict(
            "Package directory changed before publish"
        )

    monkeypatch.setattr(executor, "_publish_group", old_failure)
    assert process_work_job(settings, failed_id, session_factory=factory,
                            engine=engine, worker_id=worker_id) is False
    stage = next(p for p in package.iterdir()
                 if p.name.startswith(".nfc-media_package-stage-"))
    (stage / "foreign.txt").write_bytes(b"foreign")
    url = f"/api/media_package/executions/{failed_id}/recover"
    result = client.post(url, json={
        "confirmation": f"RECOVER_MEDIA_PACKAGE_EXECUTION_{failed_id}",
    })
    assert result.status_code == 409, result.text
    assert (stage / "foreign.txt").read_bytes() == b"foreign"
    assert client.get(f"/api/media_package/executions/{failed_id}").json()["status"] == "failed"


def test_original_zos_errno95_failed_task_recovers_with_same_manifest_and_stage(
    tmp_path, monkeypatch,
):
    """Old failed WorkJob remains immutable; the new one reuses its stage."""
    client, settings, root = _fixture(tmp_path, fuse_compat=True)
    package = root / "2611" / "261116" / "ExampleAuthor" / "ExampleBundle"
    inner = package / "clips"
    inner.mkdir(parents=True)
    for index in range(201):
        (inner / f"{index:03d}.mp4").write_bytes(f"video-{index}".encode())
    pid = _preview(client, settings, package)
    started = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    assert started.status_code == 200, started.text
    old_id = started.json()["job_id"]
    engine, factory = create_engine_and_session(settings.database_path)
    owner = "media-package-zos-recovery"
    assert acquire_worker_ownership(engine, factory, worker_id=owner)

    real_publish = executor._publish_group

    def old_incompatible_publish(frozen, group_index, fence, **_kwargs):
        raise OSError(
            errno.EOPNOTSUPP,
            "Plain directory rename no-clobber semantics are not positively proven",
            str(package / frozen["groups"][group_index]["stage"]),
        )

    monkeypatch.setattr(executor, "_publish_group", old_incompatible_publish)
    assert not process_work_job(settings, old_id, session_factory=factory,
                                engine=engine, worker_id=owner)
    old = client.get(f"/api/media_package/executions/{old_id}").json()
    assert old["status"] == "failed"
    assert old["error"].startswith(
        "[Errno 95] Plain directory rename no-clobber semantics are not positively proven: "
    )
    assert len(list((package / f".nfc-media_package-stage-{old_id}-0").iterdir())) == 200
    assert len(list((package / f".nfc-media_package-stage-{old_id}-1").iterdir())) == 1

    # The old preview WorkJob was removed on a prior operator action.
    assert client.delete(f"/api/tasks/{pid}").status_code == 200
    recovery_url = f"/api/media_package/executions/{old_id}/recover"
    token = f"RECOVER_MEDIA_PACKAGE_EXECUTION_{old_id}"
    assert client.post(recovery_url, json={"confirmation": "wrong"}).status_code == 409
    scheduled = client.post(recovery_url, json={"confirmation": token})
    assert scheduled.status_code == 200, scheduled.text
    new_id = scheduled.json()["job_id"]
    assert new_id != old_id

    native = executor.rename_noreplace_at

    def reject_group_rename(srcfd, srcname, dstfd, dstname):
        if str(srcname).startswith(".nfc-media_package-stage-"):
            raise OSError(errno.EOPNOTSUPP, "zfuse does not support atomic directory rename")
        return native(srcfd, srcname, dstfd, dstname)

    def reject_plain_rename(src, dst):
        raise OSError(
            errno.EOPNOTSUPP,
            "Plain directory rename no-clobber semantics are not positively proven",
            str(src),
        )

    monkeypatch.setattr(executor, "_publish_group", real_publish)
    monkeypatch.setattr(executor, "rename_noreplace_at", reject_group_rename)
    monkeypatch.setattr(executor, "rename_directory_noreplace_compat", reject_plain_rename)
    assert process_work_job(settings, new_id, session_factory=factory,
                            engine=engine, worker_id=owner)
    done = client.get(f"/api/media_package/executions/{new_id}").json()
    assert done["status"] == "completed"
    assert client.get(f"/api/media_package/executions/{old_id}").json()["status"] == "failed"
    published = sorted(package.glob("V*/*.mp4"))
    assert len(published) == 201
    assert not any(x.name.startswith(".nfc-") for x in package.iterdir())
    assert not inner.exists()
    assert client.post(recovery_url, json={"confirmation": token}).json()["job_id"] == new_id


def test_errno95_recovery_error_allowlist_rejects_unrelated_failures():
    from app.batch.media_package_execute_jobs import is_recoverable_media_package_publish_error

    assert is_recoverable_media_package_publish_error(
        "EXECUTION_ERROR",
        "[Errno 95] Plain directory rename no-clobber semantics are not positively proven: '/safe/stage'",
    )
    assert is_recoverable_media_package_publish_error(
        "EXECUTION_ERROR", "Package directory changed before publish",
    )
    assert is_recoverable_media_package_publish_error(
        "EXECUTION_ERROR",
        "FUSE grouped publication disabled: run the isolated NAS probe and "
        "explicitly enable MEDIA_PACKAGE_FUSE_COMPAT_ENABLED",
    )
    for code, error in (
        ("AUTH_FAILURE", "Package directory changed before publish"),
        ("EXECUTION_ERROR", "[Errno 95] Unexpected filesystem error"),
        ("EXECUTION_ERROR", "FUSE grouped publication disabled"),
        ("NOT_EXECUTION_ERROR", "FUSE grouped publication disabled: run the isolated NAS probe and explicitly enable MEDIA_PACKAGE_FUSE_COMPAT_ENABLED"),
        ("EXECUTION_ERROR", "Missing file in frozen package"),
        (None, "Package directory changed before publish"),
    ):
        assert not is_recoverable_media_package_publish_error(code, error)


def test_zos_recovery_requires_private_capability_opt_in(tmp_path, monkeypatch):
    client, settings, root = _fixture(tmp_path, fuse_compat=False)
    package = root / "2611" / "261116" / "ExampleAuthor" / "ExampleBundle"
    inner = package / "clips"
    inner.mkdir(parents=True)
    for index in range(201):
        (inner / f"{index:03d}.mp4").write_bytes(b"x")
    pid = _preview(client, settings, package)
    started = client.post(f"/api/media_package/previews/{pid}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{pid}",
    })
    old_id = started.json()["job_id"]
    engine, factory = create_engine_and_session(settings.database_path)
    owner = "zos-capability-fence"
    assert acquire_worker_ownership(engine, factory, worker_id=owner)

    def legacy_errno95(frozen, index, fence):
        raise OSError(
            errno.EOPNOTSUPP,
            "Plain directory rename no-clobber semantics are not positively proven",
            str(package / frozen["groups"][index]["stage"]),
        )

    monkeypatch.setattr(executor, "_publish_group", legacy_errno95)
    assert process_work_job(settings, old_id, session_factory=factory,
                            engine=engine, worker_id=owner) is False
    recovery = client.post(f"/api/media_package/executions/{old_id}/recover", json={
        "confirmation": f"RECOVER_MEDIA_PACKAGE_EXECUTION_{old_id}",
    })
    assert recovery.status_code == 409
    assert "FUSE compatibility is disabled" in recovery.text
    assert (package / f".nfc-media_package-stage-{old_id}-0").is_dir()


def test_failed_disabled_fuse_gate_task_resumes_exact_frozen_stage_after_private_opt_in(
    tmp_path, monkeypatch,
):
    """Production-style: 201 staged files, no new plan, no automatic retry."""
    client, settings, root = _fixture(tmp_path, fuse_compat=False)
    package = root / "2611" / "261116" / "ExampleAuthor" / "ExampleBundle"
    clips = package / "clips"
    clips.mkdir(parents=True)
    for index in range(201):
        (clips / f"{index:03d}.mp4").write_bytes(f"movie-{index}".encode())
    preview_id = _preview(client, settings, package)
    start = client.post(f"/api/media_package/previews/{preview_id}/execute", json={
        "confirmation": f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_id}",
    })
    assert start.status_code == 200, start.text
    failed_id = start.json()["job_id"]
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "media-package-disabled-fuse-recovery"
    assert acquire_worker_ownership(engine, factory, worker_id=worker_id)

    native = executor.rename_noreplace_at

    def unsupported_directory_rename(srcfd, srcname, dstfd, dstname):
        if str(srcname).startswith(".nfc-media_package-stage-"):
            raise OSError(errno.EOPNOTSUPP, "zfuse directory no-replace unavailable")
        return native(srcfd, srcname, dstfd, dstname)

    def unsafe_plain_directory_rename(source, destination):
        raise OSError(
            errno.EOPNOTSUPP,
            "Plain directory rename no-clobber semantics are not positively proven",
            str(source),
        )

    monkeypatch.setattr(executor, "rename_noreplace_at", unsupported_directory_rename)
    monkeypatch.setattr(executor, "rename_directory_noreplace_compat", unsafe_plain_directory_rename)

    assert process_work_job(settings, failed_id, session_factory=factory,
                            engine=engine, worker_id=worker_id) is False
    failed = client.get(f"/api/media_package/executions/{failed_id}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == (
        "FUSE grouped publication disabled: run the isolated NAS probe "
        "and explicitly enable MEDIA_PACKAGE_FUSE_COMPAT_ENABLED"
    )
    first = package / f".nfc-media_package-stage-{failed_id}-0"
    second = package / f".nfc-media_package-stage-{failed_id}-1"
    assert len(list(first.iterdir())) == 200
    assert len(list(second.iterdir())) == 1
    assert not (package / "clips" / "000.mp4").exists()
    assert not any(p.name.startswith("V [") for p in package.iterdir())

    recover_url = f"/api/media_package/executions/{failed_id}/recover"
    confirmation = f"RECOVER_MEDIA_PACKAGE_EXECUTION_{failed_id}"
    rejected = client.post(recover_url, json={"confirmation": confirmation})
    assert rejected.status_code == 409, rejected.text
    assert "FUSE compatibility is disabled" in rejected.text
    assert client.delete(f"/api/tasks/{failed_id}").status_code == 409
    # Emulate a separately authorized deployment after isolated NAS testing.
    settings.media_package_fuse_compat_enabled = True
    assert client.delete(f"/api/tasks/{preview_id}").status_code == 200
    accepted = client.post(recover_url, json={"confirmation": confirmation})
    assert accepted.status_code == 200, accepted.text
    recovery_id = accepted.json()["job_id"]
    assert recovery_id != failed_id
    assert client.post(recover_url, json={"confirmation": confirmation}).json()["job_id"] == recovery_id

    assert process_work_job(settings, recovery_id, session_factory=factory,
                            engine=engine, worker_id=worker_id) is True
    result = client.get(f"/api/media_package/executions/{recovery_id}").json()
    assert result["status"] == "completed"
    assert client.get(f"/api/media_package/executions/{failed_id}").json()["status"] == "failed"
    final_files = list(package.glob("V*/*.mp4"))
    assert len(final_files) == 201
    assert not first.exists() and not second.exists()
    assert not clips.exists()
    assert sorted(p.name for p in package.iterdir()) == sorted(
        [p.parent.name for p in final_files if p.name == "001.mp4"]
    )
