# NAS File Center v0.2 UI + ZFS Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ZFS large-inode persistence and add a Chinese browser-first UI over the existing safe NAS File Center service layer.

**Architecture:** Keep the JSON API and service layer as the source of truth. Add a SQLite-safe filesystem identifier type, service read-model methods, Jinja2 UI routes/templates, and bundled local static assets in the same FastAPI image.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, Jinja2, locally bundled Bootstrap 5.1.1 + Bootstrap Icons, small vanilla JavaScript, fclones.

**Spec:** `docs/superpowers/specs/2026-09-02-nas-file-center-v0.2-ui-design.md`

## Global Constraints

- Do not introduce a Node/frontend build chain.
- Do not load JS/CSS from external CDNs.
- Keep `/data` read-only compatible and respect `ALLOW_MUTATION=false`.
- All destructive plan execution continues through existing verifier/executor code.
- Existing JSON API routes remain compatible.

---

### Task 1: ZFS-safe filesystem identifier persistence

**Files:**
- Create: `app/dbtypes.py`
- Modify: `app/models.py`
- Test: `tests/test_fs_identifiers.py`

**Interfaces:**
- Produces: `FilesystemId` SQLAlchemy type that round-trips Python `int` while binding non-numeric text.

- [ ] Write a failing database round-trip test with inode `12164156718799206349`.
- [ ] Run it and confirm SQLite overflow.
- [ ] Implement `FilesystemId` and use it for filesystem device/inode columns.
- [ ] Run focused and full tests.

### Task 2: UI read models

**Files:**
- Modify: `app/service.py`
- Test: `tests/test_ui_service.py`

**Interfaces:**
- Produces: dashboard/list/detail methods for scans, duplicate groups, plans, jobs, audit events and index roots.

- [ ] Write failing tests for dashboard/list methods.
- [ ] Implement focused read-model queries with bounded limits.
- [ ] Run focused and full tests.

### Task 3: Chinese UI routes and templates

**Files:**
- Create: `app/web.py`
- Create: `app/templates/base.html`
- Create: `app/templates/dashboard.html`
- Create: `app/templates/scans.html`
- Create: `app/templates/scan_detail.html`
- Create: `app/templates/plans.html`
- Create: `app/templates/plan_detail.html`
- Create: `app/templates/rename.html`
- Create: `app/templates/organizer.html`
- Create: `app/templates/indexes.html`
- Create: `app/templates/jobs.html`
- Create: `app/templates/audit.html`
- Create: `app/templates/settings.html`
- Create: `app/templates/path_match.html`
- Create: `app/templates/batch.html`
- Create: `app/templates/error.html`
- Modify: `app/main.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: existing `FileCenterService` API plus Task 2 read models.
- Produces: browser-first routes under `/ui/*` and dashboard `/`.

- [ ] Write failing smoke/form tests.
- [ ] Add router and templates.
- [ ] Wire forms to existing service methods with redirect-after-post.
- [ ] Verify mutation actions are disabled/guarded in safe mode.
- [ ] Run UI and full tests.

### Task 4: Bundled UI assets and packaging

**Files:**
- Create: `app/static/vendor/bootstrap.min.css`
- Create: `app/static/vendor/bootstrap.bundle.min.js`
- Create: `app/static/vendor/bootstrap-icons.min.css`
- Create: `app/static/app.css`
- Create: `app/static/app.js`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: self-contained image assets with no CDN runtime dependency.

- [ ] Add asset-serving test.
- [ ] Add responsive CSS and local auto-refresh JS.
- [ ] Configure package-data inclusion for templates/static.
- [ ] Document v0.2 UI workflow and upgrade steps.
- [ ] Run full verification: tests, compileall, package build metadata inspection.
