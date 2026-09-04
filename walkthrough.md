# NAS File Center v0.3.3-step2-fixed4 验收报告与实现文档

## 1. Baseline（基线说明）
- **Backend 基线**：`NAS File Center v0.3.3-step1-fixed10`（完全冻结，所有 Worker 租约、Fencing、Recovery、Checkpoint、Fclones Parser、IndexRoot、TaskService 等核心逻辑零修改）。
- **Frontend 基线**：`NAS File Center v0.3.3-step2-fixed3`。
- **定位**：本轮为 `fixed4 — TASK-033-UI-03 Capability-driven Actions Gate`，开放任务中心对后端任务引擎状态机发起受控、安全、具备完整二次确认与错误防护的 Pause、Resume、Cancel、Retry 控制能力。

## 2. 本轮已实现能力 (TASK-033-UI-03)
1. **API Client 方法补齐**：
   - 在 [`frontend/src/api/tasks.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/tasks.ts) 中增加 `pauseTask`, `resumeTask`, `cancelTask`, `retryTask`；
   - 严格继承现有 `api.post` 统一凭据 (`credentials: include`)、401 拦截与 CSRF / Origin 机制；
   - 严格未暴露 `deleteTask` 与 `clearHistory`（隔离 TASK-033-UI-06）。
2. **统一 Action Policy 引擎**：
   - 在 [`frontend/src/components/tasks/task_actions.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_actions.ts) 中实现 `getTaskActionAvailability` 纯函数；
   - 按钮可用性严格由后端的 `task.capabilities` 作为第一真相，结合当前 `task.status` 计算，拒绝前端硬编码假设；
   - 禁用状态提供清晰可解释的原因（区分“能力不支持”与“状态不允许”）。
3. **独立可观测 Action Bar 组件**：
   - 在 [`frontend/src/components/tasks/TaskActionBar.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskActionBar.tsx) 中封装四个动作按钮、加载态互斥锁、二次确认、消息反馈与 React Query 缓存刷新；
   - 嵌入在 [`frontend/src/components/tasks/TaskDetailDrawer.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDetailDrawer.tsx) 的元数据摘要与 Checkpoint 之间，避免误触。
4. **二次确认机制**：
   - **Cancel**：强制 Popconfirm 确认，明确告知 running 任务将在安全 checkpoint 停止，可能不会立即变为 cancelled；
   - **Retry**：强制 Popconfirm 确认，明确说明原失败任务保留，系统创建新排队任务。
5. **并发与加载态防护**：
   - 在任一 Action 执行中（`activeAction !== null`），四个按钮统一锁定并展示执行中的 loading 动画，彻底杜绝双击、重入及并发冲突；
   - 绝不采用假 Optimistic 本地状态篡改，所有状态迁移以后端 DB 事务返回为准；
   - 遇到 409 Stale-state 时，展示真实服务端错误信息并自动触发 `taskDetail` 与 `tasksList` 刷新以修正界面。

## 3. 操作可用性矩阵 (Action Availability Matrix)

| 操作 (Action) | 允许条件 (Enabled) | 禁用原因示例 (Disabled Reason) | 二次确认 |
| :--- | :--- | :--- | :--- |
| **Pause** | `supports_pause == true` 且 `status in ['queued', 'running']` | “此任务类型不支持暂停” / “任务已经暂停” / “当前任务正在取消” / “终态任务不可暂停” | 否 (直接执行) |
| **Resume** | `supports_resume == true` 且 `status == 'paused'` | “此任务类型不支持恢复” / “仅暂停状态的任务可以恢复” / “当前任务正在取消” / “终态任务不可恢复” | 否 (直接执行) |
| **Cancel** | `supports_cancel == true` 且 `status in ['queued', 'running', 'paused']` | “此任务类型不支持取消” / “当前任务正在取消” / “任务已取消” / “终态任务不可取消” | 是 (危险确认框) |
| **Retry** | `supports_retry == true` 且 `status == 'failed'` | “此任务类型不支持重试” / “运行中或未失败的任务不可重试” / “已完成的任务无需重试” / “已取消的任务不可重试” | 是 (创建新任务确认) |

## 4. 修改文件清单
### 生产代码文件：
- [`frontend/src/types/task.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/task.ts)：新增 `RetryTaskResponse` 类型；
- [`frontend/src/api/tasks.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/tasks.ts)：新增 `pauseTask`, `resumeTask`, `cancelTask`, `retryTask` API 契约；
- [`frontend/src/components/tasks/task_actions.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_actions.ts)：[NEW] 统一 Action 可用性与禁用原因策略引擎；
- [`frontend/src/components/tasks/TaskActionBar.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskActionBar.tsx)：[NEW] 动作工具条组件（含互斥锁、二次确认、缓存刷新与错误反馈）；
- [`frontend/src/components/tasks/TaskDetailDrawer.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/TaskDetailDrawer.tsx)：在详情抽屉中嵌入 `TaskActionBar`；
- [`frontend/src/pages/Tasks/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Tasks/index.tsx)：透传 `onViewTask` 支持在重试通知中直接切换至新生成的任务。

