#!/usr/bin/env python3
"""Opt-in local NAS permission test confined to a new synthetic Worker unit."""

import argparse
from contextlib import ExitStack
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess

WORKER = 10002
API = 10001
SHARED = 10000
FOREIGN = 65534
ROLES = {
    "worker": (WORKER, SHARED, False),
    "api-rw": (API, SHARED, False),
    "api-ro": (API, SHARED, True),
    "foreign-shared": (FOREIGN, SHARED, False),
    "foreign-unrelated": (FOREIGN, FOREIGN, False),
}
FILES = {name: f"v16 synthetic {name}\n".encode("ascii") for name in ("write", "unlink", "rename")}
DIRECTORY = "rmdir"
LABEL = "nfc.v16.permission-fixture"
PREFIX = "nfc-v16-worker-permission-"
MAP = [[0, 0, 4294967295]]
ABSENT_ACL_ERRNOS = {getattr(errno, name) for name in ("ENODATA", "ENOATTR") if hasattr(errno, name)}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
PATH_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
TIMEOUT = 30
CONTAINER_ID = re.compile(r"[a-f0-9]{64}")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
CONTAINER_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")

# Request only the properties used by the controller. Never request Config.Env.
INSPECT_FORMAT = r"""
{
  "id": {{json .ID}}, "name": {{json .Name}}, "image": {{json .Image}},
  "running": {{json .State.Running}}, "pid": {{json .State.Pid}},
  "user": {{json .Config.User}}, "entrypoint": {{json .Config.Entrypoint}},
  "command": {{json .Config.Cmd}}, "workdir": {{json .Config.WorkingDir}},
  "healthcheck": {{json .Config.Healthcheck}},
  "userns": {{json .HostConfig.UsernsMode}}, "group_add": {{json .HostConfig.GroupAdd}},
  "privileged": {{json .HostConfig.Privileged}}, "cap_add": {{json .HostConfig.CapAdd}},
  "cap_drop": {{json .HostConfig.CapDrop}}, "security": {{json .HostConfig.SecurityOpt}},
  "read_only_root": {{json .HostConfig.ReadonlyRootfs}}, "network": {{json .HostConfig.NetworkMode}},
  "label": {{json (index .Config.Labels "nfc.v16.permission-fixture")}},
  "mounts": [
    {{- range $i, $m := .Mounts -}}
      {{- if $i }},{{ end -}}
      {"type": {{json $m.Type}}, "source": {{json $m.Source}},
       "destination": {{json $m.Destination}}, "rw": {{json $m.RW}}}
    {{- end -}}
  ]
}
"""


class Failure(Exception):
    def __init__(self, category, *, role=None, operation=None, number=None, exit_code=None):
        super().__init__(category)
        self.category = category
        self.details = {"category": category}
        if role is not None:
            self.details["role"] = role
        if operation is not None:
            self.details["operation"] = operation
        if number is not None:
            self.details["errno"] = number
            self.details["errno_name"] = errno.errorcode.get(number, "UNKNOWN")
        if exit_code is not None:
            self.details["exit_code"] = exit_code


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise Failure("INVALID_ARGUMENTS")


def _args(argv):
    parser = Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-root", required=True, help="Existing absolute host data root")
    parser.add_argument("--worker-container", default="nas-file-center-worker")
    parser.add_argument("--api-container", default="nas-file-center-api")
    parser.add_argument("--create-disposable-fixture", action="store_true", required=True)
    args = parser.parse_args(argv)
    root = args.data_root
    if (not root.startswith("/") or root.startswith("//") or root == "/"
            or str(Path(root)) != root or ".." in Path(root).parts
            or any(char in root for char in ',"\r\n\0')):
        raise Failure("INVALID_DATA_ROOT")
    if (args.worker_container == args.api_container
            or not all(CONTAINER_NAME.fullmatch(name) for name in (args.worker_container, args.api_container))):
        raise Failure("INVALID_CONTAINER_NAMES")
    return args


def _require_no_acl(fd):
    for kind in ("access", "default"):
        try:
            os.getxattr(fd, f"system.posix_acl_{kind}")
        except OSError as exc:
            if exc.errno in ABSENT_ACL_ERRNOS:
                continue
            raise Failure("ACL_METADATA_UNAVAILABLE", operation=kind, number=exc.errno) from None
        raise Failure("UNEXPECTED_ACL", operation=kind)


