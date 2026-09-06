# NAS File Center v0.3.5 Gate5-A — Implementation & Acceptance Walkthrough

## 1. Scope (本次范围)
- **唯一基线**: `nas-file-center-v0.3.4-gate4-baseline-hotfix1.zip` (Commit: `e9cf7ef5defa0678d117d60dd997e881134d2ede`)
- **核心性质**: **FILESYSTEM READ ONLY**。Preview 仅从 `IndexedPath` 与 `IndexRoot` 读取，严禁创建 BatchPlan / PlanItem / WorkJob / OperationJournal / QuarantineEntry，严禁产生文件系统突变。
- **本次实现范围**:
  1. **Unified Filter AST**: Pydantic AST 语法树模型（LogicalNode: `and`, `or`, `not`; LeafNode: `field`, `operator`, `value`, `case_sensitive`）。
  2. **Filter Validation & Complexity Guard**: 最大深度 5，单逻辑节点子项上限 50，总叶子上限 200。字段范围严格限定为 `path`, `name`, `extension`, `size`, `mtime`, `media_type`。严格拒绝 `regex` 字段与 `matches` 操作符（HTTP 422 明确提示 `"regex filtering is not supported in Gate5-A"`）。
  3. **SQL Filter Compiler**: 将 Filter AST 编译为 SQLAlchemy `IndexedPath` 谓词。精确转义 LIKE 特殊字符（`%`, `_`, `!`），支持大小写敏感/不敏感与复合布尔逻辑。
  4. **Global Exclude Rules & Persistence (`FilterPolicy`)**: 段感知目录 Basename 排除谓词生成；默认排除规则持久化在 SQLite 单例表 `filter_policy` (id=1)；硬隔离 `quarantine_root` 排除保护。
  5. **Read-only Filter Preview API**: `POST /api/filters/preview`，面向所有登录用户开放，提供服务端分页（1 <= page, 1 <= page_size <= 200, 默认 50）、稳定二级排序（`IndexedPath.id`）、SQL 聚合（`COUNT(*)` 与 `COALESCE(SUM(size), 0)`）及索引新鲜度元数据（`preview_source="index"`, `live_filesystem_verified=false`, `roots=[{root, last_indexed_at}]`）。
  6. **FilterPolicy API**: `GET /api/filter-policy`（所有登录用户可读），`PUT /api/filter-policy`（Admin 专享，普通用户 403 阻断）。
- **严格非目标**:
  - 严禁实现 Workflow DB / Compiler / UI / Revision、Plan Rebuild、Advanced Dedupe、Resource Control、Scheduler、Regex 运行时、文件突变编排。

---

## 2. Technical Implementation Details (技术实现要点)

### 2.1 模块分层结构
```text
app/filters/
├── __init__.py
├── schema.py        # Filter AST Pydantic 模型与 API 契约
├── validation.py    # 语法树深度/节点数量守卫、字段操作符语义校验与类型转换
├── media_types.py   # 扩展名到 media_type 的确定性映射
├── compiler.py      # AST 递归编译为 SQLAlchemy IndexedPath 谓词（! 转义 LIKE）
└── excludes.py      # 全局排除规则校验与段感知 SQL 谓词构建器
```

### 2.2 核心安全与只读保证
1. **0 文件系统突变**: Preview 阶段执行纯粹的 SQLite 查询，文件系统 pre/post manifest 100% 恒等一致。
2. **0 任务与计划生成**: Preview 不创建 BatchPlan、PlanItem、WorkJob、Journal、QuarantineEntry。
3. **安全模式兼容**: `ALLOW_MUTATION=false` 下 Preview 与 `PUT /api/filter-policy`（仅 SQLite 配置变更）正常运行。
4. **Index Freshness 契约 (Rule 30)**: 文件从磁盘删除而未重新索引时，Preview 继续依据 Index 返回条目并明确声明 `live_filesystem_verified=false`，重新索引后失效条目自动消失。

---

## 3. Verification & Acceptance (验证与验收结果)

### 3.1 后端全量测试 (522 passed, 100% PASS)
- 命令: `docker run --rm -v "$(pwd):/app" -w /app -e PYTHONPATH=. nas-test-env:latest pytest -q`
- 结果: **522 passed, 0 failed** (原基线 499 passed + Gate5-A 新增 23 passed)
  - `Existing baseline failures`: 0
  - `Gate5-A new failures`: 0

### 3.2 核心安全回归套件 (174 passed, 100% PASS)
- Gate2 套件: `pytest -q tests/test_gate2_*.py` -> **55 passed**
- Gate3 套件: `pytest -q tests/test_gate3_stale_plan.py tests/test_organizer_blockers_regression.py` -> **60 passed**
- Gate4 套件: `pytest -q tests/test_gate4_backend_quarantine_undo.py tests/test_quarantine_*.py` -> **59 passed**

### 3.3 前端零回归验证 (177 passed, 100% PASS)
- `cd frontend && npm test -- --run` -> **177 passed (52 suites), 0 failed**
- `npm run typecheck` -> **tsc --noEmit 零错误**
- `npm run build` -> **vite 生产构建成功**

### 3.4 Docker 镜像与容器独立黑盒验收 (CP1 ~ CP10 全部 PASS)
- 构建镜像: `docker build --platform linux/amd64 -t nas-file-center:v0.3.5-gate5a .`
- 运行黑盒脚本: `scratch/test_gate5a_blackbox_acceptance.py`
  - `CP1_HEALTH`: PASS (API & Worker 容器健康运行)
  - `CP2_INDEX`: PASS (多目录并发索引与任务执行正常)
  - `CP3_PREVIEW`: PASS (AST、操作符、media_type 准确解析；regex/matches 显式 422 拒绝)
  - `CP4_PAGINATION`: PASS (分页参数边界校验、稳定排序、SQL 聚合匹配字节与数量准确)
  - `CP5_EXCLUDES`: PASS (段感知全局目录排除生效；隔离区硬排除生效)
  - `CP6_RBAC`: PASS (普通用户读 200 写 403；Admin 读写 200)
  - `CP7_SAFE_MODE`: PASS (`ALLOW_MUTATION=false` 下 Preview 读与策略写正常)
  - `CP8_ZERO_MUTATION`: PASS (0 plan, 0 item, 0 journal, 0 quarantine, /data manifest 100% 保持一致)
  - `CP9_FRESHNESS`: PASS (严格遵守 Rule 30 索引新鲜度行为)
  - `CP10_SQLITE`: PASS (integrity_check=ok, foreign_key_check=clean, journal_mode=wal)

---

## 4. Release Provenance
Release SHA256: See external SHA256SUMS.txt generated after archive creation.
