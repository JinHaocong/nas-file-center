"""Focused contracts for the disposable Worker permission acceptance helper."""
from contextlib import redirect_stdout
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v16_nas_worker_permission_acceptance.py"


def _load():
    assert SCRIPT.exists(), "disposable Worker permission helper is required"
    spec = importlib.util.spec_from_file_location("v16_nas_worker_permission_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reject(action, category, error_type):
    try:
        action()
    except error_type as exc:
        assert exc.category == category
    else:
        raise AssertionError(f"expected {category}")


def test_cli_requires_explicit_fixture_creation_and_redacts_bad_arguments():
    program = _load()
    for argv, category in (
        (["--data-root", "/secret/nas-root"], "INVALID_ARGUMENTS"),
        (["--data-root", "/secret/nas-root", "--c"], "INVALID_ARGUMENTS"),
        (["--data-root", "/secret/nas-root,readonly", "--create-disposable-fixture"], "INVALID_DATA_ROOT"),
    ):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(program, "_docker") as docker, patch.object(
            program, "_create_directory",
        ) as create:
            result = program.main(argv)
        docker.assert_not_called()
        create.assert_not_called()
        report = json.loads(output.getvalue())
        assert result != 0 and report["failure"]["category"] == category
        assert report["fixture"] is None and "/secret" not in output.getvalue()
        assert report["release_ready"] is False


def test_protocol_failure_and_missing_errno_are_not_accepted_as_acl_absence():
    program = _load()
    with patch.object(program.os, "getxattr", side_effect=OSError(errno.ENODATA, "private")):
        program._require_no_acl(0)
    for number in (errno.EPROTONOSUPPORT, errno.ENOTSUP, None):
        with patch.object(program.os, "getxattr", side_effect=OSError(number, "private")):
            _reject(lambda: program._require_no_acl(0), "ACL_METADATA_UNAVAILABLE", program.Failure)


def test_denial_requires_permission_errno_and_allows_erofs_only_for_read_only_mutation():
    program = _load()
    for number, read_only, mutation, expected in (
        (errno.EACCES, False, True, True),
        (errno.EPERM, False, False, True),
        (errno.EROFS, True, True, True),
        (errno.EROFS, False, True, False),
        (errno.EROFS, True, False, False),
        (errno.ENOENT, True, True, False),
    ):
        assert program._is_denial(number, read_only, mutation) is expected


def test_create_command_uses_exact_image_role_and_only_disposable_unit_bind():
    program = _load()
    image = "sha256:" + "a" * 64
    fixture = "nfc-v16-worker-permission-" + "b" * 24
    source = f"/host/data/{fixture}/unit"
    name = f"{fixture}-api-ro"
    args = program._create_args(image, fixture, source, "api-ro", 10001, 10000, True)
    assert args == [
        "create", "--pull=never", "--read-only", "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--no-healthcheck", "--init=false",
        "--user", "10001:10000", "--entrypoint", "python3", "--workdir", "/",
        "--name", name, "--label", f"nfc.v16.permission-fixture={fixture}",
        "--mount", f"type=bind,src={source},dst=/probe,readonly",
        "-i", image, "-I", "-S", "-B", "-",
    ]


def test_temporary_inspection_validates_security_and_rejects_additional_mounts():
    program = _load()
    fixture = "nfc-v16-worker-permission-" + "b" * 24
    cid = "c" * 64
    image = "sha256:" + "a" * 64
    source = f"/host/data/{fixture}/unit"
    info = {
        "id": cid, "name": f"/{fixture}-api-ro", "image": image, "running": False, "pid": 0,
        "user": "10001:10000", "userns": "", "group_add": None, "privileged": False,
        "cap_add": None, "cap_drop": ["ALL"], "security": ["no-new-privileges"],
        "read_only_root": True, "network": "none", "label": fixture,
        "entrypoint": ["python3"], "command": ["-I", "-S", "-B", "-"], "workdir": "/",
        "healthcheck": {"Test": ["NONE"]},
        "mounts": [{"type": "bind", "source": source, "destination": "/probe", "rw": False}],
    }
    validate = lambda: program._verify_temporary(info, cid, image, fixture, source, "api-ro", 10001, 10000, True)
    validate()
    for key, rejected in (
        ("cap_add", ["CAP_DAC_OVERRIDE"]), ("network", "bridge"), ("running", True),
        ("mounts", info["mounts"] + [{"type": "volume", "destination": "/other"}]),
    ):
        with patch.dict(info, {key: rejected}):
            _reject(validate, "TEMPORARY_CONTAINER_MISMATCH", program.Failure)


def test_first_negative_failure_checks_inventory_and_stops_remaining_roles():
    program = _load()
    seen = []
    results = {}

    def probe(role):
        seen.append(role)
        raise program.Failure("UNEXPECTED_MUTATION", role=role)

    def snapshot():
        seen.append("snapshot")
        return {"changed": True}

    _reject(
        lambda: program._run_negatives(probe, snapshot, {"changed": False}, results),
        "EVIDENCE_CHANGED",
        program.Failure,
    )
    assert seen == ["api-rw", "snapshot"]
    assert results["api-rw"]["outcome"] == "UNEXPECTED_MUTATION"
    assert results["api-rw"]["inventory_unchanged"] is False


def _probe(program, role, path):
    uid, gid, read_only = program.ROLES[role]
    info = path.stat()
    expected = program._expected_runtime(uid, gid, [info.st_dev, info.st_ino], read_only, live=False)
    namespace = {"__name__": "embedded_probe_test"}
    exec(compile(program._make_probe(role, expected), "<embedded-probe>", "exec"), namespace)
    return namespace


def test_embedded_attestation_rejects_identity_maps_groups_caps_and_mount():
    program = _load()
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw)
        ns = _probe(program, "api-rw", path)
        expected = ns["SETTINGS"]["expected"]["self"]
        proc = path / "proc" / "self"
        proc.mkdir(parents=True)
        ns["Path"] = lambda _path: proc.parent
        for name in ("uid_map", "gid_map"):
            (proc / name).write_text("0 0 4294967295\n")
        baseline = (
            "Uid:\t10001 10001 10001 10001\nGid:\t10000 10000 10000 10000\nGroups:\n"
            "CapPrm:\t0\nCapEff:\t0\nCapBnd:\t0\nNoNewPrivs:\t1\n"
        )
        status = proc / "status"
        status.write_text(baseline)
        fd = os.open(path, os.O_PATH | os.O_DIRECTORY)
        try:
            assert ns["attest"](fd)["self"] == expected
            for old, new in (
                ("Uid:\t10001", "Uid:\t10002"), ("Groups:\n", "Groups:\t10001\n"),
                ("CapBnd:\t0", "CapBnd:\t1"), ("NoNewPrivs:\t1", "NoNewPrivs:\t0"),
            ):
                status.write_text(baseline.replace(old, new))
                try:
                    ns["attest"](fd)
                except ns["ProbeFailure"] as exc:
                    assert exc.result["status"] == "RUNTIME_ATTESTATION_MISMATCH"
                else:
                    raise AssertionError("wrong runtime process metadata was accepted")
            status.write_text(baseline)
            (proc / "uid_map").write_text("0 100000 65536\n")
            try:
                ns["attest"](fd)
            except ns["ProbeFailure"] as exc:
                assert exc.result["status"] == "RUNTIME_ATTESTATION_MISMATCH"
            else:
                raise AssertionError("remapped runtime identity was accepted")
            (proc / "uid_map").write_text("0 0 4294967295\n")
            ns["SETTINGS"]["expected"]["identity"][1] += 1
            try:
                ns["attest"](fd)
            except ns["ProbeFailure"] as exc:
                assert exc.result["status"] == "RUNTIME_ATTESTATION_MISMATCH"
            else:
                raise AssertionError("wrong mount inode was accepted")
        finally:
            os.close(fd)


