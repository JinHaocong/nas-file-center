# NAS File Center V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the existing fclones-backed NAS Dedupe Center into a safe NAS file batch-processing center with incremental indexing, generic mutation plans, flexible duplicate keep policies, quarantine, resumability, organizer statistics, and a minimal Web UI.

**Architecture:** Keep fclones as discovery-only. Persist filesystem/index/plan state in SQLite, generate deterministic immutable plans, validate each item at execution time, and route all mutations through one audited executor. Generic filesystem capabilities live outside organizer-specific code.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.x, SQLite/WAL, Jinja2, Pydantic Settings, pytest, fclones 0.35.0, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-nas-file-center-v1-design.md`

## Global Constraints

- Never use fclones destructive subcommands.
- Default deployment mounts datasets read-only.
- Permanent unlink additionally requires `ALLOW_DELETE=true`.
- Path resolution must remain within configured allowed roots.
- No mutation without a persisted dry-run plan item.
- Exact dedupe revalidates content with streaming SHA-256 immediately before mutation.
- Default deletion behavior is quarantine.
- Never recursively remove a non-empty directory.
- Never invoke a shell with interpolated filenames.
- Persist item state after each operation for resumability.
- Audit every attempted mutation.

---

### Task 1: Commit current exact-dedupe planning baseline

**Files:** `app/planning/*`, `tests/test_planning.py`

**Interfaces:** Existing `generate_plan(...) -> PlanResult` remains the duplicate assignment primitive.

- [ ] Run `pytest -q` and verify all current tests pass.
- [ ] Commit the already-tested planning baseline before extending it.

### Task 2: Extend configuration and persistence models

**Files:** Modify `app/config.py`, `app/models.py`; add `tests/test_extended_models.py`.

**Interfaces:** Add indexed filesystem records, generic batch plans/items, quarantine config, and task progress fields without breaking existing scan/duplicate models.

- [ ] Write failing tests for model creation and default quarantine settings.
- [ ] Run targeted tests and verify RED.
- [ ] Add models/config with deterministic string operation/status fields.
- [ ] Run targeted tests and full suite.

### Task 3: Incremental filesystem index

**Files:** Create `app/indexing/__init__.py`, `app/indexing/indexer.py`, `app/indexing/matcher.py`, `tests/test_indexing.py`.

**Interfaces:** `scan_root(root, allowed_roots) -> list[IndexedEntry]`; `match_entries(entries, mode, normalize_regex=None) -> dict[str, list[IndexedEntry]]`.

- [ ] Test stable relative paths, file metadata, same-relative-path grouping, basename grouping and regex-normalized grouping.
- [ ] Verify RED.
- [ ] Implement metadata-only indexing and matching.
- [ ] Verify GREEN.

### Task 4: Generic rename/stat template engine

**Files:** Create `app/batch/__init__.py`, `app/batch/rename.py`, `app/batch/stats.py`, `tests/test_batch_rename.py`.

**Interfaces:** `RenameRule`, `RenameProposal`, `build_rename_plan(...)`; `collect_tree_stats(path)`, `render_stat_name(...)`.

- [ ] Test regex replacement, prefix/suffix, zero-padded numbering, parent-name composition, collision rejection, recursive image/video/file/folder/size counts, and repeated stat suffix stripping.
- [ ] Verify RED.
- [ ] Implement pure preview functions first; no filesystem mutation in builders.
- [ ] Verify GREEN.

### Task 5: Additional duplicate policies

**Files:** Modify `app/planning/policies.py`, `app/planning/engine.py`, `tests/test_planning.py`.

**Interfaces:** Add `path-priority` and relative-path preference inputs while preserving existing policy signatures via optional parameters.

- [ ] Test glob/regex path priority, deterministic ties, and preferred-relative-path selection.
- [ ] Verify RED.
- [ ] Implement policy scoring.
- [ ] Verify all planning tests GREEN.

### Task 6: Generic batch plans and quarantine executor

**Files:** Create `app/batch/plans.py`, `app/execution/__init__.py`, `app/execution/verifier.py`, `app/execution/executor.py`, `tests/test_execution.py`.

**Interfaces:** Generic `BatchPlanItem` operations `rename`, `move`, `touch`, `quarantine`, `unlink`; exact-dedupe verifier `verify_duplicate_pair(...)`; executor returns `ItemResult`.

- [ ] Test read-only/delete-disabled guards, path escape, symlink rejection, collision, quarantine path preservation, SHA mismatch safe-skip, successful exact duplicate quarantine, and resume skipping completed items.
- [ ] Verify RED.
- [ ] Implement mutation executor with `os.replace`/`os.unlink`/`os.utime`, never shell commands.
- [ ] Verify GREEN and full suite.

### Task 7: 少女映画 organizer profile

**Files:** Create `app/organizers/__init__.py`, `app/organizers/shaonv.py`, `tests/test_organizer.py`.

**Interfaces:** Profile composes generic stats/rename/touch functions; it does not own mutation primitives.

- [ ] Test `[存疑]` preservation, P/V/size output, video-zero formatting, preview order, and root2-then-root1 mtime ordering.
- [ ] Verify RED.
- [ ] Implement profile adapters.
- [ ] Verify GREEN.

### Task 8: Service/API/UI and durable lifecycle

**Files:** Create/modify `app/service.py`, `app/main.py`, `app/web/*`, `tests/test_api.py`.

**Interfaces:** Dashboard, index/scan jobs, duplicate groups, batch-plan preview/freeze/execute, rename preview, path-match preview and audit views.

- [ ] Test health, path validation, plan lifecycle transitions and delete/quarantine guards.
- [ ] Verify RED.
- [ ] Implement minimal synchronous endpoints backed by persisted plan/item state; long jobs use durable job rows and explicit start/resume actions.
- [ ] Verify GREEN.

### Task 9: Docker packaging and NAS deployment docs

**Files:** Create `Dockerfile`, `compose.yaml`, `.dockerignore`, `.gitignore`, `config.example.env`, `README.md`.

**Interfaces:** `docker compose up -d`; default `/data:ro`; explicit execute profile `/data:rw` plus env opt-in.

- [ ] Build image with fclones 0.35.0.
- [ ] Run pytest/compile checks.
- [ ] Run compose config validation when Docker is available.
- [ ] Document 极空间 volume mapping, safe first scan, enabling quarantine, enabling permanent unlink, backups and recovery.
