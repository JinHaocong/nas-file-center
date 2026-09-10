# Gate5-F Resource Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conservative persisted Resource Control for read-heavy NAS indexing and duplicate-scan workloads while preserving the existing single-worker Task Engine and all Gate5-A through Gate5-E safety semantics.

**Architecture:** Add one singleton ResourcePolicy, a pure resource-policy evaluator, resource-aware claim admission/priority, bounded fclones thread composition, and a minimal admin Settings UI. Resource Control limits read-heavy jobs only; it never grants mutation authority, creates jobs, introduces a second worker, or changes Plan/Freeze/Validate/Execute semantics.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, zoneinfo, existing Task Engine, fclones, React, TypeScript, Ant Design, React Query.

**Spec:** `docs/history/gate5f/gate5f-architecture-freeze.md`

---

## Global Constraints

- **Target:** 极空间 NAS / Linux amd64 / Docker.
- **Priority:** Data safety > correctness > recoverability > performance > UI > feature count.
- **Worker Concurrency:** One existing Worker only; strict lease ownership / TaskLock state machine model; no second worker or parallel WorkJob execution.
- **No Scheduler / Cron:** No automatic time-based job creation, no periodic background triggers.
- **No State-Machine Redesign:** No redesign of Task Engine state machine, TaskLock, or WorkerState.
- **Filesystem Safety:** Zero filesystem mutation semantic changes; no changes to Gate3 identity authority; all quarantine and restore invariants from Gate5-E remain immutable.
- **Digest / Freshness Decoupling:** ResourcePolicy must never participate in Preview digest, Draft identity, Freeze identity, Validate filesystem freshness, or OperationJournal filesystem identity.
- **Controlled Job Kinds:** In V1, only read-heavy workloads (`index-root` and `fclones-scan`) are resource-controlled. Mutation jobs are never window-paused.
- **Canonical Profile Vocabulary:** Effective profiles are strictly `full`, `limited`, or `pause` (never `normal`). `io_limit` values remain `low`, `normal`, `unlimited`.
- **Canonical Defaults:** `scan_threads = 2`, `hash_threads = 2`, `io_limit = "normal"`, `job_priority = "normal"`, `active_window_enabled = False`, `outside_window_mode = "limited"`, `revision = 1`.
- **No CPU Auto-Scaling:** Never invoke `os.cpu_count()` to scale concurrency; thread caps are strictly bounded by explicit user configuration and safety ceilings.
- **Soft I/O Pressure:** `io_limit` represents application-level concurrency throttling (`low` = 1, `normal` = 2, `unlimited` = configured cap), not hard MB/s or IOPS rate-limiting.
- **Gate Boundaries:** Gate5-G remains strictly FORBIDDEN; v0.3.5 remains NOT CLOSED.

---

## File Structure & Responsibilities

| File Path | Role & Responsibility |
|---|---|
| `app/resource_control.py` | **[NEW]** Pure resource-policy types, validation helpers, active-window evaluator, thread-ceiling composition, job classification, and safe timezone resolver with LRU cache. |
| `app/models.py` | **[MODIFY]** Add singleton ORM model `ResourcePolicy` with table-level check constraints. |
| `app/db.py` | **[MODIFY]** Register `resource_policy` in `required_tables`, trigger backup on upgrade, and seed default singleton row in `init_db()`. |
| `app/service.py` | **[MODIFY]** Add application service methods `get_resource_policy()` and atomic two-phase `update_resource_policy()` (Phase A validation + pre-cache ZoneInfo, Phase B short SQLite `BEGIN IMMEDIATE`). |
| `app/api/router.py` | **[MODIFY]** Expose `GET /api/settings/resource-policy` and `PUT /api/settings/resource-policy` with explicit admin dependency, session auth, and `ResourcePolicyValidationError -> HTTP 422` conversion. |
| `app/tasks/recovery.py` | **[MODIFY]** Enhance `claim_next_job()` with two-phase policy preparation (Phase A outside tx, Phase B `BEGIN IMMEDIATE`) for admission and priority. |
| `app/tasks/handlers.py` | **[MODIFY]** Integrate effective thread ceiling and `context.log()` diagnostics in `FclonesScanHandler` and `IndexRootHandler`. |
| `app/scanners/fclones.py` | **[MODIFY]** Validate and accept sanitized thread parameter in `build_group_command()`. |
| `frontend/src/types/index.ts` | **[MODIFY]** Define TypeScript interfaces for `ResourcePolicy`, `EffectiveResourcePolicy`, and `ResourcePolicyUpdate` using standard `number` types. |
| `frontend/src/api/domain.ts` | **[MODIFY]** Add `resourcePolicyApi.getPolicy()` and `updatePolicy()` clients using existing `api.get<T>` / `api.put<T>` pattern. |
| `frontend/src/pages/Settings/index.tsx` | **[MODIFY]** Add Resource Control settings card with soft I/O pressure notices and admission-only status indicators. |
| `frontend/src/components/settings/resource_policy.ts` | **[NEW]** Pure UI helper for formatting options, validation, and notice copy. |

---

## Tasks

### Task 1: ResourcePolicy Persistence & Database Migration

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py`
- Create: `app/resource_control.py`
- Test: `tests/test_gate5f_resource_policy.py`
- Test: `tests/test_gate5f_migration.py`

**Interfaces:**
- Consumes: Existing `Base`, `engine`, `init_db()`, `backup_database()` in `app/db.py`.
- Produces: `ResourcePolicy` ORM class in `app/models.py`.

- [ ] **Step 1: Write failing tests for ResourcePolicy model and migration**

```python
# tests/test_gate5f_migration.py
from pathlib import Path
import pytest
from sqlalchemy import inspect, select, text
from app.db import init_db, create_engine_and_session
from app.models import ResourcePolicy