def _local_canaries(program, role, path):
    ns = _probe(program, role, path)
    ns["SETTINGS"]["worker"] = os.geteuid()
    ns["SETTINGS"]["shared"] = os.getegid()
    path.chmod(0o750)
    fd = os.open(path, os.O_PATH | os.O_DIRECTORY)
    umask = os.umask(0o077)
    try:
        ns["positive"](fd)
    finally:
        os.umask(umask)
        os.close(fd)
    return ns


def test_shared_negative_requires_read_then_stops_after_first_unexpected_write():
    program = _load()
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw)
        ns = _local_canaries(program, "api-rw", path)
        fd = os.open(path, os.O_PATH | os.O_DIRECTORY)
        real_open = os.open
        seen = []

        def unreadable(name, flags, *args, **kwargs):
            seen.append(name)
            if name == "write":
                assert flags & os.O_ACCMODE == os.O_RDONLY
                raise OSError(errno.EACCES, "private")
            return real_open(name, flags, *args, **kwargs)

        try:
            with patch.object(ns["os"], "open", side_effect=unreadable):
                try:
                    ns["negative"](fd, "api-rw")
                except ns["ProbeFailure"] as exc:
                    assert exc.result["status"] == "CANARY_PREREQUISITE_FAILED"
                else:
                    raise AssertionError("unreadable canary was accepted")
            assert seen == ["write"]
            assert (path / "write").read_bytes() == program.FILES["write"]
            try:
                ns["negative"](fd, "api-rw")
            except ns["ProbeFailure"] as exc:
                assert (exc.result["status"], exc.result["operation"]) == ("UNEXPECTED_MUTATION", "write")
            else:
                raise AssertionError("surprising mutation was accepted")
            assert (path / "write").read_bytes().startswith(b"changed")
            assert (path / "unlink").read_bytes() == program.FILES["unlink"]
            assert (path / "rename").read_bytes() == program.FILES["rename"]
            assert (path / "rmdir").is_dir()
        finally:
            os.close(fd)


