#!/usr/bin/env python3
"""Run maintenance acceptance only in a fresh disposable subtree of a local Docker host.

The operator must keep external writers out of that subtree through cleanup and recovery.
Only the fixture is mounted. Preserve its config, data and acceptance-report.json.
Acceptance requires PASS_MAINTENANCE_LIFECYCLE and a zero controller exit.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import stat
import subprocess
import sys
import time


API, WORKER, GROUP = 10001, 10002, 10000
SHA256 = r"sha256:[0-9a-f]{64}"
FULL_ID = r"[0-9a-f]{64}"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
PREFIX = "nfc-v16-maintenance-"
PASS = "PASS_MAINTENANCE_LIFECYCLE"
FAIL = "FAIL_MAINTENANCE_LIFECYCLE"
REPORT_NAME = "acceptance-report.json"
CONFIG = {
    "CONFIG_DIR": "/config", "DATA_MOUNT": "/data", "ALLOWED_ROOTS": "/data",
    "QUARANTINE_ROOT": "/data/.trash", "INITIAL_ADMIN_USERNAME": "fixture-admin",
    "MEDIA_ORGANIZER_EXECUTION_ENABLED": "true", "MEDIA_ORGANIZER_EXECUTION_MODE": "maintenance_window",
    "ALLOW_MUTATION": "true", "ALLOW_DELETE": "true", "MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK": "false",
    "NFC_SHARED_CONFIG_GID": str(GROUP),
}
GROUPS = {"mixed": {"P": 2, "V": 1}, "boundary": {"P": 200, "P_1": 1, "V": 1},
          "historical": {"P": 2, "V": 1}}


class Failure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


def validate_inputs(root, image, revision):
    require(root.startswith("/") and root != "/" and not root.startswith("//")
            and str(Path(root)) == root and ".." not in Path(root).parts
            and not any(c in root for c in ',"\r\n\x00'), "invalid absolute data root")
    repo = r"[a-z0-9][a-z0-9./:_-]*"
    require(re.fullmatch(f"({repo}@)?{SHA256}", image), "expected immutable image ID or repository digest")
    require(re.fullmatch(r"[0-9a-f]{40}", revision), "expected full 40-character candidate commit SHA")


def validate_image(info, reference, revision):
    require(re.fullmatch(SHA256, info["id"]) and info["revision"] == revision
            and not info["volumes"], "image identity, revision label or declared volumes mismatch")
    require(reference == info["id"] or reference in (info["digests"] or []),
            "requested image is absent from inspected image identities")
    return info["id"]


def identity(info):
    return [info.st_dev, info.st_ino]


def open_dir(stack, name, parent=None):
    fd = os.open(name, DIRECTORY, dir_fd=parent)
    stack.callback(os.close, fd)
    return fd


def open_tree(stack, path, trusted=False):
    fd = None
    for part in Path(path).parts:
        fd = open_dir(stack, part, fd)
        if trusted:
            info = os.fstat(fd)
            # A sticky root-owned parent (e.g. /tmp on a CI host) protects a
            # newly created root-owned child. Reject replaceable ancestors.
            require(info.st_uid == 0 and (not info.st_mode & 0o022 or info.st_mode & stat.S_ISVTX),
                    "data root has a replaceable ancestor")
    return fd


def check_binding(parent, name, child):
    named = os.stat(name, dir_fd=parent, follow_symlinks=False)
    require(stat.S_ISDIR(named.st_mode) and identity(named) == identity(os.fstat(child)),
            "fixture directory binding changed")


def create_fixture(stack, parent, path, report):
    report["fixture_created"] = False
    report["requested_fixture"] = str(path)
    require("system.posix_acl_default" not in os.listxattr(parent), "data root has an inherited default ACL")
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
    except FileExistsError:
        raise Failure("fixture name collision; preexisting directory untouched") from None
    report.update(fixture_created=True, fixture=str(path), report_destination_verified=False)
    fd = provision_new_directory(stack, parent, path.name, 0, 0, 0o700)
    report["report_destination_verified"] = True
    return fd


def new_dir(stack, parent, name, uid, gid, mode):
    os.mkdir(name, mode=0o700, dir_fd=parent)
    return provision_new_directory(stack, parent, name, uid, gid, mode)


CONFIG_DIRECTORIES = ("reports", "backups", "logs", "home")
CONFIG_BOOTSTRAP_FILES = ("app.db",)


def provision_config_directories(stack, config_fd):
    """Pre-provision the disposable shared config layout before API startup.

    Production startup validates these directories and refuses to repair
    incompatible existing entries. Creating them in the host controller keeps
    the fixture layout deterministic on NAS FUSE mounts.
    """
    return {
        name: new_dir(stack, config_fd, name, API, GROUP, 0o2770)
        for name in CONFIG_DIRECTORIES
    }


def provision_config_files(stack, config_fd):
    """Pre-create only app.db in a new fixture; runtime roles create lock files.

    The database file is provisioned by the host because API startup requires
    it before SQLite initialization. The dot-prefixed init and media locks are
    deliberately created by their owning application processes: on the target
    zfuse bind mount, host-created .db-init.lock was recorded on the host but
    returned ENOENT to API lstat during startup. O_EXCL, pinned dir_fd identity
    checks and fsync keep this limited to the disposable fixture.
    """
    expected_entries = set(CONFIG_DIRECTORIES)
    require(set(os.listdir(config_fd)) == expected_entries,
            "unexpected entry in new disposable config root")
    parent = os.fstat(config_fd)
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == API
            and parent.st_gid == GROUP and stat.S_IMODE(parent.st_mode) == 0o2770,
            "disposable config root identity or permissions mismatch")
    records = {}
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    for name in CONFIG_BOOTSTRAP_FILES:
        try:
            fd = os.open(name, flags, 0o600, dir_fd=config_fd)
        except FileExistsError:
            raise Failure(f"unexpected pre-existing config bootstrap file: {name}") from None
        stack.callback(os.close, fd)
        created = os.fstat(fd)
        require(stat.S_ISREG(created.st_mode) and created.st_uid == os.geteuid()
                and created.st_dev == parent.st_dev and created.st_nlink == 1,
                f"new config bootstrap file has unexpected initial identity: {name}")
        os.fchown(fd, API, GROUP)
        os.fchmod(fd, 0o660)
        os.fsync(fd)
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=config_fd, follow_symlinks=False)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == API and info.st_gid == GROUP
                and stat.S_IMODE(info.st_mode) == 0o660 and info.st_nlink == 1
                and identity(named) == identity(info),
                f"config bootstrap file identity or permissions mismatch: {name}")
        records[name] = {
            "identity": identity(info), "uid": info.st_uid, "gid": info.st_gid,
            "mode": oct(stat.S_IMODE(info.st_mode)), "size": info.st_size,
        }
    os.fsync(config_fd)
    return records


def probe_config_file_creation(config_root=Path("/config")):
    """Prove API/Worker can create, fsync and remove a private file in each config dir."""
    results = {}
    with ExitStack() as stack:
        root_fd = open_tree(stack, config_root)
        for label in CONFIG_DIRECTORIES:
            directory_fd = open_dir(stack, label, root_fd)
            directory = os.fstat(directory_fd)
            mode = stat.S_IMODE(directory.st_mode)
            require(stat.S_ISDIR(directory.st_mode) and directory.st_gid == GROUP
                    and (mode & 0o2070) == 0o2070 and (mode & 0o007) == 0,
                    f"config write-probe directory permissions mismatch: {label}")
            name = "nfc-v16-write-probe-" + secrets.token_hex(12)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
            except OSError as exc:
                raise Failure(
                    f"config O_EXCL create probe failed in {label}: {type(exc).__name__} errno={exc.errno}"
                ) from None
            expected = None
            try:
                info = os.fstat(file_fd)
                expected = identity(info)
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                        and info.st_gid == GROUP and stat.S_IMODE(info.st_mode) == 0o600
                        and info.st_nlink == 1,
                        f"config write-probe file identity or permissions mismatch: {label}")
                payload = b"nas-file-center-v16-config-write-probe"
                require(os.write(file_fd, payload) == len(payload),
                        f"short config write-probe write: {label}")
                os.fsync(file_fd)
                named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                require(stat.S_ISREG(named.st_mode) and identity(named) == expected,
                        f"config write-probe binding changed: {label}")
            finally:
                os.close(file_fd)
                if expected is not None:
                    try:
                        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        raise Failure(f"config write-probe entry disappeared before cleanup: {label}") from None
                    require(stat.S_ISREG(current.st_mode) and identity(current) == expected,
                            f"config write-probe cleanup binding changed; foreign entry preserved: {label}")
                    os.unlink(name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
            results[label] = {
                "directory_identity": identity(directory), "file_identity": expected,
                "uid": os.geteuid(), "gid": GROUP, "created_fsynced_removed": True,
            }
    return results


def provision_new_directory(stack, parent, name, uid, gid, mode):
    fd = open_dir(stack, name, parent)
    check_binding(parent, name, fd)
    info = os.fstat(fd)
    require(info.st_uid == 0 and not info.st_mode & 0o077 and info.st_dev == os.fstat(parent).st_dev,
            "new directory has unexpected ownership, mode or device")
    # An inherited ACL could grant access when group permissions are widened.
    if {"system.posix_acl_access", "system.posix_acl_default"} & set(os.listxattr(fd)):
        raise Failure("new fixture inherited an access or default ACL")
    os.fchown(fd, uid, gid)
    os.fchmod(fd, mode)
    check_binding(parent, name, fd)
    info = os.fstat(fd)
    require((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
            "filesystem did not preserve fixture permissions")
    return fd


def seed_case(data, case):
    if case == "historical":
        files = {"P [2 10B]/001.jpg": b"photo", "P1/cover.jpg": b"cover", "clip.mp4": b"clip"}
    elif case == "mixed":
        files = {"portrait.jpg": b"portrait", "second.jpg": b"second", "trailer.mp4": b"trailer"}
    elif case == "boundary":
        files = {f"photo-{i:03}.jpg": f"fixture photo {i}".encode() for i in range(201)}
        files["movie.mp4"] = b"fixture boundary movie"
    else:
        raise Failure("unknown disposable case")
    selection = data / case
    selection.mkdir(mode=0o750)
    unit = selection / "NO.001"
    unit.mkdir(mode=0o750)
    for name, content in files.items():
        path = unit / name
        if path.parent != unit:
            path.parent.mkdir(mode=0o750, exist_ok=True)
        with path.open("xb") as out:
            out.write(content)
    return unit


def inventory(unit):
    hashes, groups = Counter(), Counter()
    directories = []
    # Reject links and special files. Count every regular file, including
    # unexpected names/leftover stage artifacts, not just known extensions.
    def walk(directory, relative):
        for name in sorted(os.listdir(directory)):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            path = relative / name
            if stat.S_ISDIR(info.st_mode):
                with ExitStack() as nested:
                    sub = open_dir(nested, name, directory)
                    check_binding(directory, name, sub)
                    directories.append(str(path))
                    walk(sub, path)
            else:
                require(stat.S_ISREG(info.st_mode), "unexpected non-regular entry in fixture")
                fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(fd, "rb") as src:
                    require(identity(os.fstat(fd)) == identity(info), "fixture file changed while opening")
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: src.read(65536), b""):
                        digest.update(chunk)
                    hashes[digest.hexdigest()] += 1
                groups[str(path.parent)] += 1
    with ExitStack() as stack:
        walk(open_dir(stack, unit), Path("."))
    return {"hashes": dict(hashes), "count": sum(hashes.values()),
            "groups": dict(groups), "directories": directories}


def dispatch(settings, jid, fault=None):
    from app.batch import media_organizer_execute_jobs as execute
    from app.db import create_engine_and_session
    from app.tasks.context import JobContext
    from app.tasks.recovery import acquire_worker_ownership
    from app.worker import process_work_job, WorkerHeartbeatThread
    require(os.geteuid() != 0 and type(jid) is int and jid > 0, "nonroot Worker and positive job ID required")
    require(fault in (None, "publication", "cleanup"), "unknown simulated interruption")
    fired = []
    engine, factory = create_engine_and_session(settings.database_path)
    worker_id = "disposable-acceptance-worker"
    with ExitStack() as stack:
        stack.callback(engine.dispose)
        require(acquire_worker_ownership(engine, factory, worker_id), "cannot acquire real Worker lease")
        heartbeat = WorkerHeartbeatThread(engine, factory, worker_id)
        heartbeat.start()
        stack.callback(heartbeat.join, 15)
        stack.callback(heartbeat.stop_event.set)
        if fault == "publication":
            publish = execute.publish_frozen_stage
            def interrupt_publication(*args, **kwargs):
                publish(*args, **kwargs)
                fired.append("publication")
                raise RuntimeError("simulated acceptance interruption after real publication")
            stack.callback(setattr, execute, "publish_frozen_stage", publish)
            execute.publish_frozen_stage = interrupt_publication
        if fault == "cleanup":
            checkpoint = JobContext.checkpoint
            def interrupt_cleanup(context, **kwargs):
                result = checkpoint(context, **kwargs)
                if kwargs.get("checkpoint_data", {}).get("phase") == "cleanup-scanned-zero":
                    fired.append("cleanup")
                    raise RuntimeError("simulated acceptance interruption after durable zero scan")
                return result
            stack.callback(setattr, JobContext, "checkpoint", checkpoint)
            JobContext.checkpoint = interrupt_cleanup
        completed = process_work_job(settings, jid, session_factory=factory, engine=engine, worker_id=worker_id)
        require(fired == ([fault] if fault else []) and completed is (fault is None),
                f"Worker job {jid} did not reach expected outcome ({fault or 'completion'})")
    return {"job_id": jid, "dispatch_completed": completed, "lease_acquired": True, "interruption": fault}


def http(port, method, path, body=None, cookie=None):
    origin = f"http://127.0.0.1:{port}"
    conn = HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        headers = {"Origin": origin}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = conn.getresponse()
        result = {"status": response.status, "body": json.loads(response.read())}
        if path == "/api/auth/login":
            cookie_header = response.getheader("Set-Cookie") or ""
            result["cookie"] = cookie_header.partition(";")[0]
        return result
    finally:
        conn.close()


def run_case(case, unit, request, worker, snapshot, evidence):
    unit = str(unit)
    expected = GROUPS[case]
    evidence.update(complete=False, jobs=[], refusals=[], simulated_interruptions=[], recovery_jobs=[])
    def call(method, path, body=None, code=200):
        response = request(method, path, body)
        require(response["status"] == code, f"{method} {path}: expected {code}, received {response['status']}")
        return response["body"]
    def work(jid, fault=None):
        evidence["jobs"].append(worker(jid, fault))
        if fault:
            evidence["simulated_interruptions"].append(fault)
    def preview():
        path = "/api/media-organizer/previews"
        pid = call("POST", path, {"selection": str(Path(unit).parent)})["job_id"]
        work(pid)
        path = f"{path}/{pid}"
        result = call("GET", path)
        require(result["execution_mode"] == "maintenance_window" and result["requires_maintenance_window"] is True,
                "preview mode mismatch")
        rows = [r for r in result["units"] if r["unit"] == unit]
        require(len(rows) == 1, "preview missing exact disposable unit")
        return path, result, rows[0]
    def approve(path, **body):
        for label, extra, code in (("omitted", {}, 409), ("false", {"maintenance_window_confirmed": False}, 409),
                                   ("string", {"maintenance_window_confirmed": "true"}, 422)):
            call("POST", path, {**body, **extra}, code)
            evidence["refusals"].append({"path": path, "ack": label, "status": code})
        accepted = call("POST", path, {**body, "maintenance_window_confirmed": True})
        require(accepted["assurance_level"] == "maintenance_window"
                and accepted["namespace_exclusive_custody_proven"] is False, "incorrect approval assurance")
        return accepted["job_id"]
    before = evidence["before"] = snapshot()
    require(before["count"] == sum(expected.values()), "initial payload count mismatch")
    path, report, row = preview()
    require(row["status"] == "ready", "unit did not produce a ready plan")
    planned = {group["name"]: group["count"] for group in row["groups"]}
    require({name.partition(" [")[0]: count for name, count in planned.items()} == expected,
            "planned group sizes differ from expected")
    jid = approve(path + "/execute", unit=unit, confirmation=report["confirmation_tokens"][unit])
    # Every organizing shape must prove publication interruption and recovery.
    work(jid, "publication")
    jid = approve(f"/api/media-organizer/executions/{jid}/recover",
                  confirmation=f"RECOVER_MEDIA_ORGANIZER_EXECUTION_{jid}")
    evidence["recovery_jobs"].append({"phase": "execution", "job_id": jid})
    work(jid)
    base = f"/api/media-organizer/executions/{jid}"
    status = call("GET", base)
    require(status["manual_cleanup_required"] is True and status["finalized"] is False and status["cleanup"] is None,
            "independent cleanup was not pending")
    for suffix in ("cleanup-review", "cleanup-audit", "cleanup-plan"):
        review = call("GET", base + "/" + suffix)
        require(review["verification_scope"] == "worker_handoff_snapshot", "missing Worker cleanup handoff")
    cid = approve(base + "/cleanup", confirmation=review["confirmation"])
    # Exercise the cleanup-scanned-zero interruption and explicit recovery too.
    work(cid, "cleanup")
    token = call("GET", base)["cleanup"]["recovery_confirmation"]
    require(isinstance(token, str) and token, "missing cleanup recovery token")
    cid = approve(f"/api/media-organizer/cleanups/{cid}/recover", confirmation=token)
    evidence["recovery_jobs"].append({"phase": "cleanup", "job_id": cid})
    work(cid)
    final = call("GET", base)
    require(final["finalized"] is True and final["namespace_exclusive_custody_proven"] is False
            and final["assurance_level"] == "maintenance_window" and final["cleanup"]["status"] == "completed",
            "execution or cleanup evidence incomplete")
    _, _, row = preview()
    evidence["second_scan"] = {key: row[key] for key in ("needed_moves", "renamed_count")}
    require(row["status"] == "already_organized" and list(evidence["second_scan"].values()) == [0, 0],
            "canonical second scan still found changes")
    after = evidence["after"] = snapshot()
    require(after["hashes"] == before["hashes"] and after["count"] == before["count"], "payload mismatch")
    require(after["groups"] == planned and sorted(after["directories"]) == sorted(planned),
            "final file groups or directory inventory mismatch")
    evidence.update(complete=True, payload_multiset_equal=True, file_count_equal=True,
                    final_groups=planned, independent_cleanup=True,
                    namespace_exclusive_custody_proven=False, assurance_level=final["assurance_level"])


def runtime_status(process, uid):
    path = Path("/proc") / process / "status"
    fields = dict(line.split(":", 1) for line in path.read_text().splitlines() if ":" in line)
    values = {key: list(map(int, fields[key].split())) for key in ("Uid", "Gid", "Groups")}
    values.update({key: int(fields[key], 16) for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")})
    values["NoNewPrivs"] = int(fields["NoNewPrivs"])
    for name in ("uid_map", "gid_map"):
        maps = Path("/proc") / process / name
        values[name] = [list(map(int, line.split())) for line in maps.read_text().splitlines()]
        require(values[name] == [[0, 0, 4294967295]], f"unexpected {name} for {process}")
    require(values["Uid"] == [uid] * 4 and values["Gid"] == [GROUP] * 4
            and set(values["Groups"]) <= {GROUP} and values["NoNewPrivs"] == 1
            and all(values[k] == 0 for k in values if k.startswith("Cap")),
            f"runtime credentials or capabilities differ for {process}")
    return values


def mount_evidence(fd):
    entry = Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
    mount_id = next(line.split()[1] for line in entry if line.startswith("mnt_id:"))
    for record in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = record.split(" - ", 1)
        fields = left.split()
        if fields[0] == mount_id:
            return {"identity": identity(os.fstat(fd)), "read_only": bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY),
                    "mount_id": int(mount_id), "major_minor": fields[2], "filesystem": right.split()[0]}
    raise Failure("cannot identify pinned mount in procfs")


def attest(role, expected):
    uid = {"api": API, "worker": WORKER}[role]
    evidence = {"self": runtime_status("self", uid), "pid1": runtime_status("1", uid), "mounts": {}}
    with ExitStack() as stack:
        for path, readonly in (("/data", role == "api"), ("/config", False), ("/", True), ("/tmp", False)):
            fd = open_dir(stack, path)
            mount = mount_evidence(fd)
            require(mount["read_only"] == readonly, f"incorrect {role} mount mode on {path}")
            if path in expected:
                require(mount["identity"] == expected[path], f"incorrect {role} inode binding on {path}")
            evidence["mounts"][path] = mount
    return evidence


def probe_lock(settings):
    from app.tasks.media_mutation_lock import MediaMutationLockBusy, media_mutation_lock, _LOCK_NAME
    try:
        with media_mutation_lock(settings, blocking=False):
            return {"locked": True, "identity": identity((settings.config_dir / _LOCK_NAME).stat())}
    except MediaMutationLockBusy:
        return {"busy": True}


def in_container(req):
    role, op = req["role"], req["op"]
    runtime = attest(role, req["bindings"])
    if op == "attest":
        return runtime
    if role == "api":
        if op == "config-probe":
            return probe_config_file_creation(Path("/config"))
        if op == "bootstrap":
            deadline = time.monotonic() + 15
            while not Path("/tmp/nfc-bootstrap").exists() and time.monotonic() < deadline:
                time.sleep(.1)
            with open("/tmp/nfc-bootstrap", "w") as pipe:
                pipe.write(req["password"] + "\n")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if http(8080, "GET", "/health")["status"] == 200:
                        return {"ready": True}
                except OSError:
                    pass
                time.sleep(.5)
            raise Failure("API failed to start after bootstrap")
        require(op == "http", "unrecognized API action")
        return http(8080, req["method"], req["path"], req.get("body"), req.get("cookie"))
    from app.config import Settings
    settings = Settings(_env_file=None)
    if op == "config-probe":
        return probe_config_file_creation(settings.config_dir)
    if op == "lock":
        return probe_lock(settings)
    if op == "dispatch":
        return dispatch(settings, req["jid"], req.get("fault"))
    case = req["case"]
    require(case in GROUPS, "unknown case")
    unit = settings.data_mount / case / "NO.001"
    if op == "seed":
        return str(seed_case(settings.data_mount, case))
    if op == "inventory":
        return inventory(unit)
    require(op == "strict-refusal", "unrecognized Worker action")
    from app.batch.media_organizer_authority import check_api_eligibility
    from app.batch.media_organizer_custody import NamespaceCustodyUnavailable
    strict = settings.model_copy(update={"media_organizer_execution_mode": "strict",
                                         "media_organizer_namespace_quiescence_ack": True})
    try:
        check_api_eligibility(strict, unit, (unit,))
    except NamespaceCustodyUnavailable:
        return {"strict_custody_refused": True}
    raise Failure("strict production issuer unexpectedly granted custody")


# PID 1 does not import the application or touch the mounts until both runtime
# boundaries have been verified. The API bootstrap secret only crosses stdin
# and an API-owned tmpfs FIFO. It never enters Docker's stored configuration.
API_START = """import os
os.mkfifo('/tmp/nfc-bootstrap', 0o600)
with open('/tmp/nfc-bootstrap') as pipe:
    password = pipe.readline().strip()