def test_init_db_creates_resource_policy_singleton(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    inspector = inspect(engine)
    assert "resource_policy" in inspector.get_table_names()

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        assert policy is not None
        assert policy.id == 1
        assert policy.scan_threads == 2
        assert policy.hash_threads == 2
        assert policy.io_limit == "normal"
        assert policy.job_priority == "normal"
        assert policy.active_window_enabled is False
        assert policy.active_window_start is None
        assert policy.active_window_end is None
        assert policy.active_window_timezone is None
        assert policy.outside_window_mode == "limited"
        assert policy.revision == 1

def test_init_db_idempotency_preserves_custom_policy(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.scan_threads = 4
        policy.revision = 2
        session.commit()

    # Re-run init_db
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        assert policy.scan_threads == 4
        assert policy.revision == 2

def test_existing_db_upgrade_triggers_backup_before_creating_table(tmp_path: Path):
    db_file = tmp_path / "legacy.db"
    backups_dir = tmp_path / "backups"
    engine, SessionLocal = create_engine_and_session(db_file)
    # Simulate existing DB with only users and work_jobs
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'admin')"))
        conn.commit()

    init_db(engine, db_path=db_file, backups_dir=backups_dir)

    backup_files = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backup_files) >= 1
    inspector = inspect(engine)
    assert "resource_policy" in inspector.get_table_names()
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_migration.py -v`
Expected: FAIL with `ImportError: cannot import name 'ResourcePolicy' from 'app.models'`.

- [ ] **Step 3: Implement ResourcePolicy model and migration logic**

In `app/models.py`:
```python
class ResourcePolicy(Base):
    __tablename__ = "resource_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    hash_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    io_limit: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    job_priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    active_window_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_window_start: Mapped[str | None] = mapped_column(String(8), nullable=True)
    active_window_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    active_window_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outside_window_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="limited")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_resource_policy_singleton_id"),
        CheckConstraint("scan_threads >= 1 AND scan_threads <= 32", name="ck_resource_policy_scan_threads"),
        CheckConstraint("hash_threads >= 1 AND hash_threads <= 32", name="ck_resource_policy_hash_threads"),
        CheckConstraint("io_limit IN ('low', 'normal', 'unlimited')", name="ck_resource_policy_io_limit"),
        CheckConstraint("job_priority IN ('normal', 'background')", name="ck_resource_policy_job_priority"),
        CheckConstraint("outside_window_mode IN ('limited', 'pause')", name="ck_resource_policy_outside_window_mode"),
        CheckConstraint("revision >= 1", name="ck_resource_policy_revision"),
    )
