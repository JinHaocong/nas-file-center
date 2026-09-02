# NAS Dedupe Center V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Docker-deployable NAS duplicate-file management service that uses fclones for read-only discovery and a thin Python safety layer for planning, SHA-256 validation, guarded deletion, audit logging, and the optional 少女映画 organizer profile.

**Architecture:** A single FastAPI service invokes fclones as a subprocess and stores completed scan reports plus imported duplicate groups in SQLite. Planning and destructive execution are separate modules; frozen plans are independently verified before deletion, and organizer behavior is isolated from generic dedupe behavior.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite/WAL, Jinja2, Pydantic Settings, pytest, httpx, fclones 0.35.0, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-nas-dedupe-center-design.md`

## Global Constraints

- fclones is discovery-only; never invoke `fclones remove`, `link`, or `dedupe`.
- Default deployment is read-only and deletion additionally requires `ALLOW_DELETE=true`.
- Allowed dataset roots are server-configured and every filesystem path is containment-checked after resolution.
- Frozen plan items are immutable inputs to validation/execution.
- SHA-256 verification is required immediately before deletion.
- Never recursively delete directories and never use shell interpolation for filenames.
- Only one disk-intensive task may run at a time.
- SQLite uses WAL mode and execution creates a DB backup first.
- V1 has no unattended deletion, multi-user auth, scheduler, reflink, hardlink replacement, or distributed workers.

---

### Task 1: Project foundation, configuration, database, and path safety

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/models.py`
- Create: `app/path_safety.py`
- Create: `tests/test_config_and_paths.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Produces: `Settings`, `get_settings()`, `is_path_allowed(path, roots)`, `require_allowed_path(path, roots)`, SQLAlchemy `Base`, session factory, and persisted scan/plan/audit models.

- [ ] **Step 1: Write failing tests** for allowed-root parsing, resolved containment, symlink escape rejection, WAL setup, and model creation.
- [ ] **Step 2: Run tests and verify RED** with missing modules/imports.
- [ ] **Step 3: Implement minimal configuration, path safety, database setup, and models.**
- [ ] **Step 4: Run tests and verify GREEN.**
- [ ] **Step 5: Commit foundation.**

### Task 2: fclones command builder, runner, and tolerant JSON parser

**Files:**
- Create: `app/scanners/__init__.py`
- Create: `app/scanners/fclones.py`
- Create: `app/scanners/parser.py`
- Create: `tests/test_fclones.py`
- Create: `tests/fixtures/fclones_report.json`

**Interfaces:**
- Consumes: `Settings`, path safety.
- Produces: `build_group_command(...) -> list[str]`, `run_scan(...)`, `parse_fclones_report(...) -> list[ParsedGroup]`.

- [ ] **Step 1: Write failing tests** covering absolute roots, `--cache`, `--format json`, `--no-ignore`, `--hidden`, optional `--isolate`, minimum size, and JSON group parsing.
- [ ] **Step 2: Run tests and verify RED.**
- [ ] **Step 3: Implement command construction, subprocess execution without `shell=True`, raw report atomic write, and tolerant JSON parsing.**
- [ ] **Step 4: Run tests and verify GREEN.**
- [ ] **Step 5: Commit scanner integration.**

### Task 3: Plan policies and frozen plan generation

**Files:**
- Create: `app/planning/__init__.py`
- Create: `app/planning/policies.py`
- Create: `app/planning/engine.py`
- Create: `tests/test_planning.py`

**Interfaces:**
- Consumes: imported duplicate groups/files.
- Produces: deterministic `keep-first-root`, `keep-newest`, `keep-oldest`, and `balanced-roots` assignments plus directory protection accounting.

- [ ] **Step 1: Write failing tests** for each policy, 50/50 balanced A/B allocation, odd group allocation, multi-member groups, and final-file protection.
- [ ] **Step 2: Run tests and verify RED.**
- [ ] **Step 3: Implement deterministic policy selection and frozen plan creation.**
- [ ] **Step 4: Run tests and verify GREEN.**
- [ ] **Step 5: Commit planning engine.**

### Task 4: Independent validation, guarded execution, backup, and audit

**Files:**
- Create: `app/execution/__init__.py`
- Create: `app/execution/verifier.py`
- Create: `app/execution/executor.py`
- Create: `tests/test_execution.py`

**Interfaces:**
- Produces: `verify_pair(...)`, `validate_plan(...)`, `execute_plan(...)` with explicit safe-skip results and append-only audit events.

- [ ] **Step 1: Write failing tests** for deletion disabled, symlink rejection, changed size/hash skip, same inode rejection, valid deletion, DB backup, and protected-directory last-file skip.
- [ ] **Step 2: Run tests and verify RED.**
- [ ] **Step 3: Implement SHA-256 streaming verifier and `os.unlink` executor with per-item revalidation.**
- [ ] **Step 4: Run tests and verify GREEN.**
- [ ] **Step 5: Commit execution safety.**

### Task 5: 少女映画 organizer profile

**Files:**
- Create: `app/organizers/__init__.py`
- Create: `app/organizers/shaonv.py`
- Create: `tests/test_organizer.py`

**Interfaces:**
- Produces: trailing stat stripping, recursive P/V/bytes calculation, rename preview/apply, and ordered mtime refresh.

- [ ] **Step 1: Write failing tests** for repeated stat suffix stripping while preserving `[存疑]`, image/video counts, size formatting, rename preview, and ordered mtime refresh.
- [ ] **Step 2: Run tests and verify RED.**
- [ ] **Step 3: Implement organizer profile without coupling it to generic dedupe.**
- [ ] **Step 4: Run tests and verify GREEN.**
- [ ] **Step 5: Commit organizer.**

### Task 6: FastAPI service, minimal Web UI, Docker, and end-to-end smoke coverage

**Files:**
- Create: `app/main.py`
- Create: `app/service.py`
- Create: `app/web/__init__.py`
- Create: `app/web/routes.py`
- Create: `app/web/templates/base.html`
- Create: `app/web/templates/dashboard.html`
- Create: `app/web/templates/scan.html`
- Create: `app/web/templates/plan.html`
- Create: `app/web/static/app.css`
- Create: `tests/test_api.py`
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `config.example.env`
- Create: `.dockerignore`
- Create: `.gitignore`
- Create: `README.md`

**Interfaces:**
- Exposes: health, scan create/read/groups, plan create/read/freeze/validate/execute, organizer preview/apply, and HTML dashboard routes from the spec.

- [ ] **Step 1: Write failing API tests** for health, scan validation, plan lifecycle guardrails, and delete-disabled execution.
- [ ] **Step 2: Run tests and verify RED.**
- [ ] **Step 3: Implement service orchestration and API/UI routes.**
- [ ] **Step 4: Add Dockerfile that installs pinned fclones 0.35.0 with Cargo in a builder stage and a compose file defaulting the data mount to read-only.**
- [ ] **Step 5: Run full pytest suite, import/compile checks, and compose config validation if Docker is available.**
- [ ] **Step 6: Update README with 极空间 deployment instructions, safe-mode first-run flow, execute-mode opt-in, and rollback/backup notes.**
- [ ] **Step 7: Commit V1.**
