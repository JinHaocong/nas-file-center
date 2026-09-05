# NAS File Center v0.3.4-Gate2
Operation Journal + Task-backed Plan Execution + Undo Plan 验收报告

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2** 阶段性里程碑，**不是 v0.3.4 Final**。
> Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2`
- **交付目标**：
  1. **Operation Journal (操作审计日志)**：底层可逆文件变更的不可变追加流水表；
  2. **Task-backed BatchPlan Execution (任务异步驱动的执行引擎)**：`POST /api/plans/{plan_id}/execute` 从原先的同步阻塞执行彻底变更为入队 `WorkJob(kind="batch-plan-execute")`，API 请求本身的文件系统变更数严格为 0；
  3. **Undo Plan (反向执行计划生成)**：基于 Journal 反向生成标准 Draft `BatchPlan`，复用现存 Freeze -> Validate -> Execute -> Worker 统一生命周期管线；
  4. **并发与崩溃自愈安全门禁**：租约围栏防护、逐项检查点持久化、跨项取消与重试安全、崩溃重启自愈对齐。
- **唯一允许基线 (Baseline Commit)**：
  - **Commit**：`e276e5df66ba30260967b10d3070ea064255492e` (v0.3.4-Gate1-hotfix2)
  - **前一归档包**：`nas-file-center-v0.3.4-gate1-hotfix2.zip`
  - **基线 SHA256**：`5c8c5af109a999f678096901871429a060c8f76a10191e18d39df843f98c1d1b`
- **基线测试**：
  - Backend baseline：`388 tests`
  - Frontend baseline：`150 tests / 44 suites`

---

## 2. 核心架构设计与关键实现

### 1. 数据模型与无损迁移 (`OperationJournal`)
- **模型定义**（[`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py)）：
  - 核心字段：`id`, `operation`, `sequence`, `plan_id`, `plan_item_id`, `task_id`, `user_id`, `before_json`, `after_json`, `metadata_before_json`, `metadata_after_json`, `created_at`。
  - 外键策略：关联 `plans.id`, `batch_plan_items.id`, `work_jobs.id`, `users.id` 均显式配置 `ON DELETE SET NULL`，杜绝级联删除历史日志流水。
  - 索引建设：覆盖 `ix_operation_journal_plan_sequence`, `ix_operation_journal_task_id`, `ix_operation_journal_plan_item_id`, `ix_operation_journal_created_at`, `ix_operation_journal_operation`。
