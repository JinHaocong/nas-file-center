# NAS File Center v0.3.5 Gate5-A-hotfix1 — Implementation & Acceptance Walkthrough

## 1. Scope (本次范围)
- **唯一基线**: `nas-file-center-v0.3.4-gate4-baseline-hotfix1.zip` (Commit: `e9cf7ef5defa0678d117d60dd997e881134d2ede`)
- **核心性质**: **FILESYSTEM READ ONLY**。Preview 仅从 `IndexedPath` 与 `IndexRoot` 读取，严禁创建 BatchPlan / PlanItem / WorkJob / OperationJournal / QuarantineEntry，严禁产生文件系统突变。
- **Gate5-A-hotfix1 修复范围**:
  1. **P2-01: media_type in/nin runtime 500 修复**:
     - 修复 `app/filters/compiler.py` 中 `or_*` 与 `and_*` 语法错误，改为正确的 SQLAlchemy `or_(*expressions)` 与 `and_(*(not_(e) for e in expressions))`。
     - 覆盖 `media_type eq`, `neq`, `in`, `nin`，并添加 API 集成测试。
  2. **P2-02: AST 语法树 Fail-closed 严格校验**:
     - `FilterPreviewRequest`, `LeafNode`, `LogicalNode`, `FilterExpression` 均增加 `model_config = ConfigDict(extra="forbid")`，顶层与叶子节点拼写错误及未知字段统一返回 HTTP 422。
     - `LogicalNode` 严格单形态：`and`/`or` 仅允许 `children`（有 `child` 返回 422）；`not` 仅允许单个 `child`（有 `children` 返回 422），移除任何宽容兼容逻辑。
  3. **P2-03: mtime 强类型与字符串字段严格类型校验**:
     - `mtime` 仅接受时区感知的 ISO-8601 字符串（无时区返回 422）或在有效范围（0 ~ 253402300799）内的整数 epoch 秒，转换为 UTC 纳秒；浮点数、布尔值及超范围纳秒整数统一返回 422。
     - `path`, `name`, `extension`, `media_type` 的 `in`/`nin` 强制要求非空 `list[str]`（包含数字、布尔值等直接 422）；标量比较（`eq`, `neq` 等）严格要求字符串类型，禁止静默类型转换。

---

## 2. Technical Implementation Details (技术实现要点)

### 2.1 模块修改清单
- `app/filters/compiler.py`: 修复 `media_type in/nin` 谓词编译逻辑；移除 `not` 的 `children` 宽松降级。
- `app/filters/schema.py`: 为 AST 与请求模型添加 `ConfigDict(extra="forbid")`。
- `app/filters/validation.py`: 严格化 `_parse_mtime_to_ns`（拒绝 float/bool/naive ISO），严格化 `validate_filter_ast`（严格逻辑节点形态、非空字符串列表与标量字符串类型检查）。

---

## 3. Verification & Acceptance (验证与验收结果)

### 3.1 后端全量测试 (529 passed, 100% PASS)
- 命令: `docker run --rm -v "$(pwd):/app" -w /app -e PYTHONPATH=. nas-test-env:latest pytest -q`
- 结果: **529 passed, 0 failed** (原基线 499 passed + Gate5-A 与 hotfix1 新增 30 passed)
  - `Existing baseline failures`: 0
  - `Gate5-A-hotfix1 new failures`: 0

### 3.2 核心安全回归套件 (174 passed, 100% PASS)
- Gate2 套件: `pytest -q tests/test_gate2_*.py` -> **55 passed**
- Gate3 套件: `pytest -q tests/test_gate3_stale_plan.py tests/test_organizer_blockers_regression.py` -> **60 passed**
- Gate4 套件: `pytest -q tests/test_gate4_backend_quarantine_undo.py tests/test_quarantine_*.py` -> **59 passed**

### 3.3 前端零回归验证 (177 passed, 100% PASS)
- `cd frontend && npm test -- --run` -> **177 passed (52 suites), 0 failed**
- `npm run typecheck` -> **tsc --noEmit 零错误**
- `npm run build` -> **vite 生产构建成功**

### 3.4 Docker 镜像与容器独立黑盒验收 (CP1 ~ CP11 全部 PASS)
- 构建镜像: `docker build --platform linux/amd64 -t nas-file-center:v0.3.5-gate5a-hotfix1 .`
- 运行黑盒脚本: `scratch/test_gate5a_hotfix1_blackbox_acceptance.py`
  - `CP1_MEDIA_TYPE_IN`: PASS (API 200，准确匹配视频与图片)
  - `CP2_MEDIA_TYPE_NIN`: PASS (API 200，准确排除视频与图片)
  - `CP3_FILTER_TYPO`: PASS (顶层拼写错误拒绝 422)
  - `CP4_LEAF_EXTRA`: PASS (叶子额外属性拒绝 422)
  - `CP5_LOGICAL_SHAPE`: PASS (非法逻辑节点形态拒绝 422)
  - `CP6_MTIME_FLOAT`: PASS (mtime 浮点数拒绝 422)
  - `CP7_NAIVE_MTIME`: PASS (无时区 ISO 字符串拒绝 422)
  - `CP8_AWARE_MTIME`: PASS (UTC 与偏移时区 ISO 字符串正常返回 200)
  - `CP9_NON_STRING_IN`: PASS (非字符串列表项拒绝 422)
  - `CP10_ZERO_MUTATION`: PASS (0 plan, 0 item, 0 journal, 0 quarantine, /data manifest 100% 保持一致)
  - `CP11_SQLITE`: PASS (integrity_check=ok, foreign_key_check=clean, journal_mode=wal)

---

## 4. Release Provenance
Release SHA256: See external SHA256SUMS.txt generated after archive creation.
