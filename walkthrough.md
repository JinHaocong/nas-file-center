# NAS File Center v0.3.3-step2-fixed7 验收报告与实现文档
## Scan History Lifecycle + Dashboard Freshness Gate

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed6`（Commit: `edb6954`）。
- **任务目标**：本轮专注完成 `Scan History Lifecycle + Dashboard Freshness Gate`，解决两大核心产品问题：
  1. **Dashboard 历史累加语义缺陷**：此前 `duplicate_group_count` 跨历史扫描全量累计（例如多次扫描 10 + 12 = 22 组），而可释放容量却取最新扫描，导致时间与统计语义分裂；现收敛为统一的最新完成扫描快照语义，并补充扫描标识与完成时间。
  2. **Scan 历史生命周期与计划级联保护**：补齐扫描记录安全删除接口 `DELETE /api/scans/{id}` 与 UI 能力，并在删除前深度检查是否被传统计划 `Plan` 或批处理计划 `BatchPlan` 依赖，杜绝级联误删与计划悬空。
- **严格隔离原则**：
  - 本轮绝对不处理 Plan 清理（延后至 fixed8）、Index 清理（延后至 fixed9）、Audit 清理（延后至 fixed10）；
  - 零数据库 Schema 变更、零迁移变更、零新增第三方依赖；
  - 维持现有生产 Plan Engine / Worker Concurrency / Fclones Parser 零改动。

---

## 2. 根因分析与后端修复（RED → GREEN）

### A. Dashboard 历史累加与语义脱节
- **现状与缺陷**：
  在 `app/service.py` 的 `dashboard_summary()` 中，原实现使用 `session.scalar(select(func.count(DuplicateGroup.id)))`，这会无差别统计系统内全部存量重复组（含历次过时扫描结果），而 `latest_reclaimable_bytes` 却仅读取最新一次完成扫描。这使得数据面板呈现出“22 个重复组却只可释放 2.5KB”的混乱统计。
- **RED 阶段**：
  在 `tests/test_dashboard_scan_freshness.py` 中注入两笔扫描（分别含 10 组与 12 组），断言 `duplicate_group_count == 12`。在 fixed6 基线代码下断言失败（`assert 22 == 12`），精准复现。
- **GREEN 阶段**：
  在 `dashboard_summary()` 中直接取最新已完成扫描任务 `latest_completed` 的 `total_groups`：
  ```python
  latest_completed = session.scalar(
      select(ScanJob)
      .where(ScanJob.status == "completed")
      .order_by(ScanJob.finished_at.desc(), ScanJob.id.desc())
      .limit(1)
  )
  ...
  "duplicate_group_count": (latest_completed.total_groups if latest_completed else 0),
  "latest_reclaimable_bytes": (latest_completed.reclaimable_bytes if latest_completed else 0),
  "latest_scan_id": (latest_completed.id if latest_completed else None),
  "latest_scan_name": (latest_completed.name if latest_completed else None),
  "latest_scan_finished_at": (latest_completed.finished_at.isoformat() if latest_completed and latest_completed.finished_at else None),
  ```

### B. 扫描记录删除与计划依赖防级联误删
- **现状与隐患**：
  在 `ScanJob` 数据库模型中，`plans: Mapped[list[Plan]] = relationship(back_populates="scan_job", cascade="all, delete-orphan")` 声明了级联删除。如果直接删除 `ScanJob`，将直接连带销毁所有关联的去重计划！对于 `BatchPlan`，其 `metadata_json` 中记录了 `scan_job_id`，删除扫描记录也会导致其元数据脱钩。
- **RED 阶段**：
  在 `tests/test_scan_history_lifecycle.py` 中为 `ScanJob` 挂接 `Plan` 与 `BatchPlan`，尝试调用 `DELETE /api/scans/{id}`。在 fixed6 基线中该路由不存在（405 / 404），若直接调用底层删除则会导致计划被隐蔽级联删除。
- **GREEN 阶段**：
  1. 实现 `_check_scan_has_dependent_plan(session, scan_job_id)` 辅助方法：
     - 查询 `Plan.scan_job_id == scan_job_id`；
     - 查询 `json_extract(BatchPlan.metadata_json, '$.scan_job_id') == scan_job_id`；
     - 只要任一存在即返回 `True`。
  2. 实现 `delete_scan(scan_job_id)` 服务方法：
     - 仅允许终态扫描（`completed`, `failed`, `cancelled`）删除，活跃态扫描拒绝并报错（409 Conflict）；
     - 若存在关联计划，严格抛出 `ValueError("该扫描已生成关联计划，请先处理相关计划后再删除扫描记录。")`（409 Conflict），拒绝删除；
     - 允许删除时，原子级联清理孤儿数据 `DuplicateFile`、`DuplicateGroup`，最后删除 `ScanJob`，保证无孤儿记录遗留；
     - `WorkJob`（后台任务记录）与 `AuditEvent`（审计流水）严格保留，不随扫描删除而丢失。
  3. 路由契约：
     - 增加 `DELETE /api/scans/{scan_job_id}`，配备身份认证校验与 CSRF/Origin 头防护。
     - `list_scans` 与 `scan_detail` 返回字段补充 `has_dependent_plan: bool`。

---

## 3. 后端自动化测试验证（Pytest）

本轮扩展了全方位的扫描生命周期与快照新鲜度测试套件：
- `tests/test_dashboard_scan_freshness.py`：
  - 验证多扫描场景下仅统计最新完成扫描指标（解决历史累加错误）；
  - 验证零完成扫描场景（指标安全回退为 0 和 null）；
  - 验证最新扫描失败或运行中时，快照继续锚定最新“已完成”扫描；
  - 验证删除最新扫描后，仪表盘自动回退至上一笔已完成扫描；
  - 验证删除所有扫描后，仪表盘平滑归零。
- `tests/test_scan_history_lifecycle.py`：
  - 验证已关联计划（传统 Plan 或 BatchPlan）的扫描删除被严格拦截（409 Conflict），且计划与扫描均完好保留；
  - 验证无计划的终态扫描（completed/failed/cancelled）成功删除，DuplicateGroup 与 DuplicateFile 级联清空且无孤儿残留；
  - 验证活跃态扫描（queued/running）拒绝删除（409 Conflict）；
  - 验证删除扫描保留 WorkJob 与 AuditEvent；
  - 验证删除接口的 401 身份校验与 403 CSRF/Origin 防护；
  - 验证 `list_scans` 与 `scan_detail` 精准输出 `has_dependent_plan` 标志。

测试运行结果：
- 专用套件：`12 / 12 passed`；
- 后端全量测试：`262 / 262 passed`（相比 fixed6 的 250 tests 新增 12 tests，无回归）。

---

## 4. 前端实现与测试验证

### 1. 类型定义与 API Client 扩展
- [`frontend/src/types/index.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/index.ts)：
  - `DashboardSummary` 补充 `latest_scan_id`、`latest_scan_name`、`latest_scan_finished_at`；
  - `ScanJob` 补充 `has_dependent_plan?: boolean`。
