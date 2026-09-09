# NAS File Center v0.3.5 Gate5-D / D2-B2 — Implementation & Verification Walkthrough

## 1. Baseline / final commit
- Baseline: `2a9ba32dad321205bc5a37bc52de8417cb2e1cf9`
- Final implementation commit: `e88352e008c2a9bbd04b68e91f1ba4f70624bf9a`

---

## 2. Scope implemented (本阶段完成内容)

本阶段完整实现了 **Gate5-D / D2-B2: Explicit Advanced Dedupe Draft Generation + Preview Identity Enforcement**：

1. **显式高级去重草稿生成路由 (`POST /api/scans/{scan_job_id}/dedupe-plan`)**
   - 请求体通过 `DedupePlanRequest` 实施严格的 fail-closed 校验：
     - 若提供 `scorer_config`，则必须为字典对象，且必须提供 64 位十六进制的 `expected_preview_digest`；
     - 严禁混合 `policy`、`path_priority_patterns`、`relative_path_priority_patterns` 等 legacy 字段（抛出 400 `DedupeInvalidConfigError`）；
     - 若缺少 `scorer_config`，请求被识别为 legacy 去重生成，维持原有的 6 种预设策略，完全向后兼容；
   - 新增两项语义错误与标准 HTTP 状态映射：
     - `DedupePreviewChangedError` -> HTTP 409 Conflict (`code="PREVIEW_CHANGED"`)；
     - `DedupeEmptyPlanError` -> HTTP 422 Unprocessable Entity (`code="DEDUPE_EMPTY_PLAN"`)。

2. **Phase A 纯只读重新编译与预览身份强校验 (`expected_preview_digest`)**
   - 进入 `create_advanced_dedupe_plan` 时，首先冻结单次请求的安全权威快照 `_capture_effective_dedupe_safety_snapshot()`，包含 `effective_quarantine_root`、`effective_allowed_roots` 及 `protect_last_file`；
   - 重新执行 D2-A 编译逻辑 `compile_advanced_dedupe_preview()`，获取纯服务端真实决策；
   - 结合安全权威快照计算当前最新的 `preview_digest`；
   - 若当前 `preview_digest != expected_preview_digest`，立即中止并抛出 409 `PREVIEW_CHANGED`，不产生任何副作用与 Draft；
   - 若过滤后的意图操作集为空，立即中止并抛出 422 `DEDUPE_EMPTY_PLAN`，不产生任何副作用与 Draft。

3. **DB Lineage 血缘绑定 (`db_lineage_digest`)**
   - 在 `DedupePreviewCompilation` 中绑定 `db_lineage_digest`，基于 `ScanJob`（ID、状态、行版本更新时间）与 `DuplicateGroup`、`DuplicateFile` 的数量及 ID 校验和计算；
   - 在进入 Phase B 短写事务时重新校验 `db_lineage_digest`，若在 Phase A 与 Phase B 之间发生底层扫描数据并发修改，触发事务回滚并抛出 409 `PREVIEW_CHANGED`。

4. **不可变隔离意图与实体规范 (`DedupeDraftIntent`)**
   - 在 `app/planning/dedupe_generate.py` 中定义不可变数据类 `DedupeDraftIntent`；
   - 从服务端决策中过滤并提取唯一的 `keep_path`，为每一个待隔离的非保留副本建立隔离意图：
     - `action_type = "quarantine"`
     - `file_path = member.file_path`
     - `keep_path = group_keep_path`
     - 身份元数据字段严格保持 `item_id = 0`, `source_fingerprint = None`, `expected_hash = None`, `target_quarantine_path = None`，满足 Gate3 物理身份冻结前的 Draft 规范。

5. **Phase B 短事务原子持久化 (`_persist_advanced_dedupe_draft`)**
   - 零耗时 IO 锁持有：文件系统遍历、打分、哈希和平衡计算均在 Phase A 完成，Phase B 仅在 `BEGIN IMMEDIATE` 短事务中执行原子 DB 写入；
   - 严格在单个事务内原子创建 1 个 `BatchPlan(plan_type="dedupe", status="draft", scan_job_id=...)` 与对应的全部 `BatchPlanItem`；
   - 任何数据库异常均触发全量回滚，绝无半态 Draft 或孤立 Item 残留。

6. **保持 Legacy 路径 100% 兼容**
   - `create_dedupe_plan` 及其 6 种预设策略语义、`apply_legacy_strategy` 决策保持原样，回归测试全部通过。

