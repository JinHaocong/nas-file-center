# NAS File Center v0.3.3-step2-fixed2 验收报告与实现文档

## 1. Baseline（基线说明）
- **Backend 基线**：`NAS File Center v0.3.3-step1-fixed10`（完全冻结，所有 Worker 租约、Fencing、Recovery、Checkpoint、Fclones Parser、IndexRoot 等核心逻辑零修改）。
- **Frontend 基线**：`NAS File Center v0.3.3-step2-fixed1`。
- **定位**：本轮为 `fixed2` 窄范围收敛修复，关闭独立 Review 发现的两个关键 Release Blocker。

## 2. 本轮 Review Blocker
1. **BLOCKER-1**：`TASK-033-UI-02` 缺少任务预计剩余时间（ETA）的计算与渲染支持。
2. **BLOCKER-2**：代码根目录及发布包归档中的 `walkthrough.md` 仍为 `v0.3.3-step1-fixed10` 的旧版文档，未能如实反映 step2 任务中心 UI 的实现现状。

## 3. ETA 根因分析
在 `step2-fixed1` 中，Progress 区域仅包含了 `current / total` 计数、`percent` 百分比、`message` 状态描述以及父级的 `elapsed`（已耗时），未提供基于当前处理速率与剩余未完成量的动态 ETA 预估模型，导致长时间运行的任务缺乏直观的剩余完成时间感知。

## 4. ETA 设计与规则规范
在 `frontend/src/components/tasks/task_utils.ts` 中封装纯函数 `calculateTaskEta`，遵循严格数学与业务状态机判定：
1. **可计算条件**：
   - 必须满足：`status == running`、`started_at` 有效且解析合法、`current > 0`、`total > 0`、`current < total` 且 `elapsedSeconds > 0`；
   - 估算公式：`etaSeconds = Math.round(elapsedSeconds * (total - current) / current)`；
   - 严格防护：防止 `NaN`、`Infinity`、负数、除 0、时间倒流及非法时间戳。
2. **状态判定规则**：
   - **Case 1（total 未知 / <= 0）**：返回 `text: '未知'`，`isUnknown: true`，严禁伪造百分比或默认假设总数；
   - **Case 2（percent == null / indeterminate）**：返回 `text: '未知'`，保持与 Indeterminate Progress 一致；
   - **Case 3（current == 0）**：速率样本不足，返回 `text: '未知'`；
   - **Case 4（started_at 缺失或无效）**：返回 `text: '未知'`；
   - **Case 5（running 且数据有效）**：调用 `formatDuration` 格式化为 `1m 20s`、`2h 15m` 等全站统一时长文本；
   - **Case 6（completed 或 current >= total）**：确定性返回 `text: '已完成'` 或 `0s`，绝不保留历史估值；
   - **Case 7（failed / cancelled）**：确定性返回 `text: '不可用'`，防止误导；
   - **Case 8（paused / cancel_requested）**：确定性返回 `text: '已暂停'` 或 `text: '正在取消'`，停止倒计时。
3. **UI 渲染**：
   - `TaskProgress` 统一渲染 `ETA: {eta.text}`，并在 `running` 状态下结合父组件每秒本地 Ticker 平滑更新，无须高频发起网络 API 请求；
   - `TaskDetailDrawer` 在进度组件及摘要列表中均明确展示 `预计剩余 (ETA)`。

## 5. 修改文件清单
### 生产代码文件：
- [`frontend/src/components/tasks/task_utils.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_utils.ts)：实现 `calculateTaskEta` 纯函数与 `TaskEtaResult` / `TaskEtaOptions` 接口；
- [`frontend/src/components/tasks/TaskProgress.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskProgress.tsx)：接入 ETA 展示并在各个状态分支确定性呈现；
- [`frontend/src/pages/Tasks/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Tasks/index.tsx)：列表行传递 `startedAt` 与当前本地时钟，支持 1s 平滑动态倒计时；
- [`frontend/src/components/tasks/TaskDetailDrawer.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDetailDrawer.tsx)：抽屉明细中传递 `startedAt` 并在 Descriptions 中显式渲染预计剩余时长。

