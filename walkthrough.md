# NAS File Center v0.3.3-step2-fixed10 验收报告与实现文档
## Audit Retention + Data Lifecycle Settings Gate

## 1. 版本与基线（Version & Baseline）
- **交付版本**：`NAS File Center v0.3.3-step2-fixed10`
- **基线版本**：`v0.3.3-step2-fixed9-hotfix1`
- **基线 Commit**：`fa853ec3edd0753e3ad45230a7357fc7463c8b6d`
- **基线发布包 SHA256**：`f68dc648da028a7d67f40bcdfa51527549b185d710ccaacc7e6ec16cf4645773`
- **提交作者**：`Jin Haocong <jinhaocong@outlook.com>`
- **发布产物**：`nas-file-center-v0.3.3-step2-fixed10.zip`
- **Docker 镜像**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed10`

---

## 2. 核心架构与设计原则（Core Architecture & Invariants）

### A. 单例持久化数据生命周期策略（Singleton DataLifecyclePolicy）
1. **单例数据表设计**：在数据库引入 `data_lifecycle_policy` 表，严格约束全局仅有一条记录（`id=1`）。
2. **字段定义**：
   - `id`: 主键，`Integer`, 初始值为 `1`；
   - `audit_retention_days`: 保留天数，`Integer`, 初始默认值为 `0`；
   - `updated_at`: 更新时间，`DateTime(timezone=True)`, 记录策略最后修改时间。
3. **安全不变性（Safety Invariant）**：
   - `audit_retention_days = 0` 严格定义为**永久保留**；
   - `0` 绝对不可解释为清空全部审计日志；
   - 当策略为 `0` 时，调用执行清理接口强制返回 HTTP 400 Bad Request（`"Cannot apply retention cleanup when audit_retention_days is 0 (permanent retention)"`），保证绝对零删除、零自审计生成。

### B. 操作隔离与零后台自动清理（Action Isolation & No Cron Purge）
1. **保存策略 ≠ 执行删除**：`PUT /api/data-lifecycle` 仅更新并持久化保留策略天数，不触发任何历史审计删除；
2. **预览 ≠ 执行**：`GET /api/audit/retention-preview` 为纯只读分析接口，重复调用多次对数据库绝对零写入；
3. **零后台 Cron / Scheduler**：完全不引入任何后台定时轮询、定时清理线程或 Worker 自动清理，所有物理清理动作均必须由管理员在 Web 界面明确确认后手动触发；
4. **零物理文件影响**：审计清理仅在数据库事务内部作用于 `audit_events` 表，NAS 磁盘上的物理文件系统变更数恒为 `0`。

### C. 事务原子性与清理自审计（Transactional Cleanup & Self-Audit）
1. **事务隔离**：使用 SQLite `BEGIN IMMEDIATE` 排他事务；
2. **严格时间截止边界**：清理条件为 `timestamp < cutoff`，严格遵循小于语义，`timestamp == cutoff` 的边界记录保留；
3. **单条自审计记录**：每次成功清理事务内部原子插入恰好 1 条 `operation="audit.retention"` 的审计记录，记录本次清理的 `retention_days`, `cutoff`, `deleted_count`；
4. **故障完全回滚**：清理过程若发生异常，执行事务回滚，历史记录完好恢复，绝不残留成功自审计。

---

## 3. 后端实现与 API 契约（Backend Implementation & Contract）

### A. 数据库迁移与模型
- [`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py)：新增 `DataLifecyclePolicy` 模型。`AuditEvent.timestamp` 索引已就绪（`index=True`）。
- [`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py)：在 `init_db()` 中将 `"data_lifecycle_policy"` 加入 `required_tables`，在旧数据库升级时触发自动备份；安全插入单例默认记录：
  ```sql
  INSERT OR IGNORE INTO data_lifecycle_policy (id, audit_retention_days, updated_at) VALUES (1, 0, CURRENT_TIMESTAMP)
  ```

### B. 核心业务方法（`app/service.py`）
1. `get_data_lifecycle_policy() -> dict`: 查询全局策略单例，返回字典；
2. `update_data_lifecycle_policy(days: int) -> dict`: 验证 `0 <= days <= 3650`，更新单例并持久化；
3. `preview_audit_retention(now: datetime | None = None) -> dict`: 计算截止时间点、拟删除行数、拟保留行数、最早与最新记录时间；当 `retention_days == 0` 时返回 `enabled=False, delete_count=0, cutoff=None`；
4. `apply_audit_retention(transaction_guard=None, now: datetime | None = None) -> dict`: 执行 `BEGIN IMMEDIATE` 事务清理，校验 `retention_days > 0`，原子生成 `audit.retention` 自审计。

### C. 接口路由与安全拦截（`app/api/router.py`）
1. `GET /api/data-lifecycle`: 查询策略；
2. `PUT /api/data-lifecycle`: 更新策略，输入通过 `DataLifecyclePolicyUpdateRequest` 进行严格整型验证与范围 `[0, 3650]` 约束，拦截非合法类型（bool、float、str、负数）；
3. `GET /api/audit/retention-preview`: 获取清理预览；
4. `POST /api/audit/apply-retention`: 执行清理，当策略为 0 时返回 400 Bad Request；
5. 全局依赖 `get_current_user`（未认证 401），PUT/POST 自动执行 Origin/Referer CSRF 校验（无 Origin 拦截 403）。

---

## 4. 前端实现与真实呈现（Frontend Truthful UI）

### A. 类型与 API 封装
- [`frontend/src/types/index.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/types/index.ts)：新增 `DataLifecyclePolicy`, `AuditRetentionPreview`, `AuditRetentionApplyResult` 接口。
- [`frontend/src/api/domain.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/api/domain.ts)：封装 `dataLifecycleApi` 与 `auditApi.getRetentionPreview()`, `auditApi.applyRetention()`。

### B. 纯计算与状态辅助函数（`frontend/src/components/settings/data_lifecycle.ts`）
1. `formatAuditRetention(days)`: 0 格式化为 "永久保留"，正数格式化为 "保留最近 N 天"；
2. `validateRetentionDaysInput(val)`: 严格校验保留天数输入；
3. `getAuditRetentionApplyAvailability(policy, preview)`: 策略为 0 时 `canApply: false` 并附带禁用原因提示；具备候选记录时允许执行清理。

### C. 设置页面（`frontend/src/pages/Settings/index.tsx`）
- 新增独立卡片 **“数据生命周期与审计保留策略”**；
- 展示三大核心安全原则（保存策略 ≠ 执行删除、0 天 = 永久保留、预览 ≠ 执行）；
- 提供保留天数配置组件与快捷预设按钮（0 永久保留, 30天, 90天, 180天, 365天）；
- 独立“保存策略”按钮，更新成功后失效查询缓存；
- 清理预览区块：展示当前生效保留期、审计日志总数、清理截止时间点、拟删除记录数、拟保留记录数、最早记录时间；
- 独立“刷新预览”与“执行审计清理”危险按钮；
- 点击执行清理弹出 Ant Design `Modal.confirm` 二次确认弹窗，明确展示拟删除数量与不可逆警示。

### D. 审计页面真实验证（`frontend/src/pages/Audit/index.tsx`）
- 纠正原先错误的“永久记录所有文件操作”文案，变更为真实的“按系统数据生命周期保留策略记录文件操作、隔离变更与执行校验事件”；
- 页面顶部展示当前保留策略状态标签（如 `保留策略: 永久保留` 或 `保留策略: 保留最近 90 天`）；
- 保持严格只读：页面无多选 Checkbox、无单行删除按钮、无批量清理按钮。

---

## 5. 验证矩阵与测试结果（Verification Matrix）

### A. 后端自动化测试
- **全新测试套件（3个文件，16项全新测试）**：
  1. `tests/test_data_lifecycle_migration.py`: 覆盖数据库自动迁移、升级前备份、全新库零多余备份、重启持久化保持；
  2. `tests/test_data_lifecycle_policy.py`: 覆盖默认 0 永久保留、PUT 合法范围 [0, 3650]、PUT 严格拒绝非法形状（bool、float、负数、null）、保存策略零删除红线、未认证 401 与 CSRF 403 拦截；
  3. `tests/test_audit_retention.py`: 覆盖 Preview 纯只读性、0 策略预览语义、Strict `< cutoff` 严格边界保持（`timestamp == cutoff` 严格保留）、0 策略 Apply 强制拦截 400、事务原子性与 self-audit 校验、故障注入原子回滚、零候选记录正常执行自审计、WorkJob/ScanJob/BatchPlan/IndexRoot/物理文件绝对保护、认证与 CSRF 保护。
- **运行结果**：
  - `pytest tests/test_data_lifecycle_migration.py tests/test_data_lifecycle_policy.py tests/test_audit_retention.py`: **16 passed, 0 failed**
  - **全量后端测试运行**：`pytest -q`: **330 passed, 0 failed**（基线 314 个，净增 16 个）；
  - **真实告警报告**：20 个告警（18 个基线原有告警 + 2 个 Starlette/AnyIO 测试客户端废弃提示）。

### B. 前端自动化测试与构建
- **全新测试套件**：`frontend/tests/data_lifecycle.test.ts`（新增 16 项前端断言用例）；
- **运行结果**：`npm test`：**138 passed, 42 suites, 0 failed**（基线 122 个，净增 16 个）；
- **类型检查**：`npm run typecheck`：**0 errors**；
- **生产构建**：`npm run build`：**0 errors**。

### C. 生产 Docker 容器冒烟测试
- 镜像编译：`docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed10 .` 成功；
- 容器启动运行测试：
  - `GET /health` -> `200 OK`
  - 未认证 `GET /api/data-lifecycle` -> `401 Unauthorized`
  - 登录 `POST /api/auth/login` -> `200 OK`
  - 认证查询 `GET /api/data-lifecycle` -> `{"audit_retention_days": 0, ...}`
  - 认证无 Origin 修改 `PUT /api/data-lifecycle` -> `403 Forbidden` (CSRF 拦截)
  - 认证带 Origin 修改 `PUT /api/data-lifecycle` -> `{"audit_retention_days": 90, ...}`
  - 认证获取预览 `GET /api/audit/retention-preview` -> `{"retention_days": 90, "enabled": true, ...}`
  - 认证执行清理 `POST /api/audit/apply-retention` -> `{"deleted_count": 0, "remaining_count": 1, ...}`（自动记录自审计）
  - 前端 SPA 根页面 `GET /` -> `200 OK`。

---

## 6. 归档与交付说明
- **发布代码归档**：`nas-file-center-v0.3.3-step2-fixed10.zip`
- **生成方式**：`git archive --format=zip -o nas-file-center-v0.3.3-step2-fixed10.zip HEAD`
- **解压解构一致性验证**：在全新空目录解压并核验文件结构，所有跟踪源码均保持完整。
