# NAS File Center v0.3.3 FINAL RELEASE GATE 验收报告
## Production Release Verification

## 1. Release Baseline & Lineage（发布基线与演进血统）

- **正式发布版本**：`NAS File Center v0.3.3`
- **发布类型**：`FINAL RELEASE GATE (Production Release)`
- **基线版本**：`v0.3.3-step2-fixed10-hotfix2`
- **基线 Commit**：`3d671a096efda06ac0c1001bca06dcd9f38321ca`
- **基线归档包 SHA256**：`8a6acd78d8090e96bb2227beb75d8ba5eed66efe6ea7d47ec4ee34d536ebf873`
- **发布作者**：`Jin Haocong <jinhaocong@outlook.com>`

### 发布血统溯源（Release Lineage Artifacts）
| 里程碑 Gate | 核心解决领域 | 基线交付包 SHA256 |
| :--- | :--- | :--- |
| **fixed6** | Task Lifecycle & History Cleanup Gate | `e3e2095a5b0c84b7dc979fe2662745b08691371686a5888dded5f938e238d7b9` |
| **fixed7** | Scan Lifecycle & Plan Dependency Gate | `87d92404993fe1d041ee91d2f14d05a59864a1dcffd0c43a95cc5f9ef1b44181` |
| **fixed8-hotfix3** | Plan Lifecycle & Detail UI Truthfulness Gate | `3a426218335f8d42f134291fafcdfb9bcbcd9813bbbf80ce212ffc7d537c244f` |
| **fixed9-hotfix1** | Index Root Lifecycle & Directory Picker Gate | `c9727acb2061beaf5873dc9826fd6f36529f014fd66370135529106fe2184c0f` |
| **fixed10-hotfix2** | Audit Retention & Data Lifecycle Settings Gate | `8a6acd78d8090e96bb2227beb75d8ba5eed66efe6ea7d47ec4ee34d536ebf873` |
| **v0.3.3 Final** | Production Quality & Release Gate Verification | *正式发布产物（外部计算独立校验）* |

---

## 2. Release Version Metadata Consistency（版本元数据真实性与一致性治理）

### A. 初始 Final Gate 阻断原因（HOLD Root Cause）
在初次执行 Final Release Gate 时，虽全量业务回归测试通过，但经发布包自包含审计发现多处历史遗留的开发态版本字符串：
1. `app/main.py`: FastAPI 实例声明 `version="0.3.3.dev1"`；
2. `pyproject.toml`: Python 包元数据声明 `version = "0.3.3.dev1"`；
3. `frontend/src/pages/Login/index.tsx`: 登录页底部显示 `NAS File Center v0.3.2 • 极空间 / Zoraxy / Docker`；
4. `frontend/src/components/Sidebar.tsx`: 侧边栏品牌区域展示 `v0.3.2 Enterprise`；
5. `frontend/package.json`: 声明 `"version": "0.3.2-step2"`；
6. `frontend/package-lock.json`: 根包声明 `"version": "0.3.1"`。

上述不一致违反了“发布版本真实性（Provenance Truthfulness）”与“发布门禁零歧义”纪律，触发了 Final Release Gate 的 HOLD 状态。

### B. 元数据最小化统一矩阵（Version Normalization Matrix）
本轮严格执行元数据一致性修正，**业务逻辑变更 = 0**：
| 目标实体 | 修正前 | 修正后 | 校验机制 |
| :--- | :--- | :--- | :--- |
| **FastAPI `app.version`** | `0.3.3.dev1` | `0.3.3` | `test_fastapi_backend_version` |
| **pyproject `project.version`** | `0.3.3.dev1` | `0.3.3` | `test_pyproject_version` (tomllib) |
| **Login 登录页文案** | `v0.3.2` | `v0.3.3` | `test_login_page_version` |
| **Sidebar 侧边栏文案** | `v0.3.2 Enterprise` | `v0.3.3 Enterprise` | `test_sidebar_component_version` |
| **frontend `package.json`** | `0.3.2-step2` | `0.3.3` | `test_frontend_package_json_version` |
| **frontend `package-lock.json`** | `0.3.1` (root) | `0.3.3` (root) | `test_frontend_package_lock_version` |
| **README 标题与声明** | `v0.3.3-step1` | `v0.3.3` | 源码审计 |
| **Docker OpenAPI 元数据** | `0.3.3.dev1` | `0.3.3` | `/openapi.json` 运行时冒烟 |

