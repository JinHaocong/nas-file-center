# NAS File Center v0.3.3-step2-fixed9 验收报告与实现文档
## Index Root Lifecycle + Directory Picker Integration Gate

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed8-hotfix3`（Commit: `33c7896003594ddf9db254fec0575f3018d8f46d`）。
- **性质定位**：
  - 建立持久化 `IndexRoot` 实体注册表与生命周期状态模型；
  - 消除空目录索引后在列表中消失的历史缺陷；
  - 提供安全的索引元数据删除接口（`DELETE /api/indexes/{id}`）与并发任务冲突防护（409 Conflict）；
  - 目录状态真实性呈现（`available` / `missing` / `blocked`）；
  - 前端新建索引完全复用 `DirectoryPicker` 组件，无损集成。
- **严格约束**：
  - **文件系统零破坏**：删除索引元数据仅移除数据库内快照记录，绝对不修改或删除 NAS 物理文件系统中的任何目录或文件；
  - **组件零修改**：`frontend/src/components/DirectoryPicker/**` 零修改；
  - **任务与计划引擎解耦**：Task Engine、Worker Concurrency、Plan Engine、Scan Lifecycle 保持不变。

---

## 2. 核心架构设计与实现

### A. 持久化 IndexRoot 实体模型与数据库迁移（`app/models.py`, `app/db.py`）
1. **模型定义**：
   - 增加 `IndexRoot` 模型：
     - `id`: 主键自增整型；
     - `root`: 规范化绝对路径（`unique=True`, `index=True`）；
     - `created_at`: 记录首次登记时间；
     - `last_indexed_at`: 记录最近一次索引完成时间（可为空）。
2. **平滑迁移与自动备份**：
   - 在 `app/db.py` 的 `required_tables` 中纳入 `"index_roots"`，缺失时触发全量自动备份（如 `nas_file_center_backup_*.db`）；
   - 执行 `_migrate_index_roots_registry`：
     - 自动建表；
     - 从既有 `indexed_paths` 表中按 `root_key` 分组，提取 `MIN(first_seen_at)` 与 `MAX(last_seen_at)` 幂等回填存量索引根；
     - 从未结束的 `index-root` 工作任务中提取入队参数中的根路径进行补充回填；
     - 全流程幂等，无论重复启动还是全新建库均安全平稳。

### B. 服务层生命周期与冲突防护（`app/service.py`）
1. **入队即登记（`enqueue_index`）**：
   - `POST /api/indexes` 接收到路径后，先执行 `_normalize_allowed_path` 安全校验；
   - 在入队同一事务中立即创建或复用 `IndexRoot`，解决异步任务完成前前端无法观察到该 Root 的问题；
   - 响应包含 `{ "index_root_id": root_id, "work_job_id": job.id, "status": "queued", "root": normalized, "created": is_created }`。
2. **空目录索引持久化（`reindex_root`）**：
   - 索引执行完毕后，事务更新对应 `IndexRoot.last_indexed_at`；
   - 若索引目标为空目录（`files == 0 && folders == 0`），同样确保 `IndexRoot` 实体存在且打上时间戳，彻底修复空目录被索引后列表消失的问题。
3. **列表聚合与轻量状态探测（`list_index_roots`）**：
   - 分页查询主表为 `IndexRoot`；
   - 仅针对当前页面的根目录列表，通过轻量 SQL `WHERE root_key IN (...) GROUP BY root_key` 批量聚合已索引文件数与目录数（仅 2 次查询，杜绝 N+1 与子树深扫）；
   - 执行安全的轻量根目录可用性探测：
     - `available`: 处于 `ALLOWED_ROOTS` 且 `os.path.isdir` 为真；
     - `missing`: 处于 `ALLOWED_ROOTS` 但物理目录不存在；
     - `blocked`: 不在当前允许的挂载根范围内。
   - 动态检测并返回 `has_active_job`, `active_job_id`, `active_job_status`, `can_remove`。
4. **安全删除索引元数据（`delete_index_root`）**：
   - 支持通过主键 ID 删除索引根元数据；
   - 检查是否存在当前根的未结束任务（`queued` / `running` / `paused` / `cancel_requested`），存在时抛出 `HTTPException(409, "当前索引根目录正在执行索引任务，无法移除")`；
   - 校验通过后，在 `BEGIN IMMEDIATE` 事务内原子清理该根的 `IndexedPath` 快照记录与 `IndexRoot` 实体；
   - 严格不执行任何物理文件系统删除，保留系统 Audit 日志及关联任务。

### C. 路由层契约（`app/api/router.py`）
- 新增 `DELETE /api/indexes/{index_root_id}`：
  - 返回 `{ "deleted": True, "id": index_root_id, "root": root_path, "deleted_indexed_paths": count }`；
  - 自动捕获 404 及 409 异常并如实传递给前端。

### D. 前端生命周期治理与 DirectoryPicker 集成（`frontend/`）
1. **纯函数决策与呈现助手（`src/components/indexes/index_lifecycle.ts`）**：
   - `getIndexRemoveAvailability(root)`：根据任务状态与能力标记提供是否可删及禁用原因（例如“存在进行中的索引任务”）；
   - `getIndexPathStatePresentation(pathState)`：将 `available`、`missing`、`blocked` 转换为带有精确语义与 Tooltip 解释的 Tag 状态。
2. **DirectoryPicker 无损集成（`src/pages/Indexes/index.tsx`）**：
   - 新建表单中的 `root` 字段从普通文本输入替换为成熟的 `<DirectoryPicker multiple={false} allowManualInput={true} placeholder="请选择或输入要索引的目录路径..." />`；
   - 完全复用现有的安全根目录浏览树与手动输入能力，组件源码零修改。
3. **安全移除交互与列表体验**：
   - 操作列增加带有二次确认的“移除索引”危险操作气泡弹窗；
   - 若存在活跃任务，按钮呈现禁用状态并显示原因 Tooltip；
   - 移除成功后，主动失效 `['indexes']` 缓存，并在单页最后一条被删除时自动向前翻页，防止空白页。

---

## 3. 测试矩阵与自动化回归验证

### 1. 前端全量测试与构建
- **前端测试套件**：`frontend/tests/index_lifecycle.test.ts` 结合已有任务、计划、扫描生命周期测试。
  - 涵盖删除策略矩阵、路径状态展现逻辑、API 请求 URL 及契约、以及 DirectoryPicker 规范集成断言。
- **执行结果**：
  ```text
  # tests 122
  # suites 36
  # pass 122
  # fail 0
  ```
  **122 / 122 passed**（净增 10 个测试用例，100% 通过，零回归）。
- **类型检查**：`npm run typecheck` 退出码 0，**0 错误**。
- **生产打包构建**：`npm run build` 成功完成，耗时 4.03s。

### 2. 后端全量测试（Pytest）
- **运行环境**：严格按照 Rule 62（`-v "$PWD":/src:ro -w /tmp/project`）在纯净 Docker 隔离容器内运行。
- **执行结果**：
  ```text
  299 passed, 18 warnings in 39.81s
  ```
  **299 / 299 passed**（覆盖 16 个新增 Index Root 注册表与生命周期专项用例，零失败）。

### 3. Docker 镜像与容器冒烟验证
- **镜像构建**：`docker build -t kerwinjhc/nas-file-center:0.3.3-step2-fixed9 .` 顺利完成。
- **容器冒烟测试**：
  - `/health` 返回 200 OK；
  - 未认证访问 `GET /api/indexes` 严格返回 401 Unauthorized；
  - 未认证访问 `DELETE /api/indexes/1` 严格返回 401 Unauthorized；
  - 缺少 CSRF 来源访问敏感操作严格拦截。

---

## 4. 干净发布包验证与 Release Decision

- **干净归档**：使用 `git archive` 打包，排除 `.git`、`node_modules`、缓存与临时数据库。
- **解压独立验证**：在 `/tmp/verify_clean_step2_fixed9` 独立解压运行前端测试、TypeScript 校验、构建及后端 Docker 全量测试，100% 验证通过。
- **Release Decision**：**PASS / APPROVED**。
