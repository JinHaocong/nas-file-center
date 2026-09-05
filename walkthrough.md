# NAS File Center v0.3.4-Gate2-hotfix1
Worker Fencing / Undo Consistency / Recovery Hardening 验收报告

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2-hotfix1** 修复里程碑，**不是 v0.3.4 Final**。
> Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。
> 禁止提前启动 Gate3/Gate4。严禁 git push / tag / docker push。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2-hotfix1`
- **交付目标**：
  修复 Gate2 交付物经独立审查发现的 8 项核心缺陷（Worker 边界租约击穿、重试绕过单活跃任务互斥、撤销隔离未更新隔离区元数据与状态、暂停任务取消导致计划永久悬挂、Touch 崩溃恢复二次变更时间戳、隔离区 Hash 阻塞写事务、直接还原丢失操作者并产生虚假任务关联、执行意图与 Journal 元数据不持久）：
  1. **Blocker 1 (P0)**: Worker 租约围栏防护扩展至文件系统物理操作边界；
  2. **Blocker 2 (P0)**: `retry_task` 严格执行 `batch-plan-execute` 单活跃任务互斥与计划有效性校验；
  3. **Blocker 3 (P0/P1)**: 撤销隔离计划严格使用受控内部 `restore` 语义，物理还原后更新 `QuarantineEntry` 状态为 `restored` 并记录 `restored_at`，禁止客户端伪造任意 restore 计划；
  4. **Blocker 4 (P1)**: 暂停/就绪任务取消时自动同步计划生命周期至 `partial` 或 `ready`，杜绝计划永久悬挂在 `executing`；
  5. **Blocker 5 (P1)**: Touch 意图确定性纳秒时间戳持久化，崩溃恢复时精确比对，杜绝二次修改时间戳；
  6. **Blocker 6 (P1)**: 隔离区 Hash 计算完全移出 SQLite 写事务，杜绝并发 `BEGIN IMMEDIATE` 锁库；
  7. **Blocker 7 (P1)**: 直接还原接口真实记录操作者 `user_id = current_user.id`，清空历史虚假计划与任务外键关联；
  8. **Blocker 8 (P1)**: 执行意图持久化源文件 Stat 快照，OperationJournal 完整记录操作前与操作后实体元数据快照。
- **演进基线 (Baseline)**：
  - **Gate2 基线 Commit**：`e1928019cdbf163d83153d64a29f5da253430188`
  - **Gate2 基线 Artifact SHA256**：`615034cd283697d3132b842f6adad42f08e5e676d0738ff060c2ec84911aa20a`
  - **Gate1 验收基线**：`e276e5df66ba30260967b10d3070ea064255492e`
- **测试基线与当前规模**：
  - Backend：**415 passed**（净增 13 个 Gate2-hotfix1 深度安全测试，Gate1 52 个安全用例全部绿色）
  - Frontend：**151 passed / 44 suites**

---

## 2. 核心问题修复与技术实现

### 1. Blocker 1 & Blocker 6: 物理操作边界租约围栏与写事务外 Hash
- **问题**：
  - 原逻辑在 Phase 1 释放事务锁到 Phase 2 物理文件系统调用之间存在时间窗。若 Worker 发生长 GC 或网络毛刺导致租约被抢占，旧 Worker 在租约丢失后仍会调用 `execute_item` 修改物理文件系统，造成双写冲突。
  - 原逻辑在 Phase 3 的 `BEGIN IMMEDIATE` 事务内调用 `safe_quarantine_hash`，对于大文件或并发写入，长时间持有排他写锁导致 `sqlite3.OperationalError: database is locked`。
- **修复实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - **边界围栏 (Boundary Fence)**：在调用 `execute_item` 前，发起极短的独立写事务刷新并强校验 Worker 租约（`assert_active_worker_lease`），立即提交。若租约丢失抛出 `JobLeaseLost`，执行在物理 I/O 前被硬阻断。
  - **Hash 移出写事务**：将 `safe_quarantine_hash` 以及物理文件的 `stat` 移至 Phase 2（无 DB 事务锁保护的物理操作区），Phase 3 短事务仅持久化预计算好的哈希与统计数据。

### 2. Blocker 2: 任务重试单活跃任务互斥与计划校验
- **问题**：
  - `retry_task` 允许重试已失败的 `batch-plan-execute` 任务，但未校验该计划当前是否已有其他活跃任务正在执行，也未校验计划是否已被删除或已处于 `completed` 状态，导致双活跃任务并发执行同一计划或重试已完成计划。
- **修复实现**（[`app/tasks/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/service.py)）：
  - 在 `retry_task` 的 `atomic_task_transition`（`BEGIN IMMEDIATE`）内增加计划级强校验：
    1. 计划不存在 -> 抛出 `ValueError(Cannot retry execution: plan #{plan_id} not found)`；
    2. 计划状态为 `completed` -> 抛出 `ValueError(Cannot retry execution: plan #{plan_id} is already completed)`；
    3. 计划已有状态为 `queued`, `running`, `paused`, `cancel_requested` 的活跃任务 -> 抛出 `ValueError(Plan #{plan_id} already has an active execution task #{active_job.id})`。
  - API 统一将上述冲突捕获并转化为 HTTP 409 Conflict。