### C. 依赖锁定文件治理与事实纠正
- **事实纠正**：纠正先前验收文档中关于 `pnpm-lock.yaml` 的误称，项目前端实际并唯一使用标准的 `frontend/package-lock.json`；
- **依赖图谱零漂移**：`package-lock.json` 仅同步修改了根包自身的版本元数据字段，所有 `node_modules` 依赖项、版本区间、resolved URL 以及 integrity 哈希均保持完全一致，并通过了严格的 `npm ci` 洁净安装测试。

---

## 3. Release Scope Freeze & Diff Audit（变更范围与代码冻结审计）

### A. 生产行为零变更（Production Behavior Diff = 0）
- **后端代码**：除 `app/main.py` 的 `version="0.3.3"` 外，`app/**` 零逻辑修改；
- **前端代码**：除 `Login` 与 `Sidebar` 的版本显示文本外，交互与状态逻辑零修改；
- **数据库结构**：Schema 与模型定义零修改（DB diff = 0）；
- **数据库迁移**：零迁移变更（Migration diff = 0）；
- **版本一致性测试**：新增 `tests/test_release_version_consistency.py`，经历完整 TDD RED（6 项全部失败）到 GREEN（6 项全部通过）。

---

## 4. 全量自动化测试与回归矩阵（Automated Verification Matrix）

### A. 后端测试套件（Docker Rule 62 隔离环境）
- **测试命令**：`PYTHONPATH=. pytest -q`
- **执行环境**：`python:3.12-slim` 容器只读挂载 + `/tmp/project` 隔离执行
- **用例收集与执行数**：**336 / 336 passed**（含 6 个版本一致性断言，100% 通过，0 failed）
- **告警数**：20 个已知警告（18 个底层依赖日期适配提示 + 2 个 Starlette/AnyIO 测试客户端废弃提示）
- **覆盖核心**：
  - 任务中心完整状态机、Worker 租约锁定、心跳超时、分块日志与敏感信息脱敏；
  - 扫描去重历史生命周期、依赖计划强阻断、Dashboard 快照真实性；
  - 批处理计划删除权限矩阵、验证/执行中 409 阻断、旧版遗留 Plan 兼容清理；
  - 持久化 IndexRoot 注册表、空目录索引追踪、损坏工作任务状态隔离；
  - 数据生命周期单例 `id=1`、`0 = 永久保留`、只读预览与显式清理原子性事务；
  - 发布版本元数据在 FastAPI、pyproject、package.json、package-lock 及前端源码中的绝对一致性。

### B. 前端测试套件（Node.js Test Runner）
- **洁净安装验证**：`npm ci` -> 成功通过（确认 lockfile 与 package.json 零冲突）；
- **单元测试结果**：`npm test` -> **150 passed, 44 suites, 0 failed**；
- **静态类型检查**：`npm run typecheck` -> **0 errors**；
- **生产发布构建**：`npm run build` -> **0 errors**（Vite 正常产出生产包）。

---

## 5. 数据库初始化、并发保护与升级演练证明（Database Rehearsal Proofs）

在独立 Python 3.12 隔离环境中，针对生产数据库生命周期进行了全链路仿真验证：

1. **全新数据库安装（Fresh DB Installation）**：
   - 空配置目录启动：自动创建包含 `index_roots` 与 `data_lifecycle_policy` 在内的完整数据表结构；
   - 单例策略自动注入：`id=1, audit_retention_days=0`；
   - 绝不产生多余的迁移备份文件（0 backup created）；
   - `PRAGMA integrity_check` -> `ok`，`PRAGMA foreign_key_check` -> 0 错误。