- [`frontend/src/api/domain.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/domain.ts)：
  - `scansApi.deleteScan(id: number)`。

### 2. 组件层与安全按钮
- [`frontend/src/components/scans/scan_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/scans/scan_cleanup.ts)：
  - 纯函数 `getScanDeleteAvailability(scan)`，严格判定终态与计划依赖。若存在计划，给出明确禁用原因“该扫描已生成关联计划，无法删除”；若非终态，给出“仅终态扫描可删除”。
- [`frontend/src/components/scans/ScanDeleteButton.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/scans/ScanDeleteButton.tsx)：
  - 封装 Popconfirm 确认弹窗与 Tooltip 禁用提示，提供防误触的双重保护。

### 3. 页面视图优化
- **扫描列表**（[`frontend/src/pages/Scans/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Scans/index.tsx)）：
  - 操作列增加 `[查看详情]` 与 `[删除]` 按钮（使用 `ScanDeleteButton`）；
  - 删除单页最后一条数据且页码大于 1 时，自动回退上一页。
- **扫描详情**（[`frontend/src/pages/Scans/ScanDetail.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Scans/ScanDetail.tsx)）：
  - 顶部操作区增加删除扫描记录按钮，删除成功后通知并返回列表页；
  - 当扫描存在关联计划时，状态区展示“已生成关联计划”专属标签。
- **系统概览**（[`frontend/src/pages/Dashboard/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Dashboard/index.tsx)）：
  - 卡片文案更新为“最近一次扫描发现”与“最近一次扫描预计可释放”；
  - 卡片副标题展示关联扫描名称与完成时间，无扫描时显示“暂无已完成扫描”；
  - 顶部加入快照时效说明 Alert 提示栏；
  - 图表标题更新为“系统数据概览”，清晰呈现单次扫描快照语义。

### 4. 前端自动化测试与构建
- 新增单元测试套件：
  - `frontend/tests/scan_lifecycle.test.ts`：测试删除策略矩阵与 API 客户端契约；
  - `frontend/tests/dashboard_freshness.test.ts`：测试仪表盘快照时效与副标题渲染逻辑。
- 运行测试：`npm test` $\rightarrow$ `83 / 83 passed`（新增 9 个前端测试，原 74 个全部通过）；
- 类型与构建检查：`npm run typecheck && npm run build` $\rightarrow$ **0 Errors, 0 Warnings**。

---

## 5. Docker 镜像构建与冒烟测试

- **镜像标签**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed7`（平台：`linux/amd64`）。
- **冒烟验证**：
  - `GET /health` $\rightarrow$ `200 OK`；
  - `GET /api/dashboard/summary`（未登录） $\rightarrow$ `401 Unauthorized`；
  - `DELETE /api/scans/1`（未登录） $\rightarrow$ `401 Unauthorized`；
  - 前端静态资源根路径 `/` $\rightarrow$ `200 OK`，资源正常加载。