### 测试与文档文件：
- [`frontend/tests/task_observability.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/task_observability.test.ts)：新增 9 项针对 ETA 计算、状态分支与异常时间戳的单元测试；
- [`walkthrough.md`](file:///Users/Kerwin/MyProject/nas-file-center/walkthrough.md)：彻底替换为 step2-fixed2 专属验收报告。

## 6. 未修改范围
- **Backend 基线**：`v0.3.3-step1-fixed10` 零后端生产文件修改；
- **数据库与配置**：DB models 零变动、Alembic migrations 零变动、API schemas 零变动；
- **第三方依赖**：`package.json` 与 `package-lock.json` 零外部依赖引入（依赖增量 = 0）；
- **Actions 隔离**：
  - `TASK-033-UI-03` 尚未启用：Pause / Resume / Cancel / Retry 等操作按钮本阶段严格不开放交互触发，无假按钮；
  - `TASK-033-UI-06` 尚未启用：Task History Cleanup 接口与按钮本阶段不开放交互。

## 7. Backend Regression
在 Docker `python:3.12-slim` 纯净容器中执行全量测试：
```bash
docker run --rm --platform linux/amd64 -v $(pwd):/app -w /app python:3.12-slim bash -c "pip install -q -e . pytest pytest-asyncio httpx && PYTHONPATH=. pytest -q"
```
结果：**225 passed in 100%**, 0 failed, 0 skipped。

## 8. Frontend Tests
执行 `npm test`（通过 Node 22 内置轻量测试执行器运行）：
```
TAP version 13
# Subtest: Task Progress & Indeterminate Percentages (5 tests passed)
# Subtest: Task Status Tags & Mappings (1 test passed)
# Subtest: Capabilities Verification (2 tests passed)
# Subtest: Worker Status Health Mappings (2 tests passed)
# Subtest: Sensitive Information Redaction (Sanitization) (3 tests passed)
# Subtest: Duration & Elapsed Time Formatting (2 tests passed)
# Subtest: Tasks API Client Query Parameters & Contract (4 tests passed)
# Subtest: Task ETA Estimation & Deterministic Rules (9 tests passed)
--------------------------------------------------
tests: 28, suites: 8, pass: 28, fail: 0 (duration: 60ms)
```

## 9. Typecheck
执行 `npm run typecheck` (`tsc --noEmit`)：
```
exit code 0, 0 errors
```

## 10. Production Build
执行 `npm run build` (`tsc && vite build`)：
```
✓ 3702 modules transformed.
dist/index.html                            1.08 kB
dist/assets/index-D5H4csqw.js            128.83 kB
dist/assets/vendor-antd-D1t7_DvI.js    1,048.21 kB
✓ built in 3.41s
```

## 11. Docker Build
构建 `linux/amd64` 生产镜像：
```bash
docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed2 .
```
结果：多阶段构建成功完成，前端构建产物正确复制至 `/app/frontend/dist`。

## 12. Docker Smoke
启动临时容器验证：
- `GET /health` 返回 `200 OK`（`status: ok`, `allow_mutation: false`, `allow_delete: false`）；
- `GET /tasks` 返回 `200 OK`，正确定位并返回带有生产 SPA JS/CSS 的 HTML 入口。

## 13. Security Impact
- 递归脱敏器（`sanitizeContext`）持续保护所有敏感 Key（`password`、`token`、`secret`、`authorization`、`cookie`、`session` 等），将其值重写为 `***REDACTED***`；
- 全量检索禁用关键词：`grep -Rni -E '少女映画|shaonv' .` 结果为 0 条。

## 14. File Mutation Impact
零文件修改风险。本阶段所有 Task 与 Worker 查询均为只读操作，不向 NAS 文件系统发送任何写操作。

## 15. Delete Impact
`ALLOW_DELETE=false` 保持锁定，无任何删除行为。

## 16. Known Limitations
- 本阶段聚焦于任务中心只读可观测性（列表、状态、进度、ETA、Worker 心跳、详情、脱敏日志）；
- 任务控制操作（`TASK-033-UI-03`：Pause/Resume/Cancel/Retry）与历史清理操作（`TASK-033-UI-06`）留待后续能力驱动阶段开放。

## 17. Release Decision
**PASS**：全部 225 个后端测试通过，前端 28 个测试通过，TypeScript 0 errors，生产构建成功，Docker amd64 验证与 Smoke 均通过，两个 Review Blocker 彻底关闭。