2. **API 与 Worker 并发初始化冲突防护（Concurrent Init Protection）**：
   - 模拟 4 个并发工作线程同时尝试初始化同一全新数据库文件；
   - 文件锁 `_db_init_lock` 严格排队，零死锁、零数据库锁定（`database is locked`）异常，策略单例行数严格保持为 1。
3. **旧版数据库无损升级与备份前置证明（Old DB Upgrade Rehearsal & Backup Proof）**：
   - 注入 pre-fixed9 与 pre-fixed10 遗留数据库（包含用户、扫描去重组、大 inode 文件、计划项、审计日志、旧 IndexedPath 及运行中 index-root 任务，缺失 `index_roots` 与 `data_lifecycle_policy` 表）；
   - **备份前置确证（Backup Before Mutation）**：在发生任何结构变更前，自动创建备份文件；经独立解析备份文件确认：备份库内绝对不含新增的目标表，`PRAGMA integrity_check` 完整通过；
   - **数据迁移与回填确证**：目标库平滑升级，`index_roots` 从已有路径与活跃任务完整回填，`data_lifecycle_policy` 默认配置为 0 天（永久保留）；
   - **行数保护审计（Protected Row Count Audit）**：迁移前后各受保护业务表行数 100% 吻合，无任何数据丢失或漂移；
   - **迁移幂等性（Migration Idempotency）**：二次启动不产生冗余备份，不重复回填数据。

---

## 6. 安全边界与文件系统零破坏验证（Safety Invariants & Security Matrix）

### A. 物理文件系统安全边界
- 验收过程严格遵照安全红线：严禁触碰任何真实 NAS 媒体或个人数据；
- 任务删除、扫描删除、计划清理、索引根目录删除、审计历史清理等所有生命周期操作均仅作用于数据库元数据，**物理 NAS 文件与目录变更数 = 0**。

### B. 认证与访问控制（Auth & CSRF Protection）
- 未认证访问受保护 API（如 `/api/data-lifecycle`, `/api/indexes`, `/api/audit/retention-preview`）严格返回 `401 Unauthorized`；
- 修改类请求（`POST`, `PUT`, `DELETE`）缺失 `Origin` 标头时严格触发 CSRF 防御返回 `403 Forbidden`；
- 合法登录建立 HttpOnly 会话 Cookie，受保护 API 正常协同响应；
- 系统严格杜绝任意删除单条审计日志的接口（无 `DELETE /api/audit/{id}`）。

---

## 7. 已知边界说明（Known Limitations）

1. **非实时文件系统监听**：系统采用主动扫描与显式索引机制，不维护常驻 inotify/fsevents 物理文件监听；
2. **外部文件变动不自动刷新扫描快照**：若用户在外部对 NAS 物理文件执行增删，历史 Scan 结果中的重复文件快照保持该任务执行完成时刻的历史快照语义；
3. **审计清理无后台自动调度器**：严格贯彻“保存策略 ≠ 执行删除”原则，不部署后台定时清理器，保留清理必须由管理员在前端显式确认触发；
4. **多管理员并发策略窗口**：若在打开确认弹窗后、点击执行前的微小窗口内有其他管理员修改了保留策略，后端清理在执行时刻仍以数据库最新持久化单例为准。

---

## 8. 发布决议（Release Decision）

- **终审状态**：**PASS / APPROVED**
- **决议结论**：
  - `fixed6` Task Lifecycle: **CLOSED**
  - `fixed7` Scan Lifecycle: **CLOSED**
  - `fixed8` Plan Lifecycle: **CLOSED**
  - `fixed9` Index Lifecycle: **CLOSED**
  - `fixed10` Audit Lifecycle: **CLOSED**
  - **NAS File Center v0.3.3 正式批准发布**。
