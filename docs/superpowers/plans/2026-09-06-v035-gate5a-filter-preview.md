# Implementation Plan - v0.3.5 Gate5-A: Unified Filter AST, Exclude Rules, and Read-Only Preview

## 1. Overview & Baseline
- **Baseline Release**: `nas-file-center-v0.3.4-gate4-baseline-hotfix1.zip`
- **Baseline Git Commit**: `e9cf7ef5defa0678d117d60dd997e881134d2ede`
- **Baseline Backend Tests**: 499 passed, 0 failed
- **Baseline Frontend Tests**: 177 passed in 52 suites, 0 failed
- **Core Principle**: Gate5-A is strictly **FILESYSTEM READ-ONLY**. Preview analyzes `IndexedPath` and `IndexRoot`, creates 0 Plans/Jobs/Journals/Quarantines, and mutates 0 files. Global exclude rules persistence in SQLite `filter_policy` is the only allowed write operation.

---

## 2. Gate5-A Scope Checklist

- [ ] **Unified Filter AST & Validation**:
  - Pydantic models for LogicalNode (`and`, `or`, `not`) and LeafNode.
  - Allowed fields: `path`, `name`, `extension`, `size`, `mtime`, `media_type`.
  - Allowed operators: `eq`, `neq`, `contains`, `startswith`, `endswith`, `in`, `nin`, `gt`, `gte`, `lt`, `lte`.
  - Deferred & rejected: `regex` field and `matches` operator return HTTP 422 (`"regex filtering is not supported in Gate5-A"`).
  - Complexity guard: `max_depth = 5`, `max_children = 50`, `max_leaves = 200`. Empty logical nodes rejected.
  - Strict type checks: negative size rejected, mtime converted to UTC `mtime_ns`, extension normalized (lowercase, leading dot stripped).
- [ ] **SQL Compiler**:
  - Translates Filter AST to SQLAlchemy predicates on `IndexedPath`.
  - String matching safety: `contains`, `startswith`, `endswith` properly escape `%`, `_`, and `\` in LIKE predicates, preventing wildcard injection.
  - Filter operates against `IndexedPath.relative_path`, `basename`, `suffix`, `size`, `mtime_ns`.
  - Always enforces `IndexedPath.is_dir == False`.
- [ ] **Global Exclude Rules & Persistence (`FilterPolicy`)**:
  - Singleton model `FilterPolicy(id=1, exclude_dir_names_json, updated_at)`.
  - Default rules: `[".git", ".recycle", "@eaDir", ".nas-file-center-trash"]`.
  - Hard exclude: configured `quarantine_root` is always excluded from preview regardless of policy.
  - Exclude rule validation: max 64 rules, length 1..128, no `/`, no empty/`.`/`..`, no backslashes.
  - Segment-aware SQL exclude predicates (`NOT (relative_path LIKE '%/.git/%' OR ...)`).
  - APIs: `GET /api/filter-policy` (Authenticated), `PUT /api/filter-policy` (Admin only).
  - Migration in `app/db.py`: auto-backup `app.db`, `create_all`, seed `id=1`, idempotent.
- [ ] **Read-Only Filter Preview API (`POST /api/filters/preview`)**:
  - Authenticated (available to regular users).
  - Validates roots ($1 \le count \le 16$, must exist in `IndexRoot` and `ALLOWED_ROOTS`).
  - Server-side pagination: $1 \le page$, $1 \le page\_size \le 200$ (default 50).
  - Stable sort: `size`, `mtime`, `name`, `path` with secondary sort by `IndexedPath.id`.
  - SQL aggregations: `COUNT(*)` and `COALESCE(SUM(size), 0)` in SQLite.
  - Index freshness metadata: `preview_source="index"`, `live_filesystem_verified=false`, `roots=[{root, last_indexed_at}]`.
  - Zero filesystem writes: assert filesystem manifest and mutation tables unchanged.

---

## 3. Architecture & File Structure

```text
app/
├── filters/
│   ├── __init__.py
│   ├── schema.py        # Filter AST Pydantic models & API schemas
│   ├── validation.py    # Semantic validation & complexity guards
│   ├── media_types.py   # Deterministic extension -> media_type mapping
│   ├── excludes.py      # Global exclude validation & SQL predicate builder
│   └── compiler.py      # AST -> SQLAlchemy predicate compiler with LIKE escaping
├── models.py            # Add FilterPolicy model
├── db.py                # Add filter_policy to required_tables & seed defaults
├── service.py           # Add preview_filter, get_filter_policy, update_filter_policy
└── api/
    └── router.py        # Add POST /api/filters/preview, GET/PUT /api/filter-policy