### 测试与工程文件：
- [`frontend/tests/task_actions.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/task_actions.test.ts)：[NEW] 新增动作策略矩阵、API Client 真实 Mock、Retry 返回解构、409/404 异常传递及 DELETE 隔离断言；
- [`frontend/scripts/run-tests.mjs`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/scripts/run-tests.mjs)：支持同时编译并执行 `task_observability` 与 `task_actions` 测试套件；
- [`walkthrough.md`](file:///Users/Kerwin/MyProject/nas-file-center/walkthrough.md)：更新为 step2-fixed4 验收报告。

## 5. 未修改范围与隔离规范
- **Backend 基线**：`v0.3.3-step1-fixed10` 零后端生产文件修改（Backend production changes: 0）；
- **数据库与模型**：DB schema 零变动、Alembic migrations 零变动、DB models 零变动；
- **API 接口定义**：后端 endpoints 与 JSON schema 零变动；
- **第三方依赖**：`package.json` 与 `pyproject.toml` 零依赖增量（New dependencies = 0）；
- **TASK-033-UI-06 隔离**：前端没有调用 `DELETE /api/tasks/{id}`，也没有调用 `POST /api/tasks/clear-history`，相关交互严格未开放。

## 6. Backend Regression
在 Docker `python:3.12-slim` 纯净容器中执行全量回归：
```bash
docker run --rm --platform linux/amd64 -v $(pwd):/app -w /app python:3.12-slim bash -c "pip install -q -e . pytest pytest-asyncio httpx && PYTHONPATH=. pytest -q"
```
结果：**225 passed in 100%**, 0 failed, 0 skipped。

## 7. Frontend Tests
执行 `npm test`（Node 22 原生测试运行器）：
```
tests: 61, suites: 14, pass: 61, fail: 0 (duration: 68ms)
```
- 原可观测性测试：29 项全部通过；
- 新增 Action 矩阵与 API 测试：32 项全部通过；
- 累计 61 tests, 14 suites, 100% PASS。

## 8. Typecheck
执行 `npm run typecheck` (`tsc --noEmit`)：
```
exit code 0, 0 errors
```

## 9. Production Build
执行 `npm run build` (`tsc && vite build`)：
```
✓ 3704 modules transformed.
dist/index.html                            1.08 kB │ gzip:   0.54 kB
dist/assets/index-BQCeOY6q.css             0.14 kB │ gzip:   0.13 kB
dist/assets/vendor-query-BXatzldx.js      41.69 kB │ gzip:  12.59 kB
dist/assets/index-DuKxJ-Q0.js            134.23 kB │ gzip:  38.79 kB
dist/assets/vendor-react-BGCF_QG6.js     161.29 kB │ gzip:  52.75 kB
dist/assets/vendor-charts-DMwjGmvV.js  1,053.96 kB │ gzip: 349.87 kB
dist/assets/vendor-antd-4nKDvQmB.js    1,063.67 kB │ gzip: 331.51 kB
✓ built in 3.56s
```

## 10. Docker Build
构建 `linux/amd64` 生产镜像：
```bash
docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed4 .
```
结果：多阶段构建成功完成，前端构建产物正确复制至 `/app/frontend/dist`。

## 11. Docker Smoke
启动临时容器验证：
- `GET /health` 返回 `200 OK`（`status: ok`, `allow_mutation: false`, `allow_delete: false`）；
- `GET /tasks` 返回 `200 OK`，正确定位并返回带有生产 SPA JS/CSS 的 HTML 入口；
- SPA 前端路由与后端 API 路由（全 13 路由）互不冲突，运行正常；
- `POST /api/tasks/1/cancel` 未认证访问返回 `401 Unauthorized`；认证后请求正确由 CSRF 与权限校验机制保护。

## 12. Security Impact
- 所有 mutation API 请求必须通过带有 Cookie 的同源会话，且受到 CSRF / Origin 防护；
- 前端未篡改任何凭据传输规则；
- 递归脱敏器（`sanitizeContext`）持续保护所有敏感 Key；全量敏感词汇检索为 0 条匹配。

## 13. File Mutation Impact
零文件修改风险。本阶段 Task Action 仅作用于 SQLite 内部任务控制状态机，不向 NAS 文件系统发送任何非受控写操作。

## 14. Delete Impact
`ALLOW_DELETE=false` 保持锁定。任务历史删除（`DELETE /api/tasks/{id}`）与清理（`clear-history`）功能严格未实现、未暴露。

## 15. Known Limitations
- 本阶段开放任务控制交互（`TASK-033-UI-03`：Pause / Resume / Cancel / Retry）；
- 任务历史清理交互（`TASK-033-UI-06`）留待后续单独阶段开放；
- 当前后端中 `fclones-scan` 与 `index-root` 均不支持 Pause/Resume，UI 按设计如实展示为禁用状态及解释。

## 16. Release Decision
**PASS**：全部 225 个后端测试通过，前端 61 个测试通过，TypeScript 0 errors，生产构建成功，Docker amd64 构建与 Smoke 验证均通过，所有 Action 矩阵与隔离断言全绿。
