# NAS File Center v0.3.3-step2-fixed6 验收报告与实现文档
## TASK-033-UI-06 Task History Cleanup Gate

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed5`（Commit: `03dcb26`）。
- **任务目标**：本轮专注完成 `TASK-033-UI-06 Task History Cleanup Gate`，实现安全删除单条终态 Task 以及批量清理终态 Task History 的完整端到端能力。
- **严格隔离原则**：本轮绝对不处理 Plan 删除、Scan History 删除、Audit 删除、Operation Journal 删除、文件索引 Directory Picker、NAS 文件删除与 Quarantine purge，这些功能保持完全未启用与零变动。

---

## 2. 现有后端接口与安全隐患修复（RED → GREEN）

### 现有后端契约
Backend 已存在以下接口，本轮未新增任何重复或第二套 API：
- **单任务删除**：`DELETE /api/tasks/{task_id}`
  - 终态（`completed`, `failed`, `cancelled`）允许删除，返回 `{"deleted": true, "id": task_id}`；
  - 活跃态（`queued`, `running`, `paused`, `cancel_requested`）禁止删除，返回 `409 Conflict`；
  - 任务不存在返回 `404 Task not found`。
- **批量清理**：`POST /api/tasks/clear-history`
  - 请求体：`{"statuses": ["completed", "failed", "cancelled"]}`；
  - 成功返回：`{"deleted_count": N}`；
  - 仅允许终态状态。

### 后端安全缺陷追踪与修复（RED → GREEN）
- **根因发现**：在 [`app/tasks/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/service.py) 中，`clear_task_history()` 原实现为：
  ```python
  target_statuses = set(statuses or TERMINAL_STATES)
  ```
  当前端或 API 调用传入 `statuses = []` 时，Python 将空列表判定为 `falsy`，导致逻辑错误回退到 `TERMINAL_STATES`。即当用户在界面上未选择任何状态时，反而可能将系统内所有 `completed` / `failed` / `cancelled` 历史任务全量清除！
- **RED 阶段（先失败复现）**：
  在 [`tests/test_task_history_cleanup.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_task_history_cleanup.py) 中构建测试，调用 `clear_task_history(statuses=[])` 并断言其抛出 `ValueError`。在 fixed5 基线代码下直接报错 `Failed: DID NOT RAISE ValueError`，证明基线存在严重的误删风险。
- **GREEN 阶段（修复与语义拆分）**：
  将状态解析语义严格细分为三种情况：
  ```python
  if statuses is None:
      target_statuses = set(TERMINAL_STATES)
  elif len(statuses) == 0:
      raise ValueError("At least one terminal status is required")
  else:
      target_statuses = set(statuses)

  for s in target_statuses:
      if s not in TERMINAL_STATES:
          raise ValueError(f"Cannot clear non-terminal status '{s}'")
  ```
  - `statuses is None` $\rightarrow$ 缺省清理全部终态；
  - `statuses == []` $\rightarrow$ 严格抛出 `ValueError`，由外层转换为 `400 Bad Request`，**零删除**，保护所有数据安全；
  - 包含非终态 $\rightarrow$ 抛出 `ValueError`（400），原子拒绝。

---

## 3. 关联数据生命周期与安全边界

1. **TaskEvent / Task Logs 生命周期**：
   - 数据库模型中 `TaskEvent.job_id` 声明了 `ForeignKey("work_jobs.id", ondelete="CASCADE")`，且 SQLite 全局启用了 `PRAGMA foreign_keys=ON`；
   - 删除 Task 时，该任务对应的 `TaskEvent` 级联自动清除（作为任务证据链随任务一同归档移除）；
   - 不提供单条日志的删除垃圾桶，保证日志作为证据链的完整性。
2. **Audit 审计日志隔离**：
   - `AuditEvent` 为独立合规审计实体，**绝对保留**；
   - 删除任何 Task 或清理历史，均绝不触发对 `audit_events` 的删除或清理。
3. **Retry Lineage（重试衍生链保护）**：
   - `WorkJob.retry_of` 定义为 `ForeignKey("work_jobs.id", ondelete="SET NULL")`；
   - 当原失败任务被删除后，重试生成的子任务依然存活，其 `retry_of` 字段自动设为 `NULL`，外键完整性不受破坏。
4. **NAS 文件系统零修改与 ALLOW_DELETE 解耦**：
   - 任务中心元数据删除仅针对 SQLite 元数据表，**不调用任何 `os.remove` / `unlink` / `rmtree`**；
   - 该功能与保护 NAS 实机文件删除的 `ALLOW_DELETE` 完全解耦，安全边界来自：身份认证、CSRF 防护、终态状态校验与前端二次确认。

---

## 4. 前端架构与交互实现

1. **类型与 API Client**：
   - [`frontend/src/types/task.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/task.ts)：新增 `TerminalTaskStatus`、`DeleteTaskResponse`、`ClearTaskHistoryResponse`；
   - [`frontend/src/api/tasks.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/tasks.ts)：新增 `deleteTask(taskId)` 与 `clearTaskHistory(statuses)`，UI 永远显式传递状态数组，严防空缺省。
2. **统一删除策略 Policy**：
   - [`frontend/src/components/tasks/task_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_cleanup.ts)：纯函数 `getTaskDeleteAvailability(task)`：
     - `completed` / `failed` / `cancelled` $\rightarrow$ `enabled: true, reason: null`；
     - `queued` $\rightarrow$ `enabled: false, reason: "排队中的任务不能删除"`；
     - `running` $\rightarrow$ `enabled: false, reason: "执行中的任务不能删除"`；
     - `paused` $\rightarrow$ `enabled: false, reason: "暂停中的任务不能删除，请先取消任务"`；
     - `cancel_requested` $\rightarrow$ `enabled: false, reason: "任务正在取消，请等待进入终态后再删除"`。
