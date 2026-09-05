# NAS File Center v0.3.4-Gate2-hotfix4
Reconciliation Evidence Integrity / Zero Write-Tx Hash / Fail-Closed Precompute Race / No Same-Run Re-execution 验收报告

> [!IMPORTANT]
> **版本阶段声明**：
> 本交付物为 **NAS File Center v0.3.4-Gate2-hotfix4** 修复里程碑，**不是 v0.3.4 Final**。
> Gate2 维持 **HOLD** 状态。Gate3（Stale Plan 过期计划自动标记与感知）与 Gate4（Quarantine / Journal / Undo 前端独立管理页面与操作 UI）尚未实现，留待后续阶段实施。
> 禁止提前启动 Gate3/Gate4。严禁 git push / tag / docker push。

---

## 1. 交付概述与演进基线 (Baseline & Provenance)

- **当前里程碑**：`NAS File Center v0.3.4-Gate2-hotfix4`
- **交付目标**：
  解决 Gate2-hotfix3 遗留与识别的 5 项核心缺陷与并发安全漏洞：
  1. **Blocker A (P1)**: 还原崩溃重协调预计算竞争坚决不在写事务内计算哈希（Restore reconciliation precompute race never hashes under write transaction）。杜绝外部在 Phase A 扫描后、Phase B 事务前才完成还原时退化为持有 SQLite 排他写锁（`BEGIN IMMEDIATE`）长耗时哈希的问题。
  2. **Blocker B (P1)**: 隔离崩溃重协调预计算竞争坚决不在写事务内计算哈希（Quarantine reconciliation precompute race never hashes under write transaction）。杜绝外部在 Phase A 扫描后才隔离完成并在 Phase B 事务中退化为持有写锁全量哈希的问题。
  3. **Blocker C & D (P1)**: 重协调证据必须深度绑定物理文件身份（Reconcile Evidence bound to physical file identity）且过期证据坚决 Fail-Closed（Stale precomputed evidence fails closed）。引入不可变快照凭据 `ReconcileEvidence`（绑定 `content_hash`、`device`、`inode`、`size`、`mtime_ns`），在事务内校验物理 stat 与凭据强一致，一旦发生外部改写/篡改/截断，绝不使用失效凭据，坚决拒绝认领并标记 `failed`，绝不在写事务内回退计算哈希。
  4. **Blocker E (P1)**: 崩溃重协调失败项禁止在同一次 Worker 运行中重复执行（No same-run re-execution after reconcile failure）。在 Phase B 标记为 `failed` 的项被加入 `reconciled_failed_item_ids` 并在后续计划项循环中显式跳过，杜绝重入物理执行导致的二次破坏或破坏状态一致性。
- **演进基线 (Baseline)**：
  - **Gate2-hotfix3 基线 Commit**：`3c7748018cd7a95222c0df8a324880e3e57b0104`
  - **Gate2-hotfix3 基线 Artifact SHA256**：`904d8038d5b45a3e5ab891975beac5a948de0feb484ef9be3fe9a4f46e77b79b`
  - **Gate1 验收基线**：`e276e5df66ba30260967b10d3070ea064255492e`
- **测试基线与当前规模**：
  - Backend：**438 passed**（基线 434 + 净增 4 个 Gate2-hotfix4 专项测试，Gate1 52 个安全用例全绿，Gate2 50 个用例全绿）
  - Frontend：**151 passed / 44 suites**

---

## 2. 核心问题修复与技术实现

### 1. 结构性不变量：写事务内零哈希 (Zero Hash Under Write Transaction)
- **问题分析**：
  在 hotfix3 中，Worker 启动时的 `BatchPlanExecuteHandler.run()` 在 Phase A（事务外）预先扫描并哈希可能的目标文件，然后传入 Phase B 的 `_reconcile_executing_item()`。但在原逻辑中，若 Phase A 扫描时目标尚不存在，而在 Phase B 进入 `BEGIN IMMEDIATE` 写事务时目标已被外部进程（如旧 worker）写入，原实现回退为 `precomputed_hash or safe_quarantine_hash(target_path)`。此时 `safe_quarantine_hash` 就会在持有 SQLite 排他写锁期间执行，导致其他并发写连接产生 `database is locked`。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - **彻底移除 `_reconcile_executing_item()` 内的所有 `safe_quarantine_hash` 调用**。
  - 在 SQLite `BEGIN IMMEDIATE` 写锁保护下，重协调逻辑 **100% 绝对不发起任何内容哈希计算**。
  - 对于需要哈希校验的场景（quarantine 与 restore），如果无预计算凭据，或者凭据与当前文件物理 Stat 不匹配，**一律直接 fail-closed，将项置为 `failed`（或保持安全未决状态），绝不生成虚假 OperationJournal**。

### 2. 物理身份绑定凭据与过期凭据 Fail-Closed (Reconcile Evidence Identity)
- **定义数据凭据 `ReconcileEvidence`**：
  ```python
  @dataclass(frozen=True)
  class ReconcileEvidence:
      content_hash: str
      device: int
      inode: int
      size: int
      mtime_ns: int
      object_type: str = "file"
  ```
