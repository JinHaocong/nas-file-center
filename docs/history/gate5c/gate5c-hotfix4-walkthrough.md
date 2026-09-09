# NAS File Center v0.3.5 Gate5-C-hotfix4 — Implementation & Verification Walkthrough

## 1. Context & Review Findings Addressed (背景与审查问题修复)

### 1.1 前序状态与基线
```text
Gate2 = PASS (55 tests)
Gate3 = PASS (60 tests)
Gate4 = PASS (59 tests)
Gate5-A = PASS (30 tests)
Gate5-B = PASS / CLOSED (nas-file-center-v0.3.5-gate5b-hotfix4.zip)

Gate5-C-hotfix3 targeted fixes = PASS
Gate5-C overall = HOLD
Gate5-D = FORBIDDEN
v0.3.5 = NOT CLOSED

Baseline Artifact:
nas-file-center-v0.3.5-gate5c-hotfix3.zip
SHA256: bafe2e114766477e50d3867ea5738aa90edc2dc2b944517f2f16213dfdd717bf
Commit: ce6c44c694dfc5ff95f7f8662f4472d07f58463d
```

### 1.2 本轮关闭的核心审查缺陷 (P2 Findings & Optional Cleanup)

- **P2-16: Historical revision must fail closed (历史版本严格失败闭环，杜绝静默回退)**:
  - 原实现问题：
    - `revisionQuery` 使用宽容的 `parseInt(revisionQuery, 10)` 解析，导致 `?revision=abc` 解析为 `NaN`；
    - 页面逻辑判定 `targetRevision !== null` 成立，界面显示 `历史版本 rNaN`；
    - 但在传递给 `WorkflowPreviewPanel` 与回滚操作时，`targetRevision || current_revision` 表达式将假值 `NaN` 回退为 `current_revision`，导致预览和草稿生成实际上静默作用于当前最新版本。
  - 核心修复：
    - 引入独立解析工具 `parseWorkflowRevisionQuery`；
    - 严格正则全匹配 `/^[1-9]\d*$/`，拒绝非数字字符、前导零、负数、浮点数及尾随换行符或空格，并要求 `Number.isSafeInteger(num) && num > 0`；
    - 非法格式判定为 `isValid: false`，界面立即展示错误提示 Alert（“无效的历史版本号”），彻底阻断组件挂载，严禁回退至当前版本 definition，严禁渲染预览面板，严禁生成草稿计划，严禁渲染回滚按钮；
    - 合法历史版本号必须等待 `GET /api/workflows/{id}/revisions/{N}` 获取成功。若返回 404 或网络错误，界面展示错误提示 Alert（“历史版本加载失败”），严禁回退，禁止预览与计划生成；
    - 若合法数字与 `current_revision` 相同，自动规范化（normalize）为当前版本视图，标签与 definition 严格保持当前版本。

- **P2-17: Preview pagination request snapshot (预览分页请求参数快照化，消除闭包竞态)**:
  - 原实现问题：
    - `WorkflowPreviewPanel` 中 `Table onChange(p, ps)` 仅触发 `previewMutation.mutate(p)`，`mutationFn` 直接从组件状态闭包中读取 `pageSize`；
    - 当用户在 Ant Design 表格中从 50 项切换为 100 项时，由于 React 状态更新异步性与闭包捕获，首个请求发出的 `page_size` 仍为旧状态 50；
  - 核心修复：
    - 定义完整请求快照接口 `PreviewRequestParams { page: number; pageSize: number; }`；
    - `previewMutation` 的 `mutationFn` 强制从传入的入参对象中解构 `{ page, pageSize }`，禁止读取外部组件 state；
    - `Table onChange(p, ps)` 显式传入快照对象 `previewMutation.mutate({ page: p, pageSize: ps })`；
    - “生成预览 / 刷新预览”按钮点击时同样显式传入 `{ page, pageSize }` 快照；
    - 表格序号列通过 `computePreviewRowIndex(page, pageSize, idx) = (page - 1) * pageSize + idx + 1` 计算，与后端分页响应数据绝对对齐。

- **P3 Optional Cleanup: Remove hardcoded `root_ids: [1]` (清理硬编码根目录默认值)**:
  - 新建工作流初始步骤骨架、模式切换默认步骤模板及 `StepList.tsx` 的新建 Scan 步骤，统一将预设 `root_ids` 初始化为空数组 `[]`；
  - 彻底消除假定物理根目录 ID 必定为 1 的隐式耦合，由用户从系统真实注册的索引根目录列表中自主选择。

