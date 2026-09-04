# NAS File Center v0.3.3-step1-fixed9 验收报告与实现文档

## 1. 概述与目标

本轮迭代为 **NAS File Center v0.3.3-step1-fixed9**，作为 Task Engine Backend 最终 Worker 时序边界收尾与锁序治理。严格遵守“先 RED 编写测试复现失败，再 GREEN 实施代码修复”的准则，彻底解决了如下关键问题：

1. **修复 Claim → Cancel → Process Startup 时序竞争（Worker Preflight）**：
   - 彻底解决在 Worker 通过 `claim_next_job` 认领任务与 `process_work_job` 正式启动期间，外部用户调用 API 发起取消（导致状态变更为 `cancel_requested`）后，`process_work_job` 误执行 `cancel_requested -> running` 引发非法状态迁移异常并导致任务卡死的严重缺陷；
   - 在 `process_work_job` 初始阶段建立显式 Worker Preflight：在 `BEGIN IMMEDIATE` 写事务与 active lease 保护下重新加载 `WorkJob` 真实当前状态；
   - 若状态为 `cancel_requested`：原子推进至 `cancelled`，同步更新 `ScanJob` 状态、清空局部临时数据，跳过 Handler 并安全返回 `True`；
   - 若状态已处于终态或暂停状态：直接安全返回 `True` 跳过执行，杜绝状态逆转或覆盖；
   - 若状态为 `queued`：保持向后兼容，合法迁移为 `running` 后继续执行；
   - 若状态为 `running`：刷新心跳并进入 Handler。

2. **Worker Preflight 纳入完整主异常合约保护**：
   - Preflight 阶段的所有数据库读取与校验完整纳入 `try ... except` 保护；
   - 捕获 `JobLeaseLost` 时立即安全返回 `False`，绝不外冒异常，不崩溃 Worker 主循环；
   - 任务不存在或被删除时安全 rollback 并返回 `False`。

3. **`recover_interrupted_jobs` 候选集单次查询与当前状态分发**：
   - 将原先分离的 `cancel_requested` 与 `running` 查询合并为一次性原子候选集提取（`status IN ('running', 'cancel_requested')`）；
   - 在逐个恢复任务的独立 `BEGIN IMMEDIATE` 事务内重新加载最新状态并根据 `job.status` 进行分发；
   - 若在此期间任务状态由外部变更为 `cancel_requested`，自动分发至取消分支，杜绝任务漏恢复或卡死在 `cancel_requested`。

4. **严格执行 "LOCK FIRST, CLOCK SECOND, VALIDATE THIRD, MUTATE FOURTH" 锁钟次序规范**：
   - 彻底修复因在等待 SQLite writer lock 之前过早采样 `now = utcnow()`，导致锁排队等待耗时被忽略、进而可能使过期租约被误判为新鲜租约的时钟漂移风险；
   - 全面审计并规范化所有涉及租约判断与数据更新的 Worker 事务：
     - `update_worker_heartbeat`
     - `claim_next_job`
     - `recover_interrupted_jobs`
     - `JobContext.checkpoint`
     - `JobContext.log`
     - `process_work_job`（Preflight、正常完成、取消同步、未知任务失败、异常捕获）
     - `FclonesScanHandler`（分批导入、终态同步、取消/异常清理）
     - `IndexRootHandler`（批量索引、代际清理 guard）
   - 统一遵循先执行 `session.execute(text("BEGIN IMMEDIATE"))` 取得互斥写锁，再采样 `now = utcnow()`，再传参 `now=now` 校验 `assert_active_worker_lease`，最后执行数据更新的四步规范。

---

## 2. RED 失败复现与 GREEN 验证

在编码前，于 `tests/test_fixed9_regressions.py` 中编写 6 组针对性测试，在 Docker 容器（Python 3.12）内完整复现失败（RED 阶段）：

### 2.1 RED 阶段复现记录
```text
FAILED tests/test_fixed9_regressions.py::test_cancel_between_claim_and_process_start_finishes_cancelled
- 报错: JobTransitionError: Illegal state transition from 'cancel_requested' to 'running'

FAILED tests/test_fixed9_regressions.py::test_recovery_handles_cancel_that_arrives_after_candidate_snapshot
- 报错: AssertionError: Expected cancelled but got cancel_requested
```

### 2.2 GREEN 修复后验证
```text
tests/test_fixed9_regressions.py ......                                  [100%]
6 passed in 1.48s
```

### 2.3 全量自动化测试回归套件（含全部历史基线与新测试）
```text
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 97%]
......                                                                   [100%]
============================== 222 passed in 33.74s ===============================
```
所有 222 项单元测试与集成测试全部通过，零回归！

---

## 3. 前端与容器构建验证

1. **前端类型检查与生产编译**：
   ```bash
   cd frontend && npm ci && npm run typecheck && npm run build
   ```
   - 结果：TypeScript 零错误，Vite 构建产物生成正常。
2. **生产镜像多架构构建**：
   ```bash
   docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step1-fixed9 .
   ```
   - 结果：镜像成功构建，容器内 `fclones --version` 验证输出 `fclones 0.35.0` 正常。

---

## 4. 安全合规与交付包验证

1. **安全配置默认值检验**：
   - 确认核心敏感开关默认维持 Fail-closed：`ALLOW_MUTATION=false`, `ALLOW_DELETE=false`, `PROTECT_LAST_FILE=true`。
2. **敏感词合规扫描**：
   ```bash
   grep -Rni -E '少女映画|shaonv' .
   ```
   - 结果：匹配数量为 0。
3. **交付压缩包生成与干净容器复测**：
   - 打包生成 `nas-file-center-v0.3.3-step1-fixed9.zip`（排除了 `.git`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, `.DS_Store` 等临时或构建缓存）。
   - 在独立无污染容器内解压并运行完整自动化测试套件与 SQLite 数据库完整性检查（`PRAGMA integrity_check = ok`）。