def _identity(info):
    return [info.st_dev, info.st_ino]


def _read_only(fd):
    return bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY)


def _own_fd(stack, fd):
    stack.callback(os.close, fd)
    return fd


def _pin_data_root(stack, root):
    fd = None
    path = Path("/")
    for depth, part in enumerate(Path(root).parts):
        try:
            fd = _own_fd(stack, os.open(part, DIR_FLAGS, dir_fd=fd))
            path /= part
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            sticky_tmp = path == Path("/tmp") and mode == 0o1777
            if info.st_uid != 0 or (mode & 0o022 and not sticky_tmp):
                raise Failure("UNTRUSTED_DATA_ANCESTOR")
            _require_no_acl(fd)
        except (Failure, OSError) as exc:
            failure = _sanitized_error(exc)
            failure.details.update(path_role="data_ancestor", directory_depth=depth)
            raise failure from None
    if mode != 0o755:
        raise Failure("UNEXPECTED_DATA_ROOT_MODE")
    if _read_only(fd):
        raise Failure("DATA_ROOT_READ_ONLY")
    return fd


def _verify_binding(parent_fd, name, fd):
    info = os.fstat(fd)
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(named.st_mode) or _identity(named) != _identity(info):
        raise Failure("DIRECTORY_BINDING_CHANGED")
    return info


def _create_directory(stack, parent_fd, name, uid, report=None):
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        if report is not None:
            report["fixture"] = name
        fd = _own_fd(stack, os.open(name, DIR_FLAGS, dir_fd=parent_fd))
        info = _verify_binding(parent_fd, name, fd)
        if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_dev != os.fstat(parent_fd).st_dev or _read_only(fd)):
            raise Failure("UNEXPECTED_NEW_DIRECTORY")
        _require_no_acl(fd)
        os.fchown(fd, uid, SHARED)
        os.fchmod(fd, 0o750)
        info = _verify_binding(parent_fd, name, fd)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, SHARED, 0o750):
            raise Failure("FIXTURE_METADATA_MISMATCH")
        _require_no_acl(fd)
        return fd
    except (Failure, OSError) as exc:
        failure = _sanitized_error(exc)
        failure.details["stage"] = "fixture_parent" if report is not None else "fixture_unit"
        raise failure from None