---

## 3. Verification Evidence (验证执行事实记录)

### 3.1 变更文件范围审计 (`git diff --stat`)
生产代码严格限定在允许的 5 个文件，新增 2 个测试文件，绝无超出 D2-B2 范围的越界修改：
```text
 app/api/router.py                        |  79 ++++-
 app/main.py                              |   4 +-
 app/planning/dedupe_generate.py          |  79 +++++
 app/planning/dedupe_preview.py           | 102 +++++++
 app/service.py                           | 179 ++++++++++++
 tests/test_gate5d_dedupe_generate.py     | 480 +++++++++++++++++++++++++++++++
 tests/test_gate5d_dedupe_generate_api.py | 359 +++++++++++++++++++++++
 7 files changed, 1276 insertions(+), 6 deletions(-)
```

### 3.2 针对性回归测试套件 (Targeted Regression)
执行命令：
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate5d_dedupe_generate_api.py \
  tests/test_gate5d_dedupe_preview_api.py \
  tests/test_gate5d_dedupe_preview_compiler.py \
  tests/test_planning.py \
  tests/test_scan_jobs.py \
  tests/test_gate3_stale_plan.py
```
测试输出：
```text
======================= 138 passed, 2 warnings in 16.54s =======================
```
包含：
- D2-B2 单元测试与并发对抗：14 passed
- D2-B2 API 路由、参数、409/422 对抗测试：24 passed
- D2-B1 HTTP 预览接口测试：31 passed
- D2-A 编译器测试：26 passed
- Legacy Planning 套件：8 passed
- ScanJob 状态同步测试：1 passed
- Gate3 物理状态机与 Stale Plan 测试：34 passed

### 3.3 全量后端回归测试 (Full Backend Regression)
执行命令：
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
测试输出：
```text
767 passed, 20 warnings in 83.62s (0:01:23)
```
767 个后端测试用例 100% 全部通过，0 failed，0 error。

### 3.4 前端零修改回归 (Frontend No-Change Regression)
执行命令：
```bash
cd frontend && npm ci && npm run typecheck && npm run build
```
测试输出：
- `npm run typecheck`: 0 errors
- `npm run build`: built in 4.16s，静态产物顺利生成，`git status` 确认 `frontend/` 目录 0 改动。

### 3.5 Docker 跨平台构建与生产 Smoke 验证 (Docker Build & Smoke)
执行命令：
```bash
docker buildx build --platform linux/amd64 --load -t nas-file-center:d2b2 .
```
容器 Smoke 测试：
1. 启动 `nfc-d2b2-api` 容器：
   - 轮询等待健康检查响应，成功返回 HTTP 200：
     `{"status":"ok","allow_mutation":false,"allow_delete":false,"allowed_roots":["/data"]}`
2. 启动 `nfc-d2b2-worker` 容器：
   - 执行 `python -m app.worker` 顺利完成初始化并进入监听循环。
3. 容器运行状态检查：
   - `docker inspect -f '{{.State.Running}}' nfc-d2b2-api` -> `true`
   - `docker inspect -f '{{.State.Running}}' nfc-d2b2-worker` -> `true`
4. 容器与临时网络清理完成。

---

## 4. Boundaries & Explicit Non-Goals (阶段边界与禁止项核对)

1. **严禁 D3 Workflow**：未增加 `mode=dedupe` 工作流，未修改 `app/workflows/*`。
2. **严禁 D4 Frontend**：未进行任何前端去重界面开发，前端代码零改动。
3. **严禁修改 Worker 状态机**：未触碰 `app/worker.py`、`app/tasks/*`、`app/execution/*`。
4. **严禁修改数据库 Schema**：未进行任何 DB migration，未改动 `BatchPlan` / `BatchPlanItem` 模型定义。
5. **严禁自动推进状态**：Generate 仅持久化状态为 `draft` 的 BatchPlan，不进行自动 Freeze、Validate、Execute、enqueue 或 Quarantine。
6. **零文件系统副作用契约**：Generate 过程为纯元数据与数据库写操作，对文件系统 0 写入、0 修改、0 移动。

---

## 5. Formal Status (正式状态声明)

```text
D2-B2 IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW
D3 Workflow = FORBIDDEN until D2-B2 independent review closes
D4 Frontend = FORBIDDEN until D2-B2 independent review closes
```