---

## 2. Code Changes Summary (代码变更概览)

### 2.1 前端核心逻辑与工具函数
- `frontend/src/utils/workflowRevisionParser.ts` (新建):
  - 导出 `parseWorkflowRevisionQuery(rawQuery, currentRevision)`：实现严格无容错正则解析、安全整数界限校验、fail-closed 错误信息生成以及当前版本规范化；
  - 导出 `computePreviewRowIndex(page, pageSize, index)`：统一提供确定性 1-based 表格行序号计算；
  - 导出 `createInitialScanStep(id)`：统一生成初始 `root_ids: []` 的扫描步骤骨架。

### 2.2 前端页面与编排组件改造
- `frontend/src/pages/Workflows/WorkflowBuilder.tsx`:
  - 接入 `parseWorkflowRevisionQuery`，废弃宽容的 `parseInt`；
  - 增加 `!parsedRevision.isValid` 与 `isHistoricalView && isHistError` 的前置 fail-closed 拦截渲染，防止表单及预览面板加载错误数据；
  - `WorkflowPreviewPanel` 仅在非历史版本或历史版本数据成功加载时挂载，且 `revision` 严格传递 `isHistoricalView ? targetRevision! : workflow.current_revision`；
  - 新建工作流及模式重置步骤采用 `createInitialScanStep`，杜绝硬编码 `[1]`。
- `frontend/src/pages/Workflows/WorkflowPreviewPanel.tsx`:
  - 导出 `PreviewRequestParams` 接口；
  - `previewMutation` 重构为接收完整快照 `{ page, pageSize }`，并在 `onSuccess` 中同步状态；
  - “生成预览 / 刷新预览”与表格分页切换均显式传递参数快照；
  - 序号列改用 `computePreviewRowIndex` 计算。
- `frontend/src/components/workflows/StepList.tsx`:
  - 新增扫描步骤时初始 `root_ids` 设置为 `[]`。

### 2.3 测试套件
- `frontend/tests/hotfix4_red.test.ts` (新建):
  - 包含 7 组前端测试，涵盖非法字符串输入（如 `abc`, `NaN`, `1abc`, `1.5`, `0`, `-1`, 换行符等）的严格拒绝、当前版本规范化、跨页行序号计算及初始空扫描步骤。
- `frontend/scripts/run-tests.mjs`:
  - 纳入 `tests/hotfix4_red.test.ts` 统一编译与执行。

---

## 3. Verification & Acceptance Results (验证与验收结果)

### 3.1 前端单元与契约测试套件
```bash
node scripts/run-tests.mjs
# tests 251
# suites 81
# pass 251
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 174.37
```

### 3.2 前端类型检查与生产构建
```bash
npm run typecheck
# > tsc --noEmit (0 errors)

npm run build
# > tsc && vite build
# ✓ 3748 modules transformed.
# ✓ built in 4.12s
```

### 3.3 后端全量测试套件
```bash
docker exec -t -e PYTHONPATH=/app nas-test-env pytest -q
# 615 passed in 38.64s
```

### 3.4 真实 Docker 生产容器端到端黑盒验收
基于全新构建镜像 `nas-file-center:v0.3.5-gate5c-hotfix4` 执行 `scratch/test_gate5c_hotfix4_blackbox_acceptance.py`：
```text
============================================================
GATE5-C-HOTFIX4 REAL DOCKER CONTAINER BLACK-BOX ACCEPTANCE REPORT
============================================================
CP1_SPA_SERVING                    : PASS
CP2_REVISION_FAIL_CLOSED           : PASS
CP3_PREVIEW_PAGINATION_CONTRACT    : PASS
CP4_CARDINALITY_CONSTRAINTS        : PASS
CP5_DRAFT_PLAN_LINEAGE             : PASS
CP6_STRICT_SHA_FULLMATCH           : PASS
CP7_SQLITE_INTEGRITY               : PASS
============================================================
ALL ACCEPTANCE CHECKPOINTS PASSED PERFECTLY!
```

---

## 4. Current Formal Status (当前正式状态)

```text
Gate2 = PASS (55 tests)
Gate3 = PASS (60 tests)
Gate4 = PASS (59 tests)
Gate5-A = PASS (30 tests)
Gate5-B = PASS / CLOSED

Gate5-C-hotfix4 candidate ready for independent review
Gate5-C = HOLD pending independent review
Gate5-D = FORBIDDEN
v0.3.5 = NOT CLOSED
```
