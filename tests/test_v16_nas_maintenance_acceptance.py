"""Local behavioral tests for the stand-alone physical acceptance driver.

Positive lifecycle cases explicitly inject disposable custody in both local
processes. They are protocol tests, not production or physical NAS acceptance.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import pytest

from scripts import v16_nas_maintenance_acceptance as nas


DIGEST = "sha256:" + "b" * 64
REV = "1" * 40


@pytest.mark.parametrize("image", ["repo:latest", "-q", "repo@sha256:1", "x y@" + DIGEST])
def test_mutable_or_unsafe_reference_rejected(image):
    with pytest.raises(nas.Failure):
        nas.validate_inputs("/mnt/media", image, REV)


def test_revision_and_image_identity_bound():
    ref = "localhost:5000/private/nfc@" + DIGEST
    nas.validate_inputs("/mnt/media", ref, REV)
    record = {"id": DIGEST, "revision": REV, "volumes": None, "digests": [ref]}
    assert nas.validate_image(record, ref, REV) == DIGEST
    for bad in [dict(record, revision="2" * 40), dict(record, volumes={"/extra": {}}),
                dict(record, digests=[]), dict(record, id="latest")]:
        with pytest.raises(nas.Failure):
            nas.validate_image(bad, ref, REV)


@pytest.mark.parametrize("root", ["/", "../bad", "/a/../b", "/a//b", "/bad,name"])
def test_root_name_refusal(root):
    with pytest.raises(nas.Failure):
        nas.validate_inputs(root, DIGEST, REV)


def test_walk_refuses_symlink_and_replaced_binding(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        with ExitStack() as stack:
            nas.open_tree(stack, tmp_path / "alias/real")
    with ExitStack() as stack:
        parent = nas.open_tree(stack, tmp_path)
        child = nas.open_tree(stack, real)
        real.rename(tmp_path / "moved")
        real.mkdir()
        with pytest.raises(nas.Failure, match="binding"):
            nas.check_binding(parent, "real", child)


def test_collection_inventory_rejects_foreign_entry(tmp_path):
    unit = nas.seed_case(tmp_path, "mixed")
    before = nas.inventory(unit)
    assert before["count"] == 3 and sum(before["hashes"].values()) == 3
    (unit / "foreign").symlink_to(tmp_path)
    with pytest.raises(nas.Failure):
        nas.inventory(unit)


@pytest.fixture(scope="module")
def local_server(tmp_path_factory, request):
    # Use one consistent mode in the actual HTTP server and its Worker.
    # The strict-denial regression parametrizes the fixture independently;
    # other callers retain the maintenance-window lifecycle defaults.
    selected_mode = getattr(request, "param", "maintenance_window")
    if selected_mode not in ("strict", "maintenance_window"):
        raise ValueError("invalid fixture execution mode")
    if os.geteuid() == 0:
        pytest.skip("The production maintenance authority requires an unprivileged Worker")
    base = tmp_path_factory.mktemp("maintenance-http")
    data, config = base / "data", base / "config"
    data.mkdir()
    config.mkdir()
    config.chmod(0o2770)
    password = secrets.token_urlsafe(32)
    env = {**os.environ, **nas.CONFIG, "CONFIG_DIR": str(config), "DATA_MOUNT": str(data),
           "ALLOWED_ROOTS": str(data), "QUARANTINE_ROOT": str(data / ".trash"),
           "NFC_SHARED_CONFIG_GID": str(os.getegid()), "INITIAL_ADMIN_PASSWORD": password,
           "MEDIA_ORGANIZER_EXECUTION_MODE": selected_mode,
           # The strict regression must reach the real missing custody issuer.
           # This ack is only an eligibility prerequisite, never custody proof.
           "MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK":
               "true" if selected_mode == "strict" else "false"}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--fd", str(sock.fileno())],
            pass_fds=(sock.fileno(),), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                for _ in range(180):
                    try:
                        if nas.http(port, "GET", "/health")["status"] == 200:
                            break
                    except OSError:
                        pass
                    assert process.poll() is None
                    time.sleep(.2)
                else:
                    pytest.fail("API failed to start")
                login = nas.http(port, "POST", "/api/auth/login",
                                 {"username": nas.CONFIG["INITIAL_ADMIN_USERNAME"], "password": password})
                assert login["status"] == 200 and login["cookie"]
                yield data, env, port, login["cookie"]
            finally:
                process.terminate()
                process.wait(timeout=15)


def _serve_synthetic_fixture():
    """Test-only subprocess entry point; no production environment bypass."""
    import uvicorn
    from tests.test_media_organizer_grouped_worker_custody import _install_issuer

    with pytest.MonkeyPatch.context() as patch:
        _install_issuer(patch, Path(sys.argv[1]), allowed=True)
        uvicorn.run("app.main:app", fd=int(sys.argv[2]))


@pytest.fixture
def synthetic_server(tmp_path, monkeypatch):
    """Admit only this temporary tree in the real API and parent Worker."""
    from tests.test_media_organizer_grouped_worker_custody import _install_issuer

    if os.geteuid() == 0:
        pytest.skip("The production maintenance authority requires an unprivileged Worker")
    data, config = tmp_path / "data", tmp_path / "config"
    data.mkdir()
    config.mkdir()
    config.chmod(0o2770)
    password = secrets.token_urlsafe(32)
    env = {**os.environ, **nas.CONFIG, "CONFIG_DIR": str(config), "DATA_MOUNT": str(data),
           "ALLOWED_ROOTS": str(data), "QUARANTINE_ROOT": str(data / ".trash"),
           "NFC_SHARED_CONFIG_GID": str(os.getegid()), "INITIAL_ADMIN_PASSWORD": password}
    _install_issuer(monkeypatch, tmp_path, allowed=True)
    bootstrap = (
        "from tests.test_v16_nas_maintenance_acceptance import _serve_synthetic_fixture; "
        "_serve_synthetic_fixture()"
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with subprocess.Popen(
            [sys.executable, "-c", bootstrap, str(tmp_path), str(sock.fileno())],
            pass_fds=(sock.fileno(),), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                for _ in range(180):
                    try:
                        if nas.http(port, "GET", "/health")["status"] == 200:
                            break
                    except OSError:
                        pass
                    assert process.poll() is None
                    time.sleep(.2)
                else:
                    pytest.fail("Synthetic API failed to start")
                login = nas.http(port, "POST", "/api/auth/login",
                                 {"username": nas.CONFIG["INITIAL_ADMIN_USERNAME"], "password": password})
                assert login["status"] == 200 and login["cookie"]
                yield data, env, port, login["cookie"]
            finally:
                process.terminate()
                process.wait(timeout=15)


@pytest.mark.parametrize("case", ["mixed", "historical", "boundary"])
def test_ordinary_http_and_real_dispatch_recovery(synthetic_server, case, monkeypatch):
    from app.config import Settings
    data, env, port, cookie = synthetic_server
    for key in [*nas.CONFIG, "INITIAL_ADMIN_PASSWORD"]:
        monkeypatch.setenv(key, env[key])
    settings = Settings(_env_file=None)
    unit = nas.seed_case(data, case)
    evidence = {}
    def request(method, path, body=None):
        return nas.http(port, method, path, body, cookie)
    def run_job(jid, fault=None):
        return nas.dispatch(settings, jid, fault)
    nas.run_case(case, unit, request, run_job, lambda: nas.inventory(unit), evidence)
    assert evidence["complete"] and evidence["before"]["hashes"] == evidence["after"]["hashes"]
    assert evidence["second_scan"] == {"needed_moves": 0, "renamed_count": 0}
    assert set(evidence["simulated_interruptions"]) == {"publication", "cleanup"}
    assert [item["phase"] for item in evidence["recovery_jobs"]] == ["execution", "cleanup"]
    assert len(evidence["jobs"]) == 6  # initial preview, execute, recovery, cleanup, recovery, final preview
    assert [job["interruption"] for job in evidence["jobs"] if job["interruption"]] == ["publication", "cleanup"]


@pytest.mark.parametrize("local_server", ["strict"], indirect=True)
def test_live_http_refuses_strict_mode_without_custody(local_server, monkeypatch):
    from sqlalchemy import select
    from app.batch.media_organizer_execute_jobs import approval_token
    from app.config import Settings
    from app.db import create_engine_and_session
    from app.models import WorkJob

    data, env, port, cookie = local_server
    for key in [*nas.CONFIG, "INITIAL_ADMIN_PASSWORD"]:
        monkeypatch.setenv(key, env[key])
    # The API subprocess and dispatching Worker must use the same strict mode.
    # A Worker-only mode override would fail during the read-only preview.
    assert env["MEDIA_ORGANIZER_EXECUTION_MODE"] == "strict"
    settings = Settings(_env_file=None)
    assert settings.media_organizer_execution_mode == "strict"
    unit = nas.seed_case(data, "mixed")

    def snapshot():
        bindings = {}
        for path in [unit, *unit.rglob("*")]:
            info = path.lstat()
            bindings[str(path.relative_to(unit))] = (
                info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            )
        return nas.inventory(unit), bindings

    def request(method, path, body=None):
        return nas.http(port, method, path, body, cookie)

    def run_job(jid, fault=None):
        return nas.dispatch(settings, jid, fault)

    before = snapshot()
    queued = request("POST", "/api/media-organizer/previews", {"selection": str(unit.parent)})
    assert queued["status"] == 200
    pid = queued["body"]["job_id"]
    assert run_job(pid)["dispatch_completed"] is True
    preview = request("GET", f"/api/media-organizer/previews/{pid}")
    assert preview["status"] == 200
    report = preview["body"]
    assert str(unit) not in report["confirmation_tokens"]
    assert next(row for row in report["units"] if row["unit"] == str(unit))["status"] == "ready"

    engine, sessions = create_engine_and_session(settings.database_path)
    try:
        with sessions() as session:
            before_jobs = session.scalars(select(WorkJob.id).order_by(WorkJob.id)).all()
            assert session.scalars(select(WorkJob.id).where(
                WorkJob.kind == "media-organizer-execute",
            )).all() == []
        denied = request("POST", f"/api/media-organizer/previews/{pid}/execute", {
            "unit": str(unit), "confirmation": approval_token(pid, str(unit)),
            "maintenance_window_confirmed": False,
        })
        assert denied["status"] == 409
        assert "custody" in denied["body"]["detail"].lower()
        with sessions() as session:
            assert session.scalars(select(WorkJob.id).order_by(WorkJob.id)).all() == before_jobs
        assert snapshot() == before

        # The physical acceptance driver is maintenance-window only, so do
        # not invoke it with strict-mode settings. The real HTTP path must
        # continue to withhold execution tokens and preserve job/media state.
        second_preview = request("GET", f"/api/media-organizer/previews/{pid}")
        assert second_preview["status"] == 200
        assert str(unit) not in second_preview["body"]["confirmation_tokens"]
        with sessions() as session:
            assert session.scalars(select(WorkJob.id).where(
                WorkJob.kind == "media-organizer-execute",
            )).all() == []
        assert snapshot() == before
    finally:
        engine.dispose()


def test_mount_evidence_from_real_open_fd(tmp_path):
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        observed = nas.mount_evidence(fd)
        assert observed["identity"] == nas.identity(tmp_path.stat())
        assert observed["read_only"] is False
        assert observed["mount_id"] > 0 and observed["filesystem"]
        assert observed["major_minor"] == f"{os.major(tmp_path.stat().st_dev)}:{os.minor(tmp_path.stat().st_dev)}"


@pytest.mark.parametrize("role", ["api", "worker"])
def test_inspected_mount_and_runtime_contract(role, tmp_path):
    from copy import deepcopy
    uid = nas.API if role == "api" else nas.WORKER
    cid = "c" * 64
    info = {"id": cid, "image": DIGEST, "label": tmp_path.name, "name": f"/{tmp_path.name}-{role}",
            "user": f"{uid}:{nas.GROUP}", "host": {"ReadonlyRootfs": True, "NetworkMode": "none",
            "Privileged": False, "CapDrop": ["ALL"], "CapAdd": [], "PortBindings": {}, "GroupAdd": [],
            "SecurityOpt": ["no-new-privileges"], "Tmpfs": {"/tmp": "nosuid,nodev,noexec"}},
            "mounts": [{"Type": "bind", "Destination": "/config", "Source": str(tmp_path / "config"), "RW": True},
                       {"Type": "bind", "Destination": "/data", "Source": str(tmp_path / "data"), "RW": role == "worker"}]}
    assert nas.verify_container(info, cid, DIGEST, tmp_path, role)["id"] == cid
    for patch in ({"NetworkMode": "host"}, {"ReadonlyRootfs": False}, {"CapAdd": ["DAC_OVERRIDE"]},
                  {"GroupAdd": ["0"]}, {"SecurityOpt": []}, {"PortBindings": {"80/tcp": []}}):
        with pytest.raises(nas.Failure):
            nas.verify_container(dict(info, host={**info["host"], **patch}), cid, DIGEST, tmp_path, role)
    for mutation in ("socket", "wrong-data", "wrong-rw", "wrong-user", "other-container"):
        bad = deepcopy(info)
        if mutation == "socket":
            bad["mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock",
                                  "Destination": "/var/run/docker.sock", "RW": True})
        elif mutation == "wrong-data":
            bad["mounts"][-1]["Source"] = str(tmp_path)
        elif mutation == "wrong-rw":
            bad["mounts"][-1]["RW"] = role == "api"
        elif mutation == "wrong-user":
            bad["user"] = "0:0"
        else:
            bad["id"] = "d" * 64
        with pytest.raises(nas.Failure):
            nas.verify_container(bad, cid, DIGEST, tmp_path, role)


def test_root_only_cli_and_bad_revision_cannot_touch_existing_data(tmp_path, capsys):
    existing = tmp_path / "existing.jpg"
    existing.write_bytes(b"existing")
    for revision in ["abc"] + ([REV] if os.geteuid() != 0 else []):
        assert nas.main(["--data-root", str(tmp_path), "--image", DIGEST, "--candidate-sha", revision]) == 2
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "FAIL_MAINTENANCE_LIFECYCLE"
        assert report["namespace_exclusive_custody_proven"] is report["release_ready"] is False
        assert list(tmp_path.iterdir()) == [existing] and existing.read_bytes() == b"existing"


def test_production_flock_contention_through_real_subprocess(local_server, monkeypatch):
    from app.config import Settings
    _, env, _, _ = local_server
    monkeypatch.setenv("NFC_SHARED_CONFIG_GID", env["NFC_SHARED_CONFIG_GID"])
    settings = Settings(_env_file=None, CONFIG_DIR=env["CONFIG_DIR"])
    evidence = nas.lock_check([sys.executable, "-c", nas.LOCK_HOLDER], lambda: nas.probe_lock(settings), env=env)
    assert evidence["worker_refused_while_api_holds"] and evidence["worker_acquired_after_release"]
    from app.tasks.media_mutation_lock import _LOCK_NAME
    assert _LOCK_NAME == "media-mutation.lock"
    assert not _LOCK_NAME.startswith(".")
    assert evidence["lock_identity"] == nas.identity((Path(env["CONFIG_DIR"]) / _LOCK_NAME).stat())


def test_lock_holder_ready_on_high_descriptor():
    import fcntl
    import resource
    if resource.getrlimit(resource.RLIMIT_NOFILE)[0] <= 1024:
        pytest.skip("descriptor limit prevents allocating FD 1024")
    with ExitStack() as stack:
        reader, writer = os.pipe()
        stack.callback(os.close, reader)
        stack.callback(os.close, writer)
        high = fcntl.fcntl(reader, fcntl.F_DUPFD_CLOEXEC, 1024)
        stack.callback(os.close, high)
        with pytest.raises(nas.Failure, match="did not acquire"):
            nas.wait_for_lock_holder(high, 0)
        os.write(writer, b"ready")
        nas.wait_for_lock_holder(high, .5)


@pytest.mark.parametrize("kind", ["file", "directory", "permanent-directory"])
def test_evidence_sync_failure_cannot_leave_a_public_pass(tmp_path, monkeypatch, kind):
    import stat
    real_sync = os.fsync
    report = {"status": nas.PASS, "zero_exit_required": True}
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        nas.publish_report(fd, {"status": "INCOMPLETE"})
        fired = []
        def fail_sync(target):
            directory = stat.S_ISDIR(os.fstat(target).st_mode)
            if directory == (kind != "file") and (not fired or kind == "permanent-directory"):
                fired.append(True)
                raise OSError("injected sync error")
            real_sync(target)
        monkeypatch.setattr(nas.os, "fsync", fail_sync)
        nas.finish_report(fd, report)
    assert fired and report["status"] == nas.FAIL and report["report_write_failure"]
    retained = json.loads((tmp_path / "acceptance-report.json").read_text())
    assert retained["status"] == nas.FAIL and retained["zero_exit_required"] is True
    if kind == "permanent-directory":
        assert report["retained_evidence_unverified"]


def test_new_fixture_recorded_before_metadata_validation(tmp_path, monkeypatch):
    fixture = tmp_path / (nas.PREFIX + "case")
    report = {}
    def reject(*args):
        raise nas.Failure("injected new directory metadata failure")
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        monkeypatch.setattr(nas, "provision_new_directory", reject)
        with pytest.raises(nas.Failure, match="metadata"):
            nas.create_fixture(stack, fd, fixture, report)
        assert list(fixture.iterdir()) == [] and report["fixture"] == str(fixture)
        assert report["fixture_created"] is True and report["report_destination_verified"] is False
        untouched = {}
        with pytest.raises(nas.Failure, match="collision"):
            nas.create_fixture(stack, fd, fixture, untouched)
        assert untouched["fixture_created"] is False and "fixture" not in untouched


def test_fixture_root_is_searchable_but_not_listable(tmp_path, monkeypatch):
    import stat

    fixture = tmp_path / (nas.PREFIX + "searchable")
    report = {}

    def provision(stack, parent, name, uid, gid, mode):
        assert (uid, gid, mode) == (0, 0, 0o711)
        initial = os.stat(name, dir_fd=parent, follow_symlinks=False)
        assert stat.S_IMODE(initial.st_mode) == 0o700
        os.chmod(fixture, mode)
        fd = os.open(name, nas.DIRECTORY, dir_fd=parent)
        stack.callback(os.close, fd)
        return fd

    monkeypatch.setattr(nas, "provision_new_directory", provision)
    with ExitStack() as stack:
        parent_fd = nas.open_tree(stack, tmp_path)
        fd = nas.create_fixture(stack, parent_fd, fixture, report)
        info = os.fstat(fd)
        assert stat.S_IMODE(info.st_mode) == 0o711
        assert info.st_mode & stat.S_IXOTH
        assert not info.st_mode & stat.S_IROTH
        assert report["fixture_created"] is True
        assert report["report_destination_verified"] is True

    fixture.rmdir()


def test_parent_default_acl_refuses_creation(tmp_path, monkeypatch):
    fixture = tmp_path / (nas.PREFIX + "acl")
    report = {}
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        monkeypatch.setattr(os, "listxattr", lambda parent: ["system.posix_acl_default"])
        with pytest.raises(nas.Failure, match="default ACL"):
            nas.create_fixture(stack, fd, fixture, report)
    assert not fixture.exists() and not report.get("fixture_created")


@pytest.mark.parametrize("daemon", ["owns", "mismatch", "unreachable", "absent"])
def test_lost_create_response_and_missing_cidfile(tmp_path, monkeypatch, daemon):
    cid = "d" * 64
    role = "worker"
    name = f"{tmp_path.name}-{role}"
    calls = []
    def transport(args, operation, *rest, **options):
        calls.append(args)
        if args[0] == "ps":
            assert "--all" in args and "--no-trunc" in args and f"name=^/{name}$" in args
            if daemon == "unreachable":
                raise nas.Failure("daemon unavailable")
            return "" if daemon == "absent" else cid
        if args[0] == "inspect":
            assert args[-1] == cid
            return json.dumps({"id": cid, "name": "/" + name, "image": DIGEST,
                               "label": "someone-else" if daemon == "mismatch" else tmp_path.name})
        assert args == ["rm", "--force", cid]
        return cid
    monkeypatch.setattr(nas, "docker", transport)
    report = {"removed_containers": [], "container_cleanup": {}}
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        if daemon in ("owns", "absent"):
            nas.remove_container(fd, tmp_path, role, None, DIGEST, report)
        else:
            with pytest.raises(nas.Failure):
                nas.remove_container(fd, tmp_path, role, None, DIGEST, report)
    assert bool([call for call in calls if call[0] == "rm"]) == (daemon == "owns")
    state = report["container_cleanup"][role]["state"]
    assert state == {"owns": "removed", "mismatch": "identity_mismatch", "unreachable": "unverified",
                     "absent": "absent_at_lookup"}[daemon]


def test_unrecoverable_sync_error_invalidates_visible_pass(tmp_path, monkeypatch):
    import stat
    real_sync = os.fsync
    report = {"status": nas.PASS, "zero_exit_required": True}
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        nas.publish_report(fd, {"status": "INCOMPLETE"})
        after_replace = []
        def bad_storage(target):
            if after_replace:
                raise OSError("further sync unavailable")
            if stat.S_ISDIR(os.fstat(target).st_mode):
                assert json.loads((tmp_path / nas.REPORT_NAME).read_text())["status"] == nas.PASS
                after_replace.append(True)
                raise OSError("directory sync failed after publish")
            real_sync(target)
        monkeypatch.setattr(os, "fsync", bad_storage)
        nas.finish_report(fd, report)
    assert after_replace and report["status"] == nas.FAIL and report["retained_evidence_unverified"]
    assert not (tmp_path / nas.REPORT_NAME).exists()


def test_failed_create_unwinds_and_removes_daemon_committed_container(tmp_path, monkeypatch):
    fixture = tmp_path / (nas.PREFIX + "12ab")
    fixture.mkdir()
    for child in ("config", "data"):
        (fixture / child).mkdir()
    cid = "c" * 64
    daemon = {}
    def transport(args, operation, *other, **kwargs):
        if args[0] == "create":
            name = args[args.index("--name") + 1]
            daemon[cid] = {"id": cid, "image": DIGEST, "name": "/" + name, "label": fixture.name}
            raise nas.Failure("lost create response")
        if args[0] == "ps":
            assert f"name=^/{fixture.name}-worker$" in args
            return next(iter(daemon))
        if args[0] == "inspect":
            return json.dumps(daemon[args[-1]])
        assert args == ["rm", "--force", cid]
        del daemon[cid]
        return cid
    monkeypatch.setattr(nas, "docker", transport)
    # Exercise the real pinned path and cleanup callback with this harness user's
    # temp root. Production requires root-owned ancestors on the Docker host.
    walk = nas.open_tree
    monkeypatch.setattr(nas, "open_tree", lambda stack, path, trusted=False: walk(stack, path))
    report = {"roles": {}, "removed_containers": [], "container_cleanup": {}}
    with ExitStack() as stack:
        rootfd = walk(stack, tmp_path)
        fixturefd = walk(stack, fixture)
        children = {name: walk(stack, fixture / name) for name in ("config", "data")}
        with pytest.raises(nas.Failure, match="lost create response"):
            nas.run_containers(rootfd, fixturefd, fixture, children, {}, DIGEST, report)
    assert not daemon and not (fixture / "worker.cid").exists()
    assert report["removed_containers"] == [cid] and report["container_cleanup"]["worker"]["state"] == "removed"


def test_container_cleanup_captures_state_and_logs_before_force_remove(tmp_path, monkeypatch):
    cid = "e" * 64
    fixture = tmp_path / (nas.PREFIX + "diagnostics")
    fixture.mkdir()
    info = {
        "id": cid, "image": DIGEST, "label": fixture.name,
        "name": f"/{fixture.name}-api",
        "state": {"Status": "running", "Running": True, "OOMKilled": False,
                  "ExitCode": 0, "Error": "", "Pid": 4321},
    }
    calls = []
    def docker(args, operation, *other, **kwargs):
        calls.append(("docker", args[0]))
        if args[0] == "inspect":
            return json.dumps(info)
        if args[0] == "rm":
            return cid
        raise AssertionError(args)
    class Logs:
        returncode = 0
        stdout = "api startup line\\n"
        stderr = "uvicorn diagnostic\\n"
    def run(args, **kwargs):
        calls.append(("logs", args[3]))
        assert args[3] == "logs" and args[-1] == cid
        return Logs()
    monkeypatch.setattr(nas, "docker", docker)
    monkeypatch.setattr(nas.subprocess, "run", run)
    report = {"removed_containers": [], "container_cleanup": {}}
    with ExitStack() as stack:
        fd = nas.open_tree(stack, tmp_path)
        nas.remove_container(fd, fixture, "api", cid, DIGEST, report)
    assert calls == [("docker", "inspect"), ("logs", "logs"), ("docker", "rm")]
    record = report["container_cleanup"]["api"]
    assert record["pre_removal_state"]["OOMKilled"] is False
    assert record["pre_removal_state"]["Running"] is True
    assert "api startup line" in record["logs"]["stdout_tail"]
    assert "uvicorn diagnostic" in record["logs"]["stderr_tail"]
    assert record["state"] == "removed"


def test_docker_failure_retains_bounded_stderr(monkeypatch):
    class Result:
        returncode = 137
        stdout = ""
        stderr = "exec process was killed"
    monkeypatch.setattr(nas.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(nas.Failure, match=r"docker exited 137; stderr: exec process was killed"):
        nas.docker(["exec", "container", "python"], "API bootstrap")



def test_disposable_config_layout_is_preprovisioned(tmp_path, monkeypatch):
    calls = []
    def fake_new_dir(stack, parent, name, uid, gid, mode):
        assert (uid, gid, mode) == (nas.API, nas.GROUP, 0o2770)
        os.mkdir(name, mode=0o700, dir_fd=parent)
        fd = os.open(name, nas.DIRECTORY, dir_fd=parent)
        stack.callback(os.close, fd)
        calls.append(name)
        return fd
    monkeypatch.setattr(nas, "new_dir", fake_new_dir)
    config = tmp_path / "config"
    config.mkdir()
    with ExitStack() as stack:
        config_fd = nas.open_tree(stack, config)
        result = nas.provision_config_directories(stack, config_fd)
        assert tuple(result) == nas.CONFIG_DIRECTORIES
        assert all(nas.identity(os.fstat(fd)) == nas.identity((config / name).stat())
                   for name, fd in result.items())
    assert calls == ["reports", "backups", "logs", "home"]
    assert sorted(path.name for path in config.iterdir()) == ["backups", "home", "logs", "reports"]


def test_only_database_file_is_host_preprovisioned():
    assert nas.CONFIG_BOOTSTRAP_FILES == ("app.db",)


def test_disposable_config_bootstrap_files_are_preprovisioned(tmp_path, monkeypatch):
    monkeypatch.setattr(nas, "API", os.geteuid())
    monkeypatch.setattr(nas, "GROUP", os.getegid())
    config = tmp_path / "config"
    config.mkdir(mode=0o2770)
    config.chmod(0o2770)
    for name in nas.CONFIG_DIRECTORIES:
        child = config / name
        child.mkdir(mode=0o2770)
        child.chmod(0o2770)
    with ExitStack() as stack:
        config_fd = nas.open_tree(stack, config)
        records = nas.provision_config_files(stack, config_fd)
        assert set(records) == set(nas.CONFIG_BOOTSTRAP_FILES)
        assert all(nas.identity(os.stat(name, dir_fd=config_fd, follow_symlinks=False))
                   == records[name]["identity"] for name in nas.CONFIG_BOOTSTRAP_FILES)
    for name in nas.CONFIG_BOOTSTRAP_FILES:
        info = (config / name).stat()
        assert info.st_uid == nas.API and info.st_gid == nas.GROUP
        assert nas.stat.S_IMODE(info.st_mode) == 0o660
        assert info.st_size == 0 and info.st_nlink == 1


def test_config_bootstrap_refuses_existing_entry_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(nas, "API", os.geteuid())
    monkeypatch.setattr(nas, "GROUP", os.getegid())
    config = tmp_path / "config"
    config.mkdir(mode=0o2770)
    config.chmod(0o2770)
    for name in nas.CONFIG_DIRECTORIES:
        child = config / name
        child.mkdir(mode=0o2770)
        child.chmod(0o2770)
    original = config / "app.db"
    original.write_bytes(b"do-not-overwrite")
    with ExitStack() as stack:
        config_fd = nas.open_tree(stack, config)
        with pytest.raises(nas.Failure, match="unexpected entry"):
            nas.provision_config_files(stack, config_fd)
    assert original.read_bytes() == b"do-not-overwrite"
    assert not (config / "db-init.lock").exists()
    assert not (config / "media-mutation.lock").exists()


def test_config_file_creation_probe_covers_root_and_shared_subdirectories(tmp_path, monkeypatch):
    monkeypatch.setattr(nas, "GROUP", os.getegid())
    config = tmp_path / "config"
    config.mkdir(mode=0o2770)
    config.chmod(0o2770)
    for name in nas.CONFIG_DIRECTORIES:
        child = config / name
        child.mkdir(mode=0o2770)
        child.chmod(0o2770)
    original_open = os.open
    observed_creates = []

    def zfuse_open(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            observed_creates.append((os.fspath(path), flags, kwargs))
            assert os.fspath(path).startswith("/proc/self/fd/")
            assert kwargs.get("dir_fd") is None
            assert flags & os.O_RDWR
            assert flags & os.O_EXCL
            assert not flags & getattr(os, "O_NOFOLLOW", 0)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(nas.os, "open", zfuse_open)
    result = nas.probe_config_file_creation(config)
    expected = {"root", *nas.CONFIG_DIRECTORIES}
    assert set(result) == expected
    assert len(observed_creates) == len(expected)
    assert all(item["creation_path"] == "pinned_proc_fd" for item in result.values())
    assert all(item["created_fsynced_removed"] for item in result.values())
    assert sorted(path.name for path in config.iterdir()) == sorted(nas.CONFIG_DIRECTORIES)
    assert all(not list((config / name).iterdir()) for name in nas.CONFIG_DIRECTORIES)