```

In `app/db.py`:
Add `"resource_policy"` to `required_tables`.
Add singleton seeding after `Base.metadata.create_all(engine)`:
```python
        # Seed singleton ResourcePolicy if not exists
        with SessionLocal() as session:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO resource_policy (
                        id, scan_threads, hash_threads, io_limit, job_priority,
                        active_window_enabled, active_window_start, active_window_end,
                        active_window_timezone, outside_window_mode, revision, updated_at
                    ) VALUES (
                        1, 2, 2, 'normal', 'normal',
                        0, NULL, NULL,
                        NULL, 'limited', 1, CURRENT_TIMESTAMP
                    )
                """)
            )
            session.commit()
```

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_migration.py -v`
Expected: PASS with 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/db.py tests/test_gate5f_migration.py
git commit -m "feat(gate5f): add resource policy persistence"
```

---

### Task 2: Pure Policy Evaluator & Canonical Profile Vocabulary

**Files:**
- Create/Extend: `app/resource_control.py`
- Test: `tests/test_gate5f_resource_policy.py`

**Interfaces:**
- Consumes: Standard library `dataclasses`, `datetime`, `zoneinfo`, `functools.lru_cache`.
- Produces:
  - `ResourcePolicySnapshot` (frozen dataclass)
  - `EffectiveResourcePolicy` (frozen dataclass with `profile: "full" | "limited" | "pause"`)
  - `ResourcePolicyValidationError(ValueError)`
  - `ResourcePolicyConfigError(RuntimeError)`
  - `validate_resource_policy_snapshot(snapshot: ResourcePolicySnapshot) -> None`
  - `evaluate_resource_policy(snapshot: ResourcePolicySnapshot, *, now_utc: datetime) -> EffectiveResourcePolicy`
  - `parse_positive_thread_ceiling(val: Any) -> int | None`
  - `compose_fclones_thread_cap(policy_effective_cap: int, legacy_fclones_threads: Any = None, requested_task_threads: Any = None) -> int`
  - `is_resource_controlled_job(kind: str) -> bool`
  - `resolve_timezone(name: str) -> zoneinfo.ZoneInfo`

- [ ] **Step 1: Write failing tests for pure evaluator**

```python
# tests/test_gate5f_resource_policy.py
import pytest
from datetime import datetime, timezone
from app.resource_control import (
    ResourcePolicySnapshot,
    EffectiveResourcePolicy,
    ResourcePolicyValidationError,
    ResourcePolicyConfigError,
    validate_resource_policy_snapshot,
    evaluate_resource_policy,
    parse_positive_thread_ceiling,
    compose_fclones_thread_cap,
    is_resource_controlled_job,
)

def test_default_policy_evaluation_returns_full_profile():
    snap = ResourcePolicySnapshot(
        scan_threads=2,
        hash_threads=2,
        io_limit="normal",
        job_priority="normal",
        active_window_enabled=False,
        active_window_start=None,
        active_window_end=None,
        active_window_timezone=None,
        outside_window_mode="limited",
        revision=1,
    )
    validate_resource_policy_snapshot(snap)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    eff = evaluate_resource_policy(snap, now_utc=now)
    assert eff.profile == "full"
    assert eff.inside_active_window is None
    assert eff.resource_jobs_admitted is True
    assert eff.effective_thread_cap == 2
    assert eff.revision == 1

def test_io_limit_calculations():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # low limits cap to 1, profile is full
    snap_low = ResourcePolicySnapshot(4, 4, "low", "normal", False, None, None, None, "limited", 1)
    eff_low = evaluate_resource_policy(snap_low, now_utc=now)
    assert eff_low.profile == "full"
    assert eff_low.effective_thread_cap == 1

    # normal limits cap to 2 even if threads configured to 8
    snap_norm = ResourcePolicySnapshot(8, 8, "normal", "normal", False, None, None, None, "limited", 1)
    assert evaluate_resource_policy(snap_norm, now_utc=now).effective_thread_cap == 2

    # unlimited uses min(scan, hash)
    snap_unlim = ResourcePolicySnapshot(8, 6, "unlimited", "normal", False, None, None, None, "limited", 1)
    assert evaluate_resource_policy(snap_unlim, now_utc=now).effective_thread_cap == 6

def test_active_window_same_day_and_cross_midnight():
    # Same-day: 08:00 to 18:00 UTC
    snap_sameday = ResourcePolicySnapshot(4, 4, "normal", "normal", True, "08:00", "18:00", "UTC", "pause", 1)
    validate_resource_policy_snapshot(snap_sameday)
    # 08:00 exact start is inside [inclusive) -> profile 'full'
    eff_in = evaluate_resource_policy(snap_sameday, now_utc=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    assert eff_in.profile == "full"
    assert eff_in.resource_jobs_admitted is True

    # 18:00 exact end is outside [exclusive) -> profile 'pause'
    outside = evaluate_resource_policy(snap_sameday, now_utc=datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc))
    assert outside.resource_jobs_admitted is False
    assert outside.profile == "pause"

    # Cross-midnight: 22:00 to 06:00 UTC
    snap_cross = ResourcePolicySnapshot(4, 4, "normal", "normal", True, "22:00", "06:00", "UTC", "limited", 1)
    validate_resource_policy_snapshot(snap_cross)
    # 23:30 is inside
    assert evaluate_resource_policy(snap_cross, now_utc=datetime(2026, 9, 10, 23, 30, tzinfo=timezone.utc)).profile == "full"
    # 05:59 is inside
    assert evaluate_resource_policy(snap_cross, now_utc=datetime(2026, 9, 11, 5, 59, tzinfo=timezone.utc)).profile == "full"
    # 12:00 is outside -> profile 'limited'
    eff_out = evaluate_resource_policy(snap_cross, now_utc=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc))
    assert eff_out.inside_active_window is False
    assert eff_out.profile == "limited"
    assert eff_out.effective_thread_cap == 1

def test_strict_validation_rejects_malformed_inputs():
    with pytest.raises(ResourcePolicyValidationError):
        # bool masquerading as int
        validate_resource_policy_snapshot(ResourcePolicySnapshot(True, 2, "normal", "normal", False, None, None, None, "limited", 1))
    with pytest.raises(ResourcePolicyValidationError):
        # start == end when active window enabled
        validate_resource_policy_snapshot(ResourcePolicySnapshot(2, 2, "normal", "normal", True, "08:00", "08:00", "UTC", "limited", 1))
    with pytest.raises(ResourcePolicyValidationError):
        # invalid timezone
        validate_resource_policy_snapshot(ResourcePolicySnapshot(2, 2, "normal", "normal", True, "08:00", "18:00", "Mars/Phobos", "limited", 1))

def test_compose_fclones_thread_cap():
    assert compose_fclones_thread_cap(2, None, None) == 2
    assert compose_fclones_thread_cap(2, "1", None) == 1
    assert compose_fclones_thread_cap(2, "8", None) == 2  # cannot raise cap
    assert compose_fclones_thread_cap(6, 4, 3) == 3
    with pytest.raises(ResourcePolicyConfigError):
        compose_fclones_thread_cap(2, "invalid_threads", None)

def test_is_resource_controlled_job():
    assert is_resource_controlled_job("index-root") is True
    assert is_resource_controlled_job("fclones-scan") is True
    assert is_resource_controlled_job("batch-plan-execute") is False
    assert is_resource_controlled_job("quarantine-apply") is False
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_resource_policy.py -v`
Expected: FAIL with missing functions or classes in `app.resource_control`.

- [ ] **Step 3: Implement pure evaluation logic in app/resource_control.py**

Implement:
- `ResourcePolicySnapshot` and `EffectiveResourcePolicy` frozen dataclasses.
- Canonical `profile` assignment:
  - If `not active_window_enabled` or `inside_active_window`: `profile = "full"`, `effective_thread_cap = normal_cap`.
  - If outside window and `outside_window_mode == "limited"`: `profile = "limited"`, `effective_thread_cap = min(normal_cap, 1)`.
  - If outside window and `outside_window_mode == "pause"`: `profile = "pause"`, `resource_jobs_admitted = False`, `effective_thread_cap = min(normal_cap, 1)`.
- Strict type checks: `isinstance(val, int) and not isinstance(val, bool)`.
- Range checks: `1 <= threads <= 32`.
- Enums: `io_limit in ("low", "normal", "unlimited")`, `job_priority in ("normal", "background")`, `outside_window_mode in ("limited", "pause")`.
- Time parser: `HH:MM` where `0 <= HH <= 23` and `0 <= MM <= 59`.
- Cached ZoneInfo resolver via `@lru_cache(maxsize=32)`.
- Never call `os.cpu_count()`.

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_resource_policy.py -v`
Expected: PASS with all tests passing.

- [ ] **Step 5: Commit**

```bash
git add app/resource_control.py tests/test_gate5f_resource_policy.py
git commit -m "feat(gate5f): add resource policy evaluator"
```

---

### Task 3: ResourcePolicy Service & Admin API (Session Auth, Two-Phase PUT & HTTP 422 Semantics)

**Files:**
- Modify: `app/service.py`
- Modify: `app/api/router.py`
- Test: `tests/test_gate5f_resource_policy_api.py`

**Interfaces:**
- Consumes: `ResourcePolicy` ORM, `validate_resource_policy_snapshot`, `evaluate_resource_policy`, `require_admin_user`, existing session auth.
- Produces:
  - `FileCenterService.get_resource_policy() -> dict`
  - `FileCenterService.update_resource_policy(payload: dict) -> dict`
  - `GET /api/settings/resource-policy`
  - `PUT /api/settings/resource-policy` (converts `ResourcePolicyValidationError` to HTTP 422)

- [ ] **Step 1: Write failing API and Service tests using session cookie auth and complete mutation matrix**

```python
# tests/test_gate5f_resource_policy_api.py
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import User
from app.auth.password import hash_password
from app.service import FileCenterService

def make_api_client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    # Seed regular non-admin user
    with service.SessionLocal() as session:
        user = User(
            username="staff_user",
            password_hash=hash_password("StaffPassword123!"),
            role="user",
            is_active=True,
        )
        session.add(user)
        session.commit()
    app = create_app(settings)
    client = TestClient(app)
    return client, service, settings

def test_get_resource_policy_auth_matrix(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)

    # 1. Unauthenticated -> 401
    resp = client.get("/api/settings/resource-policy")
    assert resp.status_code == 401

    # 2. Normal user session -> 403
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "staff_user", "password": "StaffPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200
    user_get = client.get("/api/settings/resource-policy")
    assert user_get.status_code == 403

    # 3. Admin user session -> 200
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert admin_login.status_code == 200
    admin_get = client.get("/api/settings/resource-policy")
    assert admin_get.status_code == 200
    data = admin_get.json()
    assert data["scan_threads"] == 2
    assert data["hash_threads"] == 2
    assert data["revision"] == 1
    assert data["effective_now"]["profile"] == "full"

def test_put_resource_policy_updates_and_increments_revision(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    update_payload = {
        "scan_threads": 4,
        "hash_threads": 4,
        "io_limit": "low",
        "job_priority": "background",
        "active_window_enabled": True,
        "active_window_start": "01:00",
        "active_window_end": "07:00",
        "active_window_timezone": "UTC",
        "outside_window_mode": "pause",
    }
    resp = client.put(
        "/api/settings/resource-policy",
        json=update_payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_threads"] == 4
    assert data["io_limit"] == "low"
    assert data["revision"] == 2

def test_put_resource_policy_semantic_validation_matrix_returns_422(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )

    base_valid = {
        "scan_threads": 2,
        "hash_threads": 2,
        "io_limit": "normal",
        "job_priority": "normal",
        "active_window_enabled": True,
        "active_window_start": "01:00",
        "active_window_end": "07:00",
        "active_window_timezone": "UTC",
        "outside_window_mode": "limited",
    }

    # Matrix of semantic and schema violations
    invalid_cases = [
        ("scan_threads_zero", {**base_valid, "scan_threads": 0}),
        ("scan_threads_bool", {**base_valid, "scan_threads": True}),
        ("hash_threads_too_large", {**base_valid, "hash_threads": 33}),
        ("io_limit_invalid", {**base_valid, "io_limit": "superfast"}),
        ("job_priority_invalid", {**base_valid, "job_priority": "urgent"}),
        ("outside_window_mode_invalid", {**base_valid, "outside_window_mode": "halt"}),
        ("window_start_equals_end", {**base_valid, "active_window_start": "08:00", "active_window_end": "08:00"}),
        ("timezone_invalid", {**base_valid, "active_window_timezone": "Invalid/Zone"}),
        ("extra_field_forbidden", {**base_valid, "unexpected_field": 123}),
    ]

    for name, payload in invalid_cases:
        resp = client.put(
            "/api/settings/resource-policy",
            json=payload,
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 422, f"Failed on case {name}: {resp.text}"

        # Verify DB unchanged
        get_resp = client.get("/api/settings/resource-policy")
        assert get_resp.json()["revision"] == 1
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_resource_policy_api.py -v`
Expected: FAIL with 404 (endpoint not defined).

- [ ] **Step 3: Implement service methods with safe two-phase PUT and router endpoints**

In `app/service.py`:
```python
    def get_resource_policy(self) -> dict:
        with self.SessionLocal() as session:
            row = session.get(ResourcePolicy, 1)
            if row is None:
                raise RuntimeError("ResourcePolicy singleton missing")
            snapshot = ResourcePolicySnapshot(
                scan_threads=row.scan_threads,
                hash_threads=row.hash_threads,
                io_limit=row.io_limit,
                job_priority=row.job_priority,
                active_window_enabled=row.active_window_enabled,
                active_window_start=row.active_window_start,
                active_window_end=row.active_window_end,
                active_window_timezone=row.active_window_timezone,
                outside_window_mode=row.outside_window_mode,
                revision=row.revision,
            )
            validate_resource_policy_snapshot(snapshot)
            eff = evaluate_resource_policy(snapshot, now_utc=utcnow())
            data = row.__dict__.copy()
            data.pop("_sa_instance_state", None)
            data["effective_now"] = {
                "profile": eff.profile,
                "inside_active_window": eff.inside_active_window,
                "resource_jobs_admitted": eff.resource_jobs_admitted,
                "effective_thread_cap": eff.effective_thread_cap,
            }
            return data

    def update_resource_policy(self, payload: dict) -> dict:
        # Phase A: Outside DB write transaction
        # Validate semantic constraints, parse HH:MM, pre-resolve and cache ZoneInfo
        temp_snapshot = ResourcePolicySnapshot(
            scan_threads=payload["scan_threads"],
            hash_threads=payload["hash_threads"],
            io_limit=payload["io_limit"],
            job_priority=payload["job_priority"],
            active_window_enabled=payload["active_window_enabled"],
            active_window_start=payload.get("active_window_start"),
            active_window_end=payload.get("active_window_end"),
            active_window_timezone=payload.get("active_window_timezone"),
            outside_window_mode=payload["outside_window_mode"],
            revision=1, # evaluated against DB truth in Phase B
        )
        validate_resource_policy_snapshot(temp_snapshot)

        # Phase B: Short SQLite BEGIN IMMEDIATE write transaction (Zero ZoneInfo file I/O)
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(ResourcePolicy, 1)
            if row is None:
                session.rollback()
                raise RuntimeError("ResourcePolicy singleton missing")
            row.scan_threads = temp_snapshot.scan_threads
            row.hash_threads = temp_snapshot.hash_threads
            row.io_limit = temp_snapshot.io_limit
            row.job_priority = temp_snapshot.job_priority
            row.active_window_enabled = temp_snapshot.active_window_enabled
            row.active_window_start = temp_snapshot.active_window_start
            row.active_window_end = temp_snapshot.active_window_end
            row.active_window_timezone = temp_snapshot.active_window_timezone
            row.outside_window_mode = temp_snapshot.outside_window_mode
            row.revision = row.revision + 1
            row.updated_at = utcnow()
            session.commit()

        return self.get_resource_policy()
```

In `app/api/router.py`:
```python
class ResourcePolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scan_threads: int = Field(..., ge=1, le=32)
    hash_threads: int = Field(..., ge=1, le=32)
    io_limit: Literal["low", "normal", "unlimited"]
    job_priority: Literal["normal", "background"]
    active_window_enabled: bool
    active_window_start: str | None = None
    active_window_end: str | None = None
    active_window_timezone: str | None = None
    outside_window_mode: Literal["limited", "pause"]

@router.put("/settings/resource-policy", dependencies=[Depends(require_admin_user)])
def update_resource_policy_endpoint(
    payload: ResourcePolicyUpdateRequest,
    service: FileCenterService = Depends(get_service),
):
    try:
        return service.update_resource_policy(payload.model_dump())
    except ResourcePolicyValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
```

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_resource_policy_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service.py app/api/router.py tests/test_gate5f_resource_policy_api.py
git commit -m "feat(gate5f): expose admin resource policy api"
```

---

### Task 4: Resource-Aware Worker Claim Admission (Isolated DB & Deterministic Time)

**Files:**
- Modify: `app/tasks/recovery.py`
- Use: `app/resource_control.py`
- Test: `tests/test_gate5f_resource_claim.py`

**Interfaces:**
- Consumes: `claim_next_job()`, `assert_active_worker_lease()`, `ResourcePolicy`, `evaluate_resource_policy()`.
- Produces: Enhanced `claim_next_job()` with deterministic two-phase policy preparation, pause window holding, and background priority reordering.

- [ ] **Step 1: Write failing tests for claim admission using isolated DB helper**

```python
# tests/test_gate5f_resource_claim.py
from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import claim_next_job, acquire_worker_ownership
from app.models import WorkJob, ResourcePolicy

FROZEN_OUTSIDE_TIME = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
FROZEN_INSIDE_TIME = datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc)

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_claim_outside_pause_window_holds_resource_job_queued(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-test-1"

    # Configure active window 01:00-03:00 UTC (FROZEN_OUTSIDE_TIME 12:00 is outside)
    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = True
        policy.active_window_start = "01:00"
        policy.active_window_end = "03:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"
        policy.revision = 2

        job = WorkJob(kind="index-root", status="queued", state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_OUTSIDE_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True

        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed is None

    # Job remains queued (not paused, not failed, not cancelled)
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == "queued"

def test_claim_outside_pause_window_allows_mutation_job(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-test-2"
    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = True
        policy.active_window_start = "01:00"
        policy.active_window_end = "03:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"

        j1 = WorkJob(id=101, kind="index-root", status="queued", state_json="{}")
        j2 = WorkJob(id=102, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_OUTSIDE_TIME):
        acquire_worker_ownership(engine, SessionLocal, worker_id)
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 102

def test_background_priority_claims_non_resource_job_first(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-test-3"
    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.job_priority = "background"
        policy.active_window_enabled = False

        j1 = WorkJob(id=201, kind="fclones-scan", status="queued", state_json="{}")
        j2 = WorkJob(id=202, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_INSIDE_TIME):
        acquire_worker_ownership(engine, SessionLocal, worker_id)
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 202
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_resource_claim.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement two-phase claim pattern in app/tasks/recovery.py**

Implement:
- **Phase A (Outside write lock)**:
  Read `ResourcePolicy(1)`.
  If missing/unparseable, set `policy_valid = False` and `resource_jobs_admitted = False`.
  If valid, resolve timezone via cached `resolve_timezone()` and compute `EffectiveResourcePolicy`.
- **Phase B (`BEGIN IMMEDIATE`)**:
  `assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)`.
  Re-read `ResourcePolicy(1)`.
  If revision or policy fields differ from Phase A, rollback and retry Phase A (bounded up to 3 attempts).
  Candidate query:
  - If `resource_jobs_admitted is False`: filter `WorkJob.kind.not_in(["index-root", "fclones-scan"])`.
  - If `resource_jobs_admitted is True` and `job_priority == "background"`:
    First query non-resource-controlled queued jobs; if none, query resource-controlled queued jobs.
  - If `job_priority == "normal"`: standard FIFO query.
  Select candidate ID, update to `JobState.RUNNING.value`, commit and return candidate ID.

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_resource_claim.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/tasks/recovery.py tests/test_gate5f_resource_claim.py
git commit -m "feat(gate5f): add resource-aware task admission"
```

---

### Task 5: fclones Effective Thread Ceiling & Subprocess Isolation (Executable Tests)

**Files:**
- Modify: `app/tasks/handlers.py`
- Modify: `app/scanners/fclones.py`
- Use: `app/resource_control.py`
- Test: `tests/test_gate5f_fclones_resources.py`

**Interfaces:**
- Consumes: `compose_fclones_thread_cap`, `ResourcePolicy`, `build_group_command`, `JobContext.log`.
- Produces:
  - Bounded `--threads <N>` argument in fclones command.
  - TaskEvent `resource_policy_applied` recorded via `context.log()`.
  - Deterministic test verification without report parsing or worker lease fencing.

- [ ] **Step 1: Write failing tests with report isolation and exact log assertions**

```python
# tests/test_gate5f_fclones_resources.py
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from app.db import create_engine_and_session, init_db
from app.tasks.handlers import FclonesScanHandler
from app.models import WorkJob, ResourcePolicy
from app.resource_control import ResourcePolicyConfigError

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_fclones_scan_handler_applies_effective_threads_and_logs(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = FclonesScanHandler()
    job = WorkJob(id=1, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 1}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None  # Prevent mock lease check failure
    settings = MagicMock()
    settings.allowed_roots = ["/allowed/root"]
    settings.reports_dir = tmp_path
    settings.fclones_binary = "fclones"
    settings.fclones_threads = "4"  # legacy setting

    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.scan_threads = 2
        p.hash_threads = 2
        p.io_limit = "normal"
        session.commit()

    with patch("app.tasks.handlers.build_group_command") as mock_build,          patch("app.tasks.handlers.run_scan") as mock_run,          patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(())):
        mock_run.return_value.returncode = 0
        handler.run(job, context, settings)

        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["threads"] == "2"

        # Exact dictionary-field assertion on logged context
        call_args_list = [c for c in context.log.call_args_list if c[0][0] == "resource_policy_applied"]
        assert len(call_args_list) >= 1
        logged_ctx = call_args_list[0][1]["context"]
        assert logged_ctx["resource_policy_revision"] == 1
        assert logged_ctx["profile"] == "full"
        assert logged_ctx["effective_thread_cap"] == 2

def test_fclones_scan_corrupt_policy_fails_closed_before_subprocess(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = FclonesScanHandler()
    job = WorkJob(id=2, kind="fclones-scan", state_json='{"roots": ["/allowed/root"], "scan_job_id": 2}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None
    settings = MagicMock()
    settings.allowed_roots = ["/allowed/root"]
    settings.reports_dir = tmp_path
    settings.fclones_threads = "invalid_threads_format"

    with patch("app.tasks.handlers.run_scan") as mock_run:
        with pytest.raises(ResourcePolicyConfigError):
            handler.run(job, context, settings)
        mock_run.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_fclones_resources.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement fclones thread composition in handlers.py & fclones.py**

In `app/tasks/handlers.py` (`FclonesScanHandler.run`):
- Load current `ResourcePolicy(1)` snapshot from DB.
- Evaluate `EffectiveResourcePolicy`.
- Calculate `effective_threads = compose_fclones_thread_cap(eff.effective_thread_cap, settings.fclones_threads, state.get("threads"))`.
- If invalid configuration ceiling is detected, fail-closed before subprocess launch: record error via `context.log(..., level="error")` and raise `ResourcePolicyConfigError`.
- Call `build_group_command(..., threads=str(effective_threads))`.
- Log TaskEvent via `context.log("resource_policy_applied", "Applied resource policy", context={"resource_policy_revision": eff.revision, "profile": eff.profile, "effective_thread_cap": effective_threads})`.

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_fclones_resources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/tasks/handlers.py app/scanners/fclones.py tests/test_gate5f_fclones_resources.py
git commit -m "feat(gate5f): enforce bounded fclones resources"
```

---

### Task 6: Index-Root Resource Control Behavior (Real Settings & Real Seam)

**Files:**
- Modify (minimally, for `context.log`): `app/tasks/handlers.py`
- Test: `tests/test_gate5f_index_resources.py`

**Interfaces:**
- Consumes: `IndexRootHandler`, `FileCenterService.reindex_root`, `ResourcePolicy`, `JobContext.log`.
- Produces: Deterministic serial execution maintained (concurrency = 1); TaskEvent `resource_policy_applied` logged via `context.log()`.

- [ ] **Step 1: Write failing tests using real settings and real service seam**

```python
# tests/test_gate5f_index_resources.py
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.tasks.handlers import IndexRootHandler
from app.models import WorkJob

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_index_root_maintains_serial_execution(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    handler = IndexRootHandler()
    job = WorkJob(id=2, kind="index-root", state_json='{"root": "/allowed/root"}')
    context = MagicMock()
    context.SessionLocal = SessionLocal
    context.worker_id = None

    # Real Settings object with isolated temporary directories
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
    )

    with patch("app.service.FileCenterService.reindex_root") as mock_reindex:
        mock_reindex.return_value = {"files": 10, "folders": 2}
        handler.run(job, context, settings)

        mock_reindex.assert_called_once()
        call_args_list = [c for c in context.log.call_args_list if c[0][0] == "resource_policy_applied"]
        assert len(call_args_list) >= 1
        logged_ctx = call_args_list[0][1]["context"]
        assert logged_ctx["profile"] == "full"
        assert logged_ctx["execution_concurrency"] == 1
```

- [ ] **Step 2: Run tests to verify they fail (RED)**

Run: `pytest tests/test_gate5f_index_resources.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement diagnostic logging in IndexRootHandler**

In `app/tasks/handlers.py` (`IndexRootHandler.run`):
- Capture `ResourcePolicySnapshot`.
- Log TaskEvent via `context.log("resource_policy_applied", "Applied resource policy", context={"profile": eff.profile, "policy_thread_cap": eff.effective_thread_cap, "execution_concurrency": 1})`.
- Ensure no thread pool or parallel traversal is created.

- [ ] **Step 4: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_index_resources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/tasks/handlers.py tests/test_gate5f_index_resources.py
git commit -m "test(gate5f): lock index resource admission semantics"
```

---

### Task 7: Running-Job Window Transition Semantics (Frozen Time Enclosing Lease Acquisition)

**Files:**
- Test: `tests/test_gate5f_running_job_semantics.py`
- Modify (only if needed): `app/tasks/handlers.py`, `app/tasks/recovery.py`

**Interfaces:**
- Consumes: Non-resumable contracts `supports_pause = False` for `index-root` and `fclones-scan`.
- Produces: Concrete verification that running jobs are never killed or fake-paused when policy transitions to pause outside window, with lease and claims evaluated under unified frozen time.

- [ ] **Step 1: Write comprehensive running job boundary tests with unified frozen time**

```python
# tests/test_gate5f_running_job_semantics.py
from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.models import WorkJob, ResourcePolicy
from app.tasks.handlers import FclonesScanHandler, IndexRootHandler
from app.tasks.recovery import acquire_worker_ownership, claim_next_job

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_handlers_declare_supports_pause_false():
    assert FclonesScanHandler.supports_pause is False
    assert IndexRootHandler.supports_pause is False

def test_running_job_remains_running_on_window_transition(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-transition-test"

    with SessionLocal() as session:
        # Initially inside full profile (active window disabled)
        p = session.get(ResourcePolicy, 1)
        p.active_window_enabled = False
        p.revision = 1

        # Job 501 is RUNNING, Job 502 is queued index-root, Job 503 is queued batch mutation
        j1 = WorkJob(id=501, kind="fclones-scan", status="running", state_json='{"roots": ["/allowed/root"]}')
        j2 = WorkJob(id=502, kind="index-root", status="queued", state_json='{"root": "/allowed/root"}')
        j3 = WorkJob(id=503, kind="batch-plan-execute", status="queued", state_json='{}')
        session.add_all([j1, j2, j3])
        session.commit()

    # Transition policy: outside active window with mode = pause
    fixed_outside = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.active_window_enabled = True
        p.active_window_start = "01:00"
        p.active_window_end = "06:00"
        p.active_window_timezone = "UTC"
        p.outside_window_mode = "pause"
        p.revision = 2
        session.commit()

    # Freezing time before lease acquisition ensures clock consistency across operations
    with patch("app.tasks.recovery.utcnow", return_value=fixed_outside):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True

        claimed_mutation = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed_mutation == 503

        # Next claim sees only resource-controlled queued job j2 -> returns None
        claimed_none = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed_none is None

    # Assert running job 501 is NOT killed, NOT fake-paused, NOT failed
    with SessionLocal() as session:
        current_j1 = session.get(WorkJob, 501)
        assert current_j1.status == "running"
        assert current_j1.pause_requested_at is None
        assert current_j1.cancel_requested_at is None
        assert current_j1.error_code is None

        current_j2 = session.get(WorkJob, 502)
        assert current_j2.status == "queued"
```

- [ ] **Step 2: Run tests to verify they pass (GREEN)**

Run: `pytest tests/test_gate5f_running_job_semantics.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gate5f_running_job_semantics.py
git commit -m "test(gate5f): preserve non-resumable running jobs"
```

---

### Task 8: Frontend Resource Control Settings (TypeScript & Real API Client)

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/domain.ts`
- Modify: `frontend/src/pages/Settings/index.tsx`
- Create: `frontend/src/components/settings/resource_policy.ts`

**Interfaces:**
- Consumes: `useAuth()` (`isAdmin`), Ant Design, `@tanstack/react-query`, `api` from `./client`.
- Produces:
  - TypeScript types: `ResourcePolicy`, `EffectiveResourcePolicy`, `ResourcePolicyUpdate` with `number` types and `profile: 'full' | 'limited' | 'pause'`.
  - API client: `resourcePolicyApi.getPolicy()`, `resourcePolicyApi.updatePolicy()`.
  - Resource Control card in `SettingsPage` with soft concurrency notices.

- [ ] **Step 1: Add frontend types and API client**

In `frontend/src/types/index.ts`:
```typescript
export interface EffectiveResourcePolicy {
  profile: 'full' | 'limited' | 'pause';
  inside_active_window: boolean | null;
  resource_jobs_admitted: boolean;
  effective_thread_cap: number;
}

export interface ResourcePolicy {
  id: number;
  scan_threads: number;
  hash_threads: number;
  io_limit: 'low' | 'normal' | 'unlimited';
  job_priority: 'normal' | 'background';
  active_window_enabled: boolean;
  active_window_start: string | null;
  active_window_end: string | null;
  active_window_timezone: string | null;
  outside_window_mode: 'limited' | 'pause';
  revision: number;
  updated_at: string | null;
  effective_now: EffectiveResourcePolicy;
}

export interface ResourcePolicyUpdate {
  scan_threads: number;
  hash_threads: number;
  io_limit: 'low' | 'normal' | 'unlimited';
  job_priority: 'normal' | 'background';
  active_window_enabled: boolean;
  active_window_start?: string | null;
  active_window_end?: string | null;
  active_window_timezone?: string | null;
  outside_window_mode: 'limited' | 'pause';
}
```

In `frontend/src/api/domain.ts`:
```typescript
export const resourcePolicyApi = {
  getPolicy: () =>
    api.get<ResourcePolicy>('/api/settings/resource-policy'),
  updatePolicy: (payload: ResourcePolicyUpdate) =>
    api.put<ResourcePolicy>('/api/settings/resource-policy', payload),
};
```

- [ ] **Step 2: Implement UI card in SettingsPage and validation helper**

In `frontend/src/pages/Settings/index.tsx`:
- Enable React Query `queryKey: ['resourcePolicy']` only when `isAdmin === true`.
- Render Card "资源控制 / Resource Control":
  - Form inputs: scan thread ceiling (1..32), hash thread ceiling (1..32).
  - Select for IO pressure: low, normal, unlimited.
  - Select for Job priority: normal, background.
  - Switch for Active window enabled.
  - When enabled: start time, end time, IANA timezone selector, outside-window mode (limited / pause).
  - Status display: current effective profile (`full`, `limited`, `pause`), effective thread cap, resource jobs admitted/held, revision.
  - Clear notices:
    - "I/O pressure is application-level concurrency control. It is not guaranteed MB/s or IOPS throttling."
    - "Outside-window Pause does not schedule jobs. It only holds queued scan/index jobs from starting."

- [ ] **Step 3: Run frontend typecheck and build**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: PASS with 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/domain.ts frontend/src/pages/Settings/index.tsx frontend/src/components/settings/resource_policy.ts
git commit -m "feat(gate5f): add resource control settings ui"
```

---

### Task 9: Failure & Corruption Safety (Deterministically Corrupted & Missing Singleton)

**Files:**
- Create: `tests/test_gate5f_fail_closed.py`
- Modify (if needed for safety guards): `app/tasks/recovery.py`, `app/resource_control.py`

**Interfaces:**
- Consumes: Corrupted DB states (active window with invalid timezone, missing singleton row).
- Produces: Resource-controlled jobs fail closed without CPU-count fallback; non-resource mutation jobs remain claimable.

- [ ] **Step 1: Write failing safety tests for enabled corrupt window and missing singleton**

```python
# tests/test_gate5f_fail_closed.py
from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import text
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import claim_next_job, acquire_worker_ownership
from app.models import WorkJob

FROZEN_TIME = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_corrupted_active_window_holds_resource_job_but_allows_mutation(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fail-closed-1"

    # Deterministically force timezone evaluation by enabling window
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE resource_policy
            SET active_window_enabled = 1,
                active_window_start = '01:00',
                active_window_end = '03:00',
                active_window_timezone = 'Invalid/Zone'
            WHERE id = 1
        """))
        conn.commit()

    with SessionLocal() as session:
        j1 = WorkJob(id=301, kind="fclones-scan", status="queued", state_json="{}")
        j2 = WorkJob(id=302, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True
        # j1 fails closed (cannot be claimed safely under invalid policy)
        # j2 is mutation and must still be claimed to prevent global engine outage
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 302

def test_missing_singleton_holds_resource_job_but_allows_mutation(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fail-closed-2"

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM resource_policy WHERE id = 1"))
        conn.commit()

    with SessionLocal() as session:
        j1 = WorkJob(id=303, kind="index-root", status="queued", state_json="{}")
        j2 = WorkJob(id=304, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 304
```

- [ ] **Step 2: Run tests to verify (RED)**

Run: `pytest tests/test_gate5f_fail_closed.py -v`
Expected: FAIL if corrupted policy causes crash or blocks mutation jobs.

- [ ] **Step 3: Ensure robust error boundary in claim_next_job**

In `app/tasks/recovery.py`:
If `ResourcePolicy` is missing or fails validation or timezone resolution:
- Mark `resource_policy_valid = False`.
- Exclude resource-controlled job kinds (`index-root`, `fclones-scan`).
- Permit non-resource-controlled jobs to proceed normally.

- [ ] **Step 4: Run tests to verify (GREEN)**

Run: `pytest tests/test_gate5f_fail_closed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/tasks/recovery.py tests/test_gate5f_fail_closed.py
git commit -m "fix(gate5f): fail closed without blocking mutation jobs"
```

---

### Task 10: Full Regression Verification Gate (Frozen Concrete Suites)

**Files:**
- Full backend suite: `tests/`
- Full frontend suite: `frontend/`

- [ ] **Step 1: Run Gate5-F focused tests**
```bash
pytest tests/test_gate5f_resource_policy.py -v
pytest tests/test_gate5f_migration.py -v
pytest tests/test_gate5f_resource_policy_api.py -v
pytest tests/test_gate5f_resource_claim.py -v
pytest tests/test_gate5f_fclones_resources.py -v
pytest tests/test_gate5f_index_resources.py -v
pytest tests/test_gate5f_running_job_semantics.py -v
pytest tests/test_gate5f_fail_closed.py -v
```

- [ ] **Step 2: Run all Gate5-F tests together**
```bash
pytest tests/test_gate5f_*.py -v
```

- [ ] **Step 3: Run frozen existing Task Engine & Worker suites**
```bash
pytest tests/test_worker_recovery_and_claim.py tests/test_task_state_machine.py tests/test_task_api.py tests/test_task_checkpoint.py tests/test_task_pause_resume_e2e.py tests/test_gate2_hotfix1_worker_fencing.py -v
```

- [ ] **Step 4: Run frozen existing Fclones & Indexing suites**
```bash
pytest tests/test_fclones.py tests/test_scan_jobs.py tests/test_indexing.py tests/test_index_root_lifecycle.py tests/test_index_root_progress_regression.py -v
```

- [ ] **Step 5: Run closed gate safety regression suites**
```bash
pytest tests/test_gate5e_*.py -v
pytest tests/test_gate5d_*.py -v
pytest tests/test_gate5c_*.py -v
pytest tests/test_gate5b_*.py -v
pytest tests/test_gate5a_*.py -v
pytest tests/test_planning.py tests/test_execution.py -v
```

- [ ] **Step 6: Run full repository pytest suite**
```bash
pytest tests/
```

- [ ] **Step 7: Verify frontend typecheck and build**
```bash
cd frontend && npm run typecheck && npm run build
```

- [ ] **Step 8: Verify clean workspace**
```bash
git diff --check
git status --short
```

---

## No Scope Drift Checklist

- [ ] No Scheduler or Cron introduced.
- [ ] No automatic time-based job creation.
- [ ] No second worker or parallel WorkJob execution introduced.
- [ ] No TaskLock or WorkerState state machine redesign.
- [ ] No changes to filesystem mutation, quarantine, or restore invariants.
- [ ] No changes to Gate3 identity authority or Plan/Freeze/Validate/Execute semantics.
- [ ] ResourcePolicy never participates in Preview digest, Draft identity, Freeze identity, or OperationJournal identity.
- [ ] No hard MB/s rate limiting or cgroup/ionice dependencies.
- [ ] `os.cpu_count()` is never called to scale thread caps.
- [ ] `index-root` serial execution is strictly preserved (no indexer parallelization).
- [ ] Gate5-G remains completely untouched and forbidden.
