# NAS File Center v0.3.3-step2-fixed8 验收报告与实现文档
## Plan Lifecycle Cleanup Gate

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed7`（Commit: `7b02020`）。
- **任务目标**：本轮专注完成 `Plan Lifecycle Cleanup Gate`，彻底解决计划数据生命周期管理问题：
  1. **当前 BatchPlan 单计划安全删除**：支持对终态及未执行计划的安全删除，并在校验/执行中（`validating`, `executing`）提供防误删强隔离（409 Conflict）；
  2. **计划历史批量清理**：提供 `POST /api/plans/clear-history`，仅允许批量清理终态历史（`completed`, `failed`），严格禁止空入参或非法入参；
  3. **解锁扫描记录删除**：解决 Scan 关联 Plan 导致 fixed7 防护网拦截的“死锁”，在计划删除后自动释放扫描关联依赖；
  4. **旧版兼容计划清理**：提供 `GET /api/plans/legacy/summary` 与 `POST /api/plans/legacy/clear`，并在前端通过提示条引导一键清理旧版不参与执行链路的遗留 `Plan` / `PlanItem`，彻底解锁受阻塞的扫描记录；
  5. **Delete ≠ Undo 原则**：删除仅清理计划元数据与条目流水，严格保证 NAS 文件系统零变动（Filesystem Mutation = 0），且 AuditEvent 与 WorkJob 永久保留。
- **严格隔离原则**：
  - 零数据库 Schema 变更、零迁移变更、零新增第三方依赖；
  - 维持现有生产 Plan Engine / Worker Concurrency / Fclones Parser 零改动。

---

## 2. 根因分析与后端实现（RED → GREEN）

### A. 当前 BatchPlan 删除能力缺失与状态安全门禁
- **现状与缺陷**：
  此前系统缺少针对 `BatchPlan` 的删除接口。同时，若计划处于 `validating` 或 `executing` 状态，强行删除会导致后台校验或文件执行发生不可预知的空指针或竞态异常。
- **RED 阶段**：
  在 `tests/test_plan_history_cleanup.py` 中编写对 `DELETE /api/plans/{id}` 的测试用例。在 fixed7 基线中该路由不存在（405 Method Not Allowed 或 404 Not Found），在进行原子并发状态校验时无法拦截。
- **GREEN 阶段**：
  1. 状态矩阵白名单与黑名单策略：
     - `PLAN_SINGLE_DELETE_ALLOWED = {'draft', 'frozen', 'ready', 'partial', 'completed', 'failed'}`；
     - `PLAN_DELETE_BLOCKED_ACTIVE = {'validating', 'executing'}`；
     - 未知状态严格 fail-closed 拦截。
  2. 原子短写事务保障：
     - 在 SQLite 事务中使用 `session.execute(text("BEGIN IMMEDIATE"))`，防止在读取状态与执行删除之间发生并发状态迁移（如从 `ready` 转为 `executing`）；
  3. 关联项目级联清理：
     - 查询并删除关联的 `BatchPlanItem`，随后删除 `BatchPlan`，保证无孤儿记录遗留；
     - 关联的任务记录 `WorkJob` 和审计事件 `AuditEvent` 严格保留；
     - 文件系统变更数为 0。

### B. 计划历史批量清理（Batch History Cleanup）
- **现状与需求**：
  随着频繁去重与规整，系统中累积大量已完成或已失败的历史计划。用户需要一键批量清理终态计划。
- **RED 阶段**：
  验证 `POST /api/plans/clear-history` 在空列表 `statuses: []`、非法状态（如 `draft`, `executing`）或未授权访问时是否正确拦截。原实现无此接口。
- **GREEN 阶段**：
  1. `clear_plan_history(session, statuses)` 服务方法：
     - 严格限定仅允许 `PLAN_HISTORY_STATES = {'completed', 'failed'}`；
     - 若 `statuses` 为空或包含任何非终态值，直接拒绝抛出 `ValueError`（API 层返回 400 Bad Request），坚决不自动回退或删除全部；
     - 在短事务中查询匹配的计划 ID 列表，批量删除子项及计划本身，并返回 `{ "deleted_count": count }`。

### C. 旧版兼容计划清理（Legacy Plan Compatibility Cleanup）
- **现状与隐患**：
  在系统从旧版演进至批处理计划后，数据库中可能残留历史 `Plan` 和 `PlanItem` 记录。虽然当前执行链路已全部基于 `BatchPlan`，但 fixed7 的 `_check_scan_has_dependent_plan()` 为保证安全，同时检查了 `Plan.scan_job_id`。如果存在旧版计划，用户在 UI 计划列表中看不见它们，也无法删除它们，导致关联的扫描记录被永久阻塞无法删除。
- **RED 阶段**：
  在测试中构建孤儿/遗留 `Plan` 挂载在 `ScanJob` 上，验证其阻止扫描删除；在调用清理前，旧版计划统计接口不存在。
- **GREEN 阶段**：
  1. 契约路由实现：
     - `GET /api/plans/legacy/summary`：返回 `{ plan_count, item_count, affected_scan_count }`；
     - `POST /api/plans/legacy/clear`：原子删除所有旧版 `PlanItem` 及 `Plan`，返回清理统计并解锁关联扫描；
  2. 严格遵循静态路由在动态路由之前的挂载顺序，避免 `/plans/legacy/*` 被 `/plans/{plan_id}` 误拦截。

---

## 3. 后端自动化测试验证（Pytest）

在 `tests/test_plan_history_cleanup.py` 中实现了 21 个场景测试（Cases A through AN）：
1. **Case A - F**: 单计划删除状态矩阵（`draft`, `frozen`, `ready`, `partial`, `completed`, `failed` 允许删除，无孤儿数据遗留）；
2. **Case G - H**: 运行中状态严格拦截（`validating`, `executing` 返回 409 Conflict，计划数据完好无损）；
3. **Case I**: 未知计划状态安全防御（Fail-closed，返回 409 Conflict）；
4. **Case J**: 不存在的计划 ID 返回 404 Not Found；
5. **Case K - L**: 批量历史清理状态验证（仅允许 `completed` 与 `failed`，草稿与活跃计划完全不受影响）；
6. **Case M - O**: 批量历史清理参数严格校验（空列表 `[]`、包含非法状态均返回 400 Bad Request，实行零删除）；
7. **Case P - R**: 旧版计划汇总与一键清理验证（精准统计 affected_scan_count，清理后成功解锁关联扫描）；
8. **Case S**: Delete ≠ Undo 原则验证（NAS 文件系统真实物理文件零变更，验证删除前后散列与内容完全一致）；
9. **Case T**: WorkJob 与 AuditEvent 持久性验证（WorkJob 与 AuditEvent 记录未被级联删除）；
10. **Case U - V**: 权限与安全边界验证（未登录 401 拦截，缺失 Origin/CSRF 403 拦截）。

**测试运行结果**：
- 专用套件：`21 / 21 passed`；
- Docker 隔离全量套件（Rule 62 只读挂载）：**`283 / 283 passed`**（零失败、零回归）。

---

## 4. 前端实现与测试验证

### 1. 类型定义与 API Client 扩展
- [`frontend/src/types/index.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/index.ts)：
  - 补充 `PlanStatus`、`PlanHistoryStatus`、`DeletePlanResponse`、`ClearPlanHistoryResponse`、`LegacyPlanSummary`、`ClearLegacyPlansResponse`。
- [`frontend/src/api/domain.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/domain.ts)：
  - `plansApi.deletePlan(id)`；
  - `plansApi.clearHistory(statuses)`；
  - `plansApi.getLegacySummary()`；
  - `plansApi.clearLegacyPlans()`。

### 2. 组件实现
- [`frontend/src/components/plans/plan_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/plan_cleanup.ts)：
  - 纯函数 `getPlanDeleteAvailability(plan)`，精准映射单个删除可用性及 `hasExecutionHistory` 标识。
- [`frontend/src/components/plans/PlanDeleteButton.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/PlanDeleteButton.tsx)：
  - 删除确认按钮，支持 Tooltip 禁用原因展示及二次 Popconfirm 确认；
  - 针对含执行历史（`partial`, `completed`, `failed`）展示“不会撤销 NAS 文件操作（Delete ≠ Undo）”醒目警告；针对未执行计划展示不可逆确认。
- [`frontend/src/components/plans/PlanHistoryCleanupModal.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/PlanHistoryCleanupModal.tsx)：
  - 批量历史清理模态窗，提供 `completed` 与 `failed` 多选框，至少选一项才允许提交；
  - 详细说明清理范围与安全说明（Delete ≠ Undo，不影响活跃计划与审计记录）。
- [`frontend/src/components/plans/LegacyPlanCleanup.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/LegacyPlanCleanup.tsx)：
  - 旧版计划清理横幅，仅在检测到 `plan_count > 0` 时展示；
  - 提示受阻扫描数量并提供一键清理操作，清理后自动失效并更新扫描与计划列表缓存。

### 3. 页面视图优化
- **计划列表**（[`frontend/src/pages/Plans/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Plans/index.tsx)）：
  - 顶部操作栏新增 `[清理计划历史]` 按钮；
  - 列表上方集成 `<LegacyPlanCleanup />` 提示横幅；
  - 操作列增加 `[删除]` 按钮（使用 `PlanDeleteButton`）；
  - 删除最后一项时自动回退上一分页。
- **计划详情**（[`frontend/src/pages/Plans/PlanDetail.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Plans/PlanDetail.tsx)）：
  - 顶部操作栏集成 `[删除计划]` 按钮，删除成功后优雅导航回 `/plans` 列表页。

### 4. 前端自动化测试（Node Test Runner）
- `frontend/tests/plan_cleanup.test.ts`：覆盖策略矩阵（各类状态允许/拦截/执行历史标识）及 API Client 契约；
- `frontend/tests/legacy_plan_cleanup.test.ts`：覆盖旧版计划查询与清理 API 契约；
- 全量前端测试套件：**`92 / 92 passed`**（27 个子测试套件，零失败）；
- TypeScript 类型检查：`npm run typecheck` 零错误；
- 生产打包构建：`npm run build` 成功完成。

---

## 5. Docker 镜像与容器冒烟验证

- **镜像名称**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed8`
- **构建结果**：多阶段 Docker 构建全部完成。
- **冒烟测试结果**：
  - `GET /health`：返回 HTTP 200 OK，健康状态正常；
  - 未认证请求 `GET /api/plans`：返回 HTTP 401 Unauthorized；
  - 未认证请求 `GET /api/plans/legacy/summary`：返回 HTTP 401 Unauthorized；
  - 未认证请求 `POST /api/plans/clear-history`：返回 HTTP 401 Unauthorized；
  - 认证与安全策略符合规范。
