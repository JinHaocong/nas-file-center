# NAS File Center v0.3.5 Gate5-B — Implementation & Safety Walkthrough

## 1. Context & Scope (背景与本次范围)

当前整体状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-B Architecture Freeze = APPROVED
Gate5-B implementation = IN PROGRESS (Candidate Ready for Review)
Gate5-C+ = NOT AUTHORIZED
v0.3.5 = NOT CLOSED
```

### 1.1 Gate5-B 目标与范围红线
1. **Workflow 定义与语法校验**:
   - Pydantic AST 语法校验，支持两类严格 Pipeline 结构（`file` 模式与 `organizer` 模式）。
   - 严禁任何未知或保留步骤类型（`dedupe`, `copy`, `delete` 等），一律返回 HTTP 400 (`UNSUPPORTED_STEP`)。
2. **不可变版本模型 (Immutable Revision Model)**:
   - `workflows` 表记录工作流元数据与当前版本号，`workflow_revisions` 表记录单 JSON 步骤配方与规范化 `definition_sha256`。
   - 乐观并发锁机制：更新与回滚强制校验 `expected_current_revision`，不匹配时返回 HTTP 409 (`WORKFLOW_REVISION_CONFLICT`)。
3. **虚拟路径图 (Virtual Path Graph)**:
   - 纯内存多步变更模拟，严禁伪造物理身份（`expected_inode`, `expected_device`, `expected_mtime_ns` 严格保持为 0）。
   - 碰撞检测（`PATH_COLLISION`）、环路检测（`PATH_CYCLE`）、PathGuard 越界拦截（`PATH_OUTSIDE_ALLOWED_ROOT`）。
4. **只读 Dry-Run 试跑 API**:
   - `POST /api/workflows/{id}/preview`：零文件系统突变、零数据库计划记录生成，返回确定的 `compile_digest`，受 50k 安全上限保护。
5. **显式生成标准 BatchPlan(draft)**:
   - `POST /api/workflows/{id}/generate-plan`：校验 `expected_compile_digest`，仅在数据库生成 `status="draft"` 的通用批处理计划，绝不直接修改文件，绝不启动 Worker。
6. **RBAC 权限守卫**:
   - Admin 专享写操作（创建、修改、删除归档、回滚）。
   - Authenticated 用户（管理员与普通成员）均可只读查看、Dry-Run 试跑及生成 Draft 计划。
7. **范围绝对红线**:
   - 严禁 UI 可视化搭建器（Gate5-C）、Stale Rebuild UI（Gate5-C）、高级去重评分（Gate5-D）、资源并发限制（Gate5-E）、Scheduler 定时调度（DEFER）。
   - 严禁实现直接修改文件系统的独立执行器，所有执行必须且仅能通过既有 Gate3 Freeze + Worker 机制完成。

---

## 2. Technical Implementation (技术实现)

### 2.1 模块构成
1. **[`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py)** & **[`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py)**:
   - 定义 `Workflow` 与 `WorkflowRevision` 模型，建立唯一约束 `UNIQUE(workflow_id, revision)` 及 `CheckConstraint("current_revision >= 1")`。
   - 在 `app/db.py` 中纳入增量幂等建表与在库自动备份机制。
2. **[`app/workflows/errors.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/errors.py)**:
   - 定义结构化异常体系：`WorkflowError` 基础类，以及 `WorkflowValidationError`, `WorkflowRevisionConflictError`, `WorkflowNotFoundError`, `WorkflowArchivedError`, `VirtualGraphCollisionError`, `VirtualGraphCycleError`, `WorkflowBoundaryError`, `WorkflowSafetyLimitExceededError`, `WorkflowDigestMismatchError`。
3. **[`app/workflows/revisions.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/revisions.py)**:
   - 实现 `canonical_json_dumps` 与 `compute_definition_sha256`，保证步骤配方的键排序、紧凑分隔符与 SHA-256 哈希确定性。
4. **[`app/workflows/schema.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/schema.py)**:
   - Pydantic 模型：`ScanStep`, `FilterStep` (100% 复用 Gate5-A AST), `RenameStep`, `MoveStep`, `TouchStep`, `QuarantineStep`, `OrganizeStep`, 以及完整 API 请求/响应模型。
