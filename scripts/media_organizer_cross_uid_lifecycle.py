"""Driver for the CI-only setpriv lifecycle; not a deployment utility.

Every phase verifies its real kernel UID/GID and capabilities. Synthetic
custody is injected only in this disposable test process. Production source
and the production issuer are never modified.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

PHASE = sys.argv[1]
KIND = sys.argv[2] if len(sys.argv) > 2 else None
ROOT = Path(os.environ["NFC_SYNTH_ROOT"])
assert ROOT.is_absolute() and str(ROOT).startswith("/tmp/nfc-v16-cleanup-crossuid-")
assert os.environ.get("GITHUB_ACTIONS") == "true", "isolated CI only"
API_PHASES = {
    "queue-preview", "queue-execution", "queue-execution-recovery",
    "review-and-queue", "queue-recovery", "final-read",
}
EXPECTED_UID = 10001 if PHASE in API_PHASES else 10003 if PHASE == "foreign-denied" else 10002
assert os.getuid() == os.geteuid() == EXPECTED_UID
assert os.getgid() == os.getegid() == 10000
assert os.getgroups() == []
caps = next(line for line in Path("/proc/self/status").read_text().splitlines()
            if line.startswith("CapEff:"))
assert int(caps.split()[1], 16) == 0, "test roles must have no effective capabilities"
DATA, CONFIG, CONTROL = ROOT / "data", ROOT / "config", ROOT / "control.json"
FIXTURES = {
    "flat": {"a.jpg": b"a", "b.jpg": b"b"},
    "grouped": {"photo.jpg": b"photo", "movie.mp4": b"video"},
    "reused": {"P [2 2B]/000.jpg": b"a", "P [2 2B]/001.jpg": b"b", "movie.mp4": b"v"},
}
EXPECTED = {
    "flat": {"001.jpg": b"a", "002.jpg": b"b"},
    "grouped": {"P [1 5B]/001.jpg": b"photo", "V [1 5B]/001.mp4": b"video"},
    "reused": {"P [2 2B]/001.jpg": b"a", "P [2 2B]/002.jpg": b"b", "V [1 1B]/001.mp4": b"v"},
}
RECOVERY_CASES = {
    "flat-stage-recovery": ("flat", "frozen"),
    "grouped-publish-recovery": ("grouped", "staged"),
    "reused-published-recovery": ("reused", "published"),
    "grouped-handoff-recovery": ("grouped", "manual_cleanup_required"),
}
for case_name, (base_kind, _phase) in RECOVERY_CASES.items():
    FIXTURES[case_name] = dict(FIXTURES[base_kind])
    EXPECTED[case_name] = dict(EXPECTED[base_kind])


def denied(operation):
    try:
        value = operation()
    except PermissionError:
        return
    if isinstance(value, int):
        os.close(value)
    raise AssertionError("distinct API/foreign UID unexpectedly accessed protected data")


if PHASE == "foreign-denied":
    # Same group is intentionally insufficient for Worker-private evidence.
    # An unrelated group/config denial is already covered by preview CI.
    state = json.loads(CONTROL.read_text())
    for fixture in state["cases"].values():
        frozen = Path(fixture["frozen"])
        denied(lambda: os.open(str(frozen) + ".cleanup-progress.jsonl", os.O_RDONLY))
    print("FOREIGN_UID_PRIVATE_JOURNAL_DENIED")
    raise SystemExit(0)

from app.batch import media_organizer_custody as custody
from app.batch import media_organizer_cleanup_jobs as cleanup_jobs
from app.batch.media_organizer_execute_jobs import approval_token, recovery_token
from app.batch.media_organizer_planner import preview_semantic_unit
from app.config import Settings
from app.db import create_engine_and_session
from app.models import TaskLock, WorkJob, utcnow
from app.tasks.recovery import acquire_worker_ownership, recover_interrupted_jobs
from app.worker import process_work_job
assert Path(custody.__file__).is_relative_to(ROOT / "app")

settings = Settings(
    _env_file=None, CONFIG_DIR=str(CONFIG), DATA_MOUNT=str(DATA),
    ALLOWED_ROOTS=str(DATA), QUARANTINE_ROOT=str(DATA / ".trash"),
    MEDIA_ORGANIZER_EXECUTION_ENABLED=True, MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=True,
    ALLOW_MUTATION=True, ALLOW_DELETE=True,
    INITIAL_ADMIN_USERNAME="synthetic-admin", INITIAL_ADMIN_PASSWORD="synthetic-only-password-123",
)
try:
    custody.verified_namespace_custody(settings, DATA)
except custody.NamespaceCustodyUnavailable:
    pass
else:
    raise AssertionError("production custody issuer was unexpectedly enabled")


class FixtureCustody:
    def assert_exclusive(self, parent):
        assert Path(parent).is_relative_to(DATA), "synthetic proof escaped fixture"


def synthetic_issuer(_settings, unit):
    proof = FixtureCustody()
    proof.assert_exclusive(unit)
    return proof


custody.verified_namespace_custody = synthetic_issuer


def read_control():
    return json.loads(CONTROL.read_text())


def write_control(state):
    with CONTROL.open("r+", encoding="utf-8") as stream:
        stream.seek(0)
        json.dump(state, stream, sort_keys=True)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def media_snapshot(unit):
    return {str(path.relative_to(unit)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in unit.rglob("*") if path.is_file()}


def visible_snapshot(unit):
    result = {}
    for path in unit.rglob("*"):
        if any(part.startswith(".nfc-") for part in path.relative_to(unit).parts):
            continue
        if path.is_file():
            result[str(path.relative_to(unit))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def client():
    from fastapi.testclient import TestClient
    from app.main import create_app
    value = TestClient(create_app(settings))
    value.headers.update({"Origin": "http://testserver"})
    response = value.post("/api/auth/login", json={
        "username": "synthetic-admin", "password": "synthetic-only-password-123",
    })
    assert response.status_code == 200, response.text
    return value


def run_job(job_id, worker_id):
    engine, factory = create_engine_and_session(settings.database_path)
    try:
        assert acquire_worker_ownership(engine, factory, worker_id=worker_id)
        return process_work_job(settings, job_id, factory, engine, worker_id)
    finally:
        engine.dispose()


def capture_frozen_execution(case, frozen_job_id):
    frozen = settings.reports_dir / "media_organizer-executions" / str(frozen_job_id) / "manifest.json"
    manifest = json.loads(frozen.read_text())["manifest"]
    case["frozen"] = str(frozen)
    case["stage"] = str(Path(case["unit"]) / manifest["stage_directory"])
    assert stat.S_IMODE(Path(case["stage"]).stat().st_mode) & 0o777 == 0o700
    for path in frozen.parent.glob("*.group-*.json"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


if PHASE == "fixtures":
    state = {"worker_id": "cross-uid-worker", "cases": {}}
    for index, (kind, files) in enumerate(FIXTURES.items(), 1):
        unit = DATA / "Collection" / f"NO.{index:03d}"
        unit.mkdir(mode=0o750, parents=True)
        for name, payload in files.items():
            path = unit / name
            path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            path.write_bytes(payload)
            path.chmod(0o640)  # Newly created synthetic payload: API reads via shared GID.
        state["cases"][kind] = {"unit": str(unit)}
        if RECOVERY_CASES.get(kind, (kind, None))[0] == "reused":
            state["cases"][kind]["retained_group_inode"] = (unit / "P [2 2B]").stat().st_ino
    write_control(state)
    print("WORKER_UID_CREATED_DISPOSABLE_FIXTURES")
    raise SystemExit(0)

state = read_control()
case = state["cases"][KIND]
unit = Path(case["unit"])

if PHASE == "queue-preview":
    api = client()
    response = api.post("/api/media-organizer/previews", json={"selection": str(unit.parent)})
    assert response.status_code == 200, response.text
    case["preview_id"] = response.json()["job_id"]
elif PHASE == "preview":
    assert run_job(case["preview_id"], state["worker_id"])
elif PHASE == "queue-execution":
    api = client()
    report = api.get(f"/api/media-organizer/previews/{case['preview_id']}")
    assert report.status_code == 200, report.text
    assert any(row["unit"] == str(unit) and row["status"] == "ready"
               for row in report.json()["units"])
    response = api.post(f"/api/media-organizer/previews/{case['preview_id']}/execute", json={
        "unit": str(unit), "confirmation": approval_token(case["preview_id"], str(unit)),
    })
    assert response.status_code == 200, response.text
    case["execution_id"] = response.json()["job_id"]
elif PHASE == "interrupt-execution":
    from app.batch import media_organizer_execute_jobs as execution_jobs
    from app.batch import media_organizer_publish as publishing
    from app.batch import media_organizer_stage as staging

    crash_phase = RECOVERY_CASES[KIND][1]
    message = "synthetic execution interruption at " + crash_phase
    if crash_phase in {"frozen", "staged"}:
        owner, name = ((staging, "_move_one") if crash_phase == "frozen"
                       else (publishing, "_link_one"))
        mutate = getattr(owner, name)

        def stop_after_mutation(*args, **kwargs):
            mutate(*args, **kwargs)
            raise SystemExit(message)

        setattr(owner, name, stop_after_mutation)
    elif crash_phase == "published":
        def stop_before_handoff(*args, **kwargs):
            raise SystemExit(message)

        execution_jobs.record_deferred_cleanup_evidence = stop_before_handoff
    else:
        save_checkpoint = execution_jobs.JobContext.checkpoint

        def stop_after_handoff(context, *args, **kwargs):
            result = save_checkpoint(context, *args, **kwargs)
            if kwargs.get("checkpoint_data", {}).get("phase") == "manual_cleanup_required":
                raise SystemExit(message)
            return result

        execution_jobs.JobContext.checkpoint = stop_after_handoff
    try:
        run_job(case["execution_id"], state["worker_id"])
    except SystemExit as exc:
        assert str(exc) == message
    else:
        raise AssertionError("execution did not reach the injected interruption")
    case["failed_execution_id"] = case["execution_id"]
    capture_frozen_execution(case, case["failed_execution_id"])
    case["execution_interrupted_snapshot"] = media_snapshot(unit)
    engine, factory = create_engine_and_session(settings.database_path)
    try:
        with factory() as session:
            original = session.get(WorkJob, case["failed_execution_id"])
            assert original.status == "running"
            checkpoint = json.loads(original.checkpoint_json)
            assert checkpoint["phase"] == crash_phase
            case["failed_execution_checkpoint"] = checkpoint
    finally:
        engine.dispose()
elif PHASE == "queue-execution-recovery":
    api = client()
    denied(lambda: os.open(case["stage"], os.O_RDONLY | os.O_DIRECTORY))
    before = visible_snapshot(unit)
    failed_id = case["failed_execution_id"]
    status = api.get(f"/api/media-organizer/executions/{failed_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "failed"
    payload = {"confirmation": recovery_token(failed_id)}
    endpoint = f"/api/media-organizer/executions/{failed_id}/recover"
    response = api.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    case["execution_id"] = response.json()["job_id"]
    assert case["execution_id"] != failed_id
    repeated = api.post(endpoint, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["job_id"] == case["execution_id"]
    assert visible_snapshot(unit) == before
elif PHASE in {"execute", "recover-execution"}:
    if PHASE == "recover-execution":
        assert media_snapshot(unit) == case["execution_interrupted_snapshot"], "API changed interrupted execution"
    assert run_job(case["execution_id"], state["worker_id"])
    frozen_id = case.get("failed_execution_id", case["execution_id"])
    capture_frozen_execution(case, frozen_id)
    case["prepared_snapshot"] = media_snapshot(unit)
    if PHASE == "recover-execution":
        engine, factory = create_engine_and_session(settings.database_path)
        try:
            with factory() as session:
                original = session.get(WorkJob, frozen_id)
                recovered = session.get(WorkJob, case["execution_id"])
                assert original.status == "failed"
                assert json.loads(original.checkpoint_json) == case["failed_execution_checkpoint"]
                assert recovered.status == "completed"
                assert json.loads(recovered.checkpoint_json)["frozen_job_id"] == frozen_id
                assert json.loads(recovered.state_json)["recovery_of_job_id"] == frozen_id
        finally:
            engine.dispose()
elif PHASE == "review-and-queue":
    api = client()
    frozen = Path(case["frozen"])
    denied(lambda: os.open(case["stage"], os.O_RDONLY | os.O_DIRECTORY))
    for receipt in frozen.parent.glob("*.group-*.json"):
        denied(lambda receipt=receipt: os.open(receipt, os.O_RDONLY))
    before = visible_snapshot(unit)
    for suffix in ("cleanup-review", "cleanup-audit", "cleanup-plan"):
        response = api.get(f"/api/media-organizer/executions/{case['execution_id']}/{suffix}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verification_scope"] == "worker_handoff_snapshot"
        assert body["live_inventory_verified"] is False
        assert body["read_only"] is True
    case["confirmation"] = body["confirmation"]
    response = api.post(f"/api/media-organizer/executions/{case['execution_id']}/cleanup", json={
        "confirmation": case["confirmation"],
    })
    assert response.status_code == 200, response.text
    case["cleanup_id"] = response.json()["job_id"]
    assert visible_snapshot(unit) == before
    denied(lambda: os.open(unit / "api-must-not-create", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
elif PHASE == "interrupt-cleanup":
    assert media_snapshot(unit) == case["prepared_snapshot"], "API changed prepared media"
    finish = cleanup_jobs.finish_deferred_cleanup

    def interrupted(*args, **kwargs):
        def stop(index):
            if index == 0:
                raise SystemExit("synthetic Worker interruption after first mutation")
        return finish(*args, **kwargs, after_mutation=stop)

    cleanup_jobs.finish_deferred_cleanup = interrupted
    try:
        run_job(case["cleanup_id"], state["worker_id"])
    except SystemExit as exc:
        assert "synthetic Worker interruption" in str(exc)
    else:
        raise AssertionError("cleanup did not reach the injected interruption")
    case["interrupted_snapshot"] = media_snapshot(unit)
    journal = Path(case["frozen"] + ".cleanup-progress.jsonl")
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    case["interrupted_journal_sha256"] = hashlib.sha256(journal.read_bytes()).hexdigest()
elif PHASE in {"mark-interrupted", "mark-execution-interrupted"}:
    engine, factory = create_engine_and_session(settings.database_path)
    try:
        interrupted_id = (case["cleanup_id"] if PHASE == "mark-interrupted"
                          else case["failed_execution_id"])
        next_worker = f"cross-uid-{PHASE}-{KIND}"
        with factory() as session:
            assert session.get(WorkJob, interrupted_id).status == "running"
            session.get(TaskLock, 1).acquired_at = utcnow()
            session.commit()
        assert not acquire_worker_ownership(engine, factory, worker_id=next_worker), "live lease was stolen"
        with factory() as session:
            # Deterministic disposable crash clock; no sleep and no live lease.
            session.get(TaskLock, 1).acquired_at = utcnow() - timedelta(seconds=31)
            session.commit()
        state["worker_id"] = next_worker
        assert acquire_worker_ownership(engine, factory, worker_id=state["worker_id"])
        recovered = recover_interrupted_jobs(engine, factory, worker_id=state["worker_id"])
        assert recovered["failed_interrupted"] == 1
    finally:
        engine.dispose()
elif PHASE == "queue-recovery":
    api = client()
    denied(lambda: os.open(case["frozen"] + ".cleanup-progress.jsonl", os.O_RDONLY))
    before = visible_snapshot(unit)
    response = api.get(f"/api/media-organizer/executions/{case['execution_id']}")
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["cleanup"]["status"] == "failed"
    confirmation = status["cleanup"]["recovery_confirmation"]
    assert confirmation
    response = api.post(f"/api/media-organizer/cleanups/{case['cleanup_id']}/recover", json={
        "confirmation": confirmation,
    })
    assert response.status_code == 200, response.text
    case["recovery_id"] = response.json()["job_id"]
    assert visible_snapshot(unit) == before
elif PHASE == "recover":
    assert media_snapshot(unit) == case["interrupted_snapshot"], "API changed partial cleanup"
    journal = Path(case["frozen"] + ".cleanup-progress.jsonl")
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == case["interrupted_journal_sha256"]
    assert run_job(case["recovery_id"], state["worker_id"])
    scan = preview_semantic_unit(unit, allowed_roots=[DATA], quarantine_root=DATA / ".trash")
    assert scan["status"] == "already_organized", scan
    assert scan["needed_moves"] == scan["renamed_count"] == 0
    assert {str(path.relative_to(unit)): path.read_bytes()
            for path in unit.rglob("*") if path.is_file()} == EXPECTED[KIND]
elif PHASE == "final-read":
    api = client()
    response = api.get(f"/api/media-organizer/executions/{case['execution_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["finalized"] is True
    assert not Path(case["stage"]).exists()
    assert {str(path.relative_to(unit)): path.read_bytes()
            for path in unit.rglob("*") if path.is_file()} == EXPECTED[KIND]
    for path in unit.iterdir():
        if path.is_dir():
            info = path.stat()
            assert info.st_uid == 10002 and info.st_gid == 10000
            assert stat.S_IMODE(info.st_mode) == 0o750
            denied(lambda path=path: os.open(path / "api-must-not-create",
                                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    final_sample = unit / next(iter(EXPECTED[KIND]))
    denied(lambda: os.open(final_sample, os.O_WRONLY | os.O_TRUNC))
    assert final_sample.read_bytes() == EXPECTED[KIND][str(final_sample.relative_to(unit))]
    if "retained_group_inode" in case:
        assert (unit / "P [2 2B]").stat().st_ino == case["retained_group_inode"]
    denied(lambda: os.open(case["frozen"] + ".cleanup-progress.jsonl", os.O_RDONLY))
    if "failed_execution_id" in case:
        failed_id = case["failed_execution_id"]
        original = api.get(f"/api/media-organizer/executions/{failed_id}")
        assert original.status_code == 200, original.text
        assert original.json()["status"] == "failed"
        repeated = api.post(f"/api/media-organizer/executions/{failed_id}/recover", json={
            "confirmation": recovery_token(failed_id),
        })
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["job_id"] == case["execution_id"]
else:
    raise AssertionError(f"unknown synthetic phase {PHASE}")

write_control(state)
print(f"PASS_{PHASE.upper().replace('-', '_')}_{KIND.upper()}_UID_{os.geteuid()}")