os.unlink('/tmp/nfc-bootstrap')
if not password:
    raise SystemExit(2)
os.environ['INITIAL_ADMIN_PASSWORD'] = password
import uvicorn
uvicorn.run('app.main:app', host='127.0.0.1', port=8080, access_log=False)
"""
WORKER_START = "import signal; signal.pause()"
RPC = """import json, sys
request, source = json.load(sys.stdin)
module = {'__name__': 'nfc_acceptance_driver'}
exec(compile(source, '<acceptance-driver>', 'exec'), module)
try:
    result = {'value': module['in_container'](request)}
except Exception as error:
    result = {'failure': str(error) if isinstance(error, module['Failure']) else type(error).__name__}
print(json.dumps(result))
"""
LOCK_HOLDER = """import json, sys
from app.config import Settings
from app.tasks.media_mutation_lock import media_mutation_lock, _LOCK_NAME
settings = Settings(_env_file=None)
with media_mutation_lock(settings, blocking=False):
    st = (settings.config_dir / _LOCK_NAME).stat()
    print(json.dumps([st.st_dev, st.st_ino]), flush=True)
    sys.stdin.buffer.read(1)
"""
IMAGE_INFO = ('{"id":{{json .ID}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
              '"volumes":{{json .Config.Volumes}},"digests":{{json .RepoDigests}}}')
CONTAINER_INFO = ('{"id":{{json .ID}},"name":{{json .Name}},"image":{{json .Image}},'
                  '"label":{{json (index .Config.Labels "nfc.v16.maintenance-fixture")}},'
                  '"mounts":{{json .Mounts}},"host":{{json .HostConfig}},"user":{{json .Config.User}},'
                  '"state":{{json .State}}}')


def docker(args, operation, data=None, timeout=90):
    try:
        result = subprocess.run([*DOCKER, *args], input=data, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failure(f"{operation}: Docker unavailable or timed out ({type(exc).__name__})") from None
    if result.returncode:
        detail = (result.stderr or "").strip()
        suffix = f"; stderr: {detail[-2000:]}" if detail else ""
        raise Failure(f"{operation}: docker exited {result.returncode}{suffix}")
    return result.stdout.strip()


def container_command(image, fixture, role):
    uid = {"api": API, "worker": WORKER}[role]
    name = fixture.name
    args = ["create", "--pull=never", "--cidfile", str(fixture / (role + ".cid")),
            "--name", f"{name}-{role}", "--label", f"nfc.v16.maintenance-fixture={name}",
            "--entrypoint", "python", "--read-only", "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", f"{uid}:{GROUP}", "--no-healthcheck",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,mode=1777,size=64m",
            "--mount", f"type=bind,src={fixture}/config,dst=/config",
            "--mount", f"type=bind,src={fixture}/data,dst=/data" + (",readonly" if role == "api" else "")]
    for key, value in CONFIG.items():
        args.extend(["--env", f"{key}={value}"])
    args.extend([image, "-c", API_START if role == "api" else WORKER_START])
    return args


def verify_container(info, cid, image, fixture, role):
    require(info["id"] == cid and info["image"] == image and info["label"] == fixture.name
            and info["name"] == f"/{fixture.name}-{role}", f"incorrect {role} container identity")
    host = info["host"]
    require(info["user"] == f"{API if role == 'api' else WORKER}:{GROUP}"
            and host["ReadonlyRootfs"] is True and host["NetworkMode"] == "none"
            and host["Privileged"] is False and host["CapDrop"] == ["ALL"] and not host["CapAdd"]
            and not host["PortBindings"] and not host["GroupAdd"]
            and host["SecurityOpt"] in (["no-new-privileges"], ["no-new-privileges=true"])
            and set(host["Tmpfs"]) == {"/tmp"}, f"unexpected {role} Docker security configuration")
    binds = {}
    for mount in info["mounts"]:
        if mount["Type"] == "tmpfs" and mount["Destination"] == "/tmp":
            continue
        require(mount["Type"] == "bind", "unexpected extra container mount")
        binds[mount["Destination"]] = [mount["Source"], mount["RW"]]
    require(binds == {"/data": [str(fixture / "data"), role == "worker"],
                      "/config": [str(fixture / "config"), True]}, f"unexpected {role} bind mounts")
    return {"id": cid, "name": info["name"], "image": image, "user": info["user"], "binds": binds,
            "network": host["NetworkMode"], "readonly_root": True, "tmpfs": host["Tmpfs"]}


def wait_for_lock_holder(reader, timeout):
    with selectors.DefaultSelector() as selector:
        selector.register(reader, selectors.EVENT_READ)
        require(selector.select(timeout), "API did not acquire the config lock")


def lock_check(holder_command, try_worker_lock, env=None):
    with subprocess.Popen(holder_command, env=env,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as holder:
        try:
            wait_for_lock_holder(holder.stdout, 45)
            line = holder.stdout.readline()
            require(line, "API failed to hold shared config lock")
            held = json.loads(line)
            require(try_worker_lock() == {"busy": True}, "Worker entered while API held production lock")
        finally:
            holder.stdin.close()
            try:
                holder.wait(timeout=15)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait()
        require(holder.returncode == 0, "API failed to release config lock")
    require(try_worker_lock() == {"locked": True, "identity": held}, "Worker failed lock handoff")
    return {"worker_refused_while_api_holds": True, "worker_acquired_after_release": True, "lock_identity": held}


def remove_container(fixturefd, fixture, role, cid, image, report):
    name = f"{fixture.name}-{role}"
    record = report["container_cleanup"][role] = {"name": name, "state": "unverified"}
    if not cid:
        try:
            fd = os.open(role + ".cid", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fixturefd)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd) as handle:
                cid = handle.read(128).strip()
        if not cid or not re.fullmatch(FULL_ID, cid):
            # A daemon may commit a create before its client writes the cidfile.
            # A successful empty query distinguishes absence from daemon failure.
            cid = docker(["ps", "--all", "--no-trunc", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
                         f"resolve uncertain {role} creation")
            if not cid:
                record["state"] = "absent_at_lookup"
                return
    require(re.fullmatch(FULL_ID, cid), "cleanup lacks a unique full container ID")
    record["id"] = cid
    info = json.loads(docker(["inspect", "--type", "container", "--format", CONTAINER_INFO, cid], "cleanup identity"))
    if (info["id"], info["image"], info["label"], info["name"]) != (cid, image, fixture.name, "/" + name):
        record["state"] = "identity_mismatch"
        raise Failure(f"cleanup {role} container identity mismatch")
    state = info.get("state") or {}
    record["pre_removal_state"] = {
        key: state.get(key) for key in
        ("Status", "Running", "Paused", "Restarting", "OOMKilled", "Dead",
         "ExitCode", "Error", "StartedAt", "FinishedAt", "Pid")
    }
    # Preserve bounded stdout/stderr before --force destroys the only live
    # source of startup diagnostics. In particular, a later SIGKILL event
    # caused by this cleanup must not be mistaken for an OOM root cause.
    try:
        logs = subprocess.run([*DOCKER, "logs", "--timestamps", "--tail", "250", cid],
                              capture_output=True, text=True, timeout=30, check=False)
        record["logs"] = {
            "exit_code": logs.returncode,
            "stdout_tail": logs.stdout[-12000:],
            "stderr_tail": logs.stderr[-12000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        record["logs_capture_error"] = type(exc).__name__
    docker(["rm", "--force", cid], f"remove disposable {role}")
    report["removed_containers"].append(cid)
    record["state"] = "removed"


def run_containers(rootfd, fixturefd, fixture, childfds, config_subdirs, image, report):
    source = Path(__file__).read_text(encoding="utf-8")
    bindings = {"/" + name: identity(os.fstat(fd)) for name, fd in childfds.items()}
    ids = {}
    def check_paths():
        with ExitStack() as verification:
            actual = open_tree(verification, fixture.parent, trusted=True)
            require(identity(os.fstat(actual)) == identity(os.fstat(rootfd)), "data root binding changed")
            check_binding(actual, fixture.name, fixturefd)
            for name, fd in childfds.items():
                check_binding(fixturefd, name, fd)
            for name, fd in config_subdirs.items():
                check_binding(childfds["config"], name, fd)
            for name, record in report.get("config_files", {}).items():
                named = os.stat(name, dir_fd=childfds["config"], follow_symlinks=False)
                require(stat.S_ISREG(named.st_mode) and identity(named) == record["identity"],
                        f"config bootstrap file binding changed: {name}")
    def remove(role):
        remove_container(fixturefd, fixture, role, ids.get(role), image, report)
    def rpc(role, op, **args):
        req = {**args, "role": role, "op": op, "bindings": bindings}
        data = docker(["exec", "-i", ids[role], "python", "-c", RPC], f"{role} {op}",
                      json.dumps([req, source]), timeout=1200 if op == "dispatch" else 120)
        response = json.loads(data)
        if "failure" in response:
            raise Failure(f"{role} {op}: {response['failure']}")
        return response["value"]
    with ExitStack() as cleanup:
        for role in ("worker", "api"):
            check_paths()
            cleanup.callback(remove, role)
            raw = docker(container_command(image, fixture, role), f"create {role}")
            require(re.fullmatch(FULL_ID, raw), "Docker returned invalid container ID")
            ids[role] = raw
            info = json.loads(docker(["inspect", "--type", "container", "--format", CONTAINER_INFO, raw],
                                     f"inspect {role}"))
            evidence = report["roles"][role] = verify_container(info, raw, image, fixture, role)
            check_paths()
            docker(["start", raw], f"start {role}")
            evidence["runtime"] = rpc(role, "attest")
        check_paths()
        password = secrets.token_urlsafe(36)
        rpc("api", "bootstrap", password=password)
        report["config_write_probes"] = {
            "api": rpc("api", "config-probe"),
            "worker": rpc("worker", "config-probe"),
        }
        report["cooperative_lock"] = lock_check([*DOCKER, "exec", "-i", ids["api"], "python", "-c", LOCK_HOLDER],
                                                lambda: rpc("worker", "lock"))
        def request(method, path, body=None):
            return rpc("api", "http", method=method, path=path, body=body, cookie=cookie)
        cookie = None
        denied = request("POST", "/api/media-organizer/previews", {"selection": "/data/mixed"})
        require(denied["status"] == 401, "API accepted unauthenticated preview")
        report["unauthenticated_status"] = denied["status"]
        login = request("POST", "/api/auth/login", {"username": CONFIG["INITIAL_ADMIN_USERNAME"], "password": password})
        require(login["status"] == 200 and login.get("cookie"), "disposable admin login failed")
        cookie = login["cookie"]
        for case in GROUPS:
            evidence = report["cases"][case] = {"complete": False}
            unit = rpc("worker", "seed", case=case)
            require(unit == f"/data/{case}/NO.001", "incorrect case unit")
            require(rpc("worker", "strict-refusal", case=case) == {"strict_custody_refused": True},
                    "missing strict issuer refusal")
            evidence["strict_custody_refused"] = True
            run_case(case, unit, request, lambda jid, fault=None: rpc("worker", "dispatch", jid=jid, fault=fault),
                     lambda: rpc("worker", "inventory", case=case), evidence)
        check_paths()


def publish_report(directory, report):
    # Only the fully written, file-synced document receives the public name.
    temporary = ".acceptance-report-" + secrets.token_hex(12) + ".tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as evidence:
            json.dump(report, evidence, sort_keys=True, indent=2)
            evidence.write("\n")
            evidence.flush()
            os.fsync(evidence.fileno())
        os.replace(temporary, REPORT_NAME, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def finish_report(directory, report):
    try:
        publish_report(directory, report)
        return
    except (OSError, KeyboardInterrupt) as exc:
        report.update(status=FAIL, report_write_failure=str(exc) or type(exc).__name__)
    try:
        publish_report(directory, report)
    except (OSError, KeyboardInterrupt) as exc:
        report["retained_evidence_unverified"] = str(exc) or type(exc).__name__
        # If the first replace succeeded but its directory sync and the repair
        # both failed, invalidate a readable PASS even on partly failing storage.
        try:
            fd = os.open(REPORT_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, encoding="utf-8") as existing:
                retained = json.load(existing)
            if retained.get("status") == PASS:
                os.unlink(REPORT_NAME, dir_fd=directory)
                os.fsync(directory)
        except (OSError, ValueError, KeyboardInterrupt) as invalidation:
            report["retained_evidence_invalidation_unverified"] = str(invalidation) or type(invalidation).__name__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-root", required=True, help="existing absolute media mount path on this host")
    parser.add_argument("--image", required=True, help="already loaded image ID or repository digest")
    parser.add_argument("--candidate-sha", required=True, help="full org.opencontainers.image.revision expected")
    args = parser.parse_args(argv)
    report = {"status": FAIL, "zero_exit_required": True, "candidate_sha": args.candidate_sha,
              "requested_image": args.image, "roles": {}, "cases": {}, "removed_containers": [], "container_cleanup": {},
              "namespace_exclusive_custody_proven": False, "release_ready": False,
              "limits": ["External writers must stay paused throughout execution, cleanup, and recovery.",
                         "Interruptions are simulated after real production publication and cleanup checkpoints.",
                         "Storage evidence applies only to this newly created fixture and its host mount."]}
    fixturefd = None
    with ExitStack() as stack:
        try:
            validate_inputs(args.data_root, args.image, args.candidate_sha)
            require(os.geteuid() == 0, "root host controller required")
            root = Path(args.data_root)
            rootfd = open_tree(stack, root, trusted=True)
            require(not os.fstatvfs(rootfd).f_flag & os.ST_RDONLY, "data root is read-only")
            report["data_root"] = {"path": str(root), **mount_evidence(rootfd)}
            try:
                image_info = json.loads(docker(["image", "inspect", "--format", IMAGE_INFO, args.image], "inspect image"))
            except Failure as exc:
                raise Failure(f"{exc}; load the exact labeled candidate with docker load or pull its immutable "
                              "repository digest into this host's Docker daemon, then rerun") from None
            image = validate_image(image_info, args.image, args.candidate_sha)
            report["image"] = image_info
            fixture = root / (PREFIX + secrets.token_hex(12))
            fixturefd = create_fixture(stack, rootfd, fixture, report)
            publish_report(fixturefd, {**report, "status": "INCOMPLETE"})
            config_fd = new_dir(stack, fixturefd, "config", API, GROUP, 0o2770)
            data_fd = new_dir(stack, fixturefd, "data", WORKER, GROUP, 0o750)
            config_subdirs = provision_config_directories(stack, config_fd)
            report["config_files"] = provision_config_files(stack, config_fd)
            report["config_layout"] = {
                name: {
                    "identity": identity(os.fstat(fd)),
                    "uid": os.fstat(fd).st_uid,
                    "gid": os.fstat(fd).st_gid,
                    "mode": oct(stat.S_IMODE(os.fstat(fd).st_mode)),
                }
                for name, fd in config_subdirs.items()
            }
            children = {"config": config_fd, "data": data_fd}
            run_containers(rootfd, fixturefd, fixture, children, config_subdirs, image, report)
            require(set(report["cases"]) == set(GROUPS) and all(r.get("complete") for r in report["cases"].values())
                    and len(report["removed_containers"]) == 2, "case or container cleanup evidence incomplete")
            report["status"] = PASS
        except (Exception, KeyboardInterrupt) as exc:
            report["failure"] = str(exc) if isinstance(exc, (OSError, Failure)) else type(exc).__name__
        if fixturefd is not None:
            finish_report(fixturefd, report)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["status"] == PASS else 2


if __name__ == "__main__":
    import signal
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