3. **复用删除按钮组件**：
   - [`frontend/src/components/tasks/TaskDeleteButton.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDeleteButton.tsx)：
     - 禁用状态下 Tooltip 展示具体不可删原因；
     - 启用状态下点击触发 Popconfirm 二次确认弹窗，明确提示「删除后将同时清除该任务的事件日志。该操作不会删除 NAS 上的任何文件，也不会删除 Audit 审计记录」；
     - 确认删除为 danger 红色按钮，禁止单击直接删除；
     - 成功后自动执行 `message.success`，并在 React Query 中全局失效 `['tasksList']`，同时精准清除 `['taskDetail', taskId]` 与 `['taskLogs', taskId]` 缓存；
     - 在任务列表表格操作列（`[详情] [删除]`）与任务详情抽屉（`TaskDetailDrawer`）中高度复用。
4. **分页防空自适应处理**：
   - 当用户在第 `N (N > 1)` 页删除最后一条任务时，前端自动向前回退页码 `setPage(page - 1)`，避免界面停留在空分页中。
5. **批量清理历史模态框**：
   - [`frontend/src/components/tasks/TaskHistoryCleanupModal.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskHistoryCleanupModal.tsx)：
     - 在任务中心顶部工具栏集成「清理历史」按钮（`DeleteOutlined`，danger 样式）；
     - 弹窗仅提供 `completed`、`failed`、`cancelled` 勾选项，默认全选；
     - 明确告示清理范围：「该操作会清理所有任务类型中符合所选终态的历史任务，不是仅清理当前分页或当前任务类型筛选结果」；
     - 详细说明影响范围与安全保证；
     - 若取消全部勾选，确认按钮自动禁用，杜绝发出非法空请求；
     - 成功清理后提示真实数量（如「已清理 42 个历史任务」），自动重置分页 `setPage(1)` 并全局刷新列表。

---

## 5. 修改文件清单

### 后端生产代码（仅 1 处窄范围安全修复）：
- [`app/tasks/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/service.py)：修复 `clear_task_history` 中对空状态列表的容错缺陷。

### 前端生产代码：
- [`frontend/src/types/task.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/task.ts)：新增终态及清理响应接口定义；
- [`frontend/src/api/tasks.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/tasks.ts)：新增 `deleteTask` 与 `clearTaskHistory` 方法；
- [`frontend/src/components/tasks/task_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_cleanup.ts)：[NEW] 任务删除策略纯函数；
- [`frontend/src/components/tasks/TaskDeleteButton.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDeleteButton.tsx)：[NEW] 单任务删除按钮组件（带 Popconfirm 与 Tooltip）；
- [`frontend/src/components/tasks/TaskHistoryCleanupModal.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskHistoryCleanupModal.tsx)：[NEW] 批量清理历史模态框组件；
- [`frontend/src/pages/Tasks/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Tasks/index.tsx)：表格操作列集成删除按钮、头部工具栏集成批量清理入口、单删分页回退保护；
- [`frontend/src/components/tasks/TaskDetailDrawer.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDetailDrawer.tsx)：详情抽屉集成删除按钮并在删除后自动关闭抽屉。

