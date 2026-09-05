# NAS File Center v0.3.4-Gate2-hotfix3
Restore Mutation-Boundary Integrity / Fail-Closed Reconciliation / Zero Long Hash Transactions / Direct Restore Metadata 验收报告

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2-hotfix3** 修复里程碑，**不是 v0.3.4 Final**。
> Gate2 维持 **HOLD** 状态。Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。
> 禁止提前启动 Gate3/Gate4。严禁 git push / tag / docker push。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2-hotfix3`
- **交付目标**：
  解决 Gate2-hotfix2 验收中识别的 5 项核心缺陷与安全漏洞：
  1. **Blocker A (P0)**: 还原变更高频边界防护（Restore Mutation-Boundary Integrity）。将长耗时内容哈希与短事务彻底解耦，在物理变更紧邻边界（Pre-mutation Fence）完成哈希与元数据防篡改比对；杜绝 Phase 1 意图提交与 Phase 2 文件系统操作窗口期内的外部篡改攻击；被篡改时零物理写入、隔离记录置 `inconsistent` 并记录详细错误。
  2. **Blocker B (P0/P1)**: 崩溃恢复物理身份必须 Fail-Closed。`_check_target_identity` 在源文件元数据为空或缺失时坚决返回 `False`，拒绝仅凭目标路径存在猜测成功，防止无关实体被误认造成虚假日志。
  3. **Blocker C (P1)**: 跨文件系统目标严禁认可（Cross-Filesystem Target Rejection）。在当前 `rename_noreplace` 语意下，若目标文件的 `st_dev` 与源文件的持久化 `device` 不一致，严格判定身份不匹配并 Fail-Closed。
  4. **Blocker D (P1)**: 杜绝在 `BEGIN IMMEDIATE` 持写锁期间计算全文件哈希（Zero Long Hash under Write Transaction）。Worker 还原与崩溃恢复均在进入 SQLite 排他写事务前或在写锁外完成 `safe_quarantine_hash` 计算，彻底消除并发写事务被锁定（`OperationalError: database is locked`）的隐患。
  5. **Blocker E (P1)**: 服务层直接还原补齐完整 Stat 快照。直接还原产生的 `OperationJournal` 完整持久化隔离区源文件 Stat 快照（`metadata_before_json`）与还原后文件 Stat 快照（`metadata_after_json`），包含 `object_type`、`size`、`mtime_ns`、`device`、`inode`，彻底清除空字典 `{}`。
- **演进基线 (Baseline)**：
  - **Gate2-hotfix2 基线 Commit**：`1dc278ef79f2b00ab4eb8ee84cee49f3cb47ce9f`
  - **Gate2-hotfix2 基线 Artifact SHA256**：`06d5d663ceb2527b2cd783ca0298993f198944a9bd5ade41632458792e974d19`
  - **Gate1 验收基线**：`e276e5df66ba30260967b10d3070ea064255492e`
- **测试基线与当前规模**：
  - Backend：**434 passed**（基线 428 + 净增 6 个 Gate2-hotfix3 专项测试，Gate1 52 个安全用例全绿，Gate2 46 个用例全绿）
  - Frontend：**151 passed / 44 suites**

---

## 2. 核心问题修复与技术实现

### 1. Blocker A: 还原变更高频边界防护与三阶段解耦 (Mutation-Boundary Integrity)
- **问题分析**：
  原实现将还原哈希检查置于 Phase 1 事务中，哈希通过后提交意图。在 Phase 1 提交至 Phase 2 底层调用 `rename_noreplace` 之间存在时间窗口。若外部进程在此期间将隔离区文件篡改（即便物理长度相同），原有执行层将篡改数据物理恢复至源路径并标记成功。
- **技术实现**（[`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py), [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py), [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py), [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：
  - **拆分解耦还原原语**：
    - `validate_restore_destination_intent`: 仅检查数据库状态（`active`）、目标合法性与冲突策略，执行迅速，适合放入短数据库事务；
    - `verify_quarantine_source_integrity`: 在数据库写事务之外计算内容哈希并采集源文件 Stat 校验快照（包含 `device`、`inode`、`size`、`mtime_ns`）；
    - `assert_source_unmodified`: 在物理执行前最后一道边界校验物理 Stat 是否发生任何偏移。
  - **底层执行器守卫**：
    - `execute_item` 在执行 `operation == "restore"` 时支持将 `quarantine_root` 纳入安全源路径校验；
    - 在真正调用 `rename_noreplace` 之前，再次校验 `item.expected_hash` 与 `item.expected_size`；
    - 一旦检测到哈希不符，立即返回 `ItemResult("failed", ...)`，**绝不触碰文件系统物理变更**；
    - Phase 3 事务中将隔离记录置为 `inconsistent` 并记录详细错误原因。

### 2. Blocker B & Blocker C: 崩溃恢复身份 Fail-Closed 与跨文件系统目标阻断
- **问题分析**：
  1. `_check_target_identity` 在入参 `source_stat` 为空字典时原返回 `True`，导致缺少源身份证明时依然认定恢复成功；
  2. 当源文件与目标文件处于不同文件系统设备（`target.st_dev != source.device`）但尺寸恰巧相同时，原逻辑误判成功。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - **Fail-Closed 身份门禁**：
    ```python
    def _check_target_identity(target: Path, source_stat: dict) -> bool:
        if not source_stat or not isinstance(source_stat, dict):
            return False
        src_dev = source_stat.get("device")
        src_ino = source_stat.get("inode")
        if src_dev is None or src_ino is None:
            return False
        st = target.stat(follow_symlinks=False)
        if st.st_dev != src_dev:
            return False
        if st.st_ino != src_ino:
            return False
        return True
    ```
  - 缺失源物理身份信息坚决 Fail-Closed；
  - 严格匹配同一文件系统下的物理设备号与 Inode 节点，阻断跨设备未知实体认领。

### 3. Blocker D: 彻底消除长事务排他写锁 (Zero Long Hash under Write Transaction)
- **问题分析**：
  在 Worker 还原和崩溃恢复（`_reconcile_executing_item`）过程中，如果持有 `BEGIN IMMEDIATE` 排他事务锁的同时计算全文件 SHA256，将长时间阻塞并发 SQLite 连接，造成 `OperationalError: database is locked`。
- **技术实现**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py), [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - **服务层直接还原**：将 `restore_quarantine_entry` 改造为 3 个微阶段：
    - Phase 1（微事务）：校验目标意图，将状态设为 `restoring` 并提交；
    - Phase 2（无锁文件系统阶段）：在无事务保护下执行 `verify_quarantine_source_integrity`（全量哈希）、`assert_source_unmodified` 及物理 `rename_noreplace`；
    - Phase 3（微事务）：将状态更新为 `restored`，持久化完整 `OperationJournal`。
  - **Worker 执行与启动重协调**：
    - `BatchPlanExecuteHandler.run()` 在进入 `BEGIN IMMEDIATE` 前预先扫描并计算待协调项的内容哈希（`precomputed_reconcile_hashes`）；
    - Phase 1 事务中仅调用 `validate_restore_destination_intent`；
    - `verify_quarantine_source_integrity` 移至 Phase 1 提交之后、Phase 2 物理变更之前无锁执行。

### 4. Blocker E: 直接还原日志补全 Stat 真实快照
- **问题分析**：
  服务层直接还原调用 `restore_quarantine_entry` 时，之前写入的 `OperationJournal` 中 `metadata_before_json` 与 `metadata_after_json` 均为硬编码的 `"{}"`。
- **技术实现**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：
  - `metadata_before_json` 写入隔离区源文件的完整 Stat 快照（由 `verify_quarantine_source_integrity` 返回）；
  - `metadata_after_json` 写入还原后目标实体的真实 Stat 快照（`object_type`、`size`、`mtime_ns`、`device`、`inode`）；
  - 恢复日志元数据达到 100% 完整持久化。

---

## 3. 验证与回归测试结果 (Verification Evidence)

### 1. Gate2-hotfix3 专项测试 (6 tests)
- **测试文件**：`tests/test_gate2_hotfix3_restore_boundaries.py`
- **用例清单与覆盖**：
  1. `test_reconcile_missing_source_identity_fails_closed`: 验证源文件身份缺失时 `_check_target_identity` 与崩溃重协调坚决 Fail-Closed，零日志写入；
  2. `test_reconcile_cross_filesystem_same_size_target_fails_closed`: 验证跨不同文件系统目标（`st_dev != source.device`）坚决拒绝认领；
  3. `test_direct_restore_journal_contains_identity_metadata`: 验证直接还原记录的 `OperationJournal` 完整持久化 before 与 after 的真实 Stat 快照；
  4. `test_worker_restore_hash_does_not_hold_sqlite_write_transaction`: 验证 Worker 还原计算哈希期间其他连接可并发进行 `BEGIN IMMEDIATE` 写事务；
  5. `test_restore_reconciliation_hash_does_not_hold_sqlite_write_transaction`: 验证崩溃重协调计算哈希期间不阻塞并发写事务；
  6. `test_restore_tamper_after_phase1_before_mutation_is_rejected`: 验证 Phase 1 提交后、变更高频边界被篡改时，物理还原坚决终止，零文件系统写破坏，状态标记为 `inconsistent`。
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_hotfix3_restore_boundaries.py"
  ```
  **6 passed in 0.55s**

### 2. Gate2 全量测试 (46 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_*.py"
  ```
  **46 passed, 2 warnings in 3.95s**

### 3. Gate1 隔离区安全回归测试 (52 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
  ```
  **52 passed, 2 warnings in 2.90s**

### 4. 后端全量测试回归 (434 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest"
  ```
  **434 passed, 20 warnings in 48.65s**

### 5. 前端测试与文件系统一致性
- **前端测试**：`cd frontend && npm test -- --run` -> **151 tests / 44 suites, 151 passed, 0 failed**
- **前端代码变更**：`git diff 1dc278ef79f2b00ab4eb8ee84cee49f3cb47ce9f -- frontend/` -> **0 行修改，100% 字节一致**。

### 6. 数据库模型与迁移
- **数据库模型**：`git diff 1dc278ef79f2b00ab4eb8ee84cee49f3cb47ce9f -- app/models.py app/db.py alembic/` -> **0 行修改，零迁移增量**。

---

## 4. Scope Gate 范围核查

- [x] **严格遵守 Gate2 HOLD 约束**：未开启 Gate3，未开启 Gate4。
- [x] **无第三方依赖膨胀**：`pyproject.toml` 与 `package.json` 零新增依赖。
- [x] **无 git push / tag / docker push**。
