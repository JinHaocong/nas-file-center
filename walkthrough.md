# NAS File Center v0.3.4-Gate2-hotfix5
Restore / Reconciliation Identity Freshness 验收报告
Same-mtime Tamper Rejection / Stable Hash Snapshot / ctime-bound Runtime Evidence / Unified Restore Integrity Semantics

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2-hotfix5** 修复里程碑，**不是 v0.3.4 Final**。
> Gate2 维持 **HOLD** 状态。Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。
> 禁止提前启动 Gate3/Gate4。严禁 git push / tag / docker push。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2-hotfix5`
- **交付目标**：
  解决 Gate2-hotfix4 独立审查识别的身份新鲜度绕过漏洞与哈希快照稳定性缺陷：
  1. **Blocker A (P0)**: 服务层直接还原同时间戳篡改防护（Direct Restore Same-mtime Tamper Rejection）。阻断在哈希校验通过后、物理重命名前外部使用相同尺寸覆写相同 Inode 并使用 `os.utime()` 精确恢复 `mtime_ns` 的攻击绕过；在物理变更前校验 `ctime_ns` 变动，坚决阻断物理还原，将隔离记录置为 `inconsistent` 并记录详细错误，零写入成功日志。
  2. **Blocker B (P0)**: 还原崩溃重协调同时间戳篡改 Fail-Closed（Restore Crash Reconciliation Same-mtime Tamper Fail-Closed）。在 Phase A 采集有效哈希凭据后、Phase B 事务前，目标被篡改并恢复 `mtime_ns` 时，事务内通过 `_validate_evidence()` 检测 `ctime_ns` 差异，坚决拒绝认定还原成功，计划项判为 `failed`，隔离区置 `inconsistent`，零虚假 OperationJournal，持写锁期间零哈希。
  3. **Blocker C (P1)**: 隔离崩溃重协调同时间戳篡改 Fail-Closed（Quarantine Crash Reconciliation Same-mtime Tamper Fail-Closed）。隔离目标在证据采集后被篡改并恢复 `mtime_ns` 时，事务内检测 `ctime_ns` 不符，判为 `failed`，记录置 `abandoned`，杜绝持久化虚假的 `content_hash`，零虚假成功日志。
  4. **Root Cause A (P0)**: `mtime_ns` 用户可任意伪造，运行时完整性快照必须深度绑定 `ctime_ns`（内核状态变更纳秒时间戳），构成 Linux 环境下防静默篡改的运行时新鲜度围栏（Runtime Freshness Fence）。零 DB 模式变更。
  5. **Root Cause B (P1)**: 哈希快照跨计算过程物理稳定性验证（Stable Hash Snapshot）。在 `gather_reconcile_evidence()` 与 `verify_quarantine_source_integrity()` 中严格执行 `stat_before` 与 `stat_after` 双重比对（比对 `device`、`inode`、`size`、`mtime_ns`、`ctime_ns`），只要哈希期间文件被改写、追加或触碰，立刻拒绝产出有效凭据或报错中断，杜绝接受不稳定的哈希。
  6. **Unified Restore Integrity Semantics**: 统一服务层直接还原与 Worker 还原的运行时 Stat 快照契约（`object_type`、`size`、`mtime_ns`、`ctime_ns`、`device`、`inode`），并在物理执行前严格执行 `assert_source_unmodified` 校验。
- **演进基线 (Baseline)**：
  - **Gate2-hotfix4 基线 Commit**：`e52521410ef155be62fe0b785ce9a0bdce23ff0b`
  - **Gate2-hotfix4 基线 Artifact SHA256**：`0eb7acc6aad94166aa3e378216650d48cae2a344d11131c5a9598d9ece241d9b`
  - **Gate1 验收基线**：`e276e5df66ba30260967b10d3070ea064255492e`
- **测试基线与当前规模**：
  - Backend：**443 passed**（基线 438 + 净增 5 个 Gate2-hotfix5 专项对抗测试，Gate1 52 个安全用例全绿，Gate2 55 个用例全绿）
  - Frontend：**151 passed / 44 suites**

---

## 2. 核心问题修复与技术实现

### 1. ctime 绑定运行时新鲜度围栏 (ctime-bound Runtime Freshness Fence)
- **原理**：
  在 Linux/Unix 文件系统语义下，普通用户使用 `write()` 覆写文件会同时更新 `st_mtime` 和 `st_ctime`；即便后续使用 `os.utime()` 恢复了原始的 `atime` 与 `mtime`，`os.utime()` 自身作为 inode 元数据修改操作，依然会强制将 `st_ctime` 刷新为当前系统时间。
  因此，仅比对 `(device, inode, size, mtime_ns)` 允许了攻击者在相同 inode 上覆盖同尺寸内容并复原 mtime 绕过检查；增加对 `ctime_ns` 的不可变校验，即可在不增加持久化 DB 列的前提下，构筑运行时的强新鲜度校验屏障。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py), [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py)）：
  - 更新 `ReconcileEvidence` 运行时数据结构：
    ```python
    @dataclass(frozen=True)
    class ReconcileEvidence:
        content_hash: str
        device: int
        inode: int
        size: int
        mtime_ns: int
        ctime_ns: int
        object_type: str = "file"
    ```
  - `_validate_evidence` 严格要求包含 `ctime_ns`，并与物理实体的实时 `st_ctime_ns` 匹配；缺失或不符一律 Fail-Closed。
  - `assert_source_unmodified` 增加对 `ctime_ns` 的即时比对，阻断同时间戳物理变更。

### 2. 哈希计算稳定性双重核验 (Pre-hash & Post-hash Stat Verification)
- **原理与纠偏**：
  纠正此前文档中未彻底落地的描述，在生产代码中真正实现哈希前与哈希后的物理一致性比对。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py), [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py)）：
  - 在 `gather_reconcile_evidence(p)` 中：
    1. 执行 `st_before = p.stat(follow_symlinks=False)`；
    2. 计算无锁内容哈希 `h = safe_quarantine_hash(p)`；
    3. 执行 `st_after = p.stat(follow_symlinks=False)`；
    4. 对比前后 `st_dev`、`st_ino`、`st_size`、`st_mtime_ns`、`st_ctime_ns`；若有任何一项不同，说明哈希期间文件被变动，立即返回 `None`（拒绝产出凭据）。
  - 在 `verify_quarantine_source_integrity(target)` 中：
    同样对 `st_before` 与 `st_after` 进行完整对比，若有变动立即抛出 `ValueError("Quarantined source modified during hash verification")`。

### 3. 统一还原完整性语义与异常状态转移 (Unified Restore Semantics)
- **服务层直接还原**（[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)）：
  - 针对 `assert_source_unmodified` 抛出的 `ValueError`，捕获并将 `QuarantineEntry.state` 明确设置为 `inconsistent`，记录 `last_error` 并提交，确保失败时零文件物理移动、隔离区源文件完整保留、零还原日志生成。
- **Worker 还原执行器**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - 在 Worker 任务主循环中，在执行物理变更前调用 `assert_source_unmodified(src_p, verified_restore_stat)` 校验 `ctime_ns`；
  - 发生篡改时立即记录审计事件并将计划项标为 `failed`、隔离区标为 `inconsistent`，阻断后续 `execute_item` 物理变更。

### 4. 结构性不变量维持：排他写事务内零哈希
- 重协调函数 `_reconcile_executing_item` 绝不在 `BEGIN IMMEDIATE` 持写锁期间调用任何内容哈希；所有哈希均在 Phase A 事务外完成并绑定包含 `ctime_ns` 的不可变快照。

---

## 3. 严格 TDD 验证过程 (Strict TDD Evidence)

### 1. RED 阶段：精确复现与失败定位
在编写生产代码前，于 [`tests/test_gate2_hotfix5_freshness.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate2_hotfix5_freshness.py) 编写 5 个对抗性测试用例：
1. `test_direct_restore_same_size_same_mtime_tamper_after_hash_is_rejected`: 在基线代码上因未能阻断篡改而执行成功（`Failed: DID NOT RAISE <class 'ValueError'>`）；
2. `test_worker_restore_same_size_same_mtime_tamper_is_rejected`: 在基线代码上项被误判完成（`Item must fail, got completed`）；
3. `test_restore_reconciliation_same_inode_same_size_restored_mtime_tamper_fails_closed`: 在基线代码上崩溃重协调误认成功（`Item must fail, got completed`）；
4. `test_quarantine_reconciliation_same_inode_same_size_restored_mtime_tamper_fails_closed`: 在基线代码上崩溃重协调误认成功并写入原哈希（`Item must fail, got completed`）；
5. `test_reconcile_evidence_rejects_file_changed_during_hash`: 在基线代码上未核验 post-hash stat，文件在哈希期间变动仍返回凭据（`Expected None, got ReconcileEvidence(...)`）。
**5 个对抗用例全部精确复现预期缺陷并进入 RED 状态**。