def _docker(args, operation, source=None):
    try:
        result = subprocess.run(
            [*DOCKER, *args], input=source, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        raise Failure("DOCKER_TIMEOUT", operation=operation) from None
    except OSError as exc:
        raise Failure("DOCKER_UNAVAILABLE", operation=operation, number=exc.errno) from None
    if result.returncode:
        raise Failure("DOCKER_COMMAND_FAILED", operation=operation, exit_code=result.returncode)
    return result.stdout.strip()


def _json_object(text, category):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        raise Failure(category) from None
    if not isinstance(value, dict):
        raise Failure(category)
    return value


def _inspect(container):
    return _json_object(
        _docker(["inspect", "--type", "container", "--format", INSPECT_FORMAT, container], "inspect"),
        "INVALID_CONTAINER_INSPECTION",
    )


def _groups_match(groups):
    return groups is None or (isinstance(groups, list) and all(group == str(SHARED) for group in groups))


def _permissions_match(info):
    return (
        info.get("privileged") is False and info.get("cap_drop") == ["ALL"]
        and info.get("cap_add") in (None, []) and _groups_match(info.get("group_add"))
        and info.get("userns") in ("", "host")
    )


def _verify_live(info, name, root, uid):
    mounts = [mount for mount in info["mounts"] if mount["destination"] == "/data"]
    if (
        info.get("name") != f"/{name}" or not CONTAINER_ID.fullmatch(info.get("id", ""))
        or info.get("running") is not True or type(info.get("pid")) is not int or info["pid"] <= 0
        or info.get("user") not in (str(uid), f"{uid}:{SHARED}") or not _permissions_match(info)
        or mounts != [{"type": "bind", "source": root, "destination": "/data", "rw": False}]
    ):
        raise Failure("LIVE_CONTAINER_MISMATCH")


def _verify_image(image):
    if not IMAGE_ID.fullmatch(image):
        raise Failure("INVALID_WORKER_IMAGE_ID")
    image_format = r'{"id": {{json .ID}}, "volume_count": {{len .Config.Volumes}}}'
    info = _json_object(
        _docker(["image", "inspect", "--format", image_format, image], "inspect_image"),
        "INVALID_IMAGE_INSPECTION",
    )
    if info != {"id": image, "volume_count": 0}:
        raise Failure("UNSAFE_WORKER_IMAGE")


def _create_args(image, fixture, source, role, uid, gid, read_only):
    mount = f"type=bind,src={source},dst=/probe"
    if read_only:
        mount += ",readonly"
    return [
        "create", "--pull=never", "--read-only", "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--no-healthcheck", "--init=false",
        "--user", f"{uid}:{gid}", "--entrypoint", "python3", "--workdir", "/",
        "--name", f"{fixture}-{role}", "--label", f"{LABEL}={fixture}", "--mount", mount,
        "-i", image, "-I", "-S", "-B", "-",
    ]


def _verify_temporary(info, cid, image, fixture, source, role, uid, gid, read_only):
    mount = {"type": "bind", "source": source, "destination": "/probe", "rw": not read_only}
    if (
        info.get("id") != cid or info.get("name") != f"/{fixture}-{role}" or info.get("label") != fixture
        or info.get("image") != image or info.get("running") is not False or info.get("pid") != 0
        or info.get("user") != f"{uid}:{gid}" or not _permissions_match(info)
        or info.get("security") not in (["no-new-privileges"], ["no-new-privileges=true"])
        or info.get("read_only_root") is not True or info.get("network") != "none"
        or info.get("mounts") != [mount] or info.get("entrypoint") != ["python3"]
        or info.get("command") != ["-I", "-S", "-B", "-"] or info.get("workdir") != "/"
        or info.get("healthcheck") != {"Test": ["NONE"]}
    ):
        raise Failure("TEMPORARY_CONTAINER_MISMATCH", role=role)


def _remove_temporary(cid, role):
    try:
        _docker(["rm", "--force", cid], "remove_temporary")
    except (Failure, KeyboardInterrupt) as exc:
        detail = _sanitized_error(exc).details
        raise Failure(
            "TEMPORARY_CLEANUP_INCOMPLETE", role=role, operation=detail.get("operation"),
            exit_code=detail.get("exit_code"),
        ) from None


def _expected_process(uid, gid):
    return {"uids": [uid] * 4, "gids": [gid] * 4, "groups": [gid],
            "uid_map": MAP, "gid_map": MAP, "capabilities": [0, 0, 0], "no_new_privs": 1}


def _expected_runtime(uid, gid, identity, read_only, live):
    expected = {"self": _expected_process(uid, gid), "identity": identity, "read_only": read_only}
    if live:
        expected["pid1"] = _expected_process(uid, gid)
    return expected


def _is_denial(number, read_only, mutation):
    return number in (errno.EACCES, errno.EPERM) or (read_only and mutation and number == errno.EROFS)


def _make_probe(role, expected, live=False):
    settings = {
        "role": role, "expected": expected, "mount": "/data" if live else "/probe",
        "files": FILES, "directory": DIRECTORY, "worker": WORKER, "shared": SHARED,
        "denials": [errno.EACCES, errno.EPERM],
        "mutation_denials": [number for number in (errno.EACCES, errno.EPERM, errno.EROFS)
                             if _is_denial(number, expected["read_only"], True)],
    }
    return f"SETTINGS = {settings!r}\n{PROBE_SOURCE}"


SHARED_MUTATIONS = {"write", "unlink", "rename", "rmdir", "mkdir", "create"}
PROBE_FAILURES = {
    "RUNTIME_ATTESTATION_MISMATCH", "RUNTIME_METADATA_FAILED", "WORKER_PRIMITIVE_FAILED",
    "CANARY_PREREQUISITE_FAILED", "UNEXPECTED_MUTATION", "UNEXPECTED_READ", "UNEXPECTED_TRAVERSAL",
    "UNEXPECTED_OPERATION_ERRNO",
}
PROBE_OPERATIONS = SHARED_MUTATIONS | {
    "traverse", "read", "identity", "canaries", "create_file", "write_file", "file_fsync",
    "readback", "create_directory", "owned_cleanup", "directory_fsync",
}


def _call_probe(args, role, expected, live=False):
    result = _json_object(
        _docker(args, "execute_probe", _make_probe(role, expected, live)), "INVALID_PROBE_REPORT",
    )
    status = result.get("status")
    if isinstance(status, str) and status in PROBE_FAILURES:
        operation = result.get("operation")
        number = result.get("errno")
        raise Failure(
            status, role=role, operation=operation if isinstance(operation, str) and operation in PROBE_OPERATIONS else None,
            number=number if type(number) is int else None,
        )
    if status != "PASS" or result.get("attestation") != expected:
        raise Failure("RUNTIME_ATTESTATION_MISMATCH", role=role)
    denials = result.get("denials")
    if live or role == "worker":
        expected_ops = set()
    else:
        expected_ops = {"traverse", "read", "create"} if role == "foreign-unrelated" else SHARED_MUTATIONS
    if (
        not isinstance(denials, dict) or denials.keys() != expected_ops
        or any(type(number) is not int or not _is_denial(number, expected["read_only"], op not in ("traverse", "read"))
               for op, number in denials.items())
    ):
        raise Failure("INCOMPLETE_PROBE_REPORT", role=role)
    return {"attestation": expected, "denials": denials}


def _attest_live(name, role, root, data_id):
    uid, gid, _ = ROLES[role]
    info = _inspect(name)
    _verify_live(info, name, root, uid)
    expected = _expected_runtime(uid, gid, data_id, True, live=True)
    pid = info["pid"]
    try:
        host_maps = _process_maps(pid)
    except (OSError, ValueError):
        raise Failure("LIVE_HOST_MAPPING_UNAVAILABLE", role=role) from None
    if host_maps != [MAP, MAP]:
        raise Failure("LIVE_HOST_MAPPING_MISMATCH", role=role)
    result = _call_probe(
        ["exec", "-i", info["id"], "python3", "-I", "-S", "-B", "-"], role, expected, live=True,
    )
    if _inspect(name) != info:
        raise Failure("LIVE_CONTAINER_CHANGED", role=role)
    return info, result


def _run_temporary(image, fixture, source, identity, role):
    uid, gid, read_only = ROLES[role]
    expected = _expected_runtime(uid, gid, identity, read_only, live=False)
    try:
        cid = _docker(_create_args(image, fixture, source, role, uid, gid, read_only), "create_temporary")
    except (Failure, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt) or exc.category == "DOCKER_TIMEOUT":
            raise Failure("TEMPORARY_CREATION_UNCERTAIN", role=role, operation="create_temporary") from None
        raise
    if not CONTAINER_ID.fullmatch(cid):
        raise Failure("TEMPORARY_CREATION_UNCERTAIN", role=role, operation="create_temporary")
    try:
        _verify_temporary(_inspect(cid), cid, image, fixture, source, role, uid, gid, read_only)
        return _call_probe(["start", "-a", "-i", cid], role, expected)
    finally:
        _remove_temporary(cid, role)


def _inode_record(info):
    return {
        "identity": _identity(info), "uid": info.st_uid, "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode), "links": info.st_nlink, "size": info.st_size,
        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def _snapshot(unit_fd, frozen=None):
    unit = _inode_record(os.fstat(unit_fd))
    if ((unit["uid"], unit["gid"], unit["mode"]) != (WORKER, SHARED, 0o750) or _read_only(unit_fd)):
        raise Failure("FIXTURE_METADATA_MISMATCH")
    _require_no_acl(unit_fd)
    if frozen is not None and unit != frozen["unit"]:
        raise Failure("UNEXPECTED_SYNTHETIC_METADATA")
    if set(os.listdir(unit_fd)) != {*FILES, DIRECTORY}:
        raise Failure("UNEXPECTED_SYNTHETIC_INVENTORY")
    result = {"unit": unit, "entries": {}}
    for name in (*FILES, DIRECTORY):
        info = os.stat(name, dir_fd=unit_fd, follow_symlinks=False)
        expected_mode = 0o750 if name == DIRECTORY else 0o640
        expected_type = stat.S_ISDIR if name == DIRECTORY else stat.S_ISREG
        if (
            not expected_type(info.st_mode)
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (WORKER, SHARED, expected_mode)
            or info.st_dev != unit["identity"][0]
            or (name != DIRECTORY and (info.st_nlink != 1 or info.st_size != len(FILES[name])))
        ):
            raise Failure("UNEXPECTED_SYNTHETIC_METADATA")
        entry = _inode_record(info)
        if frozen is not None:
            baseline = frozen["entries"][name]
            if any(baseline[key] != value for key, value in entry.items()):
                raise Failure("UNEXPECTED_SYNTHETIC_METADATA")
        flags = DIR_FLAGS if name == DIRECTORY else os.O_RDONLY | FILE_FLAGS
        fd = os.open(name, flags, dir_fd=unit_fd)
        try:
            opened = os.fstat(fd)
            if not expected_type(opened.st_mode) or _inode_record(opened) != entry:
                raise Failure("UNEXPECTED_SYNTHETIC_METADATA")
            if name == DIRECTORY:
                if os.listdir(fd):
                    raise Failure("UNEXPECTED_SYNTHETIC_INVENTORY")
                _require_no_acl(fd)
            else:
                content = os.read(fd, len(FILES[name]) + 1)
                if content != FILES[name]:
                    raise Failure("UNEXPECTED_SYNTHETIC_CONTENT")
                entry["sha256"] = hashlib.sha256(content).hexdigest()
            result["entries"][name] = entry
        finally:
            os.close(fd)
    return result


def _run_negatives(probe, snapshot, frozen, results):
    for role in ROLES:
        if role == "worker":
            continue
        failure = None
        try:
            result = probe(role)
        except (Failure, OSError, KeyboardInterrupt) as exc:
            failure = exc if isinstance(exc, Failure) else _sanitized_error(exc, role=role)
            result = {"failure": failure.details}
        result["outcome"] = failure.category if failure else "PASS"
        results[role] = result
        if failure and failure.category == "TEMPORARY_CLEANUP_INCOMPLETE":
            result["inventory_unchanged"] = None
            raise failure
        try:
            same = snapshot() == frozen
        except (OSError, Failure):
            same = False
        result["inventory_unchanged"] = same
        if not same:
            raise Failure("EVIDENCE_CHANGED", role=role)
        if failure:
            raise failure


def _sanitized_error(exc, role=None):
    if isinstance(exc, Failure):
        return exc
    if isinstance(exc, KeyboardInterrupt):
        return Failure("INTERRUPTED", role=role)
    if isinstance(exc, OSError):
        return Failure("HOST_OPERATION_FAILED", role=role, number=exc.errno)
    return Failure("INTERNAL_ERROR", role=role)


PROBE_SOURCE = r"""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import stat


class ProbeFailure(Exception):
    def __init__(self, status, operation, number=None):
        self.result = {"status": status, "operation": operation, "errno": number}


def process_metadata(process):
    base = Path("/proc") / process
    fields = dict(line.split(":", 1) for line in (base / "status").read_text().splitlines() if ":" in line)
    uids = [int(value) for value in fields["Uid"].split()]
    gids = [int(value) for value in fields["Gid"].split()]
    groups = sorted({gids[1], *(int(value) for value in fields["Groups"].split())})
    maps = {name: [[int(value) for value in line.split()] for line in (base / name).read_text().splitlines()]
            for name in ("uid_map", "gid_map")}
    return {"uids": uids, "gids": gids, "groups": groups, **maps,
            "capabilities": [int(fields[name], 16) for name in ("CapPrm", "CapEff", "CapBnd")],
            "no_new_privs": int(fields["NoNewPrivs"])}


def attest(fd):
    info = os.fstat(fd)
    result = {"self": process_metadata("self"), "identity": [info.st_dev, info.st_ino],
              "read_only": bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY)}
    if "pid1" in SETTINGS["expected"]:
        result["pid1"] = process_metadata("1")
    if result != SETTINGS["expected"]:
        raise ProbeFailure("RUNTIME_ATTESTATION_MISMATCH", "identity")
    return result


@contextmanager
def worker_operation(operation):
    try:
        yield
    except OSError as exc:
        raise ProbeFailure("WORKER_PRIMITIVE_FAILED", operation, exc.errno) from None


def create_file(directory, name, content):
    with worker_operation("create_file"):
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o640, dir_fd=directory)
    try:
        with worker_operation("write_file"):
            if os.write(fd, content) != len(content):
                raise OSError(errno.EIO, "short synthetic write")
        with worker_operation("file_fsync"):
            os.fsync(fd)
        with worker_operation("readback"):
            os.lseek(fd, 0, os.SEEK_SET)
            if os.read(fd, len(content) + 1) != content:
                raise OSError(errno.EIO, "synthetic readback mismatch")
    finally:
        os.close(fd)


def positive(directory):
    old_umask = os.umask(0)
    try:
        for name, content in SETTINGS["files"].items():
            create_file(directory, name, content)
        with worker_operation("create_directory"):
            os.mkdir(SETTINGS["directory"], 0o750, dir_fd=directory)
            os.mkdir("worker-scratch-dir", 0o750, dir_fd=directory)
        create_file(directory, "worker-scratch", b"synthetic scratch\n")
        with worker_operation("owned_cleanup"):
            os.unlink("worker-scratch", dir_fd=directory)
            os.rmdir("worker-scratch-dir", dir_fd=directory)
        with worker_operation("directory_fsync"):
            fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        os.umask(old_umask)


def check_canaries(directory):
    try:
        for name, content in SETTINGS["files"].items():
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode)
                        or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
                        != (SETTINGS["worker"], SETTINGS["shared"], 0o640)
                        or os.read(fd, len(content) + 1) != content):
                    raise ProbeFailure("CANARY_PREREQUISITE_FAILED", name)
            finally:
                os.close(fd)
        fd = os.open(SETTINGS["directory"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if ((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
                    != (SETTINGS["worker"], SETTINGS["shared"], 0o750) or os.listdir(fd)):
                raise ProbeFailure("CANARY_PREREQUISITE_FAILED", "rmdir")
        finally:
            os.close(fd)
        for name in ("rename-target", "mkdir", "create"):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ProbeFailure("CANARY_PREREQUISITE_FAILED", "canaries")
    except OSError as exc:
        raise ProbeFailure("CANARY_PREREQUISITE_FAILED", "canaries", exc.errno) from None


def expected_denial(operation, callback, mutation=True):
    try:
        callback()
    except OSError as exc:
        allowed = SETTINGS["mutation_denials"] if mutation else SETTINGS["denials"]
        if exc.errno not in allowed:
            raise ProbeFailure("UNEXPECTED_OPERATION_ERRNO", operation, exc.errno) from None
        return exc.errno
    category = "UNEXPECTED_MUTATION" if mutation else (
        "UNEXPECTED_TRAVERSAL" if operation == "traverse" else "UNEXPECTED_READ"
    )
    raise ProbeFailure(category, operation)


def negative(directory, role):
    def read_canary():
        fd = os.open("write", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            os.read(fd, 1)
        finally:
            os.close(fd)

    def write_canary():
        fd = os.open("write", os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if os.write(fd, b"changed") != len(b"changed"):
                raise OSError(errno.EIO, "short synthetic mutation")
        finally:
            os.close(fd)

    def create_canary():
        fd = os.open("create", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640, dir_fd=directory)
        os.close(fd)

    if role == "foreign-unrelated":
        return {
            "traverse": expected_denial("traverse", lambda: os.stat(
                "write", dir_fd=directory, follow_symlinks=False,
            ), mutation=False),
            "read": expected_denial("read", read_canary, mutation=False),
            "create": expected_denial("create", create_canary),
        }

    check_canaries(directory)
    return {
        "write": expected_denial("write", write_canary),
        "unlink": expected_denial("unlink", lambda: os.unlink("unlink", dir_fd=directory)),
        "rename": expected_denial("rename", lambda: os.rename(
            "rename", "rename-target", src_dir_fd=directory, dst_dir_fd=directory,
        )),
        "rmdir": expected_denial("rmdir", lambda: os.rmdir(SETTINGS["directory"], dir_fd=directory)),
        "mkdir": expected_denial("mkdir", lambda: os.mkdir("mkdir", 0o750, dir_fd=directory)),
        "create": expected_denial("create", create_canary),
    }


def probe():
    try:
        fd = os.open(SETTINGS["mount"], os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ProbeFailure("RUNTIME_METADATA_FAILED", "identity", exc.errno) from None
    try:
        try:
            attestation = attest(fd)
        except (OSError, KeyError, ValueError) as exc:
            raise ProbeFailure("RUNTIME_METADATA_FAILED", "identity", getattr(exc, "errno", None)) from None
        denials = {}
        if SETTINGS["mount"] == "/probe":
            if SETTINGS["role"] == "worker":
                positive(fd)
            else:
                denials = negative(fd, SETTINGS["role"])
        return {"status": "PASS", "attestation": attestation, "denials": denials}
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        record = probe()
    except ProbeFailure as exc:
        record = exc.result
    print(json.dumps(record))
"""


def _process_maps(process):
    return [
        [[int(field) for field in line.split()]
         for line in Path(f"/proc/{process}/{kind}").read_text(encoding="ascii").splitlines()]
        for kind in ("uid_map", "gid_map")
    ]


def main(argv=None):
    report = {
        "status": "FAIL_LOCAL_PERMISSION_BOUNDARY",
        "fixture": None,
        "live": {},
        "roles": {},
        "namespace_exclusive_custody_proven": False,
        "release_ready": False,
        "unproven": [
            "root_admin", "same_uid_processes", "smb_nfs_and_fuse_service_exclusion",
            "backing_store_aliases", "future_namespace_isolation",
        ],
    }
    evidence = None
    with ExitStack() as stack:
        try:
            args = _args(argv)
            if os.geteuid() != 0:
                raise Failure("ROOT_REQUIRED")
            if _process_maps("self") != [MAP, MAP]:
                raise Failure("HOST_CONTROLLER_MAPPING_MISMATCH")

            root = args.data_root
            data_fd = _pin_data_root(stack, root)
            data_id = _identity(os.fstat(data_fd))
            worker_info, report["live"]["worker"] = _attest_live(args.worker_container, "worker", root, data_id)
            _, report["live"]["api"] = _attest_live(args.api_container, "api-ro", root, data_id)
            image = worker_info["image"]
            _verify_image(image)
            report["worker_image"] = image

            with ExitStack() as validation:
                if _identity(os.fstat(_pin_data_root(validation, root))) != data_id:
                    raise Failure("DATA_ROOT_BINDING_CHANGED")

            stack.callback(os.umask, os.umask(0o077))
            fixture = PREFIX + secrets.token_hex(12)
            parent_fd = _create_directory(stack, data_fd, fixture, 0, report)
            report_name = "acceptance-report.json"
            evidence_fd = os.open(
                report_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd,
            )
            evidence = stack.enter_context(os.fdopen(evidence_fd, "w", encoding="utf-8"))
            report["report_file"] = report_name
            unit_fd = _create_directory(stack, parent_fd, "unit", WORKER)
            identity = _identity(os.fstat(unit_fd))
            source = str(Path(root) / fixture / "unit")

            def run_role(role):
                _verify_binding(data_fd, fixture, parent_fd)
                _verify_binding(parent_fd, "unit", unit_fd)
                return _run_temporary(image, fixture, source, identity, role)

            def snapshot(frozen=None):
                _verify_binding(data_fd, fixture, parent_fd)
                _verify_binding(parent_fd, "unit", unit_fd)
                return _snapshot(unit_fd, frozen)

            report["roles"]["worker"] = {**run_role("worker"), "outcome": "PASS"}
            frozen = snapshot()
            report["frozen_inventory"] = frozen
            _run_negatives(run_role, lambda: snapshot(frozen), frozen, report["roles"])
            report["status"] = "PASS_LOCAL_PERMISSION_BOUNDARY"
        except (Exception, KeyboardInterrupt) as exc:
            report["failure"] = _sanitized_error(exc).details

        if evidence is not None:
            try:
                json.dump(report, evidence, indent=2, sort_keys=True)
                evidence.write("\n")
                evidence.flush()
                os.fsync(evidence.fileno())
            except OSError as exc:
                report["status"] = "FAIL_LOCAL_PERMISSION_BOUNDARY"
                report["report_write_failure"] = Failure("EVIDENCE_WRITE_FAILED", number=exc.errno).details

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_LOCAL_PERMISSION_BOUNDARY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