def test_embedded_probe_rejects_erofs_on_rw_and_records_foreign_traversal():
    program = _load()
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw)
        ns = _probe(program, "foreign-unrelated", path)

        def erofs():
            raise OSError(errno.EROFS, "private")

        try:
            ns["expected_denial"]("create", erofs)
        except ns["ProbeFailure"] as exc:
            assert exc.result["status"] == "UNEXPECTED_OPERATION_ERRNO"
        else:
            raise AssertionError("EROFS was accepted on a writable bind")

        denied = OSError(errno.EACCES, "private")
        with patch.object(ns["os"], "open", side_effect=denied), patch.object(ns["os"], "stat", side_effect=denied):
            report = ns["negative"](123, "foreign-unrelated")
        assert report == {"traverse": errno.EACCES, "read": errno.EACCES, "create": errno.EACCES}


def test_directory_fsync_failure_has_specific_primitive_label():
    program = _load()
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw)
        ns = _probe(program, "worker", path)
        real_fsync = os.fsync

        def unsupported_for_directories(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.ENOTSUP, "private")
            return real_fsync(fd)

        fd = os.open(path, os.O_PATH | os.O_DIRECTORY)
        umask = os.umask(0o077)
        try:
            with patch.object(ns["os"], "fsync", side_effect=unsupported_for_directories):
                try:
                    ns["positive"](fd)
                except ns["ProbeFailure"] as exc:
                    assert exc.result == {
                        "status": "WORKER_PRIMITIVE_FAILED", "operation": "directory_fsync", "errno": errno.ENOTSUP,
                    }
                else:
                    raise AssertionError("directory fsync was skipped")
        finally:
            os.umask(umask)
            os.close(fd)


def test_snapshot_does_not_read_replacement_inode_and_checks_contents():
    program = _load()
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw)
        _local_canaries(program, "worker", path)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with patch.object(program, "WORKER", os.geteuid()), patch.object(
                program, "SHARED", os.getegid(),
            ), patch.object(program, "_require_no_acl"):
                frozen = program._snapshot(fd)
                canary = path / "write"
                replacement = path / "replacement"
                replacement.write_bytes(program.FILES["write"])
                replacement.chmod(0o640)
                replacement.replace(canary)
                # Model a backend with unchanged parent timestamps so that the
                # known entry's inode guard, rather than the unit guard, fires.
                frozen["unit"] = program._inode_record(os.fstat(fd))
                with patch.object(program.os, "read") as read:
                    _reject(lambda: program._snapshot(fd, frozen), "UNEXPECTED_SYNTHETIC_METADATA", program.Failure)
                read.assert_not_called()
                canary.write_bytes(b"x" * len(program.FILES["write"]))
                _reject(lambda: program._snapshot(fd), "UNEXPECTED_SYNTHETIC_CONTENT", program.Failure)
        finally:
            os.close(fd)


def test_timeout_force_removes_created_container_before_inventory_check():
    program = _load()
    cid = "a" * 64
    events = []

    def docker(args, operation):
        events.append(args[0])
        if args[0] == "create":
            return cid
        assert args == ["rm", "--force", cid]

    def check_inventory():
        events.append("snapshot")
        return {"matches": True}

    def probe(role):
        return program._run_temporary("sha256:" + "b" * 64, "fixture", "/data/fixture/unit", [1, 2], role)

    results = {}
    with patch.object(program, "_docker", side_effect=docker), patch.object(
        program, "_inspect", return_value={},
    ), patch.object(program, "_verify_temporary"), patch.object(
        program, "_call_probe", side_effect=program.Failure("DOCKER_TIMEOUT"),
    ):
        _reject(lambda: program._run_negatives(probe, check_inventory, {"matches": True}, results),
                "DOCKER_TIMEOUT", program.Failure)
    assert events == ["create", "rm", "snapshot"]
    assert results["api-rw"]["inventory_unchanged"] is True


def test_rejected_create_never_looks_up_or_removes_existing_container():
    program = _load()
    events = []

    def docker(args, operation):
        events.append(args[0])
        if args[0] == "create":
            raise program.Failure("DOCKER_COMMAND_FAILED", operation=operation, exit_code=125)
        if args[:2] == ["container", "ls"]:
            return "c" * 64

    with patch.object(program, "_docker", side_effect=docker):
        _reject(
            lambda: program._run_temporary("sha256:" + "b" * 64, "fixture", "/data/fixture/unit", [1, 2], "api-rw"),
            "DOCKER_COMMAND_FAILED", program.Failure,
        )
    assert events == ["create"]


def test_ambiguous_create_does_not_remove_or_start_an_unknown_container():
    program = _load()
    for response in (program.Failure("DOCKER_TIMEOUT"), "malformed cid"):
        def create(args, operation):
            if args[0] != "create":
                return ""
            if isinstance(response, program.Failure):
                raise response
            return response

        with patch.object(program, "_docker", side_effect=create) as docker:
            _reject(
                lambda: program._run_temporary("sha256:" + "b" * 64, "fixture", "/data/fixture/unit", [1, 2], "api-rw"),
                "TEMPORARY_CREATION_UNCERTAIN", program.Failure,
            )
            assert docker.call_count == 1