- **迁移逻辑**（[`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py)）：
  - 在 `required_tables` 中注册 `"operation_journal"`；
  - 首次检测到表缺失时先自动备份数据库文件，第二次及后续启动无冗余备份，数据无损。

### 2. 任务驱动执行引擎与三段式租约契约 (`BatchPlanExecuteHandler`)
- **注册工作任务**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - 注册 `BatchPlanExecuteHandler`，对应 `job_type = "batch-plan-execute"`。
  - 声明 Capabilities：`supports_pause = True`, `supports_cancel = True`, `supports_retry = True`, `supports_resume = True`。
- **逐项三段式执行机制**：
  1. **Phase 1: Pre-mutation Intent**（短写入事务）：
     - 强校验 Worker Lease（`assert_active_worker_lease`）；
     - 将当前 PlanItem 标记为 `executing`，预生成必要元数据（如 `QuarantineEntry` 占位、确定性 `target_mtime_ns`），短事务即刻提交释放 SQLite 写入锁。
  2. **Phase 2: Filesystem I/O**（纯物理操作，严格不持 DB 事务）：
     - 重命名/移动强制复用内核原子原语 `rename_noreplace`，杜绝并发覆盖；
     - 隔离操作移动至隔离命名空间；
     - touch 操作采用纳秒精度确定性时间戳。
  3. **Phase 3: Post-mutation Finalize**（短写入事务）：
     - 强校验 Worker Lease：若租约丢失，绝不执行数据库写入，立即优雅退出；
     - 租约正常则持久化更新 PlanItem `completed`，并写入一条 `OperationJournal` 与一条 `AuditEvent`。
- **生命周期状态同步**（[`app/tasks/sync.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/sync.py), [`app/worker.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/worker.py)）：
  - `sync_batch_plan_status` 确保 Worker 在任务 `running`、`completed`、`paused`、`cancelled`、`failed` 时，将计划真实状态对齐，杜绝计划悬挂在 `executing`。

### 3. 生命周期互斥与安全边界 (`app/service.py`, `app/api/router.py`)
- **单计划活跃任务互斥**：
  - 校验 Plan 状态必须为 `ready` 或 `partial`；
  - 严格检查是否存在状态为 `queued`, `running`, `paused`, `cancel_requested` 的活跃任务；若已存在则直接拒绝，严禁并发双发。
- **活跃任务冲突阻断**：
  - 若计划存在活跃任务：`validate_plan`、`delete_plan`、`execute_plan` 统一抛出 409 Conflict（`StateConflictError`）；
  - `clear_plan_history` 会自动跳过仍有活跃任务关联的计划。
- **任务重试安全边界**：
  - `batch-plan-execute` 白名单限制仅允许传入 `plan_id`，杜绝特权覆盖；
  - `retry_task` 强制注入当前调用者的真实 `user_id`。

### 4. 崩溃恢复与对齐协议 (`_reconcile_executing_item`)
- Worker 启动或接管任务时，自动扫描当前计划下处于 `state = "executing"` 的悬挂条目：
  - 依据物理源文件与目标文件的实际存在性、inode、mtime 与大小执行严格对齐；
  - 若检测到物理变更已完成，补齐 Finalize 阶段并补录 Journal；
  - 若物理变更未发生，安全重置为准备状态重新调度；
  - 若处于歧义不一致状态，Fail-Closed 标记为 `failed`，绝不盲目重复覆盖。

### 5. Operation Journal 与 Undo Plan 生成
- **Journal 记录原则**：
  - 仅物理变更成功的可逆操作（`rename`, `move`, `quarantine`, `restore`, `touch`）写入 `OperationJournal`；
  - 失败、跳过或物理彻底删除（`purge`）绝不写入 Journal；
  - 单独调用 `restore_quarantine_entry` 还原条目时，亦同步追加一条 Journal 流水。
- **Undo Plan 逆向生成**（[`POST /api/plans/{plan_id}/undo-plan`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：
  - 按 Journal 的 `sequence DESC, id DESC` 严格倒序反向还原；
  - `rename A->B` 反向映射为 `rename B->A`；
  - `move A->B` 反向映射为 `move B->A`；
  - `quarantine A->Q` 反向映射为 `move Q->A` 并标记为恢复原状；
  - `touch` 反向映射为根据 `metadata_before_json` 的历史 mtime 重新 touch；
  - 0 文件系统修改，仅生成标准 Draft `BatchPlan`，由用户按既有管线审核、冻结、校验后由 Worker 执行回滚。

### 6. 前端异步真实性适配 (`frontend/src/**`)
- **API 契约更新**（[`frontend/src/api/domain.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/domain.ts)）：
  - `executePlan` 调整为接收 `{ plan_id, work_job_id, status }`；
- **类型定义**（[`frontend/src/types/index.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/index.ts)）：
  - `Plan` 补充可选字段 `active_work_job_id?: number | null`；
- **页面真实性与防护**（[`frontend/src/pages/Plans/PlanDetail.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Plans/PlanDetail.tsx)）：
  - 执行响应提示文案：“计划已加入任务队列，任务 #ID”；
  - 主动失效 `plansList`, `dashboardSummary`, `tasksList`, `workJobs` 缓存；
  - 当检测到 `active_work_job_id` 时，执行按钮与校验按钮自动禁用，并展示 Tooltip 明确提示已有任务执行中；
- **删除策略防线**（[`frontend/src/components/plans/plan_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/plan_cleanup.ts)）：
  - 若 `active_work_job_id` 存在，`canDelete` 严格返回 `false`，原因：“计划正在任务队列中执行，禁止删除”。

---

## 3. 验证与回归测试结果 (Verification Evidence)

### 1. 后端全量测试 (Pytest in Linux Docker)
- **运行命令**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app python:3.12-slim bash -c "pip install -q -e '.[test]' && PYTHONPATH=. pytest -q"
  ```
- **测试结果**：
  ```text
  ........................................................................ [ 17%]
  ........................................................................ [ 35%]
  ........................................................................ [ 53%]
  ........................................................................ [ 71%]
  ........................................................................ [ 89%]
  ..........................................                               [100%]
  ======================== 402 passed in 13.84s =========================
  ```
  - **总用例数**：**402 passed, 0 failed**（相比 baseline 388 用例净增 14 个 Gate2 专项用例，100% 绿色无退化）。
  - **专项测试分布**：
    - `tests/test_gate2_journal_models.py`：3/3 passed
    - `tests/test_gate2_plan_enqueue.py`：5/5 passed
    - `tests/test_gate2_undo_plan.py`：3/3 passed
    - `tests/test_gate2_worker_execution.py`：3/3 passed

### 2. Gate1 隔离区安全回归测试
- **运行命令**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app python:3.12-slim bash -c "pip install -q -e '.[test]' && PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
  ```
- **测试结果**：
  - **52 / 52 passed, 0 failed**（覆盖符号链接防护、fail-closed、无跟随遍历、保留根目录剪枝、启动自愈、rename_noreplace、外键约束等全量 Gate1 安全契约）。

### 3. 前端自动化测试与构建 (Frontend Regression)
- **运行命令**：
  ```bash
  npm test && npm run typecheck && npm run build
  ```
- **测试结果**：
  ```text
  # tests 151
  # suites 44
  # pass 151
  # fail 0
  ```
  - **TypeScript Typecheck**：`tsc --noEmit` 0 errors
  - **Production Build**：`tsc && vite build` built in 3.69s

### 4. 容器内端到端对抗演练 (Adversarial Smoke Rehearsal)
- **运行脚本**：`gate2_adversarial_smoke.py` 在隔离容器内执行。
- **演练结果**：
  ```text
  [SMOKE] 1. Auth OK
  [SMOKE] 2. Test files created
  [SMOKE] 3. Plan created, frozen, validated
  [SMOKE] 4. Plan enqueued as WorkJob #1 (API 0 mutations verified)
  [SMOKE] 5. Active job blocks execute/validate/delete with 409 OK
  [SMOKE] 6. Worker executed plan successfully
  [SMOKE] 7. Filesystem mutations verified; quarantine namespace task-1 verified
  [SMOKE] 8. OperationJournal recorded all 4 operations
  [SMOKE] 9. Undo Plan #2 generated (0 filesystem mutations)
  [SMOKE] 10. Undo Plan enqueued as WorkJob #2
  [SMOKE] 11. Worker executed Undo Plan
  [SMOKE] 12. FULL INVERSE VERIFICATION: All files & mtime restored to original state!
  [SMOKE] 13. Global journal query verified (8 entries)
  [SMOKE] ALL ADVERSARIAL SMOKE TESTS PASSED!
  ```

---

## 4. Scope Gate 范围核查

执行与基线提交 `e276e5df66ba30260967b10d3070ea064255492e` 的差异核查：
- [x] **未引入 Gate3 Stale Plan 自动重算与状态流转**
- [x] **未引入 Gate4 UI（无撤销按钮、无日志页面、无隔离区页面）**
- [x] **未引入第二套异步队列 / Celery / Redis，严格复用统一 WorkJob 架构**
- [x] **未引入 Workflow / Scheduler / Media 冗余模块**
- [x] **未引入任何第三方新依赖（pyproject.toml / package.json 零新增依赖）**

---

## 5. 已知局限性与后续 Gate 规划

1. **Gate3 Stale Plan 未完成**：当底层文件被外部进程修改导致校验失效时，系统在 Gate2 依靠 Worker 逐项校验 fail-closed；Gate3 将提供实时感知与计划失效（Stale）自动重算机制。
2. **Gate4 前端 UI 尚未开放**：当前 Undo Plan 生成仅通过 API（`POST /api/plans/{id}/undo-plan`）提供；隔离区可视化管理、操作日志审计流查询的前端界面留待 Gate4 构建。
3. **Purge 物理删除严格不可逆**：Purge 操作按规范仅写入 `AuditEvent`，绝不写入 `OperationJournal`，不可生成 Undo Plan。