### 2. GREEN 阶段：最小化生产加固
引入 `ctime_ns` 运行时围栏、双重 stat 稳定性对比并在 [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py)、[`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)、[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py) 完成修复后：
```bash
docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_hotfix5_freshness.py"
```
**结果：5 passed in 0.26s**

---

## 4. 全量回归与一致性核查 (Regression & Verification Suite)

### 1. Gate2 专项与全量测试套件 (55 passed)
```bash
docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_*.py"
```
**结果：55 passed, 2 warnings in 3.94s**（基线 50 + 净增 5 个 hotfix5 专项测试）

### 2. Gate1 隔离区安全回归套件 (52 passed)
```bash
docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
```
**结果：52 passed, 2 warnings in 2.70s**

### 3. 后端全量测试回归套件 (443 passed)
```bash
docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest"
```
**结果：443 passed, 20 warnings in 47.69s**（较基线 438 净增 5 个专项测试，零失败）

### 4. 前端测试与文件一致性核验 (151 passed / 0 diff)
- 前端测试套件执行：
  ```bash
  npm --prefix frontend test -- --run
  ```
  **结果：151 passed / 44 suites, 0 failed in 91.61ms**
- 前端文件变更：
  `git diff e52521410ef155be62fe0b785ce9a0bdce23ff0b HEAD -- frontend/` -> **0 行修改，100% 字节一致**。

### 5. 数据库模型与迁移零增量 (0 diff)
- `git diff e52521410ef155be62fe0b785ce9a0bdce23ff0b HEAD -- app/models.py app/db.py alembic/` -> **0 行修改，零迁移增量**。

### 6. 依赖项零增量 (0 diff)
- `git diff e52521410ef155be62fe0b785ce9a0bdce23ff0b HEAD -- pyproject.toml package.json package-lock.json` -> **0 行修改，零依赖变更**。

---

## 5. Scope Gate 范围核查确认

| 检查项 | 约束要求 | 实际状态 | 结果 |
| :--- | :--- | :--- | :--- |
| **Gate2 状态** | 必须维持 HOLD，等待 NAS 独立验收 | 已声明 HOLD | **PASS** |
| **Gate3 范围** | 禁止开启 Stale Plan 功能 | 零接触 | **PASS** |
| **Gate4 范围** | 禁止开启独立前端管理页面 | 零接触 | **PASS** |
| **外部依赖** | 禁止引入新 pip / npm 包 | 依赖配置文件 0 变更 | **PASS** |
| **发布操作** | 严禁 git push / tag / docker push | 零网络推送操作 | **PASS** |
