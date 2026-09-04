# NAS File Center v0.3.3-step1-fixed10 验收报告与实现文档

## 1. 概述与核心问题

本轮迭代为 **NAS File Center v0.3.3-step1-fixed10**，作为 Task Engine Backend 最终 Gate 的窄范围收口。针对独立 Review 在 fixed9 中发现的关键 Release Blocker：

### 1.1 核心缺陷根因分析
- **问题**：在 `TaskService` 的部分状态变更方法（如 `cancel_task()` 和 `retry_task()`）中，在进入 `atomic_task_transition`（即获取 SQLite writer lock `BEGIN IMMEDIATE`）之前，过早执行了 `now = utcnow()` 采样；
- **时序竞争（Causality Inversion）**：当并发发生 Worker `claim_next_job`（取得 writer lock，写入 `started_at`）时，concurrent `cancel_task()` 因已在排队等待写锁前采集了 `now`，导致锁等待释放后写入的 `cancel_requested_at` 比 `started_at` 更早（真实观测曾出现约 -0.250s 的时钟倒流）；
- **Retry 时序失真**：`retry_task()` 在等待 writer lock 排队期间，新生成的 `WorkJob.created_at` 同样使用了排队前的旧时间戳，不符合事务时间语义。

### 1.2 修复策略
严格践行 **LOCK FIRST $\rightarrow$ CLOCK SECOND $\rightarrow$ VALIDATE THIRD $\rightarrow$ MUTATE FOURTH $\rightarrow$ COMMIT** 约束：
1. **`atomic_task_transition` 统一提供事务时间**：
   - 在 `session.execute(text("BEGIN IMMEDIATE"))` 取得互斥写锁后，立即采样 `transaction_now = utcnow()`；
   - 通过函数签名适配将 `transaction_now` 作为参数传递给状态迁移回调函数 `transition_fn(session, job, transaction_now)`；
2. **`cancel_task` 彻底移除锁外采样**：
   - 彻底移除 `cancel_task()` 外层的 `now = utcnow()`；
   - 在回调内使用由原子锁内注入的 `now` 设置 `job.finished_at = now`、`job.cancel_requested_at = now` 以及 `sync_scan_job_status(finished_at=now)`；
   - `log_task_event` 同步使用 `timestamp=now`，确保事件与状态字段处于同一时钟基准；
3. **`retry_task` 彻底移除锁外采样**：
   - 彻底移除 `retry_task()` 外层的 `now = utcnow()`；
   - 在回调内使用原子锁内注入的 `now` 设置 `new_job.created_at = now` 及相关重试事件时间；
4. **`pause_task` 与 `resume_task` 统一规范**：
   - `pause_task` 使用锁内 `now` 设置 `job.pause_requested_at = now`；
   - `pause_task` 与 `resume_task` 触发的事件均使用锁内 `now`。
5. **`log_task_event` 增强**：
   - 新增可选参数 `timestamp: datetime | None = None`，默认为 `utcnow()`，允许事务内调用方显式传递事务级时间戳。

---

## 2. RED 失败复现与 GREEN 验证

### 2.1 RED 阶段复现证据（在 fixed9 原始代码上运行）
在 `tests/test_fixed10_regressions.py` 中编写 3 组针对 SQLite writer lock contention 的回归测试：
```text
FAILED tests/test_fixed10_regressions.py::test_cancel_uses_post_lock_transaction_time
- 报错: AssertionError: cancel_requested_at (2026-09-04 02:21:39.045859) was sampled before writer lock acquisition (2026-09-04 02:21:39.251227)
- 证据: 证明 cancel_requested_at 在锁外被提前采集，落后锁获得时间达 205ms

FAILED tests/test_fixed10_regressions.py::test_claim_then_waiting_cancel_preserves_timestamp_order
- 报错: AssertionError: Causality inversion: cancel_requested_at (2026-09-04 02:21:39.302215) < started_at (2026-09-04 02:21:39.463175)
- 证据: 明确复现了 Claim 先拿锁写入 started_at，等待锁的 Cancel 却写入了更早的 cancel_requested_at（倒流 161ms）

FAILED tests/test_fixed10_regressions.py::test_retry_uses_post_lock_transaction_time
- 报错: AssertionError: retry job created_at (2026-09-04 02:21:39.554561) was sampled before writer lock acquisition (2026-09-04 02:21:39.756961)
- 证据: 证明 retry 新任务 created_at 同样落后锁获得时间达 202ms
```

### 2.2 GREEN 修复后验证
```text
tests/test_fixed10_regressions.py ...                                    [100%]
3 passed in 0.92s
```

### 2.3 组合回归与全量测试套件结果
- **fixed9 + fixed10 回归**：9 passed in 1.56s
- **fixed1 ~ fixed10 全量 fixed 回归套件**：72 passed in 8.84s
- **仓库全量自动化测试套件**：
```text
collected 225 items
225 passed in 35.12s
```
测试总数由 fixed9 的 222 项增加到 **225 项，全部通过（100% GREEN）**，零失败！

---

## 3. 前端与容器构建验证

1. **前端类型检查与生产构建**：
   - `npm ci && npm run typecheck && npm run build`
   - TypeScript 0 错误，Vite 构建产物成功输出。
2. **生产镜像多架构构建**：
   - `docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step1-fixed10 .`
   - 镜像构建成功。
3. **Docker 容器 Smoke 测试**：
   - API 容器启动并响应 `/health` 返回 `{"status":"ok", ...}`；
   - Worker 容器启动并成功加载模块。
4. **数据库迁移与完整性检查**：
   - 运行历史版本迁移测试通过；
   - 执行 `PRAGMA integrity_check` 输出 `ok`。

---

## 4. 交付文件与合规性

1. **安全配置默认值**：
   - 保持 `ALLOW_MUTATION=false`, `ALLOW_DELETE=false`, `PROTECT_LAST_FILE=true`。
2. **敏感词合规扫描**：
   - 运行全量文本扫描，确认全库业务敏感词匹配为 0。
3. **独立临时容器解压复测**：
   - 打包生成 `nas-file-center-v0.3.3-step1-fixed10.zip`，排除了 `.git`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, `.DS_Store` 等无关文件；
   - 在全新临时容器内解压并复测全量 pytest 套件（225 项全部通过）及 `PRAGMA integrity_check = ok`。