```

---

## 4. TDD Step-by-Step Plan

### Step 1: Filter AST Models & Semantic Validation
- Write failing tests in `tests/test_filter_ast.py`:
  - Logical nodes: `and`, `or`, `not` (single child).
  - Depth limit: depth 5 accepted, depth 6 rejected with 422.
  - Children limit: 50 accepted, 51 rejected with 422.
  - Max leaves: 200 accepted, 201 rejected.
  - Empty `and: []` / `or: []` rejected with 422.
  - Unsupported `regex` field / `matches` operator explicitly rejected with 422 `"regex filtering is not supported in Gate5-A"`.
  - Field/operator type compatibility (size >= 0 integer, mtime ISO string / unix timestamp to UTC ns, extension normalized).
  - Media type mapping consistency (`image`, `video`, `audio`, `document`, `archive`, `other`).
- Implement `app/filters/media_types.py`, `app/filters/schema.py`, `app/filters/validation.py`.
- Verify GREEN.

### Step 2: SQL Filter Compiler & Literal String Escaping
- Write failing tests in `tests/test_filter_compiler.py`:
  - `contains`, `startswith`, `endswith` escaping `%`, `_`, `\`.
  - String matching against literal `100%_real.txt` matches `contains: "100%_"`.
  - `in` / `nin` set expressions.
  - `size` / `mtime_ns` numeric comparisons.
  - `media_type` compiler expansion into extension sets.
  - Composite `and`/`or`/`not` SQL generation.
- Implement `app/filters/compiler.py`.
- Verify GREEN.

### Step 3: Global Exclude Rules & DB Persistence (`FilterPolicy`)
- Write failing tests in `tests/test_filter_policy.py`:
  - Exclude rule validation: length 1..128, max 64, forbidden characters (`/`, `\`, `.`, `..`).
  - Segment-aware SQL predicate generation: excludes `.git/config`, `foo/.git/config`, but NOT `foo/.git2/config`.
  - Hard quarantine exclude predicate.
  - DB model `FilterPolicy` & `init_db` migration test (auto-backup, table creation, default seed, idempotency).
  - API tests: `GET /api/filter-policy` (user 200, admin 200), `PUT /api/filter-policy` (user 403, admin 200).
- Implement `app/filters/excludes.py`, `app/models.py` (`FilterPolicy`), `app/db.py`, and endpoints in `app/api/router.py`.
- Verify GREEN.

### Step 4: Filter Preview API & Server-side Pagination
- Write failing tests in `tests/test_filter_preview.py`:
  - `POST /api/filters/preview` with valid roots and filter.
  - Server-side pagination bounds (1 <= page, 1 <= page_size <= 200, default 50).
  - Stable sort with secondary sort by `IndexedPath.id`.
  - SQL `COUNT(*)` and `COALESCE(SUM(size), 0)`.
  - Response schema verification (`preview_source: "index"`, `live_filesystem_verified: false`).
  - Unindexed root returns 422 / 404.
  - Roots out of `ALLOWED_ROOTS` rejected.
- Implement `preview_filter` in `app/service.py` and `POST /api/filters/preview` in `app/api/router.py`.
- Verify GREEN.

### Step 5: Read-Only & Zero-Mutation Verification
- Write failing tests in `tests/test_filter_preview_readonly.py`:
  - Run preview while counting `batch_plans`, `batch_plan_items`, `work_jobs`, `operation_journal`, `quarantine_entries`.
  - Verify all counts strictly unchanged.
  - Test under `ALLOW_MUTATION=false`: preview succeeds; `PUT /api/filter-policy` succeeds for admin without filesystem mutation.
- Verify GREEN.

### Step 6: Index Freshness Contract Tests
- Write failing tests in `tests/test_filter_index_freshness.py`:
  - Step 1: index file `a.txt`, preview shows `a.txt`.
  - Step 2: remove `a.txt` from filesystem without re-indexing, preview STILL shows `a.txt` (with `live_filesystem_verified: false`, `preview_source: "index"`).
  - Step 3: re-run index, preview reflects updated index and `a.txt` disappears.
- Verify GREEN.

### Step 7: Regression, Docker Build & Native Black-box Acceptance
- Run full backend suite (`pytest -q` -> 499 + N passed).
- Run safety regressions: Gate2, Gate3, Gate4.
- Run frontend checks: `npm test -- --run`, `npm run typecheck`, `npm run build`.
- Build Docker image `nas-file-center:v0.3.5-gate5a`.
- Execute Docker black-box acceptance script (CP1 to CP10).
- Package `nas-file-center-v0.3.5-gate5a.zip` with comment `$(git rev-parse HEAD)` and external `SHA256SUMS.txt`.
- Final clean unzip & test verification in `/tmp/gate5a-final-check`.