5. **[`app/workflows/validation.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/validation.py)**:
   - 语法检查：Mode 校验、Pipeline 结构校验、参数安全与正则合法性检查，前置拦截 `dedupe` 并抛出 `UNSUPPORTED_STEP`。
6. **[`app/workflows/graph.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/graph.py)**:
   - 内存虚拟路径图 `VirtualPathGraph`：追踪候选文件虚拟状态、多步重命名/移动冲突排查、拓扑排序与依赖环路探测。
7. **[`app/workflows/compiler.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/compiler.py)**:
   - `WorkflowCompiler`：从 `IndexedPath` 结合全局排除与 Gate5-A Filter AST 进行候选集查询，执行安全上限防护（50k/100k），计算并产出不可变 `compile_digest`。
8. **[`app/workflows/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/service.py)**:
   - `WorkflowService`：承载 CRUD、乐观锁冲突判断、版本回滚、只读试跑预览与标准 `BatchPlan(status="draft")` 生产。
9. **[`app/api/router.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/api/router.py)**:
   - 挂载 10 个 REST 路由，配合 `get_current_user` 与 `require_admin_user` 实施细粒度 RBAC 拦截。

---

## 3. Verification Results (验证结果)

### 3.1 单元与集成测试套件
```bash
# 1. Gate5-B 专属测试套件 (24 tests) -> 100% PASS
docker run --rm -e PYTHONPATH=. -v "$(pwd):/app" -w /app nas-test-env:latest pytest -q tests/test_workflow_*.py
# Output: 24 passed in 2.11s

# 2. Gate5-A 专项测试套件 (30 tests) -> 100% PASS
docker run --rm -e PYTHONPATH=. -v "$(pwd):/app" -w /app nas-test-env:latest pytest -q \
  tests/test_filter_ast.py tests/test_filter_compiler.py tests/test_filter_preview.py \
  tests/test_filter_policy.py tests/test_filter_index_freshness.py tests/test_filter_preview_readonly.py
# Output: 30 passed in 1.87s

# 3. Gate2/3/4 安全核心套件 (49 tests) -> 100% PASS
docker run --rm -e PYTHONPATH=. -v "$(pwd):/app" -w /app nas-test-env:latest pytest -q \
  tests/test_gate2_worker_execution.py tests/test_gate2_undo_plan.py tests/test_gate2_hotfix1_worker_fencing.py \
  tests/test_gate3_stale_plan.py tests/test_gate4_backend_quarantine_undo.py
# Output: 49 passed in 8.35s

# 4. 后端全量测试套件 (553 tests) -> 100% PASS
docker run --rm -e PYTHONPATH=. -v "$(pwd):/app" -w /app nas-test-env:latest pytest -q
# Output: 553 passed in 65.2s

# 5. 前端测试与构建 (177 tests) -> 100% PASS
npm test -- --run && npm run build
# Output: 177 passed in 103ms, Vite production build succeeded
```

### 3.2 独立黑盒容器验收 (Checkpoints CP1 ~ CP9)
测试脚本：`test_gate5b_blackbox_acceptance.py`，针对全新独立容器 `nas-file-center:v0.3.5-gate5b` 执行端到端黑盒验证：
```text
============================================================
GATE5-B BLACKBOX ACCEPTANCE REPORT
============================================================
CP1   : PASS (Health endpoint accessible and healthy)
CP2   : PASS (DB Migration: workflows & revisions tables created, integrity ok)
CP3   : PASS (RBAC: Member write blocked 403, Admin allowed 201, Unauth 401)
CP4   : PASS (Unsupported step rejection: dedupe and copy rejected with 400 UNSUPPORTED_STEP)
CP5   : PASS (Workflow CRUD & Optimistic locking: rev bump 1->2, stale update 409)
CP6   : PASS (Rollback & Archive: rollback to rev 1 -> rev 3, DELETE archives, archived rejected 400)
CP7   : PASS (Read-only Dry-Run Preview: digest generated, 0 FS mutation, 0 DB BatchPlans created)
CP8   : PASS (Explicit Plan Generation: BatchPlan draft generated, expected_inode/device/mtime=0)
CP9   : PASS (SQLite DB integrity check ok)
============================================================
ALL CHECKPOINTS PASS
```

---

## 4. Release Candidate Identity (工件标识)

- **Docker 镜像**: `nas-file-center:v0.3.5-gate5b`
- **实现分支**: `v0.3.5-gate5b`
- **候选状态**: `Gate5-B implementation candidate ready for independent review`