- **事务外凭据收集函数 `gather_reconcile_evidence(p: Path) -> ReconcileEvidence | None`**：
  - 仅处理非软链接（symlink）的常规文件；
  - 首先通过 `p.stat(follow_symlinks=False)` 采集物理标识；
  - 随后调用 `safe_quarantine_hash(p)`；
  - 哈希完成后再次 stat 验证是否在此期间被变动；
  - 完整打包 `device`, `inode`, `size`, `mtime_ns`, `content_hash`。
- **凭据校验函数 `_validate_evidence(st: os.stat_result, evidence: ReconcileEvidence | None) -> bool`**：
  - 在 Phase B `_reconcile_executing_item` 内部，通过 `target.stat(follow_symlinks=False)` 取得当前物理快照；
  - 严格校验 `st.st_dev == evidence.device`、`st.st_ino == evidence.inode`、`st.st_size == evidence.size`、`st.st_mtime_ns == evidence.mtime_ns`；
  - 只要有任意一项不匹配（说明预计算后文件被追加、篡改、替换、重链接），凭据即刻失效；
  - 凭据失效直接进入 Fail-Closed，拒绝认领，不写日志，记录详细错误原因。

### 3. 重协调失败项禁止同 Run 重入执行 (No Same-Run Re-execution)
- **问题分析**：
  Worker 在启动或接管计划时，在 Phase B 遍历所有 `executing` 项执行 `_reconcile_executing_item()`。若某项因物理凭据不匹配或目标丢失被标记为 `item.state = "failed"`，随后 Worker 退出 Phase B 进入计划项执行主循环 `for item in items:` 时，如果仅根据初始加载的列表执行，可能尝试重新执行刚刚失败的项，造成二次破坏或违背状态机单调性。
- **技术实现**（[`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)）：
  - 引入 `reconciled_failed_item_ids: set[int] = set()`；
  - 在 Phase B 中，一旦重协调判定项失败并持久化 `item.state = "failed"`，立即将其记录进 `reconciled_failed_item_ids`；
  - 在主执行循环遍历计划项时：
    ```python
    if item.id in reconciled_failed_item_ids or item.state == "failed":
        logger.info("Skipping item %s which failed reconciliation in this run", item.id)
        continue
    ```
  - 从根本上杜绝同一 Worker 运行内对重协调失败项的再次执行。

---

## 3. 验证与回归测试结果 (Verification Evidence)

### 1. Gate2-hotfix4 专项测试 (4 tests)
- **测试文件**：`tests/test_gate2_hotfix4_reconciliation_evidence.py`
- **用例清单与覆盖**：
  1. `test_restore_reconciliation_precompute_race_never_hashes_under_write_transaction`:
     验证还原崩溃重协调在预计算竞争（Phase A 扫描时无证据）场景下，Phase B 事务中绝不调用哈希，并发写连接顺利获取排他写锁，重协调项 fail-closed 并标记 `failed`，零虚假 OperationJournal。
  2. `test_quarantine_reconciliation_precompute_race_never_hashes_under_write_transaction`:
     验证隔离崩溃重协调在预计算竞争场景下，绝不持有排他写锁计算哈希，并发写锁不受阻，重协调安全标记 `failed`，零虚假日志。
  3. `test_reconciliation_stale_precomputed_hash_evidence_fails_closed`:
     验证预计算证据在被外部篡改/追加后（物理 Stat 发生偏移），凭据失效，重协调坚决 Fail-Closed，零成功认领。
  4. `test_reconciliation_failed_item_not_reexecuted_in_same_run`:
     验证在 Phase B 重协调被判为 `failed` 的项，在同一次 Worker 运行的主循环中被显式跳过，绝不发起物理变更。
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_hotfix4_reconciliation_evidence.py"
  ```
  **4 passed in 0.49s**

### 2. Gate2 全量测试 (50 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_gate2_*.py"
  ```
  **50 passed, 2 warnings in 3.78s** (包含 hotfix1, hotfix2, hotfix3, hotfix4 全部测试)

### 3. Gate1 隔离区安全回归测试 (52 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest -v tests/test_quarantine_*.py"
  ```
  **52 passed, 2 warnings in 2.80s**

### 4. 后端全量测试回归 (438 tests)
- **运行命令与结果**：
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app nas-test-env bash -c "PYTHONPATH=. pytest"
  ```
  **438 passed, 20 warnings in 47.85s**

### 5. 前端测试与文件系统一致性
- **前端测试**：`cd frontend && npm test -- --run` -> **151 tests / 44 suites, 151 passed, 0 failed**
- **前端代码变更**：`git diff 3c7748018cd7a95222c0df8a324880e3e57b0104 -- frontend/` -> **0 行修改，100% 字节一致**。

### 6. 数据库模型与迁移
- **数据库模型**：`git diff 3c7748018cd7a95222c0df8a324880e3e57b0104 -- app/models.py app/db.py alembic/` -> **0 行修改，零迁移增量**。

---

## 4. Scope Gate 范围核查

- [x] **严格遵守 Gate2 HOLD 约束**：未开启 Gate3，未开启 Gate4。
- [x] **无第三方依赖膨胀**：`pyproject.toml` 与 `package.json` 零新增依赖。
- [x] **无 git push / tag / docker push**。