### 测试与脚本文件：
- [`tests/test_task_history_cleanup.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_task_history_cleanup.py)：[NEW] 后端 Cases A ~ S 全场景回归测试；
- [`frontend/tests/task_cleanup.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/task_cleanup.test.ts)：[NEW] 前端删除策略与 API 契约测试；
- [`frontend/tests/task_actions.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/task_actions.test.ts)：更新 404 错误断言与 UI-06 门禁断言；
- [`frontend/scripts/run-tests.mjs`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/scripts/run-tests.mjs)：加入 `task_cleanup.test.ts` 执行。

---

## 6. 未修改范围与架构纪律
- **数据库结构**：DB Schema 零修改、DB models 零修改；
- **迁移脚本**：Alembic migrations 零修改；
- **接口路由定义**：REST API 契约与路径零修改；
- **第三方依赖**：零新依赖引入（New dependencies = 0）；
- **计划与扫描隔离**：Plan 清理、Scan 历史清理、Audit 清理、Organizer 高级功能、Directory Picker 均保持未启用与零修改。

---

## 7. 全量测试与验证结果

### 1. 后端 Cases A ~ S 回归（19 项用例全部通过）
- **Case A**: DELETE completed $\rightarrow$ 200，任务删除
- **Case B**: DELETE failed $\rightarrow$ 200，任务删除
- **Case C**: DELETE cancelled $\rightarrow$ 200，任务删除
- **Case D**: DELETE queued/running/paused/cancel_requested $\rightarrow$ 409，任务保留
- **Case E**: DELETE terminal Task $\rightarrow$ 关联 TaskEvent 级联删除
- **Case F**: DELETE terminal Task $\rightarrow$ AuditEvent 严格保留
- **Case G**: POST clear-history statuses=["completed"] $\rightarrow$ 仅 completed 被清理
- **Case H**: statuses=["failed","cancelled"] $\rightarrow$ failed/cancelled 清理，completed 保留
- **Case I**: statuses=None $\rightarrow$ 所有 terminal 清理，活跃任务保留
- **Case J (CRITICAL)**: statuses=[] $\rightarrow$ 400 报错拒绝，零删除，所有任务保留
- **Case K**: statuses=["running"] $\rightarrow$ 400 报错，零删除
- **Case L**: 混合状态 ["completed","running"] $\rightarrow$ 400 报错，原子性零删除
- **Case M**: clear-history $\rightarrow$ TaskEvent 级联清理
- **Case N**: clear-history $\rightarrow$ AuditEvent 完整保留
- **Case O**: Retry 子任务在父任务被删除后存活 $\rightarrow$ FK `ondelete="SET NULL"` 生效，retry_of 变为 None
- **Case P**: 删除不存在的任务 $\rightarrow$ 404
- **Case Q**: 未认证 DELETE $\rightarrow$ 401
- **Case R**: 认证请求缺失 Origin/Referer $\rightarrow$ 403 CSRF 拦截
- **Case S**: 认证且带有合法 Origin $\rightarrow$ 正常响应

### 2. 后端全量测试（Docker `python:3.12-slim`）
- 运行命令：`docker run --rm --platform linux/amd64 -v $(pwd):/app -w /app python:3.12-slim bash -c "pip install -q -e . pytest pytest-asyncio httpx && PYTHONPATH=. pytest -q"`
- 结果：**250 passed in 100%**, 0 failed, 0 skipped（从 fixed5 的 231 项严格净增 19 项）。

### 3. 前端全量测试与构建
- `npm test`：**74 passed in 17 suites**, 0 failed（从 fixed5 的 61 项严格净增 13 项）；
- `npm run typecheck` (`tsc --noEmit`)：**0 errors**；
- `npm run build` (`tsc && vite build`)：**3707 modules transformed, 生产构建完成**。

### 4. Docker 镜像与 Smoke 验证
- 生产镜像：`kerwinjhc/nas-file-center:0.3.3-step2-fixed6` (`linux/amd64`)；
- Smoke 测试验证：
  - `GET /health` $\rightarrow$ `200 OK`；
  - `GET /tasks` $\rightarrow$ `200 OK`（SPA 路由）；
  - `DELETE /api/tasks/1`（未认证） $\rightarrow$ `401 Unauthorized`；
  - `POST /api/tasks/clear-history`（未认证） $\rightarrow$ `401 Unauthorized`。

---

## 8. Release Decision
**PASS**：`TASK-033-UI-06 Task History Cleanup Gate` 所有需求全部实现，`statuses=[]` 隐患经 RED 复现并 GREEN 修复，后端 250 项测试及前端 74 项测试 100% 通过，生产 Docker 镜像与 Smoke 验证全部正常。
