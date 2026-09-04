# NAS File Center v0.3.3-step2-fixed3 验收报告与实现文档

## 1. Baseline（基线说明）
- **Backend 基线**：`NAS File Center v0.3.3-step1-fixed10`（完全冻结，所有 Worker 租约、Fencing、Recovery、Checkpoint、Fclones Parser、IndexRoot 等核心逻辑零修改）。
- **Frontend 基线**：`NAS File Center v0.3.3-step2-fixed2`。
- **定位**：本轮为 `fixed3` 窄范围收敛修复，关闭 `step2-fixed2` 独立 Review 发现的 ETA 边界判定与守卫顺序两个关键 Blocker。

## 2. fixed2 独立 Review 发现的问题
1. **BLOCKER-1**：`percent == null` 守卫条件死代码问题。
   - 原代码写为 `if (pct === null && totalVal <= 0)`，但前面已有独立的 `if (totalVal <= 0)`；
   - 导致当 `running, current=50, total=100, percent=null, valid started_at` 时，该守卫永远不会命中，错误地穿透计算出有限 ETA，违背了 Indeterminate Progress 必须返回 ETA 未知的契约。
2. **BLOCKER-2**：`current >= total` 判定位置倒置问题。
   - 原代码在检查完 `started_at` 和 `elapsed` 之后才判定 `current >= total`；
   - 导致当 `running, current=100, total=100, percent=100, started_at=null` 时，在缺少 `started_at` 时就提前退出了，错误返回 `text: '未知'` 而非确定性的 `text: '0s'`。

## 3. 根因分析
在 `step2-fixed2` 中，`calculateTaskEta` 函数的守卫链存在时序耦合与死代码：
- `percent` 校验与 `total <= 0` 绑定在了一起，没有作为独立的有效性网关；
- 确定性完成（`current >= total`）的优先级低于对运行态时间戳（`started_at` / `elapsed`）的校验。实际上，一旦已处理数量达到或超过总量，无论起始时间是否存在或是否合法，任务在进度层面已属于完成状态，应当确定性返回 `0s`。

## 4. ETA 守卫时序规范与状态机
在 `frontend/src/components/tasks/task_utils.ts` 中重构 `calculateTaskEta`，严格按序执行以下守卫链：
1. **Case 6（completed）**：确定性返回 `{ etaSeconds: 0, text: '已完成', isUnknown: false }`；
2. **Case 7（failed / cancelled）**：确定性返回 `{ etaSeconds: null, text: '不可用', isUnknown: true }`；
3. **Case 8（paused）**：确定性返回 `{ etaSeconds: null, text: '已暂停', isUnknown: true }`；
4. **Case 8（cancel_requested）**：确定性返回 `{ etaSeconds: null, text: '正在取消', isUnknown: true }`；
5. **Non-running 状态**：若 `status !== 'running'`（如 queued），返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
6. **Guard 1（total validity）**：`total <= 0` 或 `tot == null`，返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
7. **Guard 2（percent validity）**：`pct === null || pct === undefined`（未知或不确定进度），独立返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
8. **Guard 3（current validity）**：`current <= 0`（速率样本不足），返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
9. **Guard 4（current >= total）**：已达或超总量，在时间戳前优先确定性返回 `{ etaSeconds: 0, text: '0s', isUnknown: false }`；
10. **Guard 5（started_at validity）**：`!startStr` 或非法时间戳，返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
11. **Guard 6（elapsed validity）**：`elapsedSeconds <= 0` 或非法，返回 `{ etaSeconds: null, text: '未知', isUnknown: true }`；
12. **Calculation**：`remaining = total - current`，`rawEta = (elapsedSeconds * remaining) / current`，数学防护后格式化输出。