### 3. Blocker 3 & Blocker 7: 撤销隔离与直接还原真实性
- **问题**：
  - 原撤销计划将隔离操作映射为通用 `move`，导致隔离区记录 `QuarantineEntry` 永远停留在 `active` 状态，恢复后的文件仍显示在隔离区且可被二次还原。
  - 客户端可在普通创建计划接口中传入 `operation="restore"` 伪造还原操作。
  - 直接还原接口（`POST /api/quarantine/{id}/restore`）未注入调用者，在写入 Journal 时 `user_id = None`，并错误继承历史任务和计划项的 `plan_item_id`、`task_id`，造成虚假溯源。
- **修复实现**：
  - **创建计划防护**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：`create_plan` 显式拒绝 `operation == "restore"`（HTTP 400），该操作仅限系统 Undo 引擎生成。
  - **撤销计划映射**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：`create_undo_plan` 将隔离项反向映射为 `operation = "restore"`，并在元数据中关联 `quarantine_entry_id` 与 `source_journal_id`。
  - **Worker 执行还原**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py), [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py)）：Phase 1 标记 `QuarantineEntry.state = "restoring"`；Phase 2 通过 `rename_noreplace` 跨越隔离区边界还原；Phase 3 将 `QuarantineEntry.state` 更新为 `restored` 并设置 `restored_at = now`，同时记录操作为 `restore` 的 `OperationJournal`。
  - **直接还原真实审计**（[`app/api/router.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/api/router.py), [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：直接还原端点获取 `current_user.id` 传入服务层；写入 Journal 时显式置 `plan_id = None, plan_item_id = None, task_id = None, user_id = current_user.id`，彻底清除伪造关联。

### 4. Blocker 4: 暂停/就绪任务取消与计划状态同步
- **问题**：
  - `cancel_task` 取消处于 `paused` 或 `queued` 状态的任务时，仅同步了扫描任务（`sync_scan_job_status`），遗漏了计划同步（`sync_batch_plan_status`），导致计划永久悬挂在 `executing`，用户无法再次执行或编辑。
- **修复实现**（[`app/tasks/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/service.py), [`app/tasks/sync.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/sync.py)）：
  - 在 `cancel_task` 中显式调用 `sync_batch_plan_status(session, job, "cancelled", ...)`。
  - 在 `sync_batch_plan_status` 中完善 `cancelled` 状态流转：若已有条目完成或失败，计划转入可恢复的 `partial` 状态；若所有条目均为 `pending`（如任务尚未开始或处于就绪状态取消），计划恢复为 `ready` 状态。

### 5. Blocker 5 & Blocker 8: Touch 确定性防重放与意图/日志元数据
- **问题**：
  - Touch 操作在崩溃恢复时无条件重置为 `planned` 并重新取当前时间执行 `os.utime()`，造成时间戳多次变动。
  - Phase 1 缺乏针对物理实体的持久化执行意图快照；`OperationJournal` 的 `metadata_before_json` 与 `metadata_after_json` 为空字符串字典 `"{}"`。
- **修复实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py), [`app/batch/plans.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch/plans.py)）：
  - **Phase 1 意图持久化**：操作执行前获取源文件 Stat 快照（`object_type`, `size`, `mtime_ns`, `device`, `inode`）与预确定的 `target_mtime_ns`，写入 `row.metadata_json` 的 `execution` 命名空间。
  - **Touch 确定性与对齐恢复**：`execute_item` 接收确定性 `target_mtime_ns`。崩溃恢复检查时：
    - 若物理文件的当前 `mtime_ns == target_mtime_ns`：说明物理操作已成功发生，直接推进至 `completed` 并补录 Journal，绝不二次修改；
    - 若物理文件的当前 `mtime_ns == before_mtime_ns`：说明崩溃发生在物理操作前，安全重置为 `planned` 重新执行；
    - 若与两者皆不匹配：外部进程已篡改，Fail-Closed 标记为 `failed`。
  - **Journal 元数据快照**：Phase 3 将真实的 `metadata_before_json`（源文件 Stat）与 `metadata_after_json`（操作后实体 Stat）持久化入库。

