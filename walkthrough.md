# NAS File Center v0.3.4-Gate2-hotfix2
Restore Integrity / Crash Identity Reconciliation / Retry State Gate / Undo Algebra Completion 验收报告

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2-hotfix2** 修复里程碑，**不是 v0.3.4 Final**。
> Gate2 维持 **HOLD** 状态。Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。
> 禁止提前启动 Gate3/Gate4。严禁 git push / tag / docker push。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2-hotfix2`
- **交付目标**：
  修复 Gate2-hotfix1 发现的 5 项核心安全与一致性缺陷（还原绕过隔离区完整性防护、崩溃恢复仅凭路径存在猜测试图、恢复日志元数据为空字典、重试接口接受非安全计划状态、还原操作撤销代数不完整与元数据未归一化）：
  1. **Blocker A (P0)**: 统一提炼隔离区还原领域原语（`validate_quarantine_for_restore`），使 Worker 撤销还原与服务层直接还原具备完全一致的完整性保障：哈希校验、尺寸校验、符号链接防护、非 active 状态拦截；篡改内容零文件系统变更、标记 `inconsistent` 并记录 `last_error`；
  2. **Blocker B (P0/P1)**: 崩溃恢复重协调（`_reconcile_executing_item`）禁止仅凭目标路径存在即盲目判断成功，必须比对 Phase 1 意图持久化的源文件物理身份（同文件系统比对 `st_ino` / `st_dev`，跨文件系统比对尺寸与哈希），身份不匹配时 Fail-Closed；
  3. **Blocker C (P1)**: 崩溃恢复补录的 `OperationJournal` 完整持久化操作前源文件 Stat 快照（`metadata_before_json`）与操作后目标文件 Stat 快照（`metadata_after_json`），杜绝空字典 `{}`；
  4. **Blocker D (P1)**: `retry_task` 严格对齐执行安全前置状态：`batch-plan-execute` 任务重试强校验 `plan.status in {"ready", "partial"}`，拒绝 `draft`、`frozen`、`executing` 等中间态计划（HTTP 409）；
  5. **Blocker E (P1)**: 补齐撤销代数闭包（Undo Algebra Completion）：
     - 还原操作（`operation == "restore"`）的逆向操作严格映射为隔离（`operation == "quarantine"`）；
     - 撤销还原执行时创建**全新**的 `QuarantineEntry`（状态 `active`），原已还原的隔离记录维持 `restored`，**严禁复活/重置历史记录**；
     - 归一化撤销计划元数据（`is_undo: True, undo_of_plan_id, source_journal_ids`）与撤销计划项元数据（`undo: {source_journal_id, ...}`）；
     - `create_undo_plan` 对未知/不支持操作安全拒绝，绝不盲猜；
     - `validate_plan` 增加 `restore` 计划项验证（校验对应隔离记录是否存在且处于 `active` 状态）。
- **演进基线 (Baseline)**：
  - **Gate2-hotfix1 基线 Commit**：`d7e67ec9621f53a5bb76826d28dc0422b4b33903`
  - **Gate2-hotfix1 基线 Artifact SHA256**：`643caa469e1c021d0512d128fed52bfa69679f7ed46fb9566b8be1ad73240fe4`
  - **Gate1 验收基线**：`e276e5df66ba30260967b10d3070ea064255492e`
- **测试基线与当前规模**：
  - Backend：**428 passed**（基线 415 + 净增 13 个 Gate2-hotfix2 专项测试，Gate1 52 个安全用例全部绿色）
  - Frontend：**151 passed / 44 suites**

---

## 2. 核心问题修复与技术实现

### 1. Blocker A: 统一还原领域原语与隔离区篡改防御
- **问题分析**：
  Worker 执行撤销计划中的 `restore` 操作时，原直接通过底层 `rename_noreplace` 物理移动文件，跳过了 Gate1 中服务层实现的哈希对比、符号链接校验与状态流转门禁。若隔离区文件在撤销前被外部进程篡改，Worker 会将篡改数据还原至原始路径并标记已还原。
- **技术实现**（[`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py), [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py), [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - 提取独立的还原领域原语 `validate_quarantine_for_restore(entry, *, allowed_roots, quarantine_root, ...)`：
    1. 校验 `entry.state == "active"`；
    2. 校验隔离区目标文件物理存在且非符号链接（`target.is_symlink() or os.path.islink(target)`）；
    3. 校验物理尺寸（若记录）与内容哈希（`safe_quarantine_hash(target) == entry.content_hash`）；
    4. 校验目标还原路径位于允许根目录且不在保留隔离区内。
  - 若检测到被篡改或状态异常：
    - 隔离记录状态就地转入 `inconsistent` 并记录详细 `last_error`；
    - 抛出 `StateConflictError` 或 `ValueError`；
    - Worker 捕获后立即将该计划项标记为 `failed` 并写入失败审计事件，跳过后续物理 I/O，**零物理文件系统修改，零虚假 OperationJournal 写入**。
  - 服务层直接还原 `restore_quarantine_entry` 与 Worker 执行层 `BatchPlanExecuteHandler` 100% 共享此原语。

### 2. Blocker B & Blocker C: 崩溃恢复物理身份比对与日志元数据持久化
- **问题分析**：
  `_reconcile_executing_item` 在 Worker 重启/崩溃自愈时，发现源文件不存在且目标文件存在就盲目认定操作已完成。若目标路径在崩溃期间被第三方创建了无关文件，系统会将该无关文件误认为本次迁移的目标并虚假标记成功。此外，重协调生成的 OperationJournal 的元数据快照字段直接硬编码为 `"{}"`。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - **Phase 1 意图信封持久化**：进入 Phase 1 时在 `row.metadata_json["execution"]` 完整持久化 `task_id`、`operation`、`source_stat`（`device`, `inode`, `size`, `mtime_ns`, `object_type`）及 `metadata_before`。
  - **物理身份验证原语 (`_check_target_identity`)**：
    - 重新协调 `rename`、`move`、`quarantine`、`restore` 操作时，获取目标文件的 `st_dev` 与 `st_ino`；
    - 同一文件系统下严格要求 `st.st_ino == source_stat["inode"]` 且 `st.st_dev == source_stat["device"]`；
    - 跨文件系统时严格校验尺寸一致性；
    - 若物理身份无法证实：Fail-Closed，计划项直接标记为 `failed`（`reconciliation conflict after crash (target identity mismatch)`），若是隔离操作则将隔离记录标记为 `abandoned`，若是还原操作则将隔离记录标记为 `inconsistent`，杜绝产生错误日志。
  - **真实日志快照生成**：
    - 恢复生成的 `OperationJournal` 真实复用意图中的 `metadata_before`，并对现有目标实体执行 `_build_stat_dict` 生成真实的 `metadata_after_json`，彻底告别空字典。

### 3. Blocker D: 重试任务执行安全前置状态门禁
- **问题分析**：
  `retry_task` 仅校验了计划是否处于 `completed` 状态，未限制其他非法状态。用户可以对处于 `draft`、`frozen`、`executing` 等中间或草稿状态的计划调用重试，导致跳过验证或并发执行。
- **技术实现**（[`app/tasks/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/service.py), [`app/exceptions.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/exceptions.py)）：
  - 在 `retry_task` 的事务内，对 `job.kind == "batch-plan-execute"` 增加严格的白名单状态校验：
    ```python
    if plan.status not in {"ready", "partial"}:
        raise StateConflictError(
            f"Cannot retry execution: plan #{plan_id} is in status '{plan.status}', expected 'ready' or 'partial'"
        )
    ```
  - 阻断 `draft`、`frozen`、`executing` 等非法状态的重试请求，并通过统一异常处理返回 HTTP 409 Conflict。

### 4. Blocker E: 撤销代数闭包与元数据归一化
- **问题分析**：
  1. 原 `create_undo_plan` 未处理 `entry.operation == "restore"`，直接跌入兜底逻辑，产生空源路径的错误计划项；
  2. 撤销还原操作需要重新隔离文件，但历史逻辑缺少区分，可能误用旧的已还原 `QuarantineEntry`；
  3. 撤销计划与计划项元数据格式不统一，缺少溯源字段；
  4. 对不支持的操作缺少防御性拒绝。
- **技术实现**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：
  - **还原逆操作定义**：`entry.operation == "restore"` 的逆操作严格定义为 `op = "quarantine"`，源路径取已还原路径 `source_p = after.get("restored_path")`，目标路径置 `None`（交由隔离区动态分配），计划项元数据记录 `{"undo": {"source_journal_id": entry.id, "inverse_of_restore": True}}`；
  - **新实体隔离保障**：Worker 执行该撤销隔离时，作为全新隔离流程处理，生成**全新**的 `QuarantineEntry`（`state = "active"`）。原有已被还原的历史 `QuarantineEntry` 维持 `restored` 状态不变；
  - **元数据标准化**：
    - `BatchPlan.metadata_json` 统一包含：`{"is_undo": True, "undo_of_plan_id": plan_id, "created_by_user_id": user_id, "source_journal_ids": [...]}`；
    - `BatchPlanItem.metadata_json` 统一包含：`{"undo": {"source_journal_id": entry.id, ...}}`；
  - **不支持操作防御**：若日志包含未知操作，显式抛出 `ValueError(f"Cannot create undo plan: unsupported operation '{entry.operation}' in journal #{entry.id}")`；
  - **计划验证扩展**：`validate_plan` 增加 `operation == "restore"` 分支，强校验所关联的 `QuarantineEntry` 存在且状态为 `active`，否则标记 `skipped` 且计划状态转入 `partial`，阻止就绪执行。

---

## 3. 验证与回归测试结果 (Verification Evidence)

### 1. Gate2-hotfix2 专项测试 (13 tests)
- **测试文件与覆盖**：
  - `tests/test_gate2_hotfix2_restore_integrity.py`（3 tests）：
    - `test_undo_restore_rejects_tampered_quarantine_content`: 隔离文件同尺寸篡改后撤销执行，强哈希校验失败拦截，源路径未还原，隔离记录置 `inconsistent`，计划项 `failed`，零日志写入；
    - `test_undo_restore_rejects_symlink_quarantine_target`: 隔离文件被替换为符号链接时拦截，标记 `inconsistent`；
    - `test_plan_validation_checks_quarantine_entry_for_restore`: 隔离记录非 `active`（如 `purged`）时计划验证跳过该项，计划状态置 `partial`。
  - `tests/test_gate2_hotfix2_reconciliation_identity.py`（4 tests）：
    - `test_rename_crash_reconcile_rejects_unrelated_target`: 重命名崩溃恢复检测到 inode 不匹配，拒绝误认成功，Fail-Closed 置 `failed` 且零日志写入；
    - `test_rename_crash_reconcile_accepts_matching_target_and_writes_full_metadata`: 真实重命名崩溃恢复，比对 inode 成功，补录具备完整尺寸、设备号、inode、时间戳的 Stat 元数据日志；
    - `test_quarantine_crash_reconcile_rejects_unrelated_target`: 隔离崩溃恢复检测到 inode 不匹配，隔离记录置 `abandoned`，计划项 `failed`；
    - `test_quarantine_crash_reconcile_accepts_matching_target_with_metadata`: 真实隔离崩溃恢复比对成功，激活隔离记录并写入完整元数据日志。
  - `tests/test_gate2_hotfix2_retry_status.py`（4 tests）：
    - `test_retry_rejects_draft_plan`: 拒绝草稿状态计划重试；
    - `test_retry_rejects_frozen_plan`: 拒绝冻结状态计划重试；
    - `test_retry_rejects_executing_plan`: 拒绝执行中状态计划重试；
    - `test_retry_allows_ready_or_partial_plan`: 允许 `ready` 或 `partial` 状态计划重试并生成队列任务。
  - `tests/test_gate2_hotfix2_undo_algebra.py`（2 tests）：
    - `test_undo_of_restore_generates_quarantine_and_executes_to_new_entry`: 撤销还原操作生成 `quarantine` 项，执行后生成全新的活跃隔离记录，旧隔离记录维持 `restored` 不变；
    - `test_undo_rejects_unsupported_operation`: 遇未知操作日志时防御性抛出明确异常。
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_hotfix2_*.py"
  ```
  **13 passed, 2 warnings in 1.48s**

### 2. Gate2 全量测试 (40 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_*.py"
  ```
  **40 passed, 2 warnings in 3.66s**

### 3. Gate1 隔离区安全回归测试 (52 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
  ```
  **52 passed, 2 warnings in 2.85s**

### 4. 后端全量测试回归 (428 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest"
  ```
  **428 passed, 20 warnings in 50.12s**

### 5. 前端测试与构建回归
- **前端测试**：`cd frontend && npm test -- --run` -> **151 tests / 44 suites, 151 passed, 0 failed**
- **前端代码变更**：**0 行修改**（工作区 `frontend/` 目录完全保持未动）。

### 6. 容器内端到端对抗演练 (20 阶段全量通过)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -v /Users/Kerwin/.gemini/antigravity/brain/9efda38d-9493-4ba9-9d12-d614c59af46a/scratch:/scratch -w /app nas-test-env bash -c "PYTHONPATH=. python3 /scratch/gate2_adversarial_smoke.py"
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
  [SMOKE] --- Starting Gate2 Hotfix2 Verifications ---
  [SMOKE] 17. Blocker A: Tampered quarantine content fail-closed verified OK
  [SMOKE] 18. Blocker B: Crash reconciliation identity mismatch rejected OK
  [SMOKE] 19. Blocker D: Retry on draft/frozen rejected with 409 OK
  [SMOKE] 20. Blocker E: Undo of restore -> new QuarantineEntry created, old stays restored OK
  [SMOKE] ALL ADVERSARIAL SMOKE TESTS (GATE2 + HOTFIX1 + HOTFIX2) PASSED!
  ```

---

## 4. Scope Gate 范围核查

- [x] **严格遵守 Gate2 HOLD 约束**：未开启 Gate3，未开启 Gate4。
- [x] **无第三方依赖膨胀**：`pyproject.toml` 与 `package.json` 零新增依赖。
- [x] **无 git push / tag / docker push**。