## 5. 修改文件清单
### 生产代码文件：
- [`frontend/src/components/tasks/task_utils.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/tasks/task_utils.ts)：调整 `calculateTaskEta` 守卫时序，独立 `percent` 校验，提前 `current >= total` 判定。

### 测试与文档文件：
- [`frontend/tests/task_observability.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/task_observability.test.ts)：更新现有 ETA 测试并新增显式测试 10，覆盖 A、B、C、D、E 边界测试；
- [`walkthrough.md`](file:///Users/Kerwin/MyProject/nas-file-center/walkthrough.md)：更新为 step2-fixed3 专属验收报告。

## 6. 未修改范围
- **Backend 基线**：`v0.3.3-step1-fixed10` 零后端生产文件修改；
- **数据库与配置**：DB models 零变动、Alembic migrations 零变动、API schemas 零变动；
- **第三方依赖**：`package.json` 与 `package-lock.json` 零外部依赖引入（依赖增量 = 0）；
- **Actions 隔离**：
  - `TASK-033-UI-03` 保持未启用：Pause / Resume / Cancel / Retry 等操作按钮本阶段严格不开放交互触发；
  - `TASK-033-UI-06` 保持未启用：Task History Cleanup 接口与按钮本阶段不开放交互。

## 7. Backend Regression
在 Docker `python:3.12-slim` 纯净容器中执行全量测试：
```bash
docker run --rm --platform linux/amd64 -v $(pwd):/app -w /app python:3.12-slim bash -c "pip install -q -e . pytest pytest-asyncio httpx && PYTHONPATH=. pytest -q"
```
结果：**225 passed in 100%**, 0 failed, 0 skipped。

## 8. Frontend Tests
执行 `npm test`（Node 22 内置轻量测试执行器）：
```
TAP version 13
# Subtest: Task Progress & Indeterminate Percentages (5 tests passed)
# Subtest: Task Status Tags & Mappings (1 test passed)
# Subtest: Capabilities Verification (2 tests passed)
# Subtest: Worker Status Health Mappings (2 tests passed)
# Subtest: Sensitive Information Redaction (Sanitization) (3 tests passed)
# Subtest: Duration & Elapsed Time Formatting (2 tests passed)
# Subtest: Tasks API Client Query Parameters & Contract (4 tests passed)
# Subtest: Task ETA Estimation & Deterministic Rules (10 tests passed)
--------------------------------------------------
tests: 29, suites: 8, pass: 29, fail: 0 (duration: 60ms)
```

## 9. Direct Negative / Boundary Checks（A, B, C, D, E）
- **A. `running, current=50, total=100, percent=null, valid started_at`**：
  - 断言结果：`isUnknown == true`, `text == '未知'`, `etaSeconds == null`（通过）
- **B. `running, current=50, total=100, percent=undefined, valid started_at`**：
  - 断言结果：`isUnknown == true`, `text == '未知'`, `etaSeconds == null`（通过）
- **C. `running, current=100, total=100, percent=100, started_at=null`**：
  - 断言结果：`isUnknown == false`, `text == '0s'`, `etaSeconds == 0`（通过）
- **D. `running, current=120, total=100, percent=100, started_at=invalid`**：
  - 断言结果：`isUnknown == false`, `text == '0s'`, `etaSeconds == 0`（通过）
- **E. `running, current=50, total=100, percent=50, elapsed=60s`**：
  - 断言结果：`isUnknown == false`, `text == '1m 0s'`, `etaSeconds == 60`（通过）

## 10. Typecheck
执行 `npm run typecheck` (`tsc --noEmit`)：
```
exit code 0, 0 errors
```

## 11. Production Build
执行 `npm run build` (`tsc && vite build`)：
```
✓ 3702 modules transformed.
dist/index.html                            1.08 kB │ gzip:   0.54 kB
dist/assets/index-BQCeOY6q.css             0.14 kB │ gzip:   0.13 kB
dist/assets/vendor-query-BXatzldx.js      41.69 kB │ gzip:  12.59 kB
dist/assets/index-Cl3rnQkn.js            128.83 kB │ gzip:  37.46 kB
dist/assets/vendor-react-BGCF_QG6.js     161.29 kB │ gzip:  52.75 kB
dist/assets/vendor-antd-D1t7_DvI.js    1,048.21 kB │ gzip: 328.03 kB
dist/assets/vendor-charts-DMwjGmvV.js  1,053.96 kB │ gzip: 349.87 kB
✓ built in 3.45s
```

## 12. Docker Build
构建 `linux/amd64` 生产镜像：
```bash
docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed3 .
```
结果：多阶段构建成功完成，前端构建产物正确复制至 `/app/frontend/dist`。

## 13. Docker Smoke
启动临时容器验证：
- `GET /health` 返回 `200 OK`（`status: ok`, `allow_mutation: false`, `allow_delete: false`）；
- `GET /tasks` 返回 `200 OK`，正确定位并返回带有生产 SPA JS/CSS 的 HTML 入口；
- SPA 前端路由与后端 API 路由（全 13 路由）互不冲突，运行正常。

## 14. Security Impact
- 递归脱敏器（`sanitizeContext`）持续保护所有敏感 Key（`password`、`token`、`secret`、`authorization`、`cookie`、`session` 等），将其值重写为 `***REDACTED***`；
- 全量代码检索敏感及禁用词汇规范校验：结果严格为 0 条匹配。

## 15. File Mutation Impact
零文件修改风险。本阶段所有 Task 与 Worker 查询均为只读操作，不向 NAS 文件系统发送任何写操作。

## 16. Delete Impact
`ALLOW_DELETE=false` 保持锁定，无任何删除行为。

## 17. Known Limitations
- 本阶段聚焦于任务中心只读可观测性（列表、状态、进度、ETA、Worker 心跳、详情、脱敏日志）；
- 任务控制操作（`TASK-033-UI-03`：Pause/Resume/Cancel/Retry）与历史清理操作（`TASK-033-UI-06`）留待后续能力驱动阶段开放。

## 18. Release Decision
**PASS**：全部 225 个后端测试通过，前端 29 个测试通过，TypeScript 0 errors，生产构建成功，Docker amd64 验证与 Smoke 均通过，直接边界用例 A、B、C、D、E 全绿，所有 Review Blocker 彻底关闭。