---

## 3. 验证与回归测试结果 (Verification Evidence)

### 1. Gate2-hotfix1 专项测试 (13 tests)
- **测试文件与覆盖**：
  - `tests/test_gate2_hotfix1_worker_fencing.py`（2 tests）：租约失效边界阻断验证、隔离区 Hash 移出写事务防锁库验证；
  - `tests/test_gate2_hotfix1_retry.py`（4 tests）：并发执行计划重试阻断（409）、已完成计划重试阻断（409）、已删除计划重试阻断（404/409）、就绪/部分完成计划重试成功验证；
  - `tests/test_gate2_hotfix1_cancel_lifecycle.py`（2 tests）：暂停任务取消计划转为 partial 验证、就绪任务取消计划恢复 ready 验证；
  - `tests/test_gate2_hotfix1_undo_and_restore.py`（3 tests）：客户端禁止伪造 restore 计划、撤销隔离计划完整执行并更新隔离区状态至 restored、直接还原真实记录操作者与清除虚假外键关联；
  - `tests/test_gate2_hotfix1_touch_and_intent.py`（2 tests）：Touch 崩溃自愈零重复修改验证、持久化意图与日志元数据完整性验证。
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_hotfix1_*.py"
  ```
  **13 passed, 2 warnings in 1.60s**

### 2. Gate2 全量测试 (27 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_*.py"
  ```
  **27 passed, 2 warnings in 2.86s**

### 3. Gate1 隔离区安全回归测试 (52 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
  ```
  **52 passed, 2 warnings in 2.85s**

### 4. 后端全量测试回归 (415 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest"
  ```
  **415 passed, 20 warnings in 48.08s**

### 5. 前端测试与构建回归
- **前端测试**：`npm test` -> **151 tests / 44 suites, 151 passed, 0 failed**
- **生产构建**：`npm run build` -> **`tsc && vite build` built in 3.69s (0 errors)**

### 6. 容器内端到端对抗演练 (16 阶段全量通过)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -v /Users/Kerwin/.gemini/antigravity/brain/9efda38d-9493-4ba9-9d12-d614c59af46a/scratch:/scratch -w /app nas-test-env bash -c "PYTHONPATH=. python /scratch/gate2_adversarial_smoke.py"
  ```
  ```text
  [SMOKE] 1. Auth OK
  [SMOKE] 2. Test files created
  [SMOKE] 3. Client arbitrary restore plan rejected with 400 OK
  [SMOKE] 4. Plan created, frozen, validated
  [SMOKE] 5. Plan enqueued as WorkJob #1
  [SMOKE] 6. Retry rejected when plan has active execution OK
  [SMOKE] 7. Worker executed plan successfully
  [SMOKE] 8. Retry rejected when plan is completed OK
  [SMOKE] 9. Filesystem mutations verified; quarantine namespace task-1 verified
  [SMOKE] 10. OperationJournal recorded all 4 operations with durable stat metadata
  [SMOKE] 11. Undo Plan #2 generated (0 filesystem mutations)
  [SMOKE] 12. Undo Plan enqueued as WorkJob #3
  [SMOKE] 13. Worker executed Undo Plan
  [SMOKE] 14. QuarantineEntry state updated to 'restored' and restored_at recorded
  [SMOKE] 15. FULL INVERSE VERIFICATION: All files & mtime restored to original state!
  [SMOKE] 16. Direct restore journal actor & zero fake linkage verified OK
  [SMOKE] ALL ADVERSARIAL SMOKE TESTS PASSED!
  ```

---

## 4. Scope Gate 范围核查

- [x] **严格遵守 Gate2 HOLD 约束**：未开启 Gate3，未开启 Gate4。
- [x] **无第三方依赖膨胀**：`pyproject.toml` 与 `package.json` 零新增依赖。
- [x] **无 git push / tag / docker push**。
